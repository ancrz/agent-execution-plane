"""ONT-41 TA3: máquina de estados del ciclo fix -> test y su almacén seguro (/dev/shm aislado por tmp_path)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from engine import threads_events as ev
from engine import threads_verify as tv

GAP = "omission:fn:a.f:in:covers"
BASE: dict[str, Any] = {"root": "r", "gaps": [GAP], "codep": [], "hashes": {}, "public": [], "direct": []}
REJECT = {"verdict": tv.REJECT, "reasons": [tv.NO_PROGRESS]}
ACCEPT = {"verdict": tv.ACCEPT, "reasons": []}


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> tv.CycleStore:
    return tv.CycleStore(base_dir=tmp_path / "shm", clock=clock)


def _files(store: tv.CycleStore) -> list[str]:
    with ev.state_dir(store._dir) as fd:
        return ev.list_names(fd)


def test_cycle_id_is_server_generated_hex12_and_regex_validated() -> None:
    cid = tv.new_cycle_id()
    assert len(cid) == 12 and tv.valid_cycle_id(cid)
    assert tv.new_cycle_id() != cid
    for bad in ("", "xyz", "../../etc/passwd", "ABCDEF123456", "0" * 13, None, 12):
        assert not tv.valid_cycle_id(bad)
    with pytest.raises(ValueError):
        tv.cycle_file_name(1, "../x")


def test_cycle_file_name_is_sha256_uid_cycle_prefix() -> None:
    import hashlib

    name = tv.cycle_file_name(1000, "0123456789ab")
    assert name == "cycle_" + hashlib.sha256(b"1000|0123456789ab").hexdigest()[:16] + ".json"
    assert tv.cycle_file_name(1001, "0123456789ab") != name


def test_next_state_transitions() -> None:
    assert tv.next_state(tv.OPEN, tv.ACCEPT, 0) == (tv.ACCEPTED, 1)
    assert tv.next_state(tv.OPEN, tv.PENDING, 1) == (tv.CYCLE_PENDING, 1)
    assert tv.next_state(tv.OPEN, tv.REJECT, 0) == (tv.OPEN, 1)
    assert tv.next_state(tv.CYCLE_PENDING, tv.REJECT, 1) == (tv.OPEN, 2)
    assert tv.next_state(tv.OPEN, tv.REJECT, 2) == (tv.EXHAUSTED, 3)
    with pytest.raises(ValueError):
        tv.next_state(tv.ACCEPTED, tv.REJECT, 1)
    with pytest.raises(ValueError):
        tv.next_state(tv.EXHAUSTED, tv.ACCEPT, 3)


def test_start_creates_private_file_with_frozen_base(store: tv.CycleStore, tmp_path: Path) -> None:
    out = store.open_cycle(GAP, BASE)
    assert out["status"] == "OK" and out["state"] == tv.OPEN and out["iteration"] == 0
    shm = tmp_path / "shm"
    assert stat.S_IMODE(shm.stat().st_mode) == 0o700
    [f] = [p for p in shm.iterdir() if p.name.startswith("cycle_")]
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert f.stat().st_uid == os.geteuid()
    assert f.name == tv.cycle_file_name(os.geteuid(), out["cycle_id"])
    rec = json.loads(f.read_text())
    assert rec["base"] == BASE and rec["gap"] == GAP and rec["max_iterations"] == 3


def test_start_rejects_invalid_gap(store: tv.CycleStore) -> None:
    assert store.open_cycle("", BASE)["status"] == "INVALID_GAP"
    assert store.open_cycle("x" * 500, BASE)["status"] == "INVALID_GAP"


def test_reject_reject_reject_is_exhausted_and_locks_ten_minutes(store: tv.CycleStore, clock: Clock) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    assert store.record(cid, REJECT)["state"] == tv.OPEN
    assert store.record(cid, REJECT)["iteration"] == 2
    last = store.record(cid, REJECT)
    assert last["state"] == tv.EXHAUSTED and last["iteration"] == 3
    assert last["retry_after_s"] == tv.LOCK_SECONDS
    assert store.record(cid, REJECT) == {"status": "CLOSED", "state": tv.EXHAUSTED}
    clock.t += 599
    locked = store.open_cycle(GAP, BASE)
    assert locked["status"] == "LOCKED" and 0 < locked["retry_after_s"] <= 1
    assert store.open_cycle("omission:other:in:covers", BASE)["status"] == "OK"  # el bloqueo es por gap
    clock.t += 2
    assert store.open_cycle(GAP, BASE)["status"] == "OK"


def test_restart_clears_the_lock(store: tv.CycleStore) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    for _ in range(3):
        store.record(cid, REJECT)
    assert store.open_cycle(GAP, BASE)["status"] == "LOCKED"
    assert store.open_cycle(GAP, BASE, restart=True)["status"] == "OK"
    assert store.open_cycle(GAP, BASE)["status"] == "OK"


def test_accept_is_terminal_and_closes(store: tv.CycleStore) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    out = store.record(cid, ACCEPT)
    assert out["state"] == tv.ACCEPTED
    assert store.record(cid, REJECT)["status"] == "CLOSED"
    assert store.open_cycle(GAP, BASE)["status"] == "OK"  # ACCEPTED no bloquea


def test_pending_does_not_consume_an_iteration_and_keeps_job(store: tv.CycleStore) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    out = store.record(cid, {"verdict": tv.PENDING, "reasons": [], "job": "17"})
    assert out["state"] == tv.CYCLE_PENDING and out["iteration"] == 0
    rec = store.load(cid)
    assert rec is not None and rec["job"] == "17"
    done = store.record(cid, REJECT)
    assert done["state"] == tv.OPEN and done["iteration"] == 1
    assert store.load(cid)["job"] is None  # type: ignore[index]


def test_terminal_states_are_appended_to_events_jsonl(store: tv.CycleStore, tmp_path: Path) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    for _ in range(3):
        store.record(cid, REJECT)
    events = ev.read_events(base_dir=tmp_path / "shm")
    assert [e["kind"] for e in events] == ["cycle_terminal"]
    assert events[0]["state"] == tv.EXHAUSTED and events[0]["cycle_id"] == cid and events[0]["iterations"] == 3


def test_ttl_expires_the_cycle_and_removes_the_file(store: tv.CycleStore, clock: Clock) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    clock.t += tv.CYCLE_TTL_SECONDS + 1
    assert store.load(cid) == {"cycle_id": cid, "state": tv.EXPIRED}
    assert store.record(cid, REJECT)["status"] == "NOT_FOUND"  # el archivo ya se borró al detectar el vencimiento
    assert [n for n in _files(store) if n.startswith("cycle_")] == []


def test_record_expired_between_load_and_record(store: tv.CycleStore, clock: Clock) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    clock.t += tv.CYCLE_TTL_SECONDS + 1
    assert store.record(cid, REJECT)["status"] == tv.EXPIRED


def test_invalid_and_unknown_ids(store: tv.CycleStore) -> None:
    assert store.load("../etc") is None
    assert store.record("../etc", ACCEPT) == {"status": "INVALID_CYCLE"}
    assert store.record("0" * 12, ACCEPT) == {"status": "NOT_FOUND"}


def test_corrupted_or_non_dict_cycle_file_is_ignored(store: tv.CycleStore, tmp_path: Path) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    path = tmp_path / "shm" / tv.cycle_file_name(os.geteuid(), cid)
    path.write_text("{not json")
    assert store.load(cid) is None
    path.write_text("[1, 2]")
    assert store.load(cid) is None


def test_symlinked_cycle_file_is_refused(store: tv.CycleStore, tmp_path: Path) -> None:
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    path = tmp_path / "shm" / tv.cycle_file_name(os.geteuid(), cid)
    target = tmp_path / "evil.json"
    target.write_text(path.read_text())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ev.StateFileError):
        store.load(cid)


def test_other_uid_cannot_read_the_cycle(tmp_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tv.CycleStore(base_dir=tmp_path / "shm", clock=clock)
    cid = store.open_cycle(GAP, BASE)["cycle_id"]
    other = tv.CycleStore(base_dir=tmp_path / "shm", clock=clock, uid=os.geteuid() + 1)
    assert other.load(cid) is None  # el nombre de archivo depende del uid
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 4242)
    with pytest.raises(ev.StateFileError):
        store.load(cid)
