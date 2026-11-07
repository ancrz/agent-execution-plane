"""ONT-42c C5: ledger SQLite de evolve (idempotencia UNIQUE, tope de ciclos persistido, reconciliacion con git)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from engine import threads_evolve as te
from engine import threads_ledger as tl
from engine import threads_verify as tv
from tests._evolve_support import Rig, make_rig, sh


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def test_key_is_unique_and_insert_or_ignore_is_atomic(tmp_path: Path) -> None:
    led = tl.EvolveLedger(tmp_path / "l.db")
    first = led.claim("g", "R0", "T1", "c1", r_before="R0", r_after="R1")
    assert first["claimed"] is True
    again = led.claim("g", "R0", "T1", "c2", r_before="R0", r_after="R1")
    assert again["claimed"] is False and again["row"]["cycle"] == "c1"
    with sqlite3.connect(tmp_path / "l.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM evolve_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):  # la restriccion UNIQUE existe en el esquema, no solo en el codigo
            conn.execute(
                "INSERT INTO evolve_keys (gap_canonical, base_r, tree_hash, cycle, state, created_at) VALUES ('g','R0','T1','x','s',0)"
            )


def test_duplicate_key_from_another_cycle_returns_existing_state_without_a_second_commit(rig: Rig) -> None:
    first = rig.run(octal=6, label="DIMINISHED")
    assert first["state"] == te.COMMITTED
    other = tv.CycleStore(base_dir=rig.state).open_cycle(
        "drift:open:D-88:test:t", {"root": "R0", "gaps": ["D-88", "D-90"]}, restart=True
    )["cycle_id"]
    tv.CycleStore(base_dir=rig.state).record(
        other,
        {
            "verdict": tv.ACCEPT,
            "reasons": [],
            "judged": {"tree": rig.port().candidate_tree(), "root": str(rig.work.resolve())},
        },
    )
    dup = rig.run(octal=6, label="DIMINISHED", cycle=other)
    assert dup["duplicate_of"] == rig.cycle and dup["applied"] is False
    assert sh(rig.canon, "branch", "--list", "autoevol/*").count("autoevol/") == 1  # ninguna rama/commit nuevo


def test_cycle_cap_is_persisted_across_simulated_restarts(tmp_path: Path) -> None:
    clock = [1_000_000.0]
    path = tmp_path / "l.db"
    for i in range(3):
        led = tl.EvolveLedger(path, max_cycles=3, clock=lambda: clock[0])  # "reinicio": instancia nueva cada vez
        assert led.claim(f"g{i}", "R", f"T{i}", f"c{i}", r_before="R", r_after="")["claimed"] is True
    fresh = tl.EvolveLedger(path, max_cycles=3, clock=lambda: clock[0])
    capped = fresh.claim("g9", "R", "T9", "c9", r_before="R", r_after="")
    assert capped.get("capped") is True and capped["used"] == 3
    clock[0] += tl.WINDOW_SECONDS + 1  # la ventana de 24 h libera cupo
    assert tl.EvolveLedger(path, max_cycles=3, clock=lambda: clock[0]).claim(
        "g9", "R", "T9", "c9", r_before="R", r_after=""
    )["claimed"]


def test_evolve_rejects_when_cap_is_exhausted_and_does_not_commit(rig: Rig) -> None:
    led = rig.ledger()
    for i in range(3):
        led.claim(f"other{i}", "R", f"T{i}", f"o{i}", r_before="R", r_after="")
    out = rig.run()
    assert out["status"] == "REJECT" and out["reason"] == "max_cycles"
    assert sh(rig.canon, "branch", "--list", "autoevol/*") == ""


def test_events_and_state_are_recorded_and_reconciled_with_git(rig: Rig) -> None:
    out = rig.drive()
    assert out["state"] == te.PUSHED
    led = rig.ledger()
    kinds = [e["kind"] for e in led.events(rig.cycle)]
    assert (
        kinds[0] == "evolve.committed" and "evolve.gate" in kinds and kinds[-2:] == ["evolve.merged", "evolve.pushed"]
    )
    row = led.get(rig.cycle)
    assert row is not None and row["state"] == te.PUSHED and row["tree"]
    # indice perdido/atrasado: el ledger dice COMMITTED pero git ya tiene el merge => la reentrada lo reconcilia
    led.set_state(rig.cycle, te.COMMITTED)
    rig.run()
    row = rig.ledger().get(rig.cycle)
    assert row is not None and row["state"] == te.PUSHED


def test_ledger_down_blocks_the_commit_fail_closed(rig: Rig) -> None:
    store = te.EvolveStore(base_dir=rig.state, ledger=None)
    out = te.run_evolve(
        store,
        rig.port(),
        lambda: dict(rig.live),
        cycle=rig.cycle,
        gap="D-88",
        apply=True,
        octal=7,
        label="FULL",
        cycle_dir=rig.state,
        kit=rig.fake.kit(),
    )
    assert out["status"] == "BLOCKED_GIT" and out["reason"] == "no_ledger"
    assert sh(rig.canon, "branch", "--list", "autoevol/*") == ""


def test_revert_pending_blocks_push_of_other_cycles(rig: Rig) -> None:
    rig.ledger().claim("old", "R", "T", "old-cycle", r_before="R", r_after="")
    rig.ledger().mark_reverted("old-cycle")
    out = rig.drive()
    assert out["status"] == "BLOCKED_GIT" and out["reason"] == "dev_dirty_by_revert" and out["state"] == te.MERGED
    assert sh(rig.bare, "rev-parse", "dev") != sh(rig.canon, "rev-parse", "dev")  # nada se empujo
    rig.ledger().resolve_revert("old-cycle")  # decision del usuario
    assert rig.run()["state"] == te.PUSHED


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, 3), ("", 3), ("abc", 3), ("0", 3), ("-2", 3), ("5", 5), (" 2 ", 2)]
)
def test_max_cycles_env_parsing(raw: str | None, expected: int) -> None:
    assert tl.max_cycles_from_env(raw) == expected
