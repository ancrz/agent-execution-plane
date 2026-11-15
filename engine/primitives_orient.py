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
import logging
import os
import pwd
import re
import shutil
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger("aep.primitives")

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


# --- path safety (shared by workspace-probe, file-fingerprint, dir-usage, path-users) --------------------------

_EXTRA_VETO = ("/etc/sudoers.d", "/etc/shadow-", "/etc/gshadow-")


def _is_vetoed(raw: str, *, hash_target: bool = False) -> bool:
    """True when `raw` (lexically OR after realpath, so symlinks cannot bypass) is a protected location.

    Reuses CapabilityGuard's blacklist (+ ~/.ssh, ~/.gnupg); additionally /etc/sudoers.d and, for content
    hashing only, the AEP data directory except its *.db files (integrity checks of the databases are the point).
    """
    from engine.paths import data_home
    from engine.privilege import CapabilityGuard

    lexical = os.path.abspath(os.path.expanduser(raw))
    real = os.path.realpath(lexical)
    for cand in (lexical, real):
        if CapabilityGuard.is_path_blacklisted(cand):
            return True
        if any(cand == v or cand.startswith(v + "/") for v in _EXTRA_VETO):
            return True
        if hash_target:
            dh = os.path.realpath(str(data_home()))
            if (cand == dh or cand.startswith(dh + "/")) and not cand.endswith(".db"):
                return True
    return False


# --- workspace-probe -------------------------------------------------------------------------------------------

_MANIFESTS = (
    "pyproject.toml", "setup.py", "go.mod", "package.json", "Cargo.toml", "Makefile", "Dockerfile",
    "Jenkinsfile", ".gitlab-ci.yml",
)  # fmt: skip
_MANIFEST_PREFIXES = (("requirements", ".txt"), ("docker-compose", (".yml", ".yaml")), ("compose", (".yml", ".yaml")))
_WALK_SKIP = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", "target", "dist", "build", ".claude"})
_LANG_BY_EXT = {
    ".py": "python", ".go": "go", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript", ".rs": "rust", ".c": "c", ".h": "c", ".cc": "cpp",
    ".cpp": "cpp", ".java": "java", ".kt": "kotlin", ".rb": "ruby", ".sh": "shell", ".sql": "sql",
    ".md": "markdown", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".json": "json",
}  # fmt: skip
_WALK_MAX_ENTRIES = 20_000
_WALK_MAX_S = 2.0


def _git_summary(path: str) -> dict[str, Any] | None:
    rc, out, _ = _run_cmd(["git", "-C", path, "rev-parse", "--show-toplevel"])
    if rc != 0 or not out.strip():
        return None
    info: dict[str, Any] = {"root": out.strip()}
    rc, out, _ = _run_cmd(["git", "-C", path, "rev-parse", "--short", "HEAD"])
    info["head"] = out.strip() if rc == 0 else None
    rc, out, _ = _run_cmd(["git", "-C", path, "status", "--porcelain=v1", "-b"], timeout=_SUBPROC_TIMEOUT_S)
    lines = out.splitlines() if rc == 0 else []
    if lines and lines[0].startswith("## "):
        head = lines[0][3:]
        branch, _, rest = head.partition("...")
        info["branch"] = branch.split(" ")[0] if not rest else branch
        m_ahead = re.search(r"ahead (\d+)", rest)
        m_behind = re.search(r"behind (\d+)", rest)
        if "..." in head:
            info["upstream"] = rest.split(" ")[0]
            info["ahead"] = int(m_ahead.group(1)) if m_ahead else 0
            info["behind"] = int(m_behind.group(1)) if m_behind else 0
        info["dirty_count"] = len(lines) - 1
    return info


def _walk_languages(root: str) -> tuple[dict[str, int], bool]:
    """Bounded, non-following walk counting files per language; returns (counts, truncated)."""
    counts: dict[str, int] = {}
    stack = [root]
    seen = 0
    deadline = time.monotonic() + _WALK_MAX_S
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    seen += 1
                    if seen > _WALK_MAX_ENTRIES or time.monotonic() > deadline:
                        return counts, True
                    try:
                        if ent.is_dir(follow_symlinks=False):
                            if ent.name not in _WALK_SKIP:
                                stack.append(ent.path)
                        elif ent.is_file(follow_symlinks=False):
                            lang = _LANG_BY_EXT.get(os.path.splitext(ent.name)[1].lower())
                            if lang:
                                counts[lang] = counts.get(lang, 0) + 1
                    except OSError:
                        continue
        except OSError:
            continue
    return counts, False


def _detect_manifests(root: str) -> list[str]:
    found: list[str] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for n in names:
        if n in _MANIFESTS:
            found.append(n)
        elif any(n.startswith(p) and n.endswith(sfx) for p, sfx in _MANIFEST_PREFIXES):
            found.append(n)
    if os.path.isdir(os.path.join(root, ".github", "workflows")):
        found.append(".github/workflows")
    return found


def _workspace_next_action(root: str, manifests: list[str]) -> str:
    wd = f"working_dir='{root}'"
    if "go.mod" in manifests:
        return f"sandbox_run(command='go test ./...', {wd}) or artifact_lint_and_build for Go artifacts."
    if "pyproject.toml" in manifests or "setup.py" in manifests or any(m.startswith("requirements") for m in manifests):
        py_text = _read_text(os.path.join(root, "pyproject.toml"), 20000)
        if "pytest" in py_text or os.path.isdir(os.path.join(root, "tests")):
            return f"sandbox_run(command='pytest -q', {wd})."
        return f"sandbox_run(command='python -m compileall -q .', {wd})."
    if "package.json" in manifests:
        return f"sandbox_run(command='npm test', {wd}, share_net=False)."
    if "Cargo.toml" in manifests:
        return f"sandbox_run(command='cargo test', {wd})."
    return "No recognised manifest; inspect with dir-usage or file-fingerprint."


def _run_workspace_probe(params: dict[str, Any]) -> dict[str, Any]:
    raw = str(params.get("path") or "").strip() or os.getcwd()
    if _is_vetoed(raw):
        return _param_error("Path is protected and cannot be probed.")
    root = os.path.realpath(os.path.expanduser(raw))
    if not os.path.isdir(root):
        return _param_error(f"Not a directory: {raw}")
    git = _git_summary(root)
    base = git["root"] if git else root
    manifests = _detect_manifests(base)
    langs, truncated = _walk_languages(base)
    ordered = dict(sorted(langs.items(), key=lambda kv: -kv[1]))
    tests = []
    if "go.mod" in manifests:
        tests.append("go test ./...")
    if any(m in manifests for m in ("pyproject.toml", "setup.py")) or os.path.isdir(os.path.join(base, "tests")):
        tests.append("pytest -q")
    if "package.json" in manifests:
        tests.append("npm test")
    if "Cargo.toml" in manifests:
        tests.append("cargo test")
    return {
        "primitive": "workspace-probe",
        "path": root,
        "git": git,
        "manifests": manifests,
        "languages": ordered,
        "test_hints": tests,
        "truncated": truncated,
        "next_action": _workspace_next_action(base, manifests),
        **(
            {"escalate": f"L1: sandbox_run(command='find . -type f | wc -l', working_dir='{base}') for exact counts."}
            if truncated
            else {}
        ),
    }


# --- file-fingerprint ------------------------------------------------------------------------------------------

_FP_MAX_PATHS = 20
_FP_MAX_HASH_BYTES = 256 * 1024 * 1024
_FP_CHUNK = 1024 * 1024


def _file_type(mode: int) -> str:
    import stat as st

    for fn, label in ((st.S_ISREG, "file"), (st.S_ISDIR, "dir"), (st.S_ISLNK, "symlink")):
        if fn(mode):
            return label
    return "other"


def _fingerprint_one(raw: str, want_md5: bool) -> dict[str, Any]:
    import hashlib
    import stat as st

    if _is_vetoed(raw, hash_target=True):
        return {"path": raw, "status": "PARAM_ERROR", "error": "Path is protected; fingerprint refused."}
    path = os.path.expanduser(raw)
    try:
        lst = os.lstat(path)
    except FileNotFoundError:
        return {"path": raw, "exists": False}
    except OSError as e:
        return {"path": raw, "exists": None, "error": e.strerror or "stat failed"}
    row: dict[str, Any] = {"path": raw, "exists": True, "type": _file_type(lst.st_mode)}
    if st.S_ISLNK(lst.st_mode):
        row["symlink_target"] = os.readlink(path)
    try:
        s = os.stat(path)
    except OSError:
        s = lst
        row["dangling"] = True
    try:
        owner = pwd.getpwuid(s.st_uid).pw_name
    except KeyError:
        owner = str(s.st_uid)
    row.update(
        size=s.st_size,
        mode=format(st.S_IMODE(s.st_mode), "04o"),
        uid=s.st_uid,
        owner=owner,
        mtime_ns=s.st_mtime_ns,
    )
    if not st.S_ISREG(s.st_mode):
        return row
    if s.st_size > _FP_MAX_HASH_BYTES:
        row["hash_skipped"] = "too_large"
        return row
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False) if want_md5 else None
    try:
        with open(path, "rb") as fh:
            while chunk := fh.read(_FP_CHUNK):
                sha.update(chunk)
                if md5:
                    md5.update(chunk)
    except OSError as e:
        row["hash_skipped"] = e.strerror or "unreadable"
        return row
    row["sha256"] = sha.hexdigest()
    if md5:
        row["md5"] = md5.hexdigest()
    return row


def _run_file_fingerprint(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("paths")
    if isinstance(raw, str):
        raw = [raw]
    if (
        not isinstance(raw, list)
        or not (1 <= len(raw) <= _FP_MAX_PATHS)
        or not all(isinstance(p, str) and p for p in raw)
    ):
        return _param_error(f"'paths' must be a list of 1..{_FP_MAX_PATHS} non-empty strings.")
    want_md5 = bool(params.get("md5"))
    rows = [_fingerprint_one(p, want_md5) for p in raw]
    refused = sum(1 for r in rows if r.get("status") == "PARAM_ERROR")
    return {
        "primitive": "file-fingerprint",
        "count": len(rows),
        "refused": refused,
        "files": rows,
        "next_action": "Compare sha256 with a previous run to detect change; for a directory use dir-usage.",
    }


# --- dir-usage -------------------------------------------------------------------------------------------------

_DU_MAX_ENTRIES = 200_000
_DU_MAX_S = 5.0


def _run_dir_usage(params: dict[str, Any]) -> dict[str, Any]:
    raw = str(params.get("path") or "").strip()
    if not raw:
        return _param_error("'path' is required.")
    if _is_vetoed(raw):
        return _param_error("Path is protected and cannot be measured.")
    top = _int_param(params, "top", 10, 1, 50)
    root = os.path.realpath(os.path.expanduser(raw))
    try:
        root_dev = os.lstat(root).st_dev
    except OSError as e:
        return _param_error(f"Cannot stat path: {e.strerror}")
    if not os.path.isdir(root):
        return _param_error(f"Not a directory: {raw}")

    deadline = time.monotonic() + _DU_MAX_S
    seen = 0
    truncated = False
    skipped_mounts = 0
    totals = {"disk": 0, "apparent": 0, "files": 0}
    children: dict[str, dict[str, int]] = {}
    stack: list[tuple[str, str]] = [(root, "")]  # (dir, top-level child name it belongs to)
    while stack and not truncated:
        cur, owner = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for ent in it:
                seen += 1
                if seen > _DU_MAX_ENTRIES or time.monotonic() > deadline:
                    truncated = True
                    break
                try:
                    s = ent.stat(follow_symlinks=False)
                except OSError:
                    continue
                import stat as st

                child = owner or ent.name
                is_dir = st.S_ISDIR(s.st_mode)
                if is_dir and s.st_dev != root_dev:
                    skipped_mounts += 1
                    continue
                bucket = children.setdefault(child, {"disk": 0, "apparent": 0, "files": 0})
                bucket["disk"] += s.st_blocks * 512
                bucket["apparent"] += s.st_size
                totals["disk"] += s.st_blocks * 512
                totals["apparent"] += s.st_size
                if is_dir:
                    stack.append((ent.path, child))
                else:
                    bucket["files"] += 1
                    totals["files"] += 1
    ranked = sorted(children.items(), key=lambda kv: -kv[1]["disk"])[:top]
    return {
        "primitive": "dir-usage",
        "path": root,
        "disk_bytes": totals["disk"],
        "apparent_bytes": totals["apparent"],
        "files": totals["files"],
        "entries_scanned": seen,
        "skipped_mounts": skipped_mounts,
        "truncated": truncated,
        "top": [
            {"name": n, "disk_bytes": v["disk"], "apparent_bytes": v["apparent"], "files": v["files"]}
            for n, v in ranked
        ],
        "next_action": "Largest child first; drill down with dir-usage(path=<child>), or path-users before deleting.",
        **(
            {"escalate": "L2: artifact_lint_and_build(template_name='disk-usage') then artifact_execute_in_ram."}
            if truncated
            else {}
        ),
    }


# --- process detail (shared with process_inspect) and path-users ----------------------------------------------

_ENV_VALUE_ALLOW = re.compile(r"^(AEP_.*|PATH|VIRTUAL_ENV|GOTOOLCHAIN|GOROOT|LANG|PWD|HOME|USER|SHELL)$")
_SECRET_NAME = re.compile(r"(token|secret|passw|pwd|credential|api[_-]?key|private|auth|(^|_)key($|_))", re.IGNORECASE)
_SECRET_ARG = re.compile(r"((?:token|secret|passw\w*|api[_-]?key|auth\w*)[=:])\S+", re.IGNORECASE)
_SECRET_FLAG = re.compile(
    r"^(?:--?(?:token|secret|passw\w*|api[-_]?key|auth\w*|access[-_]?token|bearer)|-p|authorization:?|bearer)$",
    re.IGNORECASE,
)
_AUTH_HEADER = re.compile(r"(authorization|bearer)\s*[:=]?\s*\S+(\s+\S+)?", re.IGNORECASE)
_URL_CRED = re.compile(r"://[^/\s:@]+:[^@\s]+@")
_PROC_ANCESTORS_MAX = 5
_ENV_NAMES_MAX = 100
_CMDLINE_ARG_MAX = 200


def _proc_status(pid: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _read_text(f"/proc/{pid}/status", 8192).splitlines():
        k, _, v = line.partition(":")
        out[k] = v.strip()
    return out


def _proc_stat_fields(pid: int) -> tuple[int, int] | None:
    """(ppid, starttime_ticks) from /proc/PID/stat (comm may contain spaces/parens: split after the last ')')."""
    raw = _read_text(f"/proc/{pid}/stat", 4096)
    rest = raw.rpartition(")")[2].split()
    try:
        return int(rest[1]), int(rest[19])
    except IndexError, ValueError:
        return None


def mask_cmdline(args: list[str]) -> list[str]:
    """Mask credentials in argv: value after a bare secret flag, `key=value`, auth headers and URL userinfo.

    Masking happens BEFORE the per-arg length cut so a secret cannot survive by straddling the limit.
    """
    out: list[str] = []
    mask_next = 0
    for arg in args:
        if mask_next:
            out.append("***")
            # "Authorization:" "Bearer" "<token>" arrives as three argv items: keep masking past the scheme word.
            mask_next = 1 if (mask_next == 2 and arg.lower() == "bearer") else 0
            continue
        masked = _AUTH_HEADER.sub(r"\1 ***", arg)
        masked = _URL_CRED.sub("://***:***@", masked)
        masked = _SECRET_ARG.sub(r"\1***", masked)
        out.append(masked[:_CMDLINE_ARG_MAX])
        if _SECRET_FLAG.fullmatch(arg):
            mask_next = 2 if arg.lower().startswith("authorization") else 1
    return out


def process_detail(pid: int, *, privileged: bool) -> dict[str, Any]:
    """Orientation detail of a process: start, ancestry, cwd, cgroup, redacted cmdline and env NAMES.

    Env VALUES are only emitted for an allow-list and never for credential-looking names. Other-uid processes
    below 7rwx (`privileged` False) expose neither cwd/exe/cmdline nor environment.
    """
    status = _proc_status(pid)
    if not status:
        return {"available": False}
    try:
        uid = int(status.get("Uid", "").split()[0])
    except IndexError, ValueError:
        uid = -1
    full = privileged or uid == os.getuid()
    detail: dict[str, Any] = {"available": True, "uid": uid, "ppid": None, "full_access": full}
    fields = _proc_stat_fields(pid)
    if fields:
        ppid, ticks = fields
        detail["ppid"] = ppid
        btime = 0
        for line in _read_text("/proc/stat", 8192).splitlines():
            if line.startswith("btime "):
                btime = int(line.split()[1])
        if btime:
            start = btime + ticks / os.sysconf("SC_CLK_TCK")
            detail["start"] = _iso(start)
            detail["uptime_s"] = max(0, int(time.time() - start))
        chain: list[dict[str, Any]] = []
        cur = ppid
        while cur > 0 and len(chain) < _PROC_ANCESTORS_MAX:
            chain.append({"pid": cur, "name": _read_text(f"/proc/{cur}/comm", 64).strip() or "?"})
            nxt = _proc_stat_fields(cur)
            cur = nxt[0] if nxt else 0
        detail["ancestors"] = chain
    cg = _read_text(f"/proc/{pid}/cgroup", 512).splitlines()
    detail["cgroup"] = cg[0].split(":", 2)[-1][:120] if cg else None
    if not full:
        detail["note"] = "other uid below 7rwx: cwd/exe/cmdline/env withheld"
        return detail
    for key in ("cwd", "exe"):
        try:
            detail[key] = os.readlink(f"/proc/{pid}/{key}")
        except OSError:
            detail[key] = None
    args = [a for a in _read_text(f"/proc/{pid}/cmdline", 16384).split("\x00") if a]
    detail["cmdline"] = mask_cmdline(args[:20])
    names: list[str] = []
    allowed: dict[str, str] = {}
    for item in _read_text(f"/proc/{pid}/environ", 262144).split("\x00"):
        name, sep, value = item.partition("=")
        if not sep or not name:
            continue
        names.append(name)
        if _ENV_VALUE_ALLOW.fullmatch(name) and not _SECRET_NAME.search(name):
            allowed[name] = value[:200]
    detail["env_names"] = sorted(set(names))[:_ENV_NAMES_MAX]
    detail["env_allowed"] = dict(sorted(allowed.items()))
    return detail


_PU_MAX_RESULTS = 200
_PU_MAX_S = 5.0
_MAPS_READ_BYTES = 1_048_576


def _under(target: str, root: str) -> bool:
    target = target.removesuffix(" (deleted)")
    return target == root or target.startswith(root.rstrip("/") + "/")


def _proc_hits(pid: int, root: str) -> list[str]:
    hits: list[str] = []
    for key in ("exe", "cwd", "root"):
        try:
            if _under(os.readlink(f"/proc/{pid}/{key}"), root):
                hits.append(key)
        except OSError:
            continue
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            try:
                if _under(os.readlink(f"/proc/{pid}/fd/{fd}"), root):
                    hits.append("fd")
                    break
            except OSError:
                continue
    except OSError:
        pass
    for line in _read_text(f"/proc/{pid}/maps", _MAPS_READ_BYTES).splitlines():
        idx = line.find("/")
        if idx > 0 and _under(line[idx:], root):
            hits.append("mmap")
            break
    return hits


def _run_path_users(params: dict[str, Any]) -> dict[str, Any]:
    raw = str(params.get("path") or "").strip()
    if not raw:
        return _param_error("'path' is required.")
    if _is_vetoed(raw):
        return _param_error("Path is protected and cannot be inspected.")
    root = os.path.realpath(os.path.expanduser(raw))
    privileged = params.get("_tier") == "7rwx"
    me = os.getuid()
    deadline = time.monotonic() + _PU_MAX_S
    users: list[dict[str, Any]] = []
    unreadable = 0
    scanned = 0
    truncated = False
    for ent in os.scandir("/proc"):
        if not ent.name.isdigit():
            continue
        pid = int(ent.name)
        scanned += 1
        if time.monotonic() > deadline:
            truncated = True
            break
        try:
            owner = ent.stat().st_uid
        except OSError:
            continue
        if owner != me and not privileged:
            unreadable += 1
            continue
        hits = _proc_hits(pid, root)
        if hits:
            if len(users) >= _PU_MAX_RESULTS:
                truncated = True
                break
            users.append({"pid": pid, "name": _read_text(f"/proc/{pid}/comm", 64).strip(), "uses": sorted(set(hits))})
    out: dict[str, Any] = {
        "primitive": "path-users",
        "path": root,
        "count": len(users),
        "processes": users,
        "scanned": scanned,
        "unreadable": unreadable,
        "truncated": truncated,
    }
    if users:
        out["next_action"] = f"process_inspect(pid={users[0]['pid']}, verbosity='detail') to see who it is."
    else:
        out["next_action"] = "No visible process uses this path: safe to modify/remove" + (
            f" (but {unreadable} other-uid processes were not readable)." if unreadable else "."
        )
    if truncated or (unreadable and not users):
        out["escalate"] = (
            "L1: run at 7rwx or aep_ctl network listeners / sandbox_run('lsof +D <path>') for full coverage."
        )
    return out


# --- disk-usage / mem-stat (legacy runners; live here so engine.primitives -> orient stays one-way) ---


def _run_disk_usage(params: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(params.get("path") or "/").strip()
    target_path = Path(raw_path or "/")
    effective_path = str(target_path) if target_path.exists() else "/"

    usage = shutil.disk_usage(effective_path)
    percent_used = round((usage.used / usage.total) * 100.0, 2) if usage.total > 0 else 0.0

    st_vfs = os.statvfs(effective_path)
    return {
        "primitive": "disk-usage",
        "path": effective_path,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "percent_used": percent_used,
        "block_size": st_vfs.f_frsize,
        "total_blocks": st_vfs.f_blocks,
        "free_blocks": st_vfs.f_bavail,
    }


def _run_mem_stat(params: dict[str, Any]) -> dict[str, Any]:
    meminfo_path = Path("/proc/meminfo")
    info: dict[str, int] = {}
    if meminfo_path.exists():
        try:
            content = meminfo_path.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                if ":" in line:
                    key, rest = line.split(":", 1)
                    parts = rest.strip().split()
                    if parts and parts[0].isdigit():
                        val_kb = int(parts[0])
                        info[key.strip()] = val_kb * 1024
        except OSError as e:
            _log.debug("Failed reading /proc/meminfo: %s", e)

    total = info.get("MemTotal", 0)
    free = info.get("MemFree", 0)
    available = info.get("MemAvailable", free)
    used = max(0, total - available) if total > 0 else 0
    percent_used = round((used / total) * 100.0, 2) if total > 0 else 0.0

    return {
        "primitive": "mem-stat",
        "total_bytes": total,
        "free_bytes": free,
        "available_bytes": available,
        "used_bytes": used,
        "percent_used": percent_used,
        "swap_total_bytes": info.get("SwapTotal", 0),
        "swap_free_bytes": info.get("SwapFree", 0),
    }


# --- orient (entry point) --------------------------------------------------------------------------------------

_ORIENT_BUDGET_S = 4.0
LADDER = (
    "L1 aep_ctl/process_inspect/sandbox_run; L2 artifact_lint_and_build+artifact_execute_in_ram "
    "(syscalls, bulk/continuous parsing, concurrency, sampling)."
)


def _orient_subprobes(path: str) -> dict[str, Any]:
    """Callables for each sub-probe; imported lazily because disk-usage/mem-stat live in engine.primitives."""
    return {
        "host": lambda: _run_host_info({}),
        "cpu": lambda: _run_cpu_load({"sample_ms": 100}),
        "mem": lambda: _run_mem_stat({}),
        "disk_root": lambda: _run_disk_usage({"path": "/"}),
        "disk_path": lambda: _run_disk_usage({"path": path}),
        "tools": lambda: _run_toolchain_probe({}),
        "workspace": lambda: _run_workspace_probe({"path": path}),
    }


def _compact_orient(res: dict[str, Any]) -> dict[str, Any]:
    h, c = res.get("host") or {}, res.get("cpu") or {}
    m, dr, dp = res.get("mem") or {}, res.get("disk_root") or {}, res.get("disk_path") or {}
    t, w = res.get("tools") or {}, res.get("workspace") or {}
    distro = (h.get("distro") or {}).get("pretty") or ""
    u = h.get("user") or {}
    git = w.get("git") or {}
    out: dict[str, Any] = {
        "primitive": "orient",
        "host": f"{h.get('hostname')} | {distro} | {h.get('kernel')} | {h.get('arch')} {h.get('ncpu')}cpu | "
        f"{h.get('virt')} | {u.get('name')} {h.get('tier')}",
        "resources": {
            "cpu_pct": c.get("usage_pct"),
            "load1": (c.get("loadavg") or [None])[0],
            "mem_pct": m.get("percent_used"),
            "disk_root_pct": dr.get("percent_used"),
            "disk_path_pct": dp.get("percent_used"),
        },
        "tools_present": [x["name"] for x in t.get("tools", []) if x.get("present")],
        "tools_missing": t.get("missing", []),
        "workspace": {
            "langs": list(w.get("languages") or {})[:3],
            "manifests": (w.get("manifests") or [])[:5],
            "git": f"{git.get('branch')}@{git.get('head')} dirty={git.get('dirty_count')}" if git else None,
        },
        "aep_ready": sorted(set((t.get("aep_ready") or {}).values())),
        "next_actions": res.get("next_actions", []),
        "escalate": res.get("escalate"),
    }
    if res.get("partial"):
        out["partial"] = True
        out["errors"] = res.get("errors")
    return out


def _run_orient(params: dict[str, Any]) -> dict[str, Any]:
    path = str(params.get("path") or "").strip() or os.getcwd()
    if _is_vetoed(path):
        return _param_error("Path is protected and cannot be probed.")
    probes = _orient_subprobes(path)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(probes))
    futs = {k: pool.submit(fn) for k, fn in probes.items()}
    deadline = time.monotonic() + _ORIENT_BUDGET_S
    res: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, fut in futs.items():
        try:
            val = fut.result(timeout=max(0.0, deadline - time.monotonic()))
        except concurrent.futures.TimeoutError:
            errors[key] = "timeout"
            continue
        except Exception as exc:  # noqa: BLE001 - one failing probe must not sink the others
            errors[key] = type(exc).__name__
            continue
        if val.get("status") == "PARAM_ERROR":
            errors[key] = str(val.get("error", "param error"))[:80]
        else:
            res[key] = val
    pool.shutdown(wait=False, cancel_futures=True)

    actions: list[str] = []
    ws = res.get("workspace") or {}
    if ws.get("manifests"):
        actions.append(str(ws.get("next_action")))
    cpu = res.get("cpu") or {}
    if cpu.get("load_per_cpu", 0) > 1.0:
        actions.append("CPU saturated: process_inspect(filter=<name>) before heavy work.")
    for key in ("disk_path", "disk_root"):
        if (res.get(key) or {}).get("percent_used", 0) >= 90:
            actions.append(f"Disk {res[key].get('path')} >= 90% used: dir-usage(path=<dir>) to find what to free.")
            break
    ready = (res.get("tools") or {}).get("aep_ready") or {}
    if "bwrap" in ready:
        actions.append("Run untrusted/shell commands isolated: sandbox_run(command=..., working_dir=<repo>).")
    actions.append("aep_ctl(action='schema') for typed system domains (network, storage, package, service).")
    res["next_actions"] = actions[:5]
    res["escalate"] = LADDER
    res["primitive"] = "orient"
    if errors:
        res["partial"] = True
        res["errors"] = errors
        res["status"] = "PARTIAL"
    if params.get("compact"):
        compact = _compact_orient(res)
        if errors:
            compact["status"] = "PARTIAL"
        return compact
    return res


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
    "workspace-probe": _desc(
        "workspace-probe",
        "4r--",
        "Que es este repo/proyecto: git (rama, head, dirty, ahead/behind), manifiestos, lenguajes y como probarlo.",
        [
            "repo",
            "project",
            "workspace",
            "git",
            "branch",
            "manifest",
            "language",
            "proyecto",
            "repositorio",
            "overview",
        ],
        {"path": {"type": "string", "required": False, "default": "", "description": "Directorio (default cwd)"}},
    ),
    "file-fingerprint": _desc(
        "file-fingerprint",
        "4r--",
        "Huella de archivos (1..20): existencia, tipo, tamano, modo, owner, mtime y sha256; rechaza rutas protegidas.",
        ["hash", "sha256", "checksum", "fingerprint", "integrity", "changed", "mtime", "md5", "huella", "cambio"],
        {
            "paths": {"type": "list", "required": True, "default": None, "description": "1..20 rutas"},
            "md5": {"type": "bool", "required": False, "default": False, "description": "Incluir md5"},
        },
    ),
    "dir-usage": _desc(
        "dir-usage",
        "4r--",
        "Cuanto ocupa una carpeta: bytes en disco/aparentes, archivos y top N hijos; sin seguir symlinks ni cruzar mounts.",
        ["folder", "directory", "size", "du", "space", "largest", "carpeta", "ocupa", "tamano", "espacio"],
        {
            "path": {"type": "string", "required": True, "default": None, "description": "Directorio"},
            "top": {"type": "int", "required": False, "default": 10, "description": "Hijos a listar 1..50"},
        },
    ),
    "path-users": _desc(
        "path-users",
        "5r-x",
        "Quien usa una ruta: procesos con exe/cwd/root/fd/mmap en ella (solo mismo uid bajo 7rwx).",
        ["lsof", "fuser", "open", "who", "uses", "busy", "in use", "quien usa", "abierto", "ocupado"],
        {"path": {"type": "string", "required": True, "default": None, "description": "Archivo o directorio"}},
    ),
    "orient": _desc(
        "orient",
        "4r--",
        "PUNTO DE ENTRADA: host + recursos + herramientas + repo + que AEP esta listo + siguientes pasos y escalera L0>L1>L2.",
        [
            "orient",
            "overview",
            "start",
            "begin",
            "where am i",
            "first",
            "arrive",
            "orientar",
            "orientarme",
            "empezar",
            "resumen",
            "primera llamada",
            "que hay aqui",
        ],
        {"path": {"type": "string", "required": False, "default": "", "description": "Workspace (default cwd)"}},
    ),  # fmt: skip
}

ORIENT_RUNNERS = {
    "host-info": _run_host_info,
    "cpu-load": _run_cpu_load,
    "toolchain-probe": _run_toolchain_probe,
    "workspace-probe": _run_workspace_probe,
    "file-fingerprint": _run_file_fingerprint,
    "dir-usage": _run_dir_usage,
    "path-users": _run_path_users,
    "orient": _run_orient,
}
