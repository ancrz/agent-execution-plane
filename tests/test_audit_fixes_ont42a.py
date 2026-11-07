"""Fixes for the Dokimos audit of 1b983f1..b605677 (D-HR-2/4/5/6, O3). Doubles only: no sysctl, TTY or sudo."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from engine import harness_reconnect as hr
from engine import threads_verify as tv
from tests.test_ont42a_harness_reconnect import _ctl, _mk_proc, _pts_nr, _Rec


def _tier(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    import server

    monkeypatch.setattr(server, "get_effective_chmod_tier", lambda *a, **k: {"tier": tier})
    monkeypatch.setattr(server, "record_audit_event", lambda *_a, **_k: None)


@pytest.mark.parametrize("mode", ["certify", "matrix"])
def test_certify_and_matrix_are_gated_below_5rx(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    _tier(monkeypatch, "4r--")
    res = _ctl(params={"mode": mode})
    assert res["status"] == "REJECTED" and res["reason"] == "tier_insufficient" and res["required"] == "5r-x"


@pytest.mark.parametrize("tier", ["5r-x", "6rw-", "7rwx"])
def test_certify_never_uses_helper_nor_certifies(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    _tier(monkeypatch, tier)
    rec = _Rec()
    monkeypatch.setattr(hr, "real_adapters", lambda audit=None: rec.adapters())
    res = _ctl(params={"mode": "certify", "message": "hello world", "confirm": True})
    assert res["status"] == "LOOPBACK_OK" and res["certified"] is False and res["certify_mode"] == "pty_loopback"
    assert res["message_received"] == "hello world" and rec.helper_calls == 0
    assert rec.audits
    assert rec.audits[-1][0] == "UNVERIFIED"
    assert all(s != "CERTIFIED" for s, _ in rec.audits)


def test_certify_rejects_non_ascii_and_reports_sysctl_change() -> None:
    assert hr.certify_loopback("h\x1bi", adapters=_Rec().adapters())["status"] == "ERROR"
    drifting = _Rec(sysctl=["0", "1"])
    res = hr.certify_loopback("ping", adapters=drifting.adapters())
    assert res["status"] == "FAIL" and res["certified"] is False and drifting.audits[-1][0] == "FAIL"


def test_matrix_does_not_spawn_external_clis_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AEP_HARNESS_RECONNECT_DRY", raising=False)
    calls: list[Any] = []

    def fake_run(*a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        calls.append(a)
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(hr.subprocess, "run", fake_run)
    monkeypatch.setattr(hr.shutil, "which", lambda _n: "/usr/bin/fake")
    _mk_proc(tmp_path, 10, 1, "/usr/bin/python3")
    res = hr.probe_console_reach(proc_root=tmp_path, start_pid=10, adapters=_Rec().adapters())
    assert calls == [] and res["harnesses"]["claude"]["cli_probe_detail"] == "dry_mode"
    hr.probe_console_reach(proc_root=tmp_path, start_pid=10, adapters=_Rec().adapters(), probe_cli=True)
    assert len(calls) == len(hr.SUPPORTED_HARNESSES)


def test_rpc_is_never_reported_ok_and_maps_to_unsupported(tmp_path: Path) -> None:
    assert hr._probe_rpc("agy")["available"] is False and hr._probe_rpc("codex")["available"] is False
    assert hr._run_rpc("agy", "srv") == (False, "rpc_unsupported:agy")
    assert hr._run_rpc("codex", "bad name!") == (False, "invalid_server_name")
    _mk_proc(tmp_path, 100, 1, "/usr/local/bin/agy", 0)
    _mk_proc(tmp_path, 200, 100, "/usr/bin/python3")
    ad = _Rec().adapters()
    ad.probe_rpc = lambda _h: {"available": True, "transport": "x"}
    ad.run_rpc = hr._run_rpc
    res = hr.execute(tier="7rwx", confirm=True, front_stale=True, proc_root=tmp_path, start_pid=200, adapters=ad)
    assert res["status"] == "UNSUPPORTED" and res["route"] == "manual"


def test_unverified_harness_commands_default_to_manual(tmp_path: Path) -> None:
    assert hr.HARNESS_PROFILES["claude"]["verified"] is True
    for name in ("agy", "codex", "gemini"):
        assert hr.HARNESS_PROFILES[name]["verified"] is False
        root = tmp_path / name
        _mk_proc(root, 100, 1, f"/usr/local/bin/{name}", _pts_nr(4))
        plan = hr.build_plan(front_stale=True, proc_root=root, start_pid=100, adapters=_Rec().adapters())
        assert plan["recommended_route"] == "manual" and plan["reason"] == "command_unverified"
        assert plan["command_verified"] is False
        rec = _Rec()
        res = hr.execute(
            tier="7rwx", confirm=True, front_stale=True, proc_root=root, start_pid=100, adapters=rec.adapters()
        )
        assert res["status"] == "UNSUPPORTED" and rec.helper_calls == 0


def test_rpc_branch_unsupported_when_run_rpc_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles = {**hr.HARNESS_PROFILES, "claude": {**hr.HARNESS_PROFILES["claude"], "transports": ("rpc_reload",)}}
    monkeypatch.setattr(hr, "HARNESS_PROFILES", profiles)
    _mk_proc(tmp_path, 100, 1, "/usr/bin/claude", 0)
    _mk_proc(tmp_path, 200, 100, "/usr/bin/python3")
    ad = _Rec().adapters()
    ad.probe_rpc = lambda _h: {"available": True}
    ad.run_rpc = hr._run_rpc
    res = hr.execute(tier="7rwx", confirm=True, front_stale=True, proc_root=tmp_path, start_pid=200, adapters=ad)
    assert res["status"] == "UNSUPPORTED" and res["reason"] == "rpc_unsupported:claude"


# ---- O3: direct tests with doubles -------------------------------------------------------------------------


def test_open_tty_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_open(path: str, flags: int) -> int:
        seen.update(path=path, flags=flags)
        return 42

    monkeypatch.setattr(hr.os, "open", fake_open)
    assert hr.open_tty("/dev/pts/9") == 42
    assert seen["path"] == "/dev/pts/9"
    assert seen["flags"] == os.O_RDWR | os.O_NOCTTY | os.O_NOFOLLOW


class _FakeProc:
    def __init__(self, *, out: str = "{}", rc: int = 0, hang: bool = False) -> None:
        self.pid, self.returncode, self._out, self._hang, self.calls = 4242, rc, out, hang, 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.calls += 1
        if self._hang and self.calls == 1:
            raise subprocess.TimeoutExpired("sudo", timeout or 0)
        if self._hang:
            self.returncode = -15
        return self._out, ""


def test_run_helper_builds_fixed_argv_and_returns_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_popen(cmd: list[str], **kw: Any) -> _FakeProc:
        captured.update(cmd=cmd, kw=kw)
        return _FakeProc(out='{"injected":1}', rc=0)

    monkeypatch.setattr(hr.subprocess, "Popen", fake_popen)
    rc, out, timed_out = hr.run_helper(136, 3, "aa", 7)
    assert (rc, out, timed_out) == (0, '{"injected":1}', False)
    assert captured["cmd"][: len(hr.HELPER_CMD_PREFIX)] == list(hr.HELPER_CMD_PREFIX)
    assert captured["cmd"][-4:] == [hr.HELPER_SCRIPT, "136", "3", "aa"]
    assert captured["kw"]["stdin"] == 7 and captured["kw"]["env"] == hr.HELPER_ENV and "shell" not in captured["kw"]


def test_run_helper_timeout_kills_group(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(hr.subprocess, "Popen", lambda *_a, **_k: _FakeProc(hang=True))
    monkeypatch.setattr(hr.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    rc, _out, timed_out = hr.run_helper(136, 3, "aa", 7, timeout=0.01)
    assert timed_out is True and rc == -15 and killed == [(4242, hr.signal.SIGTERM)]


def test_validate_server_and_harness_name() -> None:
    assert hr.validate_server("abc-1_x") == "abc-1_x"
    for bad in (None, "", "A", "-x", "a b", "x" * 65, 5):
        assert hr.validate_server(bad) is None  # type: ignore[arg-type]
    cases = {
        "/usr/bin/claude": "claude",
        "/usr/local/bin/codex-cli": "codex",
        "/opt/Antigravity/resources/bin/language_server": "agy",
        "/x/node_modules/@google/gemini-cli/bin/g": "gemini",
        "/x/@openai/codex/bin/c": "codex",
        "/home/u/.local/share/claude/versions/2.1.319": "claude",
        "/home/u/claude/versions/../versions/2.1.319": "",
        "/usr/bin/bash": "",
    }
    for exe, want in cases.items():
        assert hr._harness_name(exe) == want, exe


def test_tests_reasons_branches() -> None:
    f = tv._tests_reasons
    assert f(None, trusted=True) == ([], False)
    assert f({"status": "pending"}, trusted=True) == ([], True)
    assert f({"wrong_tree": True}, trusted=True) == ([tv.WRONG_TREE], False)
    assert f({"available": False}, trusted=True) == ([tv.SANDBOX_UNAVAILABLE], False)
    assert f({"unsandboxed": True}, trusted=False) == ([tv.SANDBOX_UNAVAILABLE], False)
    assert f({"unsandboxed": True, "ran": 3}, trusted=True) == ([], False)
    assert f({"failed": 1}, trusted=True) == ([tv.TESTS_FAIL], False)
    assert f({"errors": 2}, trusted=True) == ([tv.TESTS_FAIL], False)
    assert f({"timeout": True}, trusted=True) == ([tv.TESTS_FAIL], False)
    assert f({"exit_code": 1, "ran": 5}, trusted=True) == ([tv.TESTS_FAIL], False)
    assert f({"ran": 2, "exit_code": 0}, trusted=True, selected=3) == ([tv.TESTS_FAIL], False)
    assert f({"ran": 3, "exit_code": 0}, trusted=True, selected=3) == ([], False)


def test_capped_truncates_and_reports_total() -> None:
    items = [str(i) for i in range(tv.LIST_CAP + 5)]
    out = tv._capped(items)
    assert out["total"] == len(items) and out["items"] == items[: tv.LIST_CAP]
    assert tv._capped([]) == {"items": [], "total": 0}
