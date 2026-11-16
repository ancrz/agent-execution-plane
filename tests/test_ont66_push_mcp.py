"""ONT-66 T4: `notifications/message` (logger "aep.notice") emitted ONCE per change, through the REAL front over stdio.

The analysed tree is a synthetic copy pointed to by AEP_REPO_ROOT (never the real repo) and AEP_DATA_HOME is temporary."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_ont66_notice_piggyback import _CLEAN, _DRIFT, _tree

import aep_front

PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def _call(session: ClientSession, name: str, args: dict[str, Any]) -> dict[str, Any]:
    res = await session.call_tool(name, args)
    return json.loads(res.content[0].text)


async def _wait_for(pred: Any, session: ClientSession, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    out: dict[str, Any] = {}
    while time.monotonic() < deadline:
        out = await _call(session, "process_inspect", {"pid": 0, "verbosity": "terse"})
        if pred(out):
            return out
        await asyncio.sleep(0.4)
    return out


def test_push_is_emitted_once_per_change_with_a_real_mcp_client(tmp_path: Path) -> None:
    assert callable(aep_front.LivePlaneManager.emit_push)  # the probed unit
    repo = tmp_path / "repo"
    repo.mkdir()
    _tree(repo, _DRIFT)
    data = tmp_path / "data"
    data.mkdir()
    env = {
        **os.environ,
        "AEP_REPO_ROOT": str(repo),
        "AEP_DATA_HOME": str(data),
        "AEP_HOTSWAP": "1",
        "AEP_NOTICE_REFRESH_S": "0.5",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    logs: list[Any] = []

    async def on_log(params: Any) -> None:
        logs.append(params)

    async def _run() -> None:
        params = StdioServerParameters(command=sys.executable, args=[str(PROJECT_ROOT / "aep_front.py")], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, logging_callback=on_log) as session:
                init = await session.initialize()
                assert init.capabilities.logging is not None  # `logging` capability declared
                first = await _wait_for(lambda o: "aep_notice" in o, session)
                # the synthetic tree also trips plane:code_stale (its disk fingerprint != the loaded code): count >= 1
                n0 = first["aep_notice"]["count"]
                assert n0 >= 1 and "claim_drift" in first["aep_notice"]["ask_user"]
                for _ in range(5):  # many calls, same notice set: no further push
                    assert "aep_notice" in await _call(session, "process_inspect", {"pid": 0, "verbosity": "terse"})
                await asyncio.sleep(0.5)
                assert len(logs) == 1, logs
                msg = logs[0]
                assert msg.logger == "aep.notice" and msg.level == "warning"
                assert msg.data["count"] == n0 and msg.data["ask_user"].endswith("¿Quieres mejorarlo?")
                await _call(session, "autoevol", {"action": "ack", "all": True})
                (repo / "README.md").write_text(_DRIFT + "Also 16 tools here.\n")  # NEW drift after the ack
                again = await _wait_for(lambda o: "aep_notice" in o, session)
                assert again["aep_notice"]["count"] == 1
                await asyncio.sleep(0.5)
                assert len(logs) == 2 and logs[1].data["count"] == 1
                (repo / "README.md").write_text(_CLEAN)  # resolved: no notice, no push
                gone = await _wait_for(lambda o: "aep_notice" not in o, session)
                assert "aep_notice" not in gone
                await asyncio.sleep(0.5)
                assert len(logs) == 2

    asyncio.run(_run())


@pytest.mark.parametrize("level", ["warning", "error"])
def test_emit_push_dedupes_and_waits_for_a_session(level: str) -> None:
    class _Session:
        def __init__(self) -> None:
            self.sent: list[tuple[str, Any, str]] = []

        async def send_log_message(self, level: str, data: Any, logger: str | None = None) -> None:
            self.sent.append((level, data, str(logger)))

    async def _run() -> None:
        mgr = aep_front.LivePlaneManager()
        push = {"level": level, "logger": "aep.notice", "data": {"count": 1, "ask_user": "x"}}
        assert await mgr.emit_push(push) is False and mgr.pending_push == push  # no session yet: kept pending
        session = _Session()
        mgr.cached_session = session  # type: ignore[assignment]
        assert await mgr.emit_push(push) is True
        assert await mgr.emit_push(push) is False  # identical content: never resent
        assert session.sent == [(level, push["data"], "aep.notice")]
        assert await mgr.emit_push({**push, "data": {"count": 2, "ask_user": "y"}}) is True

    asyncio.run(_run())


def test_no_findings_means_zero_notifications_and_no_notice_block(tmp_path: Path) -> None:
    """The repo itself has 0 gaps (GAPS_BASELINE) and loaded == disk: nothing to announce."""
    assert callable(aep_front.LivePlaneManager.call_tool)
    data = tmp_path / "data"
    data.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "AEP_REPO_ROOT"}
    env.update({"AEP_DATA_HOME": str(data), "AEP_HOTSWAP": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    logs: list[Any] = []

    async def on_log(params: Any) -> None:
        logs.append(params)

    async def _run() -> None:
        params = StdioServerParameters(command=sys.executable, args=[str(PROJECT_ROOT / "aep_front.py")], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, logging_callback=on_log) as session:
                await session.initialize()
                await asyncio.sleep(4.0)  # the hot analysis has finished by now
                for _ in range(4):
                    assert "aep_notice" not in await _call(session, "process_inspect", {"pid": 0, "verbosity": "terse"})
                await asyncio.sleep(0.5)
                assert logs == []

    asyncio.run(_run())
