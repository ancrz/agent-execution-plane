"""ONT-66 T1: analisis caliente tras la carga del backend: en segundo plano, sin FDs filtrados, sin tocar la BD real."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

import server
from engine import notices
from engine import threads as th


@pytest.fixture
def mini_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    repo = tmp_path / "repo"
    (repo / "engine").mkdir(parents=True)
    (repo / "engine" / "__init__.py").write_text("")
    (repo / "engine" / "mod.py").write_text("def f():\n    return 1\n")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("AEP_DATA_HOME", str(data))
    monkeypatch.setattr(server, "REPO_ROOT", repo)
    th.clear_cache()
    yield repo
    th.clear_cache()


def _join() -> None:
    thread = notices._HOT["thread"]
    if thread is not None:
        thread.join(timeout=30)


def test_start_hot_analysis_populates_cache_without_blocking(mini_repo: Path) -> None:
    _join()
    assert th.cached_analysis(mini_repo) is None
    t0 = time.perf_counter()
    assert server.start_hot_analysis() is True
    assert time.perf_counter() - t0 < 0.5  # lanzar no espera al analisis
    _join()
    assert th.cached_analysis(mini_repo) is not None
    state = notices.hot_state()
    assert state["error"] is None and state["elapsed_ms"] is not None and state["running"] is False
    assert state["elapsed_ms"] < 3000  # criterio: cache caliente en < 3 s


def test_hot_analysis_leaks_no_fds_and_never_writes_the_data_home(mini_repo: Path, tmp_path: Path) -> None:
    _join()
    before = set(os.listdir("/proc/self/fd"))
    server.start_hot_analysis()
    _join()
    after = set(os.listdir("/proc/self/fd"))
    assert len(after - before) == 0
    assert list((tmp_path / "data").iterdir()) == []  # AEP_DATA_HOME intacto: ni BD ni ledger


def test_hot_analysis_is_idempotent_while_running_and_fail_soft() -> None:
    _join()
    gate = threading.Event()
    first = notices.start_hot_analysis(gate.wait)
    assert first is not None
    assert notices.start_hot_analysis(gate.wait) is None  # ya hay uno corriendo
    gate.set()
    first.join(timeout=5)

    def boom() -> None:
        raise RuntimeError("x")

    done = threading.Event()
    t = notices.start_hot_analysis(boom, on_done=done.set)
    assert t is not None
    t.join(timeout=5)
    assert done.is_set() and notices.hot_state()["error"] == "RuntimeError"


def test_hot_analysis_can_be_disabled_and_refresh_is_throttled(
    mini_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _join()
    monkeypatch.setenv("AEP_HOT_ANALYSIS", "0")
    assert server.start_hot_analysis() is False
    monkeypatch.setenv("AEP_HOT_ANALYSIS", "1")
    server.start_hot_analysis()
    _join()
    th.clear_cache()
    monkeypatch.setenv("AEP_NOTICE_REFRESH_S", "3600")
    server._hot_refresh_if_due()  # aun no toca: la cache sigue vacia
    _join()
    assert th.cached_analysis(mini_repo) is None
    monkeypatch.setenv("AEP_NOTICE_REFRESH_S", "0")
    server._hot_refresh_if_due()
    _join()
    assert th.cached_analysis(mini_repo) is not None


def test_cached_analysis_follows_the_tree_last_analyzed_even_on_a_cache_hit(mini_repo: Path) -> None:
    """Revert-to-earlier-content must not leave `cached_analysis` pointing at the newer, different entry."""
    a = th.analyze(mini_repo)
    (mini_repo / "engine" / "mod.py").write_text("def f():\n    return 2\n")
    b = th.analyze(mini_repo)
    assert a.inputs_hash != b.inputs_hash
    (mini_repo / "engine" / "mod.py").write_text("def f():\n    return 1\n")
    again = th.analyze(mini_repo)
    assert again.inputs_hash == a.inputs_hash
    latest = th.cached_analysis(mini_repo)
    assert latest is not None and latest.inputs_hash == a.inputs_hash
