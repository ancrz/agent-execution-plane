"""ONT-42c C4-C7, auditoria Dokimos (adversarial). `xfail(strict)` = defecto abierto: al arreglarse el xpass falla y obliga a quitar el marcador."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import threads_evolve as te
from tests._evolve_support import Rig, make_rig

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def _red_rig(rig: Rig) -> dict:
    rig.fake.results["tests/test_b.py"] = {"ran": 2, "passed": 1, "failed": 1, "errors": 0, "exit_code": 1}
    out = rig.drive()
    assert out["reason"] == "gate_failed"
    return out


def test_forged_green_gate_in_state_json_must_not_merge(rig: Rig) -> None:
    _red_rig(rig)
    store = rig.store()
    rec = store.load(rig.cycle)
    rec["gate"]["verdict"] = "green"  # mismo uid: escribe el JSON de estado
    store.save(rig.cycle, rec)
    out = rig.run()
    assert out.get("state") != te.MERGED and not (rig.canon / "new.txt").exists(), out


def test_forged_merged_state_must_not_reach_push_without_gate(rig: Rig) -> None:
    _red_rig(rig)
    store = rig.store()
    rec = store.load(rig.cycle)
    rec["state"] = te.MERGED
    store.save(rig.cycle, rec)
    out = rig.run()
    assert out.get("state") != te.PUSHED, out


def test_cap_cannot_be_dodged_by_changing_gap_or_base_r(tmp_path: Path) -> None:
    from engine import threads_ledger as tl

    led = tl.EvolveLedger(tmp_path / "l.db", max_cycles=2)
    assert led.claim("g1", "R1", "T1", "c1", r_before="R1", r_after="")["claimed"]
    assert led.claim("g2", "R2", "T2", "c2", r_before="R2", r_after="")["claimed"]
    out = led.claim("g3", "R3", "T3", "c3", r_before="R3", r_after="")
    assert out.get("capped") is True
    assert led.claim("g1", "R1", "T1", "c9", r_before="R1", r_after="")["row"]["cycle"] == "c1"  # idempotente


def test_ledger_tables_are_in_migrated_schema(tmp_path: Path) -> None:
    from engine import threads_ledger as tl

    sql = (ROOT / "schemas" / "database.sql").read_text(encoding="utf-8")
    led = tl.EvolveLedger(tmp_path / "l.db")
    assert led.get("none") is None  # abre la BD y crea el DDL perezoso
    assert "evolve_keys" in sql and "evolve_events" in sql


def test_resolve_revert_has_a_documented_user_path(tmp_path: Path) -> None:
    from engine import threads_ledger as tl

    led = tl.EvolveLedger(tmp_path / "l.db")
    assert led.resolve_revert("nope") is False  # solo desbloquea ciclos REVERTED
    docs = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (ROOT / "docs").rglob("*.md")
        if "pipeline" not in p.parts
    )
    assert "resolve_revert" in docs or "REVERT_RESOLVED" in docs


def test_lkg_after_swap_triggers_revert_even_if_first_post_verify_was_ok(rig: Rig) -> None:
    rig.live.update(stale=True, loaded="old", disk="new")  # swap en curso: el push espera
    seen = {"n": 0}

    def post_verify(_rec: dict) -> dict:
        seen["n"] += 1
        return {"ok": True} if seen["n"] == 1 else {"ok": False, "reason": "serving_lkg"}

    kit = rig.fake.kit()
    kit.post_verify = post_verify
    rig.fake.kit = lambda: kit  # type: ignore[method-assign]
    first = rig.drive()
    assert first.get("awaiting") == "reload", first
    second = rig.run()
    assert second.get("state") == te.REVERTED, second


def test_ledger_ddl_parity_with_database_sql() -> None:
    from engine import threads_ledger as tl

    sql = " ".join((ROOT / "schemas" / "database.sql").read_text(encoding="utf-8").split())
    for stmt in tl.DDL:
        assert " ".join(stmt.split()) + ";" in sql


def test_resolve_revert_is_not_an_mcp_tool_but_a_cli_subcommand(tmp_path: Path) -> None:
    from engine import threads_ledger as tl

    led = tl.EvolveLedger(tmp_path / "l.db")
    assert led.claim("g", "R", "T", "c1", r_before="R", r_after="")["claimed"]
    led.mark_reverted("c1")
    assert led.revert_pending() is True and led.resolve_revert("c1") is True and led.revert_pending() is False
    assert "resolve_revert" not in (ROOT / "server.py").read_text(encoding="utf-8")
    assert "resolve-revert" in (ROOT / "scripts" / "aep-ctl").read_text(encoding="utf-8")
