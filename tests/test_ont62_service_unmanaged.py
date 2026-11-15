"""ONT-62/T4: `aep-ctl service status` distinguishes user units and unmanaged live processes from a missing unit."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from engine.telemetry import infer_severity

ROOT = Path(__file__).resolve().parent.parent
_PROPS = "ActiveState=inactive\nSubState=dead\nLoadState=not-found\nMainPID=0\nUnitFileState=\n"
_USER_PROPS = "ActiveState=active\nSubState=running\nLoadState=loaded\nMainPID=42\nUnitFileState=enabled\n"


def _load_ctl() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("aep_ctl_under_test", str(ROOT / "scripts" / "aep-ctl"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _fake_proc(root: Path, entries: dict[str, str]) -> Path:
    for pid, comm in entries.items():
        (root / pid).mkdir(parents=True)
        (root / pid / "comm").write_text(comm + "\n")
    (root / "self").mkdir()
    return root


@pytest.fixture
def ctl(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load_ctl()
    monkeypatch.setattr(module, "_need", lambda _b: "/usr/bin/systemctl")
    monkeypatch.setattr(module, "_tier", lambda: "FULL")
    return module


def _systemctl(monkeypatch: pytest.MonkeyPatch, ctl: ModuleType, system: str, user: str) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> subprocess.CompletedProcess:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=user if "--user" in cmd else system, stderr="")

    monkeypatch.setattr(ctl, "_run", fake_run)
    return calls


def test_unmanaged_process_is_reported_with_pids(monkeypatch, ctl, tmp_path):
    _systemctl(monkeypatch, ctl, _PROPS, _PROPS)
    proc = _fake_proc(tmp_path / "proc", {"101": "pueued", "102": "bash", "103": "pueued"})
    res = _status_with_proc(monkeypatch, ctl, proc, "pueued")
    assert res["status"] == "RUNNING_UNMANAGED"
    assert res["pids"] == [101, 103]
    assert res["scope"] == "process"
    assert res["hint"] == "running without a systemd unit (no restart on boot)"
    assert infer_severity(res["status"]) == "WARN"


def _status_with_proc(monkeypatch: pytest.MonkeyPatch, ctl: ModuleType, proc: Path, name: str):
    real = ctl._find_pids_by_comm
    monkeypatch.setattr(ctl, "_find_pids_by_comm", lambda n: real(n, str(proc)))
    return _classified(ctl.domain_service("status", name))


def _classified(res: dict) -> dict:
    """Every status the ctl emits must be classified by engine.telemetry (ONT-57 contract)."""
    assert infer_severity(res["status"]) in {"INFO", "WARN"}
    return res


def test_service_suffix_is_ignored_for_comm_match(monkeypatch, ctl, tmp_path):
    _systemctl(monkeypatch, ctl, _PROPS, _PROPS)
    proc = _fake_proc(tmp_path / "proc", {"7": "pueued"})
    assert _status_with_proc(monkeypatch, ctl, proc, "pueued.service")["pids"] == [7]


def test_not_found_when_no_unit_and_no_process(monkeypatch, ctl, tmp_path):
    _systemctl(monkeypatch, ctl, _PROPS, _PROPS)
    proc = _fake_proc(tmp_path / "proc", {"1": "init"})
    res = _status_with_proc(monkeypatch, ctl, proc, "pueued")
    assert res["status"] == "NOT_FOUND"


def test_user_scope_unit_wins_over_process_scan(monkeypatch, ctl, tmp_path):
    _systemctl(monkeypatch, ctl, _PROPS, _USER_PROPS)
    proc = _fake_proc(tmp_path / "proc", {"42": "pueued"})
    res = _status_with_proc(monkeypatch, ctl, proc, "pueued")
    assert res["status"] == "OK"
    assert res["scope"] == "user"


def test_loaded_system_unit_is_untouched(monkeypatch, ctl):
    calls = _systemctl(monkeypatch, ctl, _USER_PROPS, _PROPS)
    res = _classified(ctl.domain_service("status", "nginx"))
    assert res["status"] == "OK" and "scope" not in res
    assert all("--user" not in c for c in calls)


def test_leading_dash_name_is_rejected_before_any_systemctl_call(monkeypatch, ctl):
    calls = _systemctl(monkeypatch, ctl, _PROPS, _PROPS)
    with pytest.raises(SystemExit):
        ctl.domain_service("status", "--all")
    assert calls == [] and infer_severity("ERROR") == "ERROR"


def test_comm_is_truncated_like_the_kernel(tmp_path):
    ctl = _load_ctl()
    proc = _fake_proc(tmp_path / "proc", {"9": "a-very-long-nam"})  # kernel keeps 15 chars
    assert ctl._find_pids_by_comm("a-very-long-name-service-x", str(proc)) == [9]
    assert infer_severity("RUNNING_UNMANAGED") == "WARN"


def _ctl_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(ROOT / "scripts" / "aep-ctl"), *args], capture_output=True, text=True, timeout=60, check=False
    )


def test_polyglot_header_survives_formatting_sh_can_run_the_ctl():
    """Regression: ruff format once rewrote line 4 and `sh scripts/aep-ctl` died with a syntax error."""
    res = _ctl_cli("schema")
    assert res.returncode == 0, res.stderr
    assert "service" in res.stdout and infer_severity("OK") == "INFO"


def test_double_dash_name_is_param_error_not_traceback():
    res = _ctl_cli("service", "status", "--", "-x")
    assert res.returncode == 1 and "Traceback" not in res.stderr
    assert json.loads(res.stdout)["status"] == "PARAM_ERROR"
    assert infer_severity("PARAM_ERROR") == "ERROR"
