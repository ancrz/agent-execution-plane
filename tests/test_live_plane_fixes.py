"""
tests/test_live_plane_fixes.py (ONT-39: Fix Cycle L2-fix1 Verification Suite)

Verification of fixes F1, F2, F3, F4:
- T-F1: A tool or child writing to stdout (via injected subprocess / hook) does not corrupt MCP JSON-RPC stream; 3 subsequent calls succeed with valid JSON-RPC.
- T-F2: Backend emits >256 KiB to stderr (via AEP_TEST_STDERR_FLOOD=1) and calls continue responding in < 5 seconds without pipe deadlock.
- T-F3: MCP initialize response contains non-empty instructions including "discover".
- T-F4: front_stale is False at fresh startup, and becomes True after touching aep_front.py across capabilities verbosities.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_t_f1_stdout_corruption_resilience() -> None:
    """T-F1: Child or tool stdout writes do not corrupt MCP protocol stream; 3 subsequent calls succeed."""

    async def _run() -> None:
        env = dict(os.environ)
        env["AEP_HOTSWAP"] = "1"
        env["AEP_TEST_STDOUT_CORRUPT"] = "1"

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(PROJECT_ROOT / "aep_front.py")],
            env=env,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                init_res = await session.initialize()
                assert init_res.serverInfo.name == "Agent-Execution-Plane"

                # Call 1: triggers AEP_TEST_STDOUT_CORRUPT hook during tool execution
                res1 = await session.call_tool("discover", {"action": "capabilities", "verbosity": "terse"})
                data1 = json.loads(res1.content[0].text)
                assert data1.get("status") == "OK"

                # 3 subsequent calls must all return valid JSON-RPC without parse error
                # Subsequent call 1
                res2 = await session.call_tool("topos_audit_dag", {"tasks": ["t1", "t2"]})
                data2 = json.loads(res2.content[0].text)
                assert "verdict" in data2 or "status" in data2

                # Subsequent call 2
                res3 = await session.call_tool("discover", {"action": "playbook", "verbosity": "summary"})
                data3 = json.loads(res3.content[0].text)
                assert data3.get("status") == "OK"

                # Subsequent call 3
                res4 = await session.call_tool("discover", {"action": "capabilities", "verbosity": "summary"})
                data4 = json.loads(res4.content[0].text)
                assert data4.get("status") == "OK"

    asyncio.run(_run())


def test_t_f2_stderr_flood_no_deadlock() -> None:
    """T-F2: Backend writing >256 KiB to stderr does not deadlock and responds in < 5 seconds."""

    async def _run() -> None:
        env = dict(os.environ)
        env["AEP_HOTSWAP"] = "1"
        env["AEP_TEST_STDERR_FLOOD"] = "1"

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(PROJECT_ROOT / "aep_front.py")],
            env=env,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                t0 = time.time()
                await session.initialize()
                init_dur = time.time() - t0
                assert init_dur < 5.0, f"Initialize took too long: {init_dur}s"

                # Tool call timing check
                t1 = time.time()
                res = await session.call_tool("discover", {"action": "capabilities", "verbosity": "terse"})
                call_dur = time.time() - t1
                assert call_dur < 5.0, f"Tool call took too long: {call_dur}s"

                data = json.loads(res.content[0].text)
                assert data.get("status") == "OK"

                # Verify backend log file exists and contains > 256 KiB
                # D-5: logs are per-front. The backend's parent is the front: resolve its exact log.
                backend_pid = data["pid"]
                front_pid = next(
                    int(line.split()[1])
                    for line in Path(f"/proc/{backend_pid}/status").read_text().splitlines()
                    if line.startswith("PPid:")
                )
                log_file = (
                    Path.home() / ".local" / "share" / "agent-os" / "logs" / f"aep_backend_{front_pid}_gen1.log"
                )
                assert log_file.exists()
                assert log_file.stat().st_size >= 256 * 1024

    asyncio.run(_run())


def test_t_f3_initialize_instructions() -> None:
    """T-F3: initialize response contains non-empty instructions that include 'discover'."""

    async def _run() -> None:
        env = dict(os.environ)
        env["AEP_HOTSWAP"] = "1"

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(PROJECT_ROOT / "aep_front.py")],
            env=env,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                init_res = await session.initialize()
                assert init_res.instructions is not None, "instructions should not be None"
                assert len(init_res.instructions) > 0, "instructions should not be empty"
                assert "discover" in init_res.instructions, "instructions should include 'discover'"

    asyncio.run(_run())


def test_t_f4_front_stale_detection() -> None:
    """T-F4: front_stale is False freshly started, and True after touching aep_front.py."""

    async def _run() -> None:
        front_path = PROJECT_ROOT / "aep_front.py"
        orig_st = front_path.stat()

        env = dict(os.environ)
        env["AEP_HOTSWAP"] = "1"

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(front_path)],
            env=env,
        )

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Call 1: freshly started, front_stale should be False across verbosities
                    res1 = await session.call_tool("discover", {"action": "capabilities", "verbosity": "terse"})
                    data1 = json.loads(res1.content[0].text)
                    assert data1.get("status") == "OK"
                    assert data1.get("front_stale") is False, f"Expected False, got {data1.get('front_stale')}"

                    # Touch aep_front.py to make its mtime strictly newer than front start time
                    future_ns = time.time_ns() + 100_000_000  # +100ms
                    os.utime(front_path, ns=(future_ns, future_ns))

                    # Call 2: front_stale should now be True
                    res2 = await session.call_tool("discover", {"action": "capabilities", "verbosity": "terse"})
                    data2 = json.loads(res2.content[0].text)
                    assert data2.get("status") == "OK"
                    assert data2.get("front_stale") is True, f"Expected True, got {data2.get('front_stale')}"

                    # Also verify exposed in summary verbosity
                    res3 = await session.call_tool("discover", {"action": "capabilities", "verbosity": "summary"})
                    data3 = json.loads(res3.content[0].text)
                    assert data3.get("front_stale") is True
        finally:
            os.utime(front_path, ns=(orig_st.st_atime_ns, orig_st.st_mtime_ns))

    asyncio.run(_run())
