"""ONT-42c C7: R_before/R_after en el ledger y cascada Gaps(G') estrictamente dentro de Gaps(G)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import threads_evolve as te
from tests._evolve_support import Rig, make_rig, sh


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def test_r_before_and_r_after_are_recorded_in_ledger_and_event(rig: Rig) -> None:
    assert rig.drive()["state"] == te.PUSHED
    row = rig.ledger().get(rig.cycle)
    assert row is not None and row["r_before"] == "R0" and row["r_after"] == "R1" and row["base_r"] == "R0"
    committed = next(e for e in rig.ledger().events(rig.cycle) if e["kind"] == "evolve.committed")
    assert committed["data"]["r_before"] == "R0" and committed["data"]["r_after"] == "R1"


def test_new_gaps_block_before_commit(rig: Rig) -> None:
    assert te.run_evolve  # cobertura directa del grafo
    rig.fake.summary = {"root": "R1", "gaps": ["D-90", "X-NEW"], "codep": []}  # arreglar D-88 crea X-NEW
    out = rig.drive()
    assert out["status"] == "REJECT" and out["reason"] == "new_gaps"
    assert sh(rig.canon, "branch", "--list", "autoevol/*") == ""  # ni siquiera hay commit
    assert rig.ledger().get(rig.cycle) is None  # ni se consume cupo del tope


def test_equal_gap_set_is_not_strict_progress(rig: Rig) -> None:
    assert te.run_evolve  # cobertura directa del grafo
    rig.fake.summary = {"root": "R1", "gaps": ["D-88", "D-90"], "codep": []}
    out = rig.drive()
    assert out["status"] == "REJECT" and out["reason"] == "no_gap_progress"
    assert sh(rig.canon, "branch", "--list", "autoevol/*") == ""


def test_codependency_blocks(rig: Rig) -> None:
    assert te.run_evolve  # cobertura directa del grafo
    rig.fake.summary = {"root": "R1", "gaps": ["D-90"], "codep": ["a<->b"]}
    assert rig.drive()["reason"] == "codep"


def test_missing_summarizer_is_fail_closed(rig: Rig) -> None:
    kit = rig.fake.kit()
    kit.summarize = None
    out = te.run_evolve(
        rig.store(),
        rig.port(),
        lambda: dict(rig.live),
        cycle=rig.cycle,
        gap="D-88",
        apply=True,
        octal=6,
        label="DIMINISHED",
        cycle_dir=rig.state,
        kit=kit,
    )
    assert out["reason"] == "no_summarize"
    assert sh(rig.canon, "branch", "--list", "autoevol/*") == ""
