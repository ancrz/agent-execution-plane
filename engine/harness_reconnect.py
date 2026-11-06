"""ONT-42a / 4D Bridge: harness_reconnect (`dimensional_bridge_4d`).

Out-of-band ("4th-dimension") harness control primitive: allows an agent operating inside a 3rd-dimension
chat/CLI session to step outside the harness boundary and reload/unblock its host harness (Claude Code,
Antigravity `agy`, OpenAI `codex`, or Google `gemini` CLI) via native out-of-band RPC (`rpc_reload`) or
a self-restoring kernel `dev.tty.legacy_tiocsti` + `TIOCSTI` window (`tty_inject`).

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

PRIMITIVE_NAME = "dimensional_bridge_4d"
DEFAULT_SERVER = "agent-execution-plane"
SERVER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HARNESS_RECONNECT: dict[str, str] = {
    "claude": "/mcp reconnect {server}",
    "codex": "/mcp reconnect {server}",
    "gemini": "/mcp reconnect {server}",
    "agy": "/mcp reconnect {server}",
}
HARNESS_PROFILES: dict[str, dict[str, Any]] = {
    "claude": {"transports": ("tty_inject",), "manual": "/mcp reconnect {server}"},
    "agy": {
        "transports": ("rpc_reload", "tty_inject"),
        "manual": "agy mcp add {server} <launcher> (or Connect-RPC RefreshMcpServers)",
    },
    "codex": {
        "transports": ("rpc_reload", "tty_inject"),
        "manual": "/mcp reconnect {server} (or codex app-server config/mcpServer/reload)",
    },
    "gemini": {"transports": ("tty_inject",), "manual": "/mcp reconnect {server}"},
}
SUPPORTED_HARNESSES: tuple[str, ...] = tuple(HARNESS_PROFILES.keys())
PTS_MAJOR = 136
SYSCTL_PATH = "/proc/sys/dev/tty/legacy_tiocsti"
MAX_ANCESTRY_DEPTH = 64
# Pointer emitted by discover/heal only when front_stale is true (token budget). A pure string, no new capability.
RECONNECT_POINTER = 'aep_ctl(domain="ipc", action="harness_reconnect", params={"mode":"plan"})'

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


# Claude Code installs versioned binaries (e.g. ~/.local/share/claude/versions/2.1.318); the resolved exe is a semver.
_VERSIONED_CLAUDE_RE = re.compile(r"^/.+/claude/versions/\d+\.\d+\.\d+$")
_EXE_ALIASES: dict[str, str] = {
    "claude": "claude",
    "agy": "agy",
    "antigravity": "agy",
    "codex": "codex",
    "codex-cli": "codex",
    "gemini": "gemini",
    "gemini-cli": "gemini",
}


def _harness_name(exe: str) -> str:
    """Map a resolved /proc/<pid>/exe target to a harness key ("" if unknown). Never uses comm/argv."""
    base = os.path.basename(exe)
    if base in _EXE_ALIASES:
        return _EXE_ALIASES[base]
    if base.startswith("language_server") or "/Antigravity/" in exe:
        return "agy"
    if "/@openai/codex/" in exe:
        return "codex"
    if "/@google/gemini-cli/" in exe:
        return "gemini"
    if "/../" not in exe and _VERSIONED_CLAUDE_RE.fullmatch(exe):
        return "claude"
    return ""


def find_harness(
    proc_root: str | Path,
    start_pid: int,
    uid: int,
    *,
    target_harness: str | None = None,
) -> dict[str, Any]:
    """Walk the real ancestry of `start_pid` looking for a known harness.

    Uses `/proc/<pid>/exe` (not comm/argv, both forgeable) and requires the same uid as the caller.
    If `target_harness` is explicitly specified and valid, filters or resolves to that harness.
    Returns {"found": bool, "reason": str, ...}.
    """
    if target_harness is not None:
        norm = _EXE_ALIASES.get(target_harness.strip().lower(), "")
        if norm not in HARNESS_PROFILES:
            return {"found": False, "reason": "unknown_target_harness"}
    else:
        norm = ""
    root = Path(proc_root)
    pid = start_pid
    seen: set[int] = set()
    for _ in range(MAX_ANCESTRY_DEPTH):
        if pid <= 1 or pid in seen:
            break
        seen.add(pid)
        try:
            exe_base = _harness_name(os.readlink(root / str(pid) / "exe"))
            owner = (root / str(pid)).stat().st_uid
        except OSError:
            exe_base, owner = "", -1
        if exe_base in HARNESS_RECONNECT and (not norm or exe_base == norm):
            if owner != uid:
                return {"found": False, "reason": "harness_uid_mismatch", "pid": pid}
            return {"found": True, "reason": "ok", "pid": pid, "harness": exe_base}
        st = _read_stat(root, pid)
        if st is None:
            break
        pid = st["ppid"]
    if norm in ("agy", "codex"):
        # Out-of-band RPC harnesses (agy language_server, codex app-server) can be targeted directly by the agent.
        return {"found": True, "reason": "target_override", "pid": start_pid, "harness": norm}
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
    rpc_info: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Pure plan: recommended_route in {noop, manual, tty_inject, rpc_reload, gui_unsupported}."""
    srv = validate_server(server if server is not None else DEFAULT_SERVER)
    hname = harness.get("harness") if harness.get("found") else None
    profile = HARNESS_PROFILES.get(str(hname or ""), {})
    manual_tmpl = str(profile.get("manual") or "/mcp reconnect {server}")
    manual_cmd = manual_tmpl.format(server=srv or DEFAULT_SERVER)
    rpc_avail = bool((rpc_info or {}).get("available"))
    plan: dict[str, Any] = {
        "primitive": PRIMITIVE_NAME,
        "supported_harnesses": list(SUPPORTED_HARNESSES),
        "front_stale": bool(front_stale),
        "harness": hname,
        "harness_pid": harness.get("pid"),
        "tty": tty.get("path") if tty.get("ok") else None,
        "sysctl": sysctl_value,
        "rpc_available": rpc_avail,
        "manual_command": manual_cmd,
        "caveats": list(CAVEATS),
    }
    if not front_stale and not force:
        plan.update(recommended_route="noop", reason="front_stale=false")
    elif srv is None:
        plan.update(recommended_route="manual", reason="invalid_server_name")
    elif not harness.get("found"):
        plan.update(recommended_route="gui_unsupported" if session_type.lower() == "wayland" else "manual", reason=harness.get("reason", "harness_not_found"))
    elif rpc_avail and "rpc_reload" in profile.get("transports", ()):
        plan.update(recommended_route="rpc_reload", reason="ok")
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
    fd = os.open(os.path.join(base, LOCK_NAME), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
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


def _probe_rpc(harness: str) -> dict[str, Any]:
    """Read-only probe for native out-of-band RPC channels (Antigravity Connect-RPC or Codex app-server sock)."""
    if harness == "codex":
        base = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
        sock = base / "app-server-control" / "app-server-control.sock"
        try:
            is_sock = sock.exists() and stat.S_ISSOCK(sock.stat().st_mode)
        except OSError:
            is_sock = False
        return {"available": is_sock, "transport": "codex_app_server_sock", "endpoint": str(sock) if is_sock else None}
    if harness == "agy":
        try:
            ps = subprocess.check_output(["ps", "-eo", "pid,args"], text=True, timeout=3)
            for line in ps.splitlines():
                if "language_server" in line and "--csrf_token" in line:
                    return {"available": True, "transport": "connect_rpc", "pid": int(line.split()[0])}
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return {"available": False, "transport": "connect_rpc"}
    return {"available": False}


def _run_rpc(harness: str, server: str) -> tuple[bool, str]:
    """Execute out-of-band RPC reload for `agy` (RefreshMcpServers) or `codex` (config/mcpServer/reload)."""
    if validate_server(server) is None:
        return False, "invalid_server_name"
    if harness == "codex":
        base = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
        sock = base / "app-server-control" / "app-server-control.sock"
        try:
            if not (sock.exists() and stat.S_ISSOCK(sock.stat().st_mode)):
                return False, "codex_sock_absent"
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                ["codex", "app-server", "proxy", "--sock", str(sock)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            try:
                for msg in (
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "aep-4d", "version": "1.0.0"}}},
                    {"jsonrpc": "2.0", "method": "initialized", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "config/mcpServer/reload", "params": None},
                ):
                    if proc.stdin is not None:
                        proc.stdin.write(json.dumps(msg) + "\n")
                        proc.stdin.flush()
            finally:
                proc.terminate()
                proc.wait(timeout=3)
            return True, "codex_rpc_reloaded"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"codex_rpc_error:{type(exc).__name__}"
    if harness == "agy":
        try:
            ps = subprocess.check_output(["ps", "-eo", "pid,args"], text=True, timeout=3)
            ss = subprocess.check_output(["ss", "-tulnp"], text=True, timeout=3)
            for line in ps.splitlines():
                if "language_server" in line and "--csrf_token" in line:
                    pid = line.split()[0]
                    m = re.search(r"--csrf_token\s+(\S+)", line)
                    tok = m.group(1) if m else ""
                    for port in re.findall(r"127\.0\.0\.1:(\d+).*?pid=" + re.escape(pid) + r",", ss):
                        for scheme in ("https", "http"):
                            res = subprocess.run(  # noqa: S603 - fixed curl argv to localhost
                                [
                                    "curl", "-sk", "--max-time", "5", "-w", "%{http_code}", "-o", "/dev/null", "-X", "POST",
                                    f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RefreshMcpServers",
                                    "-H", "Content-Type: application/json",
                                    "-H", "Connect-Protocol-Version: 1",
                                    "-H", f"x-codeium-csrf-token: {tok}", "-d", "{}",
                                ],
                                capture_output=True, text=True, timeout=6, check=False,
                            )
                            if res.stdout.strip() in ("200", "204"):
                                return True, "agy_connect_rpc_reloaded"
            return False, "agy_language_server_unreachable"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"agy_rpc_error:{type(exc).__name__}"
    return False, "rpc_unsupported_for_harness"


@dataclass
class Adapters:
    """Every side-effecting dependency, injectable. Defaults are the real ones; `audit` is wired by the server."""

    read_sysctl: Callable[[], str | None] = read_sysctl
    acquire_lock: Callable[[], int] = acquire_lock
    release_lock: Callable[[int], None] = release_lock
    open_tty: Callable[[str], int] = open_tty
    check_fd: Callable[[int, int, int], tuple[bool, str]] = check_tty_fd
    run_helper: Callable[..., tuple[int, str, bool]] = run_helper
    probe_rpc: Callable[[str], dict[str, Any]] = field(default=lambda _h: {"available": False})
    run_rpc: Callable[[str, str], tuple[bool, str]] = field(default=lambda _h, _s: (False, "rpc_disabled"))
    audit: Callable[[str, dict[str, Any]], bool] = field(default=lambda _status, _details: False)


def dry_adapters(audit: Callable[[str, dict[str, Any]], bool] | None = None) -> Adapters:
    """AEP_HARNESS_RECONNECT_DRY=1 (tests): no sysctl, no pts, no sudo, no lock, no live RPC."""
    return Adapters(
        read_sysctl=lambda: "0",
        acquire_lock=lambda: -1,
        release_lock=lambda _fd: None,
        open_tty=lambda _p: os.open(os.devnull, os.O_RDWR),
        check_fd=lambda _fd, _rdev, _uid: (True, "dry"),
        run_helper=lambda _ma, _mi, _hex, _fd, timeout=0: (0, json.dumps({"dry": True, "injected": 0}), False),
        probe_rpc=lambda _h: {"available": False},
        run_rpc=lambda _h, _s: (True, "dry_rpc"),
        audit=audit or (lambda _s, _d: False),
    )


def real_adapters(audit: Callable[[str, dict[str, Any]], bool] | None = None) -> Adapters:
    if os.environ.get("AEP_HARNESS_RECONNECT_DRY") == "1":
        return dry_adapters(audit)
    return Adapters(probe_rpc=_probe_rpc, run_rpc=_run_rpc, audit=audit or (lambda _s, _d: False))


def build_plan(
    *,
    front_stale: bool,
    server: str | None = None,
    proc_root: str | Path = "/proc",
    start_pid: int | None = None,
    uid: int | None = None,
    session_type: str = "",
    target_harness: str | None = None,
    force: bool = False,
    adapters: Adapters | None = None,
) -> dict[str, Any]:
    """Read-only plan (any tier). Never opens a TTY nor touches the sysctl."""
    ad = adapters or real_adapters()
    harness = find_harness(
        proc_root,
        os.getpid() if start_pid is None else start_pid,
        os.getuid() if uid is None else uid,
        target_harness=target_harness,
    )
    tty = resolve_tty(proc_root, harness["pid"]) if harness.get("found") else {"ok": False, "reason": "no_harness"}
    rpc_info = ad.probe_rpc(str(harness.get("harness") or "")) if harness.get("found") else {"available": False}
    return decision_tree(
        front_stale=front_stale,
        harness=harness,
        tty=tty,
        sysctl_value=ad.read_sysctl(),
        server=server,
        session_type=session_type,
        rpc_info=rpc_info,
        force=force,
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
    target_harness: str | None = None,
    force: bool = False,
    adapters: Adapters | None = None,
    timeout: float = HELPER_TIMEOUT_S,
) -> dict[str, Any]:
    """Gated, fail-closed execution. Gate order: tier -> confirm -> front_stale/force -> ancestry/target -> allowlist ->
    rpc_reload (if available) or (tty -> sysctl -> flock -> open+validate tty -> audit attempt -> helper -> sysctl verify) -> audit result."""
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
        return {
            "primitive": PRIMITIVE_NAME,
            "status": status,
            "reason": reason,
            "route": route,
            "audit_degraded": degraded,
            **extra,
        }

    if tier != "7rwx":
        return done("REJECTED", "tier_insufficient")
    if confirm is not True:
        return done("REJECTED", "confirm_required")
    if not front_stale and not force:
        return done("NOOP", "front_stale=false", route="noop")
    harness = find_harness(proc_root, os.getpid() if start_pid is None else start_pid, me, target_harness=target_harness)
    if not harness.get("found"):
        return done("REJECTED", harness["reason"])
    hname = str(harness["harness"])
    payload = build_payload(hname, server)
    if payload is None or not validate_payload(payload):
        return done("REJECTED", "payload_not_allowed")

    # Out-of-band RPC route (agy Connect-RPC / codex app-server sock) when available: zero sysctl/TTY mutation.
    rpc_info = ad.probe_rpc(hname)
    if rpc_info.get("available") and "rpc_reload" in HARNESS_PROFILES.get(hname, {}).get("transports", ()):
        try:
            lock_fd = ad.acquire_lock()
        except LockBusyError:
            return done("BUSY", "lock_held")
        except (NoRuntimeDirError, OSError):
            return done("REJECTED", "no_runtime_dir")
        rpc_meta: dict[str, Any] = {
            "harness": hname,
            "harness_pid": harness["pid"],
            "server": server or DEFAULT_SERVER,
            "transport": rpc_info.get("transport", "rpc"),
        }
        try:
            audit("ATTEMPT", rpc_meta)
            ok_rpc, why_rpc = ad.run_rpc(hname, server or DEFAULT_SERVER)
            if ok_rpc:
                return done("OK", why_rpc, route="rpc_reload", **rpc_meta)
            return done("FAIL", why_rpc, route="manual", severity="HIGH", **rpc_meta)
        finally:
            ad.release_lock(lock_fd)

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
        "harness": hname,
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
