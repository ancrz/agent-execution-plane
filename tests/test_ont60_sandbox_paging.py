"""ONT-60 T1: sandbox_run truncated => output_ref + cursor, and paging without re-execution."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import server

pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")


@pytest.fixture(autouse=True)
def _pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pool = tmp_path / "pool"
    monkeypatch.setenv("AEP_POOL_DIR", str(pool))
    return pool


def _run(**kw) -> dict:
    return json.loads(asyncio.run(server.sandbox_run(**kw)))


def _page_all(ref: str, limit: int) -> str:
    cursor: str | None = "0"
    chunks: list[str] = []
    while cursor is not None:
        page = json.loads(asyncio.run(server.sandbox_run(output_ref=ref, cursor=cursor, limit=limit)))
        assert page["status"] == "OK"
        chunks.append(page["output"])
        assert page["truncated"] == (page["cursor"] is not None)
        cursor = page["cursor"]
    return "\n".join(chunks)


def test_summary_truncation_exposes_cursor_and_pages_to_the_end() -> None:
    out = _run(command="seq 1 3000", verbosity="summary")
    if out["status"] == "EXEC_FAILED":
        pytest.skip("sandbox cannot run in this environment")
    assert out["truncated"] is True
    assert out["cursor"] is not None
    ref = out["output_ref"]
    assert oct(Path(ref).stat().st_mode & 0o777) == "0o600"
    rebuilt = _page_all(ref, limit=500)
    assert rebuilt.splitlines() == [str(i) for i in range(1, 3001)]


def test_short_output_is_not_truncated() -> None:
    out = _run(command="echo hola", verbosity="summary")
    if out["status"] == "EXEC_FAILED":
        pytest.skip("sandbox cannot run in this environment")
    assert out["truncated"] is False
    assert out["cursor"] is None
    assert "output_ref" not in out


def test_output_ref_outside_pool_is_param_error(tmp_path: Path) -> None:
    stray = tmp_path / "stray.out"
    stray.write_text("secret\n")
    assert _run(output_ref=str(stray))["status"] == "PARAM_ERROR"
    assert _run(output_ref="/etc/passwd")["status"] == "PARAM_ERROR"
    assert _run(output_ref=str(server._sandbox_out_dir() / "sandbox_req_0000000000.out"))["status"] == "PARAM_ERROR"


def test_unpersistable_output_is_not_truncated_and_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_sandbox_out_persist", lambda *_a, **_k: None)
    out = _run(command="seq 1 3000", verbosity="summary")
    if out["status"] == "EXEC_FAILED":
        pytest.skip("sandbox cannot run in this environment")
    assert out["truncated"] is False
    assert out["severity"] == "WARN"
    assert out["limits"] == ["output not persisted"]
    assert len(out["stdout"].splitlines()) == 3000


def test_reaper_drops_expired_and_caps_count(tmp_path: Path) -> None:
    d = server._sandbox_out_dir()
    old = d / "sandbox_req_aaaaaaaaaa.out"
    old.write_text("x")
    server._sandbox_out_reap(d, now=old.stat().st_mtime + server._SANDBOX_OUT_TTL_SEC + 5)
    assert not old.exists()
    for i in range(server._SANDBOX_OUT_MAX_FILES + 5):
        (d / f"sandbox_req_{i:010x}.out").write_text("x")
    server._sandbox_out_reap(d)
    assert len(list(d.glob("sandbox_*.out"))) == server._SANDBOX_OUT_MAX_FILES


def test_persist_cap_is_exactly_the_maximum() -> None:
    assert server._SANDBOX_OUT_MAX_FILES > 0
    for i in range(server._SANDBOX_OUT_MAX_FILES + 10):
        assert server._sandbox_out_persist(f"req_{i:010x}", "x", "")
    d = server._sandbox_out_dir()
    assert len(list(d.glob("sandbox_*.out"))) == server._SANDBOX_OUT_MAX_FILES
