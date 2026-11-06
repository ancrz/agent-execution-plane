"""ONT-42a: harness_reconnect. Reload the orchestrator's MCP front by typing `/mcp reconnect <server>` into the
harness TTY (TIOCSTI) inside a short, self-restoring sysctl window.

Design: pure functions with injected dependencies (no import of `server`). Everything is fail-closed: any
missing link resolves to route `manual` / `unsupported` and never changes host state.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import signal
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SERVER = "agent-execution-plane"
SERVER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HARNESS_RECONNECT: dict[str, str] = {"claude": "/mcp reconnect {server}"}
PTS_MAJOR = 136
SYSCTL_PATH = "/proc/sys/dev/tty/legacy_tiocsti"
MAX_ANCESTRY_DEPTH = 64

# Typed-prompt hazard and TIOCSTI risk are always surfaced by `plan` (C9).
CAVEATS: tuple[str, ...] = (
    "typed-prompt hazard: text already typed in the harness prompt is submitted together with the injected command",
    "TIOCSTI is a legacy interface; dev.tty.legacy_tiocsti is a global sysctl opened for under 2 s",
    "if sudo wraps stdin in a new pty the helper fails closed (unsupported -> manual)",
)


def parse_proc_stat(text: str) -> dict[str, int] | None:
    """Parse `/proc/<pid>/stat`: returns ppid and tty_nr (comm may contain spaces and parentheses)."""
    end = text.rfind(")")
    if end < 0:
        return None
    rest = text[end + 1 :].split()
    # rest[0]=state, [1]=ppid, [2]=pgrp, [3]=session, [4]=tty_nr
    if len(rest) < 5:
        return None
    try:
        return {"ppid": int(rest[1]), "tty_nr": int(rest[4])}
    except ValueError:
        return None


def tty_nr_to_dev(tty_nr: int) -> tuple[int, int]:
    """Decode the kernel's tty_nr (new_encode_dev layout) into (major, minor)."""
    major = (tty_nr >> 8) & 0xFFF
    minor = (tty_nr & 0xFF) | ((tty_nr >> 12) & 0xFFF00)
    return major, minor


def _read_stat(proc_root: Path, pid: int) -> dict[str, int] | None:
    try:
        return parse_proc_stat((proc_root / str(pid) / "stat").read_text())
    except OSError:
        return None


def find_harness(proc_root: str | Path, start_pid: int, uid: int) -> dict[str, Any]:
    """Walk the real ancestry of `start_pid` looking for a known harness.

    Uses `/proc/<pid>/exe` (not comm/argv, both forgeable) and requires the same uid as the caller.
    Returns {"found": bool, "reason": str, ...}.
    """
    root = Path(proc_root)
    pid = start_pid
    seen: set[int] = set()
    for _ in range(MAX_ANCESTRY_DEPTH):
        if pid <= 1 or pid in seen:
            break
        seen.add(pid)
        try:
            exe_base = os.path.basename(os.readlink(root / str(pid) / "exe"))
            owner = (root / str(pid)).stat().st_uid
        except OSError:
            exe_base, owner = "", -1
        if exe_base in HARNESS_RECONNECT:
            if owner != uid:
                return {"found": False, "reason": "harness_uid_mismatch", "pid": pid}
            return {"found": True, "reason": "ok", "pid": pid, "harness": exe_base}
        st = _read_stat(root, pid)
        if st is None:
            break
        pid = st["ppid"]
    return {"found": False, "reason": "harness_not_in_ancestry"}


def resolve_tty(proc_root: str | Path, harness_pid: int) -> dict[str, Any]:
    """Resolve the harness controlling TTY once from `/proc/<pid>/stat` tty_nr. Only pts (major 136) accepted."""
    st = _read_stat(Path(proc_root), harness_pid)
    if st is None or st["tty_nr"] == 0:
        return {"ok": False, "reason": "no_controlling_tty"}
    major, minor = tty_nr_to_dev(st["tty_nr"])
    if major != PTS_MAJOR:
        return {"ok": False, "reason": "not_a_pts"}
    return {"ok": True, "major": major, "minor": minor, "rdev": os.makedev(major, minor), "path": f"/dev/pts/{minor}"}


def validate_server(server: str | None) -> str | None:
    """Return the server name if it matches the allowlist regex, else None."""
    if isinstance(server, str) and SERVER_RE.fullmatch(server):
        return server
    return None


def build_payload(harness: str, server: str | None) -> bytes | None:
    """Exact allowlist: `/mcp reconnect <server>` + `\\r`. Returns None for unknown harness or invalid server."""
    template = HARNESS_RECONNECT.get(harness)
    srv = validate_server(server if server is not None else DEFAULT_SERVER)
    if template is None or srv is None:
        return None
    return (template.format(server=srv) + "\r").encode("ascii")


def validate_payload(payload: bytes) -> bool:
    """Re-validate a payload against the allowlist (used by the parent and again inside the helper)."""
    if not payload.endswith(b"\r") or payload.count(b"\r") != 1:
        return False
    body = payload[:-1].decode("ascii", errors="replace")
    m = re.fullmatch(r"/mcp reconnect ([a-z0-9][a-z0-9_-]{0,63})", body)
    return m is not None


def check_tty_fd(fd: int, expected_rdev: int, uid: int) -> tuple[bool, str]:
    """Validate an already-open fd (C2): isatty, char device, pts major, owned by caller, rdev as expected."""
    try:
        if not os.isatty(fd):
            return False, "not_a_tty"
        st = os.fstat(fd)
    except OSError:
        return False, "fstat_failed"
    if not stat.S_ISCHR(st.st_mode):
        return False, "not_char_device"
    if os.major(st.st_rdev) != PTS_MAJOR:
        return False, "not_pts_major"
    if st.st_uid != uid:
        return False, "tty_uid_mismatch"
    if st.st_rdev != expected_rdev:
        return False, "rdev_mismatch"
    return True, "ok"


def decision_tree(
    *,
    front_stale: bool,
    harness: dict[str, Any],
    tty: dict[str, Any],
    sysctl_value: str | None,
    server: str | None = None,
    session_type: str = "",
) -> dict[str, Any]:
    """Pure plan: recommended_route in {noop, manual, tty_inject, gui_unsupported}."""
    srv = validate_server(server if server is not None else DEFAULT_SERVER)
    manual_cmd = f"/mcp reconnect {srv or DEFAULT_SERVER}"
    plan: dict[str, Any] = {
        "front_stale": bool(front_stale),
        "harness": harness.get("harness") if harness.get("found") else None,
        "harness_pid": harness.get("pid"),
        "tty": tty.get("path") if tty.get("ok") else None,
        "sysctl": sysctl_value,
        "manual_command": manual_cmd,
        "caveats": list(CAVEATS),
    }
    if not front_stale:
        plan.update(recommended_route="noop", reason="front_stale=false")
    elif srv is None:
        plan.update(recommended_route="manual", reason="invalid_server_name")
    elif not harness.get("found"):
        plan.update(recommended_route="gui_unsupported" if session_type.lower() == "wayland" else "manual", reason=harness.get("reason", "harness_not_found"))
    elif not tty.get("ok"):
        plan.update(recommended_route="gui_unsupported" if session_type.lower() == "wayland" else "manual", reason=tty.get("reason", "no_tty"))
    elif sysctl_value is None:
        plan.update(recommended_route="manual", reason="unsupported:sysctl_absent")
    else:
        plan.update(recommended_route="tty_inject", reason="ok")
    return plan


# ---------------------------------------------------------------------------------------------------------------
# Privileged helper. Runs as root under `sudo -n /usr/bin/python3 -I -S -c`. Receives (major, minor, payload_hex)
# in argv and the TTY as an already-validated fd 0 (sudo closes fds >= 3). It never receives a path.
# Exit codes: 0 ok | 2 bad args/payload | 3 sysctl absent | 4 ioctl refused | 5 restore mismatch | 6 stdin mismatch.
# ---------------------------------------------------------------------------------------------------------------
HELPER_SCRIPT = r"""
import fcntl, json, os, re, signal, stat, sys, termios

SYSCTL = "/proc/sys/dev/tty/legacy_tiocsti"
PTS_MAJOR = 136


def done(code, **kw):
    sys.stdout.write(json.dumps(kw))
    sys.stdout.flush()
    os._exit(code)


def _term(signum, frame):
    raise SystemExit(128 + signum)


try:
    major, minor, payload = int(sys.argv[1]), int(sys.argv[2]), bytes.fromhex(sys.argv[3])
except (IndexError, ValueError):
    done(2, error="bad_args")
if not re.fullmatch(rb"/mcp reconnect [a-z0-9][a-z0-9_-]{0,63}\r", payload):
    done(2, error="payload_rejected")
try:
    st = os.fstat(0)
    ok = os.isatty(0) and stat.S_ISCHR(st.st_mode) and major == PTS_MAJOR and st.st_rdev == os.makedev(major, minor)
except OSError:
    ok = False
if not ok:
    done(6, error="stdin_mismatch")
try:
    with open(SYSCTL) as f:
        orig = f.read().strip()
except OSError:
    done(3, error="sysctl_absent")

for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(s, _term)
injected = 0
code = 0
err = None
try:
    with open(SYSCTL, "w") as f:
        f.write("1")
    for b in payload:
        fcntl.ioctl(0, termios.TIOCSTI, bytes([b]))
        injected += 1
except OSError as e:
    code, err = 4, "ioctl:" + str(e.errno)
except SystemExit as e:
    code, err = 7, "signal:" + str(e.code)
finally:
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, signal.SIG_IGN)
    try:
        with open(SYSCTL, "w") as f:
            f.write(orig)
        with open(SYSCTL) as f:
            after = f.read().strip()
    except OSError:
        after = None
if after != orig:
    done(5, error="restore_mismatch", orig=orig, after=after, injected=injected)
done(code, error=err, orig=orig, after=after, injected=injected)
"""

HELPER_CMD_PREFIX: tuple[str, ...] = ("sudo", "-n", "/usr/bin/python3", "-I", "-S", "-c")
HELPER_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}
HELPER_TIMEOUT_S = 10.0
LOCK_NAME = "aep_harness_reconnect.lock"


class LockBusyError(RuntimeError):
    """Another injection holds the lock (BUSY)."""


class NoRuntimeDirError(RuntimeError):
    """No $XDG_RUNTIME_DIR nor /run/user/<uid>: fail-closed."""


def read_sysctl(path: str = SYSCTL_PATH) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def acquire_lock(uid: int | None = None) -> int:
    """Non-blocking exclusive flock on a 0600 lockfile under the user runtime dir. Fail-closed."""
    u = os.getuid() if uid is None else uid
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{u}"
    if not os.path.isdir(base):
        raise NoRuntimeDirError(base)
    fd = os.open(os.path.join(base, LOCK_NAME), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise LockBusyError(base) from exc
    return fd


def release_lock(fd: int) -> None:
    if fd < 0:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def open_tty(path: str) -> int:
    """Open as the invoking user (never root), no ctty, never following symlinks."""
    return os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NOFOLLOW)


def run_helper(major: int, minor: int, payload_hex: str, tty_fd: int, timeout: float = HELPER_TIMEOUT_S) -> tuple[int, str, bool]:
    """Run the sudo helper with the TTY fd as stdin. Returns (rc, stdout, timed_out). Timeout -> SIGTERM to the group."""
    cmd = [*HELPER_CMD_PREFIX, HELPER_SCRIPT, str(major), str(minor), payload_hex]
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, absolute interpreter, no shell
        cmd, stdin=tty_fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=HELPER_ENV, start_new_session=True, text=True
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or "", False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            out, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            out = ""
        return proc.returncode if proc.returncode is not None else -1, out or "", True


@dataclass
class Adapters:
    """Every side-effecting dependency, injectable. Defaults are the real ones; `audit` is wired by the server."""

    read_sysctl: Callable[[], str | None] = read_sysctl
    acquire_lock: Callable[[], int] = acquire_lock
    release_lock: Callable[[int], None] = release_lock
    open_tty: Callable[[str], int] = open_tty
    check_fd: Callable[[int, int, int], tuple[bool, str]] = check_tty_fd
    run_helper: Callable[..., tuple[int, str, bool]] = run_helper
    audit: Callable[[str, dict[str, Any]], bool] = field(default=lambda _status, _details: False)


def dry_adapters(audit: Callable[[str, dict[str, Any]], bool] | None = None) -> Adapters:
    """AEP_HARNESS_RECONNECT_DRY=1 (tests): no sysctl, no pts, no sudo, no lock."""
    return Adapters(
        read_sysctl=lambda: "0",
        acquire_lock=lambda: -1,
        release_lock=lambda _fd: None,
        open_tty=lambda _p: os.open(os.devnull, os.O_RDWR),
        check_fd=lambda _fd, _rdev, _uid: (True, "dry"),
        run_helper=lambda _ma, _mi, _hex, _fd, timeout=0: (0, json.dumps({"dry": True, "injected": 0}), False),
        audit=audit or (lambda _s, _d: False),
    )


def real_adapters(audit: Callable[[str, dict[str, Any]], bool] | None = None) -> Adapters:
    if os.environ.get("AEP_HARNESS_RECONNECT_DRY") == "1":
        return dry_adapters(audit)
    return Adapters(audit=audit or (lambda _s, _d: False))


def build_plan(
    *,
    front_stale: bool,
    server: str | None = None,
    proc_root: str | Path = "/proc",
    start_pid: int | None = None,
    uid: int | None = None,
    session_type: str = "",
    adapters: Adapters | None = None,
) -> dict[str, Any]:
    """Read-only plan (any tier). Never opens a TTY nor touches the sysctl."""
    ad = adapters or real_adapters()
    harness = find_harness(proc_root, os.getpid() if start_pid is None else start_pid, os.getuid() if uid is None else uid)
    tty = resolve_tty(proc_root, harness["pid"]) if harness.get("found") else {"ok": False, "reason": "no_harness"}
    return decision_tree(
        front_stale=front_stale, harness=harness, tty=tty, sysctl_value=ad.read_sysctl(), server=server, session_type=session_type
    )


def execute(
    *,
    tier: str,
    confirm: bool,
    front_stale: bool,
    server: str | None = None,
    proc_root: str | Path = "/proc",
    start_pid: int | None = None,
    uid: int | None = None,
    adapters: Adapters | None = None,
    timeout: float = HELPER_TIMEOUT_S,
) -> dict[str, Any]:
    """Gated, fail-closed execution. Gate order: tier -> confirm -> front_stale -> ancestry -> allowlist -> tty ->
    sysctl -> flock -> open+validate tty -> audit attempt -> helper -> sysctl verify -> audit result."""
    ad = adapters or real_adapters()
    me = os.getuid() if uid is None else uid
    degraded = False

    def audit(status: str, details: dict[str, Any]) -> None:
        nonlocal degraded
        try:
            ok = bool(ad.audit(status, details))
        except Exception as exc:  # noqa: BLE001 - audit failure never blocks the report, but is never silent
            logger.warning("harness_reconnect audit failed: %s", exc)
            ok = False
        if not ok:
            degraded = True
            logger.warning("harness_reconnect audit_degraded status=%s details=%s", status, details)

    def done(status: str, reason: str, route: str = "manual", **extra: Any) -> dict[str, Any]:
        audit(status, {"reason": reason, **extra})
        return {"status": status, "reason": reason, "route": route, "audit_degraded": degraded, **extra}

    if tier != "7rwx":
        return done("REJECTED", "tier_insufficient")
    if confirm is not True:
        return done("REJECTED", "confirm_required")
    if not front_stale:
        return done("NOOP", "front_stale=false", route="noop")
    harness = find_harness(proc_root, os.getpid() if start_pid is None else start_pid, me)
    if not harness.get("found"):
        return done("REJECTED", harness["reason"])
    payload = build_payload(harness["harness"], server)
    if payload is None or not validate_payload(payload):
        return done("REJECTED", "payload_not_allowed")
    tty = resolve_tty(proc_root, harness["pid"])
    if not tty.get("ok"):
        return done("UNSUPPORTED", tty["reason"])
    sysctl_before = ad.read_sysctl()
    if sysctl_before is None:
        return done("UNSUPPORTED", "sysctl_absent")
    try:
        lock_fd = ad.acquire_lock()
    except LockBusyError:
        return done("BUSY", "lock_held")
    except (NoRuntimeDirError, OSError):
        return done("REJECTED", "no_runtime_dir")

    info: dict[str, Any] = {
        "harness_pid": harness["pid"],
        "tty_rdev": tty["rdev"],
        "server": server or DEFAULT_SERVER,
        "sysctl_before": sysctl_before,
    }
    tty_fd = -1
    try:
        try:
            tty_fd = ad.open_tty(tty["path"])
        except OSError:
            return done("UNSUPPORTED", "tty_open_failed", **info)
        ok, why = ad.check_fd(tty_fd, tty["rdev"], me)
        if not ok:
            return done("REJECTED", f"tty_validation:{why}", **info)
        audit("ATTEMPT", info)
        rc, timed_out, helper_error = -1, False, None
        try:
            rc, _out, timed_out = ad.run_helper(tty["major"], tty["minor"], payload.hex(), tty_fd, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - helper crash must still reach the restore verification below
            helper_error = type(exc).__name__
        info["sysctl_after"] = ad.read_sysctl()
        if info["sysctl_after"] != sysctl_before:
            return done("FAIL", "sysctl_not_restored", severity="CRITICAL", **info)
        if helper_error or timed_out:
            return done("FAIL", "helper_timeout" if timed_out else f"helper_error:{helper_error}", severity="HIGH", **info)
        if rc == 0:
            return done("OK", "injected", route="tty_inject", **info)
        if rc in (3, 4, 6):
            return done("UNSUPPORTED", {3: "sysctl_absent", 4: "ioctl_refused", 6: "stdin_mismatch"}[rc], **info)
        return done("FAIL", f"helper_rc_{rc}", severity="HIGH", **info)
    finally:
        if tty_fd >= 0:
            try:
                os.close(tty_fd)
            except OSError:
                pass
        ad.release_lock(lock_fd)
