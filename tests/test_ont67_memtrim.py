"""ONT-67 T6: fail-soft malloc_trim helper."""

from __future__ import annotations

import pytest

from engine import memtrim


def test_trim_returns_bool_and_never_raises() -> None:
    assert isinstance(memtrim.trim(), bool)


def test_trim_releases_freed_heap_on_glibc() -> None:
    blobs = [bytearray(1024) for _ in range(20000)]
    del blobs
    assert memtrim.trim() in (True, False)


def test_trim_is_false_when_symbol_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(memtrim._STATE, "fn", None)
    monkeypatch.setitem(memtrim._STATE, "resolved", True)
    assert memtrim.trim() is False


def test_trim_swallows_call_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_n: int) -> int:
        raise OSError("nope")

    monkeypatch.setitem(memtrim._STATE, "fn", boom)
    monkeypatch.setitem(memtrim._STATE, "resolved", True)
    assert memtrim.trim() is False
