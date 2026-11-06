"""ONT-41 TA5: events_<uid>.jsonl append-only, rotación, primitivas seguras y espejo idempotente al ledger."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest

from engine import threads_events as ev
from engine.security import verify_audit_chain


@pytest.fixture
def shm(tmp_path: Path) -> Path:
    return tmp_path / "aep_autoevol"


def _conn(tmp_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(tmp_path / "ledger.db")


def test_state_dir_path_honours_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(ev.ENV_DIR, raising=False)
    assert ev.state_dir_path() == Path(ev.DEFAULT_DIR)
    monkeypatch.setenv(ev.ENV_DIR, str(tmp_path / "x"))
    assert ev.state_dir_path() == tmp_path / "x"


def test_open_state_dir_creates_0700_and_tightens_loose_permissions(shm: Path) -> None:
    fd = ev.open_state_dir(shm)
    os.close(fd)
    assert stat.S_IMODE(shm.stat().st_mode) == 0o700
    shm.chmod(0o755)
    with ev.state_dir(shm):
        pass
    assert stat.S_IMODE(shm.stat().st_mode) == 0o700


def test_open_state_dir_refuses_symlink_and_foreign_owner(shm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real"
    real.mkdir()
    shm.symlink_to(real)
    with pytest.raises(ev.StateFileError):
        ev.open_state_dir(shm)
    shm.unlink()
    shm.mkdir()
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 4242)
    with pytest.raises(ev.StateFileError):
        ev.open_state_dir(shm)


def test_create_exclusive_write_atomic_read_remove_list(shm: Path) -> None:
    with ev.state_dir(shm) as fd:
        assert ev.create_file_exclusive(fd, "a.json", b"1") is True
        assert ev.create_file_exclusive(fd, "a.json", b"2") is False
        assert ev.read_file(fd, "a.json") == b"1"
        ev.write_file_atomic(fd, "a.json", b"3")
        assert ev.read_file(fd, "a.json") == b"3"
        assert stat.S_IMODE((shm / "a.json").stat().st_mode) == 0o600
        assert ev.list_names(fd) == ["a.json"]  # sin temporales residuales
        assert ev.read_file(fd, "missing") is None
        assert ev.remove_file(fd, "a.json") is True
        assert ev.remove_file(fd, "a.json") is False


def test_read_file_rejects_symlink_oversize_and_non_regular(shm: Path, tmp_path: Path) -> None:
    with ev.state_dir(shm) as fd:
        (tmp_path / "t").write_text("secret")
        (shm / "link").symlink_to(tmp_path / "t")
        with pytest.raises(ev.StateFileError):
            ev.read_file(fd, "link")
        ev.write_file_atomic(fd, "big", b"x" * 100)
        with pytest.raises(ev.StateFileError):
            ev.read_file(fd, "big", max_bytes=10)
        (shm / "sub").mkdir()
        with pytest.raises(ev.StateFileError):
            ev.read_file(fd, "sub")


def test_file_names_cannot_escape_the_directory(shm: Path) -> None:
    with ev.state_dir(shm) as fd:
        for bad in ("../x", "a/b", "", "..", ".", "a\x00b"):
            with pytest.raises(ev.StateFileError):
                ev.create_file_exclusive(fd, bad, b"x")


def test_write_atomic_cleans_temp_on_failure(shm: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with ev.state_dir(shm) as fd:

        def boom(*_a: object, **_k: object) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            ev.write_file_atomic(fd, "a.json", b"x")
        assert ev.list_names(fd) == []


def test_append_event_format_permissions_and_uid_file(shm: Path) -> None:
    out = ev.append_event("probe", {"a": 1}, base_dir=shm, clock=lambda: 12.3456)
    assert out["appended"] is True and out["rotated"] is False and len(out["line_sha"]) == 16
    path = shm / f"events_{os.geteuid()}.jsonl"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    [line] = path.read_text().splitlines()
    obj = json.loads(line)
    assert obj["kind"] == "probe" and obj["a"] == 1 and obj["ts"] == 12.346
    assert len(obj["nonce"]) == 8


def test_every_line_is_unique_even_for_identical_payloads(shm: Path) -> None:
    for _ in range(20):
        ev.append_event("same", {"x": 1}, base_dir=shm, clock=lambda: 1.0)
    lines = (shm / f"events_{os.geteuid()}.jsonl").read_text().splitlines()
    assert len(set(lines)) == 20


def test_append_is_fail_soft_when_dir_unusable(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    out = ev.append_event("k", base_dir=blocker / "sub")
    assert out["appended"] is False and "error" in out


def test_append_refuses_symlinked_events_file(shm: Path, tmp_path: Path) -> None:
    shm.mkdir(mode=0o700)
    target = tmp_path / "victim"
    target.write_text("keep")
    (shm / f"events_{os.geteuid()}.jsonl").symlink_to(target)
    assert ev.append_event("k", base_dir=shm)["appended"] is False
    assert target.read_text() == "keep"


def test_rotation_by_line_count_keeps_dot_one(shm: Path) -> None:
    name = shm / f"events_{os.geteuid()}.jsonl"
    shm.mkdir(mode=0o700)
    name.write_text("".join(json.dumps({"kind": "old", "i": i}) + "\n" for i in range(ev.EVENTS_MAX_LINES)))
    out = ev.append_event("new", base_dir=shm)
    assert out["rotated"] is True
    rotated = shm / f"{name.name}.1"
    assert rotated.read_text().count("\n") == ev.EVENTS_MAX_LINES
    assert [json.loads(x)["kind"] for x in name.read_text().splitlines()] == ["new"]
    kinds = [e["kind"] for e in ev.read_events(base_dir=shm)]
    assert kinds[-1] == "new" and kinds.count("old") == ev.EVENTS_MAX_LINES
    assert [e["kind"] for e in ev.read_events(base_dir=shm, include_rotated=False)] == ["new"]


def test_rotation_by_size(shm: Path) -> None:
    shm.mkdir(mode=0o700)
    name = shm / f"events_{os.geteuid()}.jsonl"
    name.write_text(json.dumps({"kind": "fat", "pad": "x" * ev.EVENTS_MAX_BYTES}) + "\n")
    assert ev.append_event("n", base_dir=shm)["rotated"] is True
    assert (shm / f"{name.name}.1").is_file()


def test_second_rotation_overwrites_dot_one(shm: Path) -> None:
    shm.mkdir(mode=0o700)
    name = shm / f"events_{os.geteuid()}.jsonl"
    for tag in ("first", "second"):
        name.write_text(json.dumps({"kind": tag, "pad": "x" * ev.EVENTS_MAX_BYTES}) + "\n")
        ev.append_event("n", base_dir=shm)
    assert json.loads((shm / f"{name.name}.1").read_text().splitlines()[0])["kind"] == "second"


def test_read_events_skips_corrupt_and_non_object_lines(shm: Path) -> None:
    ev.append_event("ok", base_dir=shm)
    with open(shm / f"events_{os.geteuid()}.jsonl", "a") as fh:
        fh.write("garbage\n[1]\n\n")
    assert [e["kind"] for e in ev.read_events(base_dir=shm)] == ["ok"]


def test_mirror_is_idempotent_and_chain_stays_valid(shm: Path, tmp_path: Path) -> None:
    for i in range(3):
        ev.append_event("cycle_terminal", {"state": "EXHAUSTED", "i": i}, base_dir=shm)
    conn = _conn(tmp_path)
    first = ev.mirror_to_ledger(conn, base_dir=shm, tier_octal=6)
    assert first == {"mirrored": 3, "skipped": 0, "invalid": 0}
    again = ev.mirror_to_ledger(conn, base_dir=shm, tier_octal=7)
    assert again == {"mirrored": 0, "skipped": 3, "invalid": 0}
    ev.append_event("cycle_terminal", {"state": "ACCEPTED"}, base_dir=shm)
    assert ev.mirror_to_ledger(conn, base_dir=shm)["mirrored"] == 1
    rows = conn.execute("SELECT action, status, tool_name FROM security_audit_log").fetchall()
    assert len(rows) == 4 and set(rows) == {(ev.LEDGER_ACTION, "RECORDED", "autoevol")}
    assert verify_audit_chain(conn)["valid"] is True
    conn.close()


def test_mirror_is_a_noop_below_tier_6(shm: Path, tmp_path: Path) -> None:
    ev.append_event("cycle_terminal", {"state": "EXHAUSTED"}, base_dir=shm)
    conn = _conn(tmp_path)
    out = ev.mirror_to_ledger(conn, base_dir=shm, tier_octal=5)
    assert out["mirrored"] == 0 and out["reason"] == "tier < 6rw-"
    assert ev.mirror_to_ledger(conn, base_dir=shm, tier_octal=6)["mirrored"] == 1  # esperó en el JSONL
    conn.close()


def test_mirror_counts_invalid_lines_and_caps_per_call(shm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ev.append_event("a", base_dir=shm)
    ev.append_event("b", base_dir=shm)
    with open(shm / f"events_{os.geteuid()}.jsonl", "a") as fh:
        fh.write("garbage\n")
    conn = _conn(tmp_path)
    monkeypatch.setattr(ev, "MIRROR_MAX_LINES", 1)
    first = ev.mirror_to_ledger(conn, base_dir=shm)
    assert first["mirrored"] == 1
    monkeypatch.setattr(ev, "MIRROR_MAX_LINES", 10)
    second = ev.mirror_to_ledger(conn, base_dir=shm)
    assert (second["mirrored"], second["skipped"], second["invalid"]) == (1, 1, 1)
    conn.close()


def test_mirror_without_events_file(shm: Path, tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    assert ev.mirror_to_ledger(conn, base_dir=shm) == {"mirrored": 0, "skipped": 0, "invalid": 0}
    conn.close()
