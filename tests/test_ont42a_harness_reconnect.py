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
    for hname in ("claude", "codex", "gemini", "agy"):
        assert hr.build_payload(hname, None) == b"/mcp reconnect agent-execution-plane\r"
        assert hr.build_payload(hname, "my_srv-1") == b"/mcp reconnect my_srv-1\r"
    for bad in ("", "A", "-x", "a b", "a;rm", "a\x1b", "x" * 65, "a\r"):
        assert hr.build_payload("claude", bad) is None
    assert hr.build_payload("unknown_harness", "x") is None


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


# ---------------------------------------------------------------------------------------------------------------
# execute(): every collaborator is a double. Nothing here opens /dev/pts, writes /proc/sys or runs sudo.
# ---------------------------------------------------------------------------------------------------------------


class _Rec:
    def __init__(self, *, sysctl: list[str | None] | None = None, helper: object = (0, "{}", False), lock: object = 5) -> None:
        self.sysctl = list(sysctl or ["0", "0"])
        self.helper = helper
        self.lock = lock
        self.audits: list[tuple[str, dict]] = []
        self.helper_calls = 0
        self.released: list[int] = []
        self.audit_ok = True

    def adapters(self) -> hr.Adapters:
        def read() -> str | None:
            return self.sysctl.pop(0) if len(self.sysctl) > 1 else self.sysctl[0]

        def lock() -> int:
            if isinstance(self.lock, Exception):
                raise self.lock
            return int(self.lock)  # type: ignore[arg-type]

        def helper(*_a: object, **_k: object) -> tuple[int, str, bool]:
            self.helper_calls += 1
            if isinstance(self.helper, Exception):
                raise self.helper
            return self.helper  # type: ignore[return-value]

        def audit(status: str, details: dict) -> bool:
            self.audits.append((status, details))
            if not self.audit_ok:
                raise RuntimeError("ledger ro")
            return True

        return hr.Adapters(
            read_sysctl=read,
            acquire_lock=lock,
            release_lock=self.released.append,
            open_tty=lambda _p: os.open(os.devnull, os.O_RDWR),
            check_fd=lambda _fd, _rdev, _uid: (True, "ok"),
            run_helper=helper,
            audit=audit,
        )


def _proc(tmp_path: Path) -> Path:
    _mk_proc(tmp_path, 100, 1, "/usr/bin/claude", _pts_nr(3))
    _mk_proc(tmp_path, 200, 100, "/usr/bin/python3")
    return tmp_path


def _run(tmp_path: Path, rec: _Rec, **over: object) -> dict:
    kw: dict = dict(tier="7rwx", confirm=True, front_stale=True, proc_root=_proc(tmp_path), start_pid=200, adapters=rec.adapters())
    kw.update(over)
    return hr.execute(**kw)


def test_execute_happy_path_and_audit_pair(tmp_path: Path) -> None:
    rec = _Rec()
    res = _run(tmp_path, rec)
    assert res["status"] == "OK" and res["route"] == "tty_inject" and res["audit_degraded"] is False
    assert [s for s, _ in rec.audits] == ["ATTEMPT", "OK"]
    assert rec.helper_calls == 1 and rec.released == [5]
    assert "mcp reconnect" not in str(rec.audits)


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        (dict(tier="6rw-"), "tier_insufficient"),
        (dict(tier="FULL"), "tier_insufficient"),
        (dict(confirm=False), "confirm_required"),
        (dict(confirm="yes"), "confirm_required"),
        (dict(server="bad name;"), "payload_not_allowed"),
        (dict(start_pid=999), "harness_not_in_ancestry"),
        (dict(uid=os.getuid() + 1), "harness_uid_mismatch"),
    ],
)
def test_execute_rejections_never_reach_helper(tmp_path: Path, over: dict, reason: str) -> None:
    rec = _Rec()
    res = _run(tmp_path, rec, **over)
    assert res["status"] == "REJECTED" and res["reason"] == reason
    assert rec.helper_calls == 0 and rec.audits  # rejections are audited


def test_execute_noop_when_front_not_stale(tmp_path: Path) -> None:
    rec = _Rec()
    res = _run(tmp_path, rec, front_stale=False)
    assert res["status"] == "NOOP" and rec.helper_calls == 0


def test_execute_unsupported_when_sysctl_absent(tmp_path: Path) -> None:
    rec = _Rec(sysctl=[None])
    res = _run(tmp_path, rec)
    assert res["status"] == "UNSUPPORTED" and res["route"] == "manual" and rec.helper_calls == 0


def test_execute_busy_and_no_runtime_dir(tmp_path: Path) -> None:
    assert _run(tmp_path, _Rec(lock=hr.LockBusyError("x")))["status"] == "BUSY"
    res = _run(tmp_path, _Rec(lock=hr.NoRuntimeDirError("x")))
    assert res["status"] == "REJECTED" and res["reason"] == "no_runtime_dir"


def test_execute_sysctl_restored_when_helper_raises(tmp_path: Path) -> None:
    rec = _Rec(helper=RuntimeError("boom"))
    res = _run(tmp_path, rec)
    assert res["status"] == "FAIL" and res["reason"].startswith("helper_error") and rec.released == [5]


def test_execute_sysctl_restored_when_helper_times_out(tmp_path: Path) -> None:
    res = _run(tmp_path, _Rec(helper=(-15, "", True)))
    assert res["status"] == "FAIL" and res["reason"] == "helper_timeout"


def test_execute_restore_mismatch_is_critical(tmp_path: Path) -> None:
    rec = _Rec(sysctl=["0", "1"])
    res = _run(tmp_path, rec)
    assert res["status"] == "FAIL" and res["severity"] == "CRITICAL" and res["reason"] == "sysctl_not_restored"
    assert rec.audits[-1][0] == "FAIL"


def test_execute_restore_mismatch_wins_over_helper_ok(tmp_path: Path) -> None:
    assert _run(tmp_path, _Rec(sysctl=["0", "1"], helper=(0, "{}", False)))["severity"] == "CRITICAL"


@pytest.mark.parametrize(("rc", "reason"), [(3, "sysctl_absent"), (4, "ioctl_refused"), (6, "stdin_mismatch")])
def test_execute_helper_unsupported_codes_fall_back_to_manual(tmp_path: Path, rc: int, reason: str) -> None:
    res = _run(tmp_path, _Rec(helper=(rc, "{}", False)))
    assert res["status"] == "UNSUPPORTED" and res["reason"] == reason and res["route"] == "manual"


def test_execute_other_helper_rc_fails(tmp_path: Path) -> None:
    assert _run(tmp_path, _Rec(helper=(5, "{}", False)))["status"] == "FAIL"


def test_execute_audit_failure_degrades_but_still_runs(tmp_path: Path) -> None:
    rec = _Rec()
    rec.audit_ok = False
    res = _run(tmp_path, rec)
    assert res["status"] == "OK" and res["audit_degraded"] is True
    assert [s for s, _ in rec.audits][0] == "ATTEMPT"  # attempted before the injection


def test_execute_tty_validation_failure_is_rejected(tmp_path: Path) -> None:
    rec = _Rec()
    ad = rec.adapters()
    ad.check_fd = lambda _fd, _rdev, _uid: (False, "rdev_mismatch")
    res = _run(tmp_path, rec, adapters=ad)
    assert res["status"] == "REJECTED" and "rdev_mismatch" in res["reason"] and rec.helper_calls == 0
    assert rec.released == [5]


def test_build_plan_is_read_only_and_flags_route(tmp_path: Path) -> None:
    plan = hr.build_plan(front_stale=True, proc_root=_proc(tmp_path), start_pid=200, adapters=_Rec().adapters())
    assert plan["recommended_route"] == "tty_inject" and plan["tty"] == "/dev/pts/3"


def test_dry_adapters_never_touch_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEP_HARNESS_RECONNECT_DRY", "1")
    res = hr.execute(tier="7rwx", confirm=True, front_stale=True, proc_root=_proc(tmp_path), start_pid=200)
    assert res["status"] == "OK" and res["audit_degraded"] is True


def test_acquire_lock_contention_and_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    fd = hr.acquire_lock()
    try:
        assert (tmp_path / hr.LOCK_NAME).stat().st_mode & 0o777 == 0o600
        with pytest.raises(hr.LockBusyError):
            hr.acquire_lock()
    finally:
        hr.release_lock(fd)
    hr.release_lock(hr.acquire_lock())
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "missing"))
    with pytest.raises(hr.NoRuntimeDirError):
        hr.acquire_lock()


# ---------------------------------------------------------------------------------------------------------------
# T3/T4: schema (interdep) and the aep_ctl ipc branch.
# ---------------------------------------------------------------------------------------------------------------


def test_schema_declares_harness_reconnect_with_valid_tier() -> None:
    from engine.privilege import CONTROL_PLANE_SCHEMA

    ipc = CONTROL_PLANE_SCHEMA["ipc"]
    assert "harness_reconnect" in ipc["actions"]
    pre = ipc["preconditions"]["harness_reconnect"]
    assert pre["privilege_tier"] in ("FULL", "DIMINISHED")  # never "7rwx" (test_net_security_telemetry contract)
    assert pre["deterministic"] is True and "fail_soft_behavior" in pre
    assert set(ipc["actions"]) == set(ipc["preconditions"])
    for old in ("status", "ping", "lease", "release", "reap", "pool", "flush", "metrics", "stats", "cache"):
        assert old in ipc["actions"]


def _ctl(**kw: object) -> dict:
    import asyncio
    import json

    import server

    return json.loads(asyncio.run(server.aep_ctl(domain="ipc", action="harness_reconnect", **kw)))  # type: ignore[arg-type]


def test_ipc_plan_is_read_only_and_carries_caveats(monkeypatch: pytest.MonkeyPatch) -> None:
    import server

    monkeypatch.setattr(server, "_is_front_stale", lambda: True)
    res = _ctl(params={"mode": "plan"})
    assert res["status"] == "OK" and res["mode"] == "plan"
    assert res["primitive"] == hr.PRIMITIVE_NAME
    assert set(res["supported_harnesses"]) == {"claude", "agy", "codex", "gemini"}
    assert res["recommended_route"] in {"manual", "tty_inject", "rpc_reload", "gui_unsupported"}
    assert any("typed-prompt" in c for c in res["caveats"])


def test_multi_harness_session_steward_profiles_and_rpc(tmp_path: Path) -> None:
    # 1. Ancestry detection for agy, codex, gemini, and versioned claude
    for idx, (exe, expected) in enumerate(
        [
            ("/opt/Antigravity/antigravity", "agy"),
            ("/usr/local/bin/agy", "agy"),
            ("/usr/local/bin/codex", "codex"),
            ("/usr/local/bin/gemini", "gemini"),
            ("/home/u/.local/share/claude/versions/2.1.318", "claude"),
        ],
        start=1,
    ):
        sub = tmp_path / f"p_{idx}"
        _mk_proc(sub, 100, 1, exe, _pts_nr(4))
        _mk_proc(sub, 200, 100, "/usr/bin/python3")
        found = hr.find_harness(sub, 200, os.getuid())
        assert found["found"] and found["harness"] == expected

    # 2. Target override for RPC harnesses (agy / codex) and unknown target rejection
    empty_proc = tmp_path / "empty"
    _mk_proc(empty_proc, 200, 1, "/usr/bin/python3")
    assert hr.find_harness(empty_proc, 200, os.getuid(), target_harness="agy")["harness"] == "agy"
    assert hr.find_harness(empty_proc, 200, os.getuid(), target_harness="codex")["harness"] == "codex"
    assert hr.find_harness(empty_proc, 200, os.getuid(), target_harness="invalid")["reason"] == "unknown_target_harness"

    # 3. RPC reload route (agy / codex) executes without touching sysctl or TTY, and force=True bypasses front_stale=False
    rec = _Rec()
    ad = rec.adapters()
    ad.probe_rpc = lambda h: {"available": h in ("agy", "codex"), "transport": "connect_rpc"}
    ad.run_rpc = lambda h, s: (True, f"{h}_reloaded:{s}")
    plan = hr.build_plan(
        front_stale=False,
        force=True,
        target_harness="agy",
        proc_root=empty_proc,
        start_pid=200,
        adapters=ad,
    )
    assert plan["recommended_route"] == "rpc_reload" and plan["harness"] == "agy"
    res = hr.execute(
        tier="7rwx",
        confirm=True,
        front_stale=False,
        force=True,
        target_harness="agy",
        proc_root=empty_proc,
        start_pid=200,
        adapters=ad,
    )
    assert res["status"] == "OK" and res["route"] == "rpc_reload" and rec.helper_calls == 0
    assert [s for s, _ in rec.audits] == ["ATTEMPT", "OK"]
    assert hr.real_adapters().probe_rpc("claude")["available"] is False
    cert = hr.certify_loopback("hello world", proc_root=empty_proc, start_pid=200, target_harness="agy", adapters=ad)
    assert cert["status"] == "OK" and cert["certified"] is True and cert["message_received"] == "hello world"
    assert cert["primitive"] == "autonomous_session_steward"
    ctl_cert = _ctl(params={"mode": "certify", "message": "hello world"})
    assert ctl_cert["status"] == "OK" and ctl_cert["certified"] is True and ctl_cert["message_received"] == "hello world"


def test_console_reach_battery_across_installed_harnesses(tmp_path: Path) -> None:
    """Battery validating console/TUI reach for agy, claude, codex, and gemini:
    - Sibling peer-process discovery in /proc (e.g. agy agent targeting active claude on /dev/pts/0).
    - Prevention of caller-TTY theft when targeting an idle CLI/RPC harness (codex pid=None -> tty=None).
    - Full matrix probe (`probe_console_reach` / `mode='matrix'`) distinguishing `rpc_reload` vs `tty_inject`.
    """
    proc = tmp_path / "proc_multi"
    # Caller (PID 200) runs under Antigravity language_server (PID 100, GUI/no TTY) but has its own subshell pts/3
    _mk_proc(proc, 100, 1, "/opt/Antigravity/resources/bin/language_server", 0)
    _mk_proc(proc, 200, 100, "/usr/bin/python3", _pts_nr(3))
    # Sibling Claude Code TUI session (PID 300) running on /dev/pts/0
    _mk_proc(proc, 300, 1, "/home/u/.local/share/claude/versions/2.1.319", _pts_nr(0))

    # 1. Peer-process discovery: targeting 'claude' from 'agy' child finds PID 300 on /dev/pts/0
    found_claude = hr.find_harness(proc, 200, os.getuid(), target_harness="claude")
    assert found_claude == {"found": True, "reason": "peer_process", "pid": 300, "harness": "claude"}
    assert hr.resolve_tty(proc, found_claude["pid"])["path"] == "/dev/pts/0"

    # 2. Idle RPC/CLI harness ('codex' not in /proc): target_override sets pid=None and NEVER steals caller's /dev/pts/3
    found_codex = hr.find_harness(proc, 200, os.getuid(), target_harness="codex")
    assert found_codex == {"found": True, "reason": "target_override", "pid": None, "harness": "codex"}
    assert hr.resolve_tty(proc, found_codex["pid"]) == {"ok": False, "reason": "no_controlling_tty"}

    # 3. Matrix reach evaluation across all 4 harnesses
    ad = _Rec().adapters()
    ad.probe_rpc = lambda h: {"available": h in ("agy", "codex"), "transport": f"{h}_rpc"}
    matrix = hr.probe_console_reach(proc_root=proc, start_pid=200, uid=os.getuid(), adapters=ad)
    assert matrix["status"] == "OK" and matrix["mode"] == "matrix"
    hmap = matrix["harnesses"]
    assert hmap["claude"]["active_pid"] == 300 and hmap["claude"]["controlling_tty"] == "/dev/pts/0"
    assert hmap["claude"]["recommended_route"] == "tty_inject" and hmap["claude"]["requires_sudo_tiocsti"] is True
    assert hmap["agy"]["active_pid"] == 100 and hmap["agy"]["controlling_tty"] is None
    assert hmap["agy"]["recommended_route"] == "rpc_reload" and hmap["agy"]["requires_sudo_tiocsti"] is False
    assert hmap["codex"]["active_pid"] is None and hmap["codex"]["controlling_tty"] is None
    assert hmap["codex"]["recommended_route"] == "rpc_reload" and hmap["codex"]["requires_sudo_tiocsti"] is False
    assert hmap["gemini"]["active_pid"] is None and hmap["gemini"]["recommended_route"] == "manual"
    ctl_mat = _ctl(params={"mode": "matrix"})
    assert ctl_mat["status"] == "OK" and set(ctl_mat["harnesses"]) == {"claude", "agy", "codex", "gemini"}

    # 4. When agy or codex runs in a console (/dev/pts/4), kernel tty_inject takes precedence over rpc_reload
    for hname, exe in (("agy", "/usr/local/bin/agy"), ("codex", "/usr/local/bin/codex")):
        sub = tmp_path / f"pts_{hname}"
        _mk_proc(sub, 500, 1, exe, _pts_nr(4))
        p_pts = hr.build_plan(front_stale=True, target_harness=hname, proc_root=sub, start_pid=500, adapters=ad)
        assert p_pts["tty"] == "/dev/pts/4" and p_pts["recommended_route"] == "tty_inject"




def test_ipc_execute_requires_tier_and_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    import server

    recorded: list[str] = []
    monkeypatch.setattr(server, "record_audit_event", lambda *_a, **k: recorded.append(k["status"]))
    monkeypatch.setattr(server, "_is_front_stale", lambda: True)
    monkeypatch.setattr(server, "get_effective_chmod_tier", lambda *a, **k: {"tier": "4r--"})
    low = _ctl(params={"mode": "execute", "confirm": True})
    assert low["status"] == "REJECTED" and low["reason"] == "tier_insufficient"
    monkeypatch.setattr(server, "get_effective_chmod_tier", lambda *a, **k: {"tier": "7rwx"})
    no_confirm = _ctl(params={"mode": "execute"})
    assert no_confirm["reason"] == "confirm_required"
    assert _ctl(params={"mode": "execute", "confirm": "true"})["reason"] == "confirm_required"  # strict bool, not truthy
    assert recorded == ["REJECTED", "REJECTED", "REJECTED"] and no_confirm["audit_degraded"] is False


def test_ipc_unknown_mode_is_error() -> None:
    res = _ctl(params={"mode": "yolo"})
    assert res["status"] == "ERROR" and res["valid"] == ["plan", "execute"]


# ---------------------------------------------------------------------------------------------------------------
# T5: D-25 (commit drift is informational; fingerprint / LKG / unavailable fingerprint decide stale).
# ---------------------------------------------------------------------------------------------------------------


def _discover(monkeypatch: pytest.MonkeyPatch, *, loaded_fp: str, disk_fp: str, lkg: bool = False, front: bool = False, verbosity: str = "detail", drift: bool = True) -> dict:
    import asyncio
    import json

    import server

    monkeypatch.setattr(server, "LOADED_COMMIT", "old1111" if drift else "new2222")
    monkeypatch.setattr(server, "_read_git_head_commit", lambda: "new2222")
    monkeypatch.setattr(server, "LOADED_FINGERPRINT", loaded_fp)
    monkeypatch.setattr(server, "code_fingerprint", lambda *_a, **_k: disk_fp)
    monkeypatch.setattr(server, "_is_front_stale", lambda: front)
    if lkg:
        orig = server._get_live_meta
        monkeypatch.setattr(server, "_get_live_meta", lambda: {**orig(), "serving_from": "lkg"})
    return json.loads(asyncio.run(server.discover(action="capabilities", verbosity=verbosity, force_refresh=True)))


def test_d25_docs_only_commit_is_not_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _discover(monkeypatch, loaded_fp="fp1", disk_fp="fp1")
    assert data["stale"] is False and data["commit_drift"] is True
    assert "restart" not in data["next_action"].lower() and "docs-only" in data["next_action"]


def test_d25_code_changing_commit_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _discover(monkeypatch, loaded_fp="fp1", disk_fp="fp2")
    assert data["stale"] is True and data["commit_drift"] is True and "fingerprint mismatch" in data["summary"]


def test_d25_lkg_is_stale_without_commit_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _discover(monkeypatch, loaded_fp="fp1", disk_fp="fp1", lkg=True, drift=False)
    assert data["stale"] is True and "LKG" in data["summary"]


@pytest.mark.parametrize("loaded", ["", "unknown"])
def test_d25_unavailable_fingerprint_stays_conservative(monkeypatch: pytest.MonkeyPatch, loaded: str) -> None:
    data = _discover(monkeypatch, loaded_fp=loaded, disk_fp="fp1")
    assert data["stale"] is True and "fingerprint unavailable" in data["summary"]


def test_d25_no_drift_emits_no_commit_drift_nor_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import json

    import server

    monkeypatch.setattr(server, "_is_front_stale", lambda: False)
    data = json.loads(asyncio.run(server.discover(action="capabilities", verbosity="detail", force_refresh=True)))
    assert "commit_drift" not in data and "harness_reconnect" not in data.get("next_action", "")


def test_front_stale_points_to_reconnect_plan_only(monkeypatch: pytest.MonkeyPatch) -> None:
    stale = _discover(monkeypatch, loaded_fp="fp1", disk_fp="fp1", front=True)
    assert stale["front_stale"] is True and hr.RECONNECT_POINTER in stale["next_action"]
    assert '"mode":"plan"' in hr.RECONNECT_POINTER and "execute" not in hr.RECONNECT_POINTER


def test_heal_points_to_reconnect_plan_when_front_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import json

    import server

    monkeypatch.setattr(server, "_is_front_stale", lambda: True)
    res = json.loads(asyncio.run(server.autoevol(action="heal", verbosity="detail")))
    assert json.dumps(hr.RECONNECT_POINTER)[1:-1] in json.dumps(res)


def test_isolation_fixture_blocks_sysctl_write_pts_and_sudo_helper() -> None:
    import subprocess

    assert os.environ["AEP_HARNESS_RECONNECT_DRY"] == "1"
    with pytest.raises(AssertionError):
        open("/proc/sys/dev/tty/legacy_tiocsti", "w")  # noqa: SIM115
    with pytest.raises(AssertionError):
        os.open("/dev/pts/0", os.O_RDONLY)
    with pytest.raises(AssertionError):
        subprocess.Popen(["sudo", "-n", "/usr/bin/python3", "-c", hr.HELPER_SCRIPT])  # noqa: S603
    hr.read_sysctl()  # read-only access stays allowed


def test_helper_script_compiles_and_fails_closed_without_tty() -> None:
    """Runs the helper as the current user with a non-tty stdin: it must exit before reading the sysctl."""
    import subprocess
    import sys

    compile(hr.HELPER_SCRIPT, "<helper>", "exec")
    good = hr.build_payload("claude", "x").hex()  # type: ignore[union-attr]
    r = subprocess.run([sys.executable, "-I", "-S", "-c", hr.HELPER_SCRIPT, "136", "3", good], stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert r.returncode == 6 and b"stdin_mismatch" in r.stdout
    bad = subprocess.run([sys.executable, "-I", "-S", "-c", hr.HELPER_SCRIPT, "136", "3", b"rm -rf /\r".hex()], stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert bad.returncode == 2 and b"payload_rejected" in bad.stdout
    assert subprocess.run([sys.executable, "-I", "-S", "-c", hr.HELPER_SCRIPT], stdin=subprocess.DEVNULL, capture_output=True, check=False).returncode == 2
