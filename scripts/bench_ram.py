#!/usr/bin/env python3
"""bench_ram.py (ONT-67 T0): reproducible RAM/latency bench for the AEP backend.

Each run launches a fresh worker process that imports `server` (the same tool manager the live backend serves) with
a TEMPORARY `AEP_DATA_HOME` and `AEP_POOL_DIR` (never the real DB or the real pool), runs a scripted load, and records
VmRSS / RssAnon / RssFile / VmSwap (from /proc/self/status) plus per-call latency after every phase.

Usage:
  bench_ram.py [--runs 3] [--label NAME] [--env KEY=VALUE ...] [--out FILE.json] [--idle-wait SECONDS]
  bench_ram.py --compare BASE.json CAND.json     # markdown table of medians, base vs candidate

The worker is a child of this script and always terminates (no daemon is left behind).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MEM_KEYS = {"VmRSS": "rss_kb", "RssAnon": "anon_kb", "RssFile": "file_kb", "VmSwap": "swap_kb"}
REPEATS = 3  # calls per phase; latency is the median of these


def read_mem() -> dict[str, int]:
    """Memory counters of the current process (kB), from /proc/self/status."""
    out = dict.fromkeys(MEM_KEYS.values(), 0)
    with open("/proc/self/status", encoding="utf-8") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            if key in MEM_KEYS:
                out[MEM_KEYS[key]] = int(rest.split()[0])
    return out


async def _call(tm: Any, name: str, args: dict[str, Any]) -> float:
    t0 = time.perf_counter()
    await tm.call_tool(name, args)
    return (time.perf_counter() - t0) * 1000.0


def _phases(root: str) -> list[tuple[str, str, dict[str, Any]]]:
    big = "seq 1 400000"
    return [
        ("discover", "discover", {"action": "capabilities", "verbosity": "summary"}),
        (
            "catalog_query",
            "artifact_catalog",
            {"action": "query", "query": "disk usage monitor", "verbosity": "summary"},
        ),
        ("orient", "discover", {"use_case": "inspect memory pressure", "verbosity": "summary"}),
        ("autoevol_graph", "autoevol", {"action": "graph", "verbosity": "summary"}),
        ("sandbox_big_out", "sandbox_run", {"command": big, "working_dir": root, "verbosity": "summary"}),
        ("kanban_board", "kanban_board", {"action": "board", "verbosity": "summary"}),
    ]


async def _worker(idle_wait: float) -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    import server  # noqa: PLC0415 - must import after the temp env is set by the parent

    tm = server.mcp._tool_manager
    result: dict[str, Any] = {"phases": []}
    result["phases"].append({"phase": "import", "latency_ms": None, **read_mem()})
    for label, tool, args in _phases(str(REPO_ROOT)):
        lat: list[float] = []
        for _ in range(REPEATS):
            lat.append(await _call(tm, tool, args))
        result["phases"].append(
            {"phase": label, "latency_ms": round(statistics.median(lat), 2), "first_ms": round(lat[0], 2), **read_mem()}
        )
    await asyncio.sleep(idle_wait)
    result["phases"].append({"phase": f"idle_{idle_wait:g}s", "latency_ms": None, **read_mem()})
    # Post-idle query: measures the lazy-reload cost of anything unloaded while idle.
    lat_after = await _call(
        tm, "artifact_catalog", {"action": "query", "query": "disk usage monitor", "verbosity": "summary"}
    )
    result["phases"].append(
        {
            "phase": "catalog_after_idle",
            "latency_ms": round(lat_after, 2),
            "first_ms": round(lat_after, 2),
            **read_mem(),
        }
    )
    return result


def run_worker(idle_wait: float) -> int:
    print("BENCH_JSON " + json.dumps(asyncio.run(_worker(idle_wait))), flush=True)
    return 0


def run_once(extra_env: dict[str, str], idle_wait: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="aep_bench_") as tmp:
        shm = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tmp)
        pool = Path(tempfile.mkdtemp(prefix="aep_bench_pool_", dir=shm))
        env = {
            **os.environ,
            "AEP_DATA_HOME": tmp,
            "AEP_POOL_DIR": str(pool),
            "PYTHONPATH": str(REPO_ROOT),
            **extra_env,
        }
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", "--idle-wait", str(idle_wait)],
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
                cwd=str(REPO_ROOT),
            )
        finally:
            subprocess.run(["rm", "-rf", str(pool)], check=False)
    for line in proc.stdout.splitlines():
        if line.startswith("BENCH_JSON "):
            return json.loads(line[len("BENCH_JSON ") :])
    raise RuntimeError(f"worker failed rc={proc.returncode}: {proc.stderr[-800:]}")


def aggregate(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, ph in enumerate(runs[0]["phases"]):
        row: dict[str, Any] = {"phase": ph["phase"]}
        for key in ("rss_kb", "anon_kb", "file_kb", "swap_kb", "latency_ms", "first_ms"):
            vals = [r["phases"][idx].get(key) for r in runs if r["phases"][idx].get(key) is not None]
            row[key] = round(statistics.median(vals), 2) if vals else None
        rows.append(row)
    return rows


def compare(base_path: str, cand_path: str) -> str:
    base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    cand = json.loads(Path(cand_path).read_text(encoding="utf-8"))
    lines = [
        f"| phase | RSS kB {base['label']} -> {cand['label']} | RssAnon kB | swap kB | p50 ms | first-call ms |",
        "|---|---|---|---|---|---|",
    ]
    for b, c in zip(base["median"], cand["median"], strict=False):

        def pair(key: str, b: dict[str, Any] = b, c: dict[str, Any] = c) -> str:
            bv, cv = b[key], c[key]
            if bv is None or cv is None:
                return "-"
            pct = f" ({(cv - bv) / bv * 100:+.1f}%)" if bv else ""
            return f"{bv:g} -> {cv:g}{pct}"

        lines.append(
            f"| {b['phase']} | {pair('rss_kb')} | {pair('anon_kb')} | {pair('swap_kb')} | {pair('latency_ms')} | {pair('first_ms')} |"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--label", default="run")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--out", default=None)
    ap.add_argument("--idle-wait", type=float, default=6.0)
    ap.add_argument("--compare", nargs=2, metavar=("BASE", "CAND"))
    args = ap.parse_args()
    if args.worker:
        return run_worker(args.idle_wait)
    if args.compare:
        print(compare(*args.compare))
        return 0
    extra = dict(kv.split("=", 1) for kv in args.env)
    runs = [run_once(extra, args.idle_wait) for _ in range(max(1, args.runs))]
    payload = {"label": args.label, "env": extra, "runs": runs, "median": aggregate(runs)}
    text = json.dumps(payload, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    for row in payload["median"]:
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
