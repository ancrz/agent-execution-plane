"""ONT-66 T3/T5: `aep_notice` en TODA respuesta mientras haya avisos sin ack; ack, reaparicion, resolucion; sin avisos
las respuestas son byte-identicas a las previas a ONT-66. Siempre sobre un arbol sintetico (REPO_ROOT parcheado) y con
AEP_DATA_HOME temporal: nunca el repo ni la BD reales."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import server
from engine import notices
from engine import threads as th
from engine.telemetry import RequestTelemetry, attach_envelope, set_notice_provider

_SERVER = """
from engine.helper import util
mcp = object()

@mcp.tool()
async def autoevol(action: str = "list", verbosity: str = "summary"):
    act = action
    if act == "list":
        return util()
    return 1
"""
_PRIV = """
_CAPABILITIES = {"orientation": (4, 4, "self", ["autoevol"], "d")}
CHMOD_DEGRADATION_MATRIX = {"tools": {"autoevol": {}}}
_CAP_TACTICAL = {"orientation": {"canonical_calls": ['autoevol(action="list")']}}
CONTROL_PLANE_SCHEMA = {}
"""
_TEST = "import server\n\n\ndef test_autoevol():\n    server.autoevol(action='list')\n"
_CLEAN = 'autoevol(action="list") 1 tools\n'
_DRIFT = 'autoevol(action="list") 15 tools\n'


def _tree(root: Path, readme: str) -> None:
    for sub in ("tests", "engine", "schemas"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "engine" / "__init__.py").write_text("")
    (root / "engine" / "helper.py").write_text('def util():\n    return "x"\n')
    (root / "engine" / "privilege.py").write_text(_PRIV)
    (root / "server.py").write_text(_SERVER)
    (root / "tests" / "test_autoevol.py").write_text(_TEST)
    (root / "README.md").write_text(readme)
    (root / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "repo"
    root.mkdir()
    _tree(root, _DRIFT)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("AEP_DATA_HOME", str(data))
    monkeypatch.setattr(server, "REPO_ROOT", root)
    monkeypatch.setattr(server, "_NOTICE_TTL_S", 0.0)
    monkeypatch.setattr(server, "_NOTICE_REGISTRY", None)
    monkeypatch.setattr(server, "_notice_plane", lambda: {})
    monkeypatch.setattr(server, "_HOT_LAST_KICK", [0.0])
    th.clear_cache()
    th.analyze(root)
    yield root
    th.clear_cache()


def _reanalyze(root: Path, readme: str) -> None:
    (root / "README.md").write_text(readme)
    th.analyze(root)


def _call(tool: str, **kw: Any) -> dict[str, Any]:
    return json.loads(asyncio.run(getattr(server, tool)(**kw)))


def test_any_tool_carries_aep_notice_with_ask_user_until_ack(repo: Path) -> None:
    for verbosity in ("terse", "summary", "detail"):
        out = _call("process_inspect", pid=0, verbosity=verbosity)
        blk = out["aep_notice"]
        assert blk["count"] == 1 and blk["severity"] == "WARN"
        assert "claim_drift" in blk["ask_user"] and blk["ask_user"].endswith("¿Quieres mejorarlo?")
        assert blk["next_action"].startswith("autoevol(action='spec', gap='drift:claim:")
        assert len(json.dumps(blk, ensure_ascii=False).encode()) <= notices.BLOCK_MAX_BYTES
    # "ruidoso": se repite en cada respuesta (no se suprime por repeticion) y llega a otras tools
    assert "aep_notice" in _call("topos_audit_dag", tasks=["a"], dependencies={}, verbosity="terse")
    assert "aep_notice" in _call("aep_ctl", action="schema", verbosity="terse")
    ack = _call("autoevol", action="ack", all=True)
    assert ack["status"] == "OK" and len(ack["acked"]) == 1 and ack["remaining"] == 0
    assert "aep_notice" not in ack
    assert "aep_notice" not in _call("process_inspect", pid=0, verbosity="terse")


def test_new_drift_after_ack_reappears_and_resolution_retires_it(repo: Path) -> None:
    _call("autoevol", action="ack", all=True)
    _reanalyze(repo, _DRIFT + "Also 16 tools here.\n")
    out = _call("process_inspect", pid=0, verbosity="terse")
    assert out["aep_notice"]["count"] == 1  # solo el nuevo; el primero sigue acked
    listed = _call("autoevol", action="notices")
    assert listed["count"] == 2 and {n["state"] for n in listed["notices"]} == {"acked", "seen"}
    assert "aep_notice" not in listed
    _reanalyze(repo, _CLEAN)
    assert "aep_notice" not in _call("process_inspect", pid=0, verbosity="terse")
    assert _call("autoevol", action="notices")["count"] == 0
    _reanalyze(repo, _DRIFT)  # reaparece tras resolverse: es nuevo otra vez
    assert "aep_notice" in _call("process_inspect", pid=0, verbosity="terse")


def test_ack_by_ids_validates_input(repo: Path) -> None:
    assert _call("autoevol", action="ack")["status"] == "PARAM_ERROR"
    assert _call("autoevol", action="ack", ids=["nope"])["status"] == "NOT_FOUND"
    gap_id = _call("autoevol", action="notices")["notices"][0]["id"]
    done = _call("autoevol", action="ack", ids=[gap_id])
    assert done["acked"] == [gap_id] and done["remaining"] == 0
    assert "aep_notice" not in _call("process_inspect", pid=0, verbosity="terse")


def test_spec_and_gaps_responses_do_not_duplicate_the_block(repo: Path) -> None:
    assert "aep_notice" not in _call("autoevol", action="gaps", verbosity="terse")
    gap_id = _call("autoevol", action="notices")["notices"][0]["id"]
    assert "aep_notice" not in _call("autoevol", action="spec", gap=gap_id, verbosity="terse")


def _stable(raw: str) -> dict[str, Any]:
    out = json.loads(raw)
    for volatile in ("t", "telemetry"):
        out.pop(volatile, None)
    return out


def _snapshot_calls() -> dict[str, dict[str, Any]]:
    res: dict[str, dict[str, Any]] = {}
    for verb in ("terse", "summary", "detail"):
        res[f"dag:{verb}"] = _stable(
            asyncio.run(server.topos_audit_dag(tasks=["a", "b"], dependencies={"b": ["a"]}, verbosity=verb))
        )
        res[f"schema:{verb}"] = _stable(asyncio.run(server.aep_ctl(action="schema", verbosity=verb)))
        res[f"playbook:{verb}"] = _stable(asyncio.run(server.discover(action="playbook", verbosity=verb)))
    return res


def test_without_notices_responses_are_byte_identical_to_pre_ont66(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reanalyze(repo, _CLEAN)
    assert server._notices_refresh(force=True) == []
    _snapshot_calls()  # warms the playbook RAM cache so both snapshots hit the same path
    with_provider = _snapshot_calls()
    monkeypatch.setenv("AEP_NOTICES", "0")  # camino previo a ONT-66
    baseline = _snapshot_calls()
    assert with_provider == baseline
    assert all("aep_notice" not in v for v in with_provider.values())
    assert all(json.dumps(v) == json.dumps(baseline[k]) for k, v in with_provider.items())


def test_a_failing_provider_never_breaks_a_response(repo: Path) -> None:
    def boom(tool: str, action: str) -> dict[str, Any]:
        raise RuntimeError(tool + action)

    set_notice_provider(boom)
    try:
        raw = attach_envelope({"status": "OK"}, RequestTelemetry("x", "y"), verbosity="terse")
        assert "aep_notice" not in json.loads(raw)
    finally:
        set_notice_provider(server._notice_block)


def test_literal_notices_and_ack_calls_list_then_silence(repo: Path) -> None:
    listed = json.loads(asyncio.run(server.autoevol(action="notices")))
    assert listed["status"] == "OK" and listed["count"] == 1 and listed["notices"][0]["state"] in ("new", "seen")
    acked = json.loads(asyncio.run(server.autoevol(action="ack", all=True)))
    assert acked["status"] == "OK" and acked["remaining"] == 0
    assert json.loads(asyncio.run(server.autoevol(action="notices")))["notices"][0]["state"] == "acked"
