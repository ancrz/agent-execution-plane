"""Dokimos audit E4: defectos conocidos como xfail estricto (se convierten en fallo al corregirse; entonces quitar el marcador)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import server
from engine import threads
from engine import threads_ledger as tl
from engine import threads_reconcile as tr
from engine.privilege import _PrivilegeCache
from engine.threads_model import Gap

_SERVER = '''
mcp = object()

@mcp.tool()
async def autoevol(action: str = "list", verbosity: str = "summary"):
    act = action
    if act == "list":
        return 1
    if act == "info":
        return 2
'''
_PRIV = '''
_CAPABILITIES = {"orientation": (4, 4, "self", ["autoevol"], "d")}
CHMOD_DEGRADATION_MATRIX = {"tools": {"autoevol": {}}}
_CAP_TACTICAL = {}
CONTROL_PLANE_SCHEMA = {}
'''
_TEST_HELPER = '''
import server

def _ctl(**kw):
    return server.autoevol(**kw)

def test_info_via_helper():
    _ctl(action="info")
'''


@pytest.mark.xfail(strict=True, reason="D-E4-1: el extractor pierde action/domain constantes pasados a un helper de test que reenvia **kw")
def test_helper_forwarded_constant_kwargs_create_covers_edge(tmp_path: Path) -> None:
    for d in ("engine", "tests", "schemas"):
        (tmp_path / d).mkdir()
    (tmp_path / "server.py").write_text(_SERVER)
    (tmp_path / "engine" / "__init__.py").write_text("")
    (tmp_path / "engine" / "privilege.py").write_text(_PRIV)
    (tmp_path / "tests" / "test_h.py").write_text(_TEST_HELPER)
    (tmp_path / "README.md").write_text("x\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    a = threads.analyze(tmp_path, use_cache=False)
    assert a.graph.in_edges("action:autoevol:info", "covers")


@pytest.mark.xfail(strict=True, reason="D-E4-2: reconcile abre ciclos sin presupuesto propio ni opt-in; 3 llamadas agotan el tope de la ventana")
def test_reconcile_opening_is_not_default_and_has_own_budget(tmp_path: Path) -> None:
    gaps = [Gap(id=f"drift:claim:c{i}", kind="claim_drift", node="n", severity=0.8, detail="d") for i in range(3)]
    led = tl.EvolveLedger(tmp_path / "l.db", max_cycles=3)
    live: set[str] = set()

    def open_cycle(gap: str) -> dict:
        cyc = f"c{len(live)}"
        live.add(cyc)
        return {"status": "OK", "cycle": cyc}

    kw = {
        "ledger": led,
        "open_cycle": open_cycle,
        "cycle_state": lambda c: "OPEN" if c in live else None,
        "evolve_plan": lambda **k: {"state": "PATCH_AWAITED"},
    }
    for _ in range(3):
        tr.reconcile(gaps, plane={}, cached_specs={g.id for g in gaps}, octal=6, **kw)
    assert len(live) == 0 or led.used() == 0 and len(live) <= 1  # por defecto no abre; o presupuesto propio acotado a 1


@pytest.mark.xfail(strict=True, reason="D-E4-3: autoevol(reconcile) ignora limit")
def test_reconcile_honours_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gaps = [Gap(id=f"drift:claim:c{i}", kind="claim_drift", node="n", severity=0.8, detail="d") for i in range(6)]
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AEP_AUTOEVOL_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("AEP_FORCE_TIER", "4r--")
    _PrivilegeCache.reset()
    monkeypatch.setattr(threads, "analyze", lambda root, **kw: SimpleNamespace(gaps=gaps))
    monkeypatch.setattr("engine.threads_spec_cache.cached_gap_ids", lambda db: set())
    monkeypatch.setattr(server, "_BACKEND_META_GETTER", lambda: {})
    try:
        res = json.loads(asyncio.run(server.autoevol(action="reconcile", limit=2, verbosity="summary")))
    finally:
        _PrivilegeCache.reset()
    assert len(res["proposals"]) <= 2
