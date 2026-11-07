"""Backlog O-2: reapear un ciclo OPEN huerfano (hot-swap) no reinicia el presupuesto de iteraciones ni de env_retries."""

from __future__ import annotations

import os
from pathlib import Path

from engine import threads_verify as tv


def _store(tmp_path: Path, alive: dict[int, bool]) -> tv.CycleStore:
    return tv.CycleStore(base_dir=tmp_path / "shm", pid_alive=lambda pid: alive.get(pid, False))


def test_reaped_orphan_budget_is_inherited_by_new_cycle(tmp_path: Path) -> None:
    alive = {os.getpid(): True}
    store = _store(tmp_path, alive)
    old = store.open_cycle("gap:1", {"gaps": ["gap:1"]})["cycle_id"]
    store.record(old, {"verdict": tv.REJECT, "reasons": ["x"]})  # iteration 1
    store.note_environmental(old, ["sandbox"])  # env_retries 1
    assert store.load(old)["iteration"] == 1
    alive[os.getpid()] = False  # hot-swap: el dueño murio
    opened = store.open_cycle("gap:1", {"gaps": ["gap:1"]})
    assert opened["iteration"] == 1
    new = store.load(opened["cycle_id"])
    assert store.load(old) is None
    assert new["iteration"] == 1 and new["env_retries"] == 1


def test_inheritance_keeps_the_iteration_cap(tmp_path: Path) -> None:
    alive = {os.getpid(): True}
    store = _store(tmp_path, alive)
    old = store.open_cycle("gap:1", {"gaps": ["gap:1"]})["cycle_id"]
    for _ in range(tv.MAX_ITERATIONS - 1):
        store.record(old, {"verdict": tv.REJECT, "reasons": []})
    alive[os.getpid()] = False
    new_id = store.open_cycle("gap:1", {"gaps": ["gap:1"]})["cycle_id"]
    assert store.load(new_id)["iteration"] == tv.MAX_ITERATIONS - 1
    out = store.record(new_id, {"verdict": tv.REJECT, "reasons": []})
    assert out["state"] == tv.EXHAUSTED  # el presupuesto heredado se agota igual que en el ciclo reapeado


def test_other_gap_and_live_owner_do_not_transfer_budget(tmp_path: Path) -> None:
    alive = {os.getpid(): True}
    store = _store(tmp_path, alive)
    other = store.open_cycle("gap:other", {"gaps": []})["cycle_id"]
    store.record(other, {"verdict": tv.REJECT, "reasons": []})
    fresh = store.open_cycle("gap:1", {"gaps": []})
    assert fresh["iteration"] == 0 and "env_retries" not in store.load(fresh["cycle_id"])
