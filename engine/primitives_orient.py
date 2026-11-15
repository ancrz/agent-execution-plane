"""
Engine: primitives_orient.py — Layer-0 orientation primitives (ONT-63).

Read-only, in-RAM answers to the questions every agent asks on arrival at a host: where am I,
what resources are there, which tools exist, what is this repo / file / process, can I reach X.
Pure stdlib; no shell; every subprocess has a timeout and a minimal environment.

Runners take a params dict and return a plain dict.  A runner may include a top-level
``status`` (PARAM_ERROR / PERMISSION_DENIED / PARTIAL) which `execute_primitive` lifts to the envelope.
Descriptors and runners are merged into `engine.primitives` (single registry, single `_RUNNERS`).
"""

from __future__ import annotations

import concurrent.futures
import grp
import os
import pwd
import re
import shutil
import socket
import subprocess
import time
from datetime import UTC, datetime
from typing import Any

# --- shared helpers --------------------------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9._+][A-Za-z0-9._+-]*$")  # same contract as `aep_ctl package check`
_SUBPROC_TIMEOUT_S = 2.0


def _param_error(msg: str) -> dict[str, Any]:
    return {"status": "PARAM_ERROR", "error": msg}


def _int_param(params: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    raw = params.get(key, default)
    try:
        val = int(raw)
    except TypeError, ValueError:
        val = default
    return max(lo, min(hi, val))


def _read_text(path: str, limit: int = 65536) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _min_env() -> dict[str, str]:
    """Minimal environment for probing subprocesses: no inherited secrets, no toolchain downloads."""
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/"),
        "LANG": "C",
        "LC_ALL": "C",
        "GOTOOLCHAIN": "local",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run_cmd(argv: list[str], *, cwd: str | None = None, timeout: float = _SUBPROC_TIMEOUT_S) -> tuple[int, str, str]:
    """Run argv without shell; returns (rc, stdout, stderr); rc=-1 on spawn failure, -2 on timeout."""
    try:
        r = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=cwd,
            env=_min_env(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"
    except OSError, subprocess.SubprocessError:
        return -1, "", "spawn_failed"
    return r.returncode, r.stdout or "", r.stderr or ""


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _desc(
    name: str, tier: str, description: str, tags: list[str], params: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "name": name,
        "category": "orientation",
        "capability": "system_inspect",
        "tags": tags,
        "description": description,
        "params": params or {},
        "required_tier": tier,
    }


# --- host-info -------------------------------------------------------------------------------------------------


def _parse_os_release() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _read_text("/etc/os-release").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            if k in ("ID", "VERSION_ID", "PRETTY_NAME"):
                out[k] = v.strip().strip('"')
    return out


def _detect_virt() -> str:
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return "container"
    cg = _read_text("/proc/1/cgroup")
    if any(tok in cg for tok in ("docker", "kubepods", "lxc", "containerd", "libpod")):
        return "container"
    product = _read_text("/sys/class/dmi/id/product_name", 256).strip().lower()
    if product:
        if any(tok in product for tok in ("virtual", "kvm", "qemu", "vmware", "bochs", "droplet", "standard pc")):
            return "vm"
        return "bare"
    return "unknown"


def _run_host_info(params: dict[str, Any]) -> dict[str, Any]:
    from engine.privilege import get_effective_chmod_tier

    un = os.uname()
    osr = _parse_os_release()
    try:
        uptime_s = float(_read_text("/proc/uptime", 128).split()[0])
    except IndexError, ValueError:
        uptime_s = 0.0
    uid = os.getuid()
    try:
        uname = pwd.getpwuid(uid).pw_name
    except KeyError:
        uname = str(uid)
    groups: list[str] = []
    for gid in sorted(set(os.getgroups()) | {os.getgid()}):
        try:
            groups.append(grp.getgrgid(gid).gr_name)
        except KeyError:
            groups.append(str(gid))
    return {
        "primitive": "host-info",
        "hostname": socket.gethostname(),
        "kernel": f"{un.sysname} {un.release}",
        "arch": un.machine,
        "distro": {"id": osr.get("ID"), "version_id": osr.get("VERSION_ID"), "pretty": osr.get("PRETTY_NAME")},
        "uptime_s": int(uptime_s),
        "boot": _iso(time.time() - uptime_s) if uptime_s else None,
        "ncpu": os.cpu_count() or 1,
        "virt": _detect_virt(),
        "user": {"name": uname, "uid": uid, "gid": os.getgid(), "groups": groups},
        "tier": get_effective_chmod_tier()["tier"],
        "next_action": "default_primitives(action='run', name='toolchain-probe') to see which tools exist here.",
    }


# --- cpu-load --------------------------------------------------------------------------------------------------


def _cpu_times() -> tuple[int, int]:
    """(busy, total) jiffies from the aggregate 'cpu' line of /proc/stat."""
    for line in _read_text("/proc/stat", 4096).splitlines():
        if line.startswith("cpu "):
            vals = [int(x) for x in line.split()[1:] if x.isdigit()]
            if len(vals) >= 4:
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                total = sum(vals[:8])
                return total - idle, total
    return 0, 0


def _run_cpu_load(params: dict[str, Any]) -> dict[str, Any]:
    sample_ms = _int_param(params, "sample_ms", 200, 50, 1000)
    ncpu = os.cpu_count() or 1
    try:
        l1, l5, l15 = os.getloadavg()
    except OSError:
        l1 = l5 = l15 = 0.0
    b0, t0 = _cpu_times()
    time.sleep(sample_ms / 1000.0)
    b1, t1 = _cpu_times()
    usage = round(100.0 * (b1 - b0) / (t1 - t0), 1) if t1 > t0 else None
    pressure = None
    for tok in _read_text("/proc/pressure/cpu", 512).splitlines()[:1]:
        m = re.search(r"avg10=([0-9.]+)", tok)
        if m:
            pressure = float(m.group(1))
    return {
        "primitive": "cpu-load",
        "loadavg": [round(l1, 2), round(l5, 2), round(l15, 2)],
        "ncpu": ncpu,
        "load_per_cpu": round(l1 / ncpu, 2),
        "usage_pct": usage,
        "sample_ms": sample_ms,
        "psi_cpu_some_avg10": pressure,
        "next_action": (
            "Load is high: process_inspect(pid=N) on the top consumer before launching heavy work."
            if l1 / ncpu > 1.0
            else "CPU has headroom; proceed."
        ),
    }


# --- toolchain-probe -------------------------------------------------------------------------------------------

DEFAULT_TOOLS: tuple[str, ...] = (
    "python3", "go", "node", "npm", "rustc", "cargo", "gcc", "make", "git", "docker", "podman", "bwrap",
    "bpftrace", "pueue", "uv", "golangci-lint", "systemctl", "journalctl", "nft", "sudo",
)  # fmt: skip
_NEVER_EXEC = frozenset({"sudo"})  # presence only: never executed
_AEP_ENABLES: dict[str, str] = {
    "bwrap": "sandbox_run",
    "bpftrace": "kernel_trace",
    "go": "artifact_lint_and_build",
    "pueue": "async_job_dispatch",
    "systemctl": "aep_ctl(domain='service')",
}
_TOOLCHAIN_BUDGET_S = 3.0
_TOOLCHAIN_MAX_NAMES = 30
_TOOLCHAIN_WORKERS = 8


def _probe_one(name: str) -> dict[str, Any]:
    found = shutil.which(name)
    if not found:
        return {"name": name, "present": False}
    row: dict[str, Any] = {"name": name, "present": True, "path": found, "realpath": os.path.realpath(found)}
    if name in _NEVER_EXEC:
        return row
    flag = "version" if name == "go" else "--version"
    rc, out, err = _run_cmd([found, flag], timeout=_SUBPROC_TIMEOUT_S)
    lines = (out or err).strip().splitlines()
    if rc == 0 and lines:
        row["version"] = lines[0].strip()[:120]
    return row


def probe_tools(names: list[str]) -> tuple[list[dict[str, Any]], bool]:
    """Probe tools in parallel (<=8 workers) within a 3 s total budget; returns (rows, budget_exceeded)."""
    deadline = time.monotonic() + _TOOLCHAIN_BUDGET_S
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=_TOOLCHAIN_WORKERS)
    futs = {n: pool.submit(_probe_one, n) for n in names}
    rows: list[dict[str, Any]] = []
    exceeded = False
    for n in names:
        try:
            rows.append(futs[n].result(timeout=max(0.0, deadline - time.monotonic())))
        except concurrent.futures.TimeoutError:
            exceeded = True
            found = shutil.which(n)
            rows.append({"name": n, "present": bool(found), "path": found, "version_timeout": True})
    pool.shutdown(wait=False, cancel_futures=True)
    return rows, exceeded


def _run_toolchain_probe(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("names")
    if raw in (None, "", []):
        names = list(DEFAULT_TOOLS)
    else:
        if isinstance(raw, str):
            raw = [t for t in re.split(r"[,\s]+", raw) if t]
        if not isinstance(raw, list) or not raw:
            return _param_error("'names' must be a list of binary names.")
        names = [str(n) for n in raw]
        if len(names) > _TOOLCHAIN_MAX_NAMES:
            return _param_error(f"At most {_TOOLCHAIN_MAX_NAMES} names per call.")
        bad = [n for n in names if not _NAME_RE.fullmatch(n)]
        if bad:
            return _param_error(f"Invalid tool name(s) (allowed [A-Za-z0-9._+-], no leading dash): {bad[:3]}")
        names = list(dict.fromkeys(names))
    rows, exceeded = probe_tools(names)
    present = {r["name"] for r in rows if r.get("present")}
    aep_ready = {t: cap for t, cap in _AEP_ENABLES.items() if t in present}
    missing = [r["name"] for r in rows if not r.get("present")]
    return {
        "primitive": "toolchain-probe",
        "count": len(rows),
        "present_count": len(present),
        "tools": rows,
        "missing": missing,
        "aep_ready": aep_ready,
        "budget_exceeded": exceeded,
        "next_action": (
            "Usable now via AEP: " + ", ".join(sorted(set(aep_ready.values())))
            if aep_ready
            else "No AEP-enabling tools found; aep_ctl(domain='package', action='check', name=...) for details."
        ),
    }


# --- registry --------------------------------------------------------------------------------------------------

ORIENT_REGISTRY: dict[str, dict[str, Any]] = {
    "host-info": _desc(
        "host-info",
        "4r--",
        "Quien/donde soy: hostname, kernel, distro, arch, uptime, ncpu, virt/contenedor, usuario/grupos y tier AEP.",
        [
            "host",
            "hostname",
            "kernel",
            "distro",
            "os",
            "arch",
            "uptime",
            "virt",
            "container",
            "vm",
            "user",
            "sistema",
            "equipo",
            "donde",
            "estoy",
            "which host",
        ],
    ),  # fmt: skip
    "cpu-load": _desc(
        "cpu-load",
        "4r--",
        "Carga de CPU: loadavg 1/5/15, load por cpu, uso % muestreado de /proc/stat y PSI.",
        ["cpu", "load", "loadavg", "usage", "pressure", "psi", "busy", "carga", "procesador"],
        {"sample_ms": {"type": "int", "required": False, "default": 200, "description": "Muestreo 50..1000 ms"}},
    ),
    "toolchain-probe": _desc(
        "toolchain-probe",
        "4r--",
        "Que herramientas hay: PATH y version de python3/go/node/git/docker/bwrap/... y que capacidades AEP habilitan.",
        ["tools", "toolchain", "installed", "version", "binary", "which", "path", "instalado", "herramientas"],
        {
            "names": {
                "type": "list",
                "required": False,
                "default": None,
                "description": "Binarios (<=30) o lista estandar",
            }
        },
    ),
}

ORIENT_RUNNERS = {
    "host-info": _run_host_info,
    "cpu-load": _run_cpu_load,
    "toolchain-probe": _run_toolchain_probe,
}
