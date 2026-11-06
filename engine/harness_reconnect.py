"""ONT-42a: harness_reconnect. Reload the orchestrator's MCP front by typing `/mcp reconnect <server>` into the
harness TTY (TIOCSTI) inside a short, self-restoring sysctl window.

Design: pure functions with injected dependencies (no import of `server`). Everything is fail-closed: any
missing link resolves to route `manual` / `unsupported` and never changes host state.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

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
