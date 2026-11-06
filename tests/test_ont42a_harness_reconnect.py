"""ONT-42a harness_reconnect: pure functions and gates. No real sysctl, TTY or sudo is ever touched."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine import harness_reconnect as hr


def _mk_proc(root: Path, pid: int, ppid: int, exe: str, tty_nr: int = 0, comm: str = "x") -> None:
    d = root / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} {pid} {tty_nr} 0 0\n")
    link = d / "exe"
    if link.is_symlink():
        link.unlink()
    link.symlink_to(exe)


def _pts_nr(minor: int) -> int:
    return (hr.PTS_MAJOR << 8) | (minor & 0xFF) | ((minor & ~0xFF) << 12)


def test_parse_proc_stat_handles_parens_in_comm() -> None:
    st = hr.parse_proc_stat("12 (a) b (c)) S 7 12 12 34816 0")
    assert st == {"ppid": 7, "tty_nr": 34816}
    assert hr.parse_proc_stat("garbage") is None


def test_tty_nr_roundtrip() -> None:
    assert hr.tty_nr_to_dev(_pts_nr(5)) == (136, 5)
    assert hr.tty_nr_to_dev(_pts_nr(300)) == (136, 300)


def test_find_harness_by_real_ancestry(tmp_path: Path) -> None:
    _mk_proc(tmp_path, 100, 1, "/usr/bin/claude", _pts_nr(3), comm="evil")
    _mk_proc(tmp_path, 200, 100, "/usr/bin/python3")
    _mk_proc(tmp_path, 300, 200, "/usr/bin/python3")
    res = hr.find_harness(tmp_path, 300, os.getuid())
    assert res["found"] and res["pid"] == 100 and res["harness"] == "claude"


def test_find_harness_ignores_forged_comm(tmp_path: Path) -> None:
    _mk_proc(tmp_path, 100, 1, "/usr/bin/bash", comm="claude")
    _mk_proc(tmp_path, 200, 100, "/usr/bin/python3")
    assert hr.find_harness(tmp_path, 200, os.getuid())["found"] is False


def test_find_harness_rejects_other_uid(tmp_path: Path) -> None:
    _mk_proc(tmp_path, 100, 1, "/usr/bin/claude")
    _mk_proc(tmp_path, 200, 100, "/usr/bin/python3")
    res = hr.find_harness(tmp_path, 200, os.getuid() + 1)
    assert res == {"found": False, "reason": "harness_uid_mismatch", "pid": 100}


def test_find_harness_not_in_ancestry_and_cycle(tmp_path: Path) -> None:
    _mk_proc(tmp_path, 10, 20, "/usr/bin/python3")
    _mk_proc(tmp_path, 20, 10, "/usr/bin/python3")
    assert hr.find_harness(tmp_path, 10, os.getuid())["reason"] == "harness_not_in_ancestry"


def test_resolve_tty(tmp_path: Path) -> None:
    _mk_proc(tmp_path, 1000, 1, "/usr/bin/claude", _pts_nr(7))
    _mk_proc(tmp_path, 1001, 1, "/usr/bin/claude", 0)
    _mk_proc(tmp_path, 1002, 1, "/usr/bin/claude", (4 << 8) | 1)
    ok = hr.resolve_tty(tmp_path, 1000)
    assert ok["ok"] and ok["path"] == "/dev/pts/7" and ok["rdev"] == os.makedev(136, 7)
    assert hr.resolve_tty(tmp_path, 1001)["reason"] == "no_controlling_tty"
    assert hr.resolve_tty(tmp_path, 1002)["reason"] == "not_a_pts"
    assert hr.resolve_tty(tmp_path, 9999)["ok"] is False


def test_build_payload_allowlist() -> None:
    assert hr.build_payload("claude", None) == b"/mcp reconnect agent-execution-plane\r"
    assert hr.build_payload("claude", "my_srv-1") == b"/mcp reconnect my_srv-1\r"
    for bad in ("", "A", "-x", "a b", "a;rm", "a\x1b", "x" * 65, "a\r"):
        assert hr.build_payload("claude", bad) is None
    assert hr.build_payload("codex", "x") is None


def test_validate_payload_rejects_control_bytes() -> None:
    assert hr.validate_payload(b"/mcp reconnect abc\r")
    for bad in (b"/mcp reconnect abc", b"/mcp reconnect abc\r\r", b"/mcp reconnect a\x1bc\r", b"rm -rf /\r", b"/mcp reconnect abc\n"):
        assert not hr.validate_payload(bad)


def test_check_tty_fd_rejects_regular_file_and_non_tty(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_text("x")
    fd = os.open(f, os.O_RDONLY)
    try:
        assert hr.check_tty_fd(fd, 0, os.getuid()) == (False, "not_a_tty")
    finally:
        os.close(fd)
    assert hr.check_tty_fd(-1, 0, os.getuid())[0] is False


def _h(found: bool = True, **kw: object) -> dict:
    return {"found": found, "pid": 5, "harness": "claude", "reason": "ok", **kw}


def _t(ok: bool = True) -> dict:
    return {"ok": ok, "path": "/dev/pts/3", "reason": "no_controlling_tty"}


@pytest.mark.parametrize(
    ("kwargs", "route"),
    [
        (dict(front_stale=False, harness=_h(), tty=_t(), sysctl_value="0"), "noop"),
        (dict(front_stale=True, harness=_h(False, reason="harness_not_in_ancestry"), tty=_t(), sysctl_value="0"), "manual"),
        (dict(front_stale=True, harness=_h(False), tty=_t(), sysctl_value="0", session_type="wayland"), "gui_unsupported"),
        (dict(front_stale=True, harness=_h(), tty=_t(False), sysctl_value="0"), "manual"),
        (dict(front_stale=True, harness=_h(), tty=_t(), sysctl_value=None), "manual"),
        (dict(front_stale=True, harness=_h(), tty=_t(), sysctl_value="0", server="BAD NAME"), "manual"),
        (dict(front_stale=True, harness=_h(), tty=_t(), sysctl_value="0"), "tty_inject"),
    ],
)
def test_decision_tree_routes(kwargs: dict, route: str) -> None:
    plan = hr.decision_tree(**kwargs)
    assert plan["recommended_route"] == route
    assert plan["caveats"] and "typed-prompt" in plan["caveats"][0]
