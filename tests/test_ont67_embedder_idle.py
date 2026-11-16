"""ONT-67 T3: the embedder model is unloaded after AEP_EMBED_IDLE_S and reloaded transparently."""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

from engine import embedder as emb


class _FakeModel:
    made = 0

    def __init__(self, model_name: str, **kwargs: object) -> None:
        type(self).made += 1
        self.kwargs = kwargs

    def embed(self, texts: list[str]):
        for _ in texts:
            yield [0.5] * emb.EMBEDDING_DIM


@pytest.fixture
def fake_fastembed(monkeypatch: pytest.MonkeyPatch) -> type[_FakeModel]:
    _FakeModel.made = 0
    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=_FakeModel))
    return _FakeModel


def _wait(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_idle_seconds_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(emb.IDLE_ENV, raising=False)
    assert emb.idle_seconds() == 600.0
    monkeypatch.setenv(emb.IDLE_ENV, "0")
    assert emb.idle_seconds() == 0.0
    monkeypatch.setenv(emb.IDLE_ENV, "2.5")
    assert emb.idle_seconds() == 2.5
    monkeypatch.setenv(emb.IDLE_ENV, "junk")
    assert emb.idle_seconds() == 600.0


def test_unloads_when_idle_and_reloads_transparently(monkeypatch: pytest.MonkeyPatch, fake_fastembed) -> None:
    monkeypatch.setenv(emb.IDLE_ENV, "0.2")
    e = emb.LocalEmbedder()
    assert e.is_available and e.is_loaded
    assert _wait(lambda: not e.is_loaded), "model should be unloaded after the idle period"
    assert e.is_available  # unloaded is not unavailable
    vec = e.embed("hello")
    assert vec is not None and len(vec) == emb.EMBEDDING_DIM
    assert e.is_loaded and e.loads == 2 and e.unloads == 1


def test_use_postpones_unload(monkeypatch: pytest.MonkeyPatch, fake_fastembed) -> None:
    monkeypatch.setenv(emb.IDLE_ENV, "0.5")
    e = emb.LocalEmbedder()
    for _ in range(4):
        time.sleep(0.2)
        assert e.embed("x") is not None
    assert e.unloads == 0 and e.is_loaded


def test_zero_means_never_unload(monkeypatch: pytest.MonkeyPatch, fake_fastembed) -> None:
    monkeypatch.setenv(emb.IDLE_ENV, "0")
    e = emb.LocalEmbedder()
    time.sleep(0.3)
    assert e.is_loaded and e.unloads == 0 and e._timer is None


def test_explicit_unload_and_batch_reload(monkeypatch: pytest.MonkeyPatch, fake_fastembed) -> None:
    monkeypatch.setenv(emb.IDLE_ENV, "0")
    e = emb.LocalEmbedder()
    assert e.unload() is True and e.unload() is False
    out = e.embed_batch(["a", "b"])
    assert out is not None and len(out) == 2 and all(v is not None for v in out)


def test_concurrent_embed_during_unload_never_fails(monkeypatch: pytest.MonkeyPatch, fake_fastembed) -> None:
    monkeypatch.setenv(emb.IDLE_ENV, "0.05")
    e = emb.LocalEmbedder()
    results: list[object] = []

    def worker() -> None:
        for _ in range(30):
            results.append(e.embed("q"))
            time.sleep(0.03)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 120 and all(r is not None for r in results)


def test_unload_trims_the_heap(monkeypatch: pytest.MonkeyPatch, fake_fastembed) -> None:
    calls: list[int] = []
    monkeypatch.setattr(emb.memtrim, "trim", lambda: calls.append(1) or True)
    monkeypatch.setenv(emb.IDLE_ENV, "0")
    e = emb.LocalEmbedder()
    assert e.unload() and calls == [1]
