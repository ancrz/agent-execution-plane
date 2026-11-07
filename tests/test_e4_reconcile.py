"""E4: reconciliacion acotada por tier (`engine.threads_reconcile`, `autoevol(reconcile)`, `discover(...).reconcile_top`)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import server
from engine import threads
from engine import threads_ledger as tl
from engine import threads_reconcile as tr
from engine.privilege import _PrivilegeCache
from engine.threads_model import Gap

DRIFT = Gap(id="drift:claim:claim:README.md:3", kind="claim_drift", node="claim:x", severity=0.8, detail="tools: 9 vs 17")
DRIFT2 = Gap(id="drift:claim:claim:README.md:9", kind="claim_drift", node="claim:y", severity=0.7, detail="tests: 1 vs 2")
OPEN = Gap(id="drift:open:D-01b:t", kind="open_discrepancy", node="test:t", severity=0.5, detail="xfail", ref="D-01b")
OMIT = Gap(id="omission:x", kind="omission", node="function:x", severity=0.3, detail="no test")
LKG = {"serving_from": "lkg", "reload_error": True}


class Spy:
    """Efectos inyectados: registran cada llamada. Un git/heal-apply real no existe en este modulo."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.plans: list[dict[str, Any]] = []
        self.heals = 0
        self.live: set[str] = set()

    def open_cycle(self, gap: str) -> dict[str, Any]:
        self.opened.append(gap)
        cyc = f"cyc{len(self.opened)}"
        self.live.add(cyc)
        return {"status": "OK", "cycle": cyc}

    def cycle_state(self, cyc: str) -> str | None:
        return "OPEN" if cyc in self.live else None

    def evolve_plan(self, **kw: Any) -> dict[str, Any]:
        self.plans.append(kw)
        return {"state": "PATCH_AWAITED"}

    def heal_dry_run(self) -> dict[str, Any]:
        self.heals += 1
        return {"status": "CLEAN", "total_threads": 0}

    def kw(self, ledger: Any) -> dict[str, Any]:
        return {
            "ledger": ledger,
            "open_cycle": self.open_cycle,
            "cycle_state": self.cycle_state,
            "evolve_plan": self.evolve_plan,
            "heal_dry_run": self.heal_dry_run,
            "open_cycles": True,
        }


def _ledger(tmp_path: Path, cap: int = 3) -> tl.EvolveLedger:
    return tl.EvolveLedger(tmp_path / "l.db", max_cycles=cap)


# -- propuestas ---------------------------------------------------------------------------------------
def test_proposals_cover_plane_drift_discrepancy_and_are_deterministic() -> None:
    gaps = [OMIT, OPEN, DRIFT2, DRIFT]
    cached = {DRIFT.id}
    a = tr.propose(gaps, plane=LKG, cached_specs=cached)
    b = tr.propose(list(reversed(gaps)), plane=dict(LKG), cached_specs=set(cached))
    assert a == b  # misma entrada (en cualquier orden) = mismas propuestas
    assert (a[0]["action"], a[0]["gap"], a[0]["kind"]) == ("heal", "plane:serving_lkg", "plane_degraded")
    by_gap = {p["gap"]: p for p in a}
    assert by_gap[DRIFT.id]["action"] == "evolve" and by_gap[DRIFT.id]["tier_required"] == 6
    assert by_gap[DRIFT2.id]["action"] == "spec"  # sin spec cacheada: primero spec
    assert by_gap[OPEN.id]["action"] == "report"
    assert set(a[0]) == {"gap", "kind", "action", "reason", "tier_required"}


def test_no_drift_no_proposal() -> None:
    assert tr.propose([OMIT], plane={}, cached_specs=set(), include_omissions=False) == []
    assert tr.top([]) is None


# -- politica por tier ---------------------------------------------------------------------------------
@pytest.mark.parametrize("octal", [4, 5])
def test_read_tiers_never_touch_ledger_or_effects(octal: int, tmp_path: Path) -> None:
    spy = Spy()
    led = _ledger(tmp_path)
    out = tr.reconcile([DRIFT], plane=LKG, cached_specs={DRIFT.id}, octal=octal, **spy.kw(led))
    assert out["mode"] == "report" and out["executed"] == [] and out["proposals"]
    assert not spy.opened and not spy.plans and spy.heals == 0
    assert not (tmp_path / "l.db").exists()  # ni siquiera se abrio el ledger


def test_6rw_opens_plan_cycles_but_no_heal(tmp_path: Path) -> None:
    spy = Spy()
    out = tr.reconcile([DRIFT], plane=LKG, cached_specs={DRIFT.id}, octal=6, **spy.kw(_ledger(tmp_path)))
    assert spy.heals == 0 and spy.opened == [DRIFT.id]
    assert all(p["apply"] is False for p in spy.plans) and out["applied"] is False


def test_7rwx_heal_dry_run_and_plan_only_never_apply(tmp_path: Path) -> None:
    spy = Spy()
    out = tr.reconcile([DRIFT], plane=LKG, cached_specs={DRIFT.id}, octal=7, **spy.kw(_ledger(tmp_path)))
    assert spy.heals == 1 and spy.opened == [DRIFT.id]
    assert spy.plans and all(p["apply"] is False for p in spy.plans)
    assert any(e["action"] == "heal" and e["dry_run"] is True for e in out["executed"])
    assert all(e.get("applied", False) is False for e in out["executed"])


def test_reconcile_module_has_no_git_or_server_import() -> None:
    import ast

    tree = ast.parse(Path(tr.__file__).read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.update([node.module or "", *(f"{node.module}.{a.name}" for a in node.names)])
    assert not mods & {"server", "aep_front", "subprocess", "engine.threads_gitport", "engine.threads_evolve"}
    applies = [k.value for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords if k.arg == "apply"]
    assert applies and all(isinstance(v, ast.Constant) and v.value is False for v in applies)  # apply siempre literal False


# -- idempotencia y tope -------------------------------------------------------------------------------
def test_idempotent_no_duplicate_cycles_or_events(tmp_path: Path) -> None:
    spy = Spy()
    led = _ledger(tmp_path)
    first = tr.reconcile([DRIFT], plane={}, cached_specs={DRIFT.id}, octal=6, **spy.kw(led))
    second = tr.reconcile([DRIFT], plane={}, cached_specs={DRIFT.id}, octal=6, **spy.kw(led))
    assert first["proposals"] == second["proposals"]
    assert spy.opened == [DRIFT.id]  # el segundo paso continua, no abre otro
    assert second["executed"][0]["continued"] is True and second["executed"][0]["cycle"] == "cyc1"
    assert len(led.recent("reconcile.opened")) == 1 and len(led.recent("reconcile.run")) == 1


def test_expired_cycle_is_replaced_within_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEP_RECONCILE_MAX_OPENS", "2")
    spy = Spy()
    led = _ledger(tmp_path)
    tr.reconcile([DRIFT], plane={}, cached_specs={DRIFT.id}, octal=6, **spy.kw(led))
    spy.live.clear()  # el ciclo vencio
    tr.reconcile([DRIFT], plane={}, cached_specs={DRIFT.id}, octal=6, **spy.kw(led))
    assert len(spy.opened) == 2


def test_cycle_cap_is_respected_and_shared_with_evolve_ledger(tmp_path: Path) -> None:
    spy = Spy()
    led = _ledger(tmp_path, cap=2)
    assert led.claim("g", "R", "T", "c0", r_before="R", r_after="")["claimed"] is True  # 1 ciclo de evolve ya consumido
    gaps = [DRIFT, DRIFT2]
    cached = {DRIFT.id, DRIFT2.id}
    tr.reconcile(gaps, plane={}, cached_specs=cached, octal=7, **spy.kw(led))
    assert len(spy.opened) == 1  # un nuevo por llamada
    out = tr.reconcile(gaps, plane={}, cached_specs=cached, octal=7, **spy.kw(led))
    assert len(spy.opened) == 1  # tope 2 = 1 evolve + 1 reconcile: ya no se abre otro
    assert any(e.get("capped") for e in out["executed"])
    assert led.recent("reconcile.capped")


def test_at_most_one_new_cycle_per_call(tmp_path: Path) -> None:
    spy = Spy()
    tr.reconcile([DRIFT, DRIFT2], plane={}, cached_specs={DRIFT.id, DRIFT2.id}, octal=6, **spy.kw(_ledger(tmp_path, cap=9)))
    assert len(spy.opened) == 1


def test_ledger_events_only_from_tier_6(tmp_path: Path) -> None:
    led = _ledger(tmp_path)
    tr.reconcile([DRIFT], plane={}, cached_specs=set(), octal=6, **Spy().kw(led))
    assert [e["cycle"] for e in led.recent("reconcile.run")] == ["reconcile"]


# -- tool autoevol(reconcile) y discover --------------------------------------------------------------
def _call(**kw: object) -> dict:
    return json.loads(asyncio.run(server.autoevol(**kw)))  # type: ignore[arg-type]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    home, state = tmp_path / "home", tmp_path / "state"
    home.mkdir()
    state.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AEP_AUTOEVOL_DIR", str(state))
    monkeypatch.setenv("AEP_AUTOEVOL_MAX_CYCLES", "2")
    monkeypatch.setattr(threads, "analyze", lambda root, **kw: SimpleNamespace(gaps=[DRIFT, DRIFT2]))
    monkeypatch.setattr("engine.threads_spec_cache.cached_gap_ids", lambda db: {DRIFT.id, DRIFT2.id})
    monkeypatch.setattr(server, "_BACKEND_META_GETTER", lambda: {"serving_from": "lkg", "last_reload_error": "x"})
    yield SimpleNamespace(home=home, state=state)
    _PrivilegeCache.reset()


def _tier(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", tier)
    _PrivilegeCache.reset()


def _snapshot(*dirs: Path) -> list[str]:
    return sorted(str(p.relative_to(d)) + f"@{d.name}" for d in dirs for p in d.rglob("*"))


@pytest.mark.parametrize("tier", ["4r--", "5r-x"])
def test_tool_low_tier_reports_and_writes_nothing(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    _tier(monkeypatch, tier)
    before = _snapshot(env.home, env.state)
    res = _call(action="reconcile", verbosity="terse")
    assert res["status"] == "OK" and res["executed"] == [] and res["proposals"][0]["action"] == "heal"
    assert _snapshot(env.home, env.state) == before  # DB y disco intactos


def test_tool_7rwx_never_calls_git_heal_apply_or_evolve_apply(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _tier(monkeypatch, "7rwx")
    from engine import threads_gitport as gp
    from engine import threads_ops as ops

    heal_calls: list[bool] = []
    evolve_calls: list[bool] = []
    monkeypatch.setattr(gp, "GitCli", lambda *a, **k: pytest.fail("reconcile no debe construir un puerto git"))
    monkeypatch.setattr(
        ops, "run_heal", lambda tree, **kw: heal_calls.append(kw["apply"]) or {"status": "CLEAN", "total_threads": 0}
    )
    monkeypatch.setattr(ops, "_open_cycle", lambda *a, **k: {"status": "OK", "cycle": "c" * 32})
    monkeypatch.setattr(server, "_autoevol_evolve", lambda tree, **kw: evolve_calls.append(kw["apply"]) or {"state": "PATCH_AWAITED"})
    res = _call(action="reconcile", apply=True, restart=True, open_cycles=True)  # `apply=True` se ignora
    assert heal_calls == [False] and evolve_calls and not any(evolve_calls)
    assert res["applied"] is False and any(e["action"] == "heal" for e in res["executed"])


def test_tool_cap_env_limits_cycles(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _tier(monkeypatch, "6rw-")
    from engine import threads_ops as ops

    opened: list[str] = []
    monkeypatch.setattr(ops, "_open_cycle", lambda store, tree, gap, *a: opened.append(gap) or {"status": "OK", "cycle": f"{len(opened):032x}"})
    monkeypatch.setattr(server, "_autoevol_evolve", lambda tree, **kw: {"state": "PATCH_AWAITED"})
    monkeypatch.setattr("engine.threads_evolve.read_cycle", lambda c, **k: {"state": "OPEN"})
    monkeypatch.setenv("AEP_RECONCILE_MAX_OPENS", "2")
    for _ in range(4):
        _call(action="reconcile", open_cycles=True)
    assert len(opened) == 2  # AEP_RECONCILE_MAX_OPENS=2


def test_tool_default_only_proposes_and_env_opt_in_opens(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _tier(monkeypatch, "6rw-")
    from engine import threads_ops as ops

    opened: list[str] = []
    monkeypatch.setattr(ops, "_open_cycle", lambda store, tree, gap, *a: opened.append(gap) or {"status": "OK", "cycle": "d" * 32})
    monkeypatch.setattr(server, "_autoevol_evolve", lambda tree, **kw: {"state": "PATCH_AWAITED"})
    monkeypatch.setattr("engine.threads_evolve.read_cycle", lambda c, **k: {"state": "OPEN"})
    _call(action="reconcile")
    assert opened == []
    monkeypatch.setenv("AEP_RECONCILE_OPEN", "1")
    _call(action="reconcile")
    assert len(opened) == 1


def test_reconcile_registered_in_actions() -> None:
    assert "reconcile" in server._AUTOEVOL_ACTIONS and "reconcile" in server._TOOL_ACTIONS["autoevol"]


def _caps(verbosity: str = "terse") -> dict[str, Any]:
    raw = asyncio.run(server.discover(action="capabilities", verbosity=verbosity, session_id="t-e4", force_refresh=True))
    return json.loads(raw)


def _tokens(payload: dict[str, Any]) -> int:
    t = payload.get("t")
    return int(t["tok"]) if isinstance(t, dict) and "tok" in t else int(payload["telemetry"]["estimated_tokens"])


def test_discover_terse_shows_single_top_within_budget_and_writes_nothing(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tier(monkeypatch, "4r--")
    before = _snapshot(env.home, env.state)
    payload = _caps("terse")
    assert payload["reconcile_top"] == "heal:plane:serving_lkg" and isinstance(payload["reconcile_top"], str)
    assert _tokens(payload) <= 400, _tokens(payload)
    assert _snapshot(env.home, env.state) == before


def test_discover_top_from_cached_drift_and_absent_when_clean(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_BACKEND_META_GETTER", lambda: {})
    monkeypatch.setattr("engine.threads_spec_cache.cached_gap_ids", lambda db: set())
    monkeypatch.setattr(threads, "cached_analysis", lambda root: SimpleNamespace(gaps=[DRIFT, OMIT]))
    monkeypatch.setattr(server, "_is_front_stale", lambda: False)
    top = _caps("terse").get("reconcile_top")
    assert top == f"spec:{DRIFT.id}"
    monkeypatch.setattr(threads, "cached_analysis", lambda root: SimpleNamespace(gaps=[OMIT]))
    assert "reconcile_top" not in _caps("terse")  # sin drift ni plano degradado: el campo no existe
    assert "reconcile_top" not in _caps("summary")  # solo en terse


def test_direct_coverage_of_reconcile_surface(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Referencias calificadas literales: el grafo no debe dejar huerfanos la accion ni las consultas del ledger."""
    _tier(monkeypatch, "4r--")
    res = json.loads(asyncio.run(server.autoevol(action="reconcile")))
    assert res["status"] == "OK"
    led = _ledger(tmp_path)
    assert tl.EvolveLedger.used(led) == 0
    assert tl.EvolveLedger.recent(led, "reconcile.run") == []
