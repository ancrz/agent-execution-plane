"""ONT-67 T1: process_inspect reports the real resident-memory breakdown (VmRSS/RssAnon/RssFile/VmSwap)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

import server
from engine.primitives_orient import process_memory


def _status_kb(pid: int, key: str) -> int:
    with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith(key + ":"):
                return int(line.split()[1])
    raise AssertionError(key)


def test_process_memory_matches_proc_status_for_self() -> None:
    mem = process_memory(os.getpid())
    assert set(mem) >= {"rss_kb", "rss_anon_kb", "rss_file_kb", "swap_kb"}
    assert abs(mem["rss_kb"] - _status_kb(os.getpid(), "VmRSS")) < 4096
    # anon + file (+ shmem) never exceeds the resident set by more than rounding
    assert mem["rss_anon_kb"] + mem["rss_file_kb"] <= mem["rss_kb"] + 64
    assert mem["rss_anon_kb"] > 0


def test_process_memory_missing_pid_is_empty() -> None:
    assert process_memory(2**22 + 12345) == {}


@pytest.mark.anyio
async def test_process_inspect_self_detail_has_memory_and_rss_is_server_vmrss() -> None:
    res = json.loads(await server.process_inspect(pid=0, verbosity="detail"))
    assert res["pid"] == os.getpid()
    assert abs(res["rss_kb"] - _status_kb(os.getpid(), "VmRSS")) < 8192
    assert res["memory"]["rss_anon_kb"] > 0
    assert abs(res["memory"]["rss_kb"] - res["rss_kb"]) < 8192


@pytest.mark.anyio
async def test_process_inspect_summary_is_unchanged_without_memory_block() -> None:
    res = json.loads(await server.process_inspect(pid=0, verbosity="summary"))
    assert "memory" not in res
    assert abs(res["rss_kb"] - _status_kb(os.getpid(), "VmRSS")) < 8192  # summary rss_kb is the real VmRSS


@pytest.mark.anyio
async def test_process_inspect_other_pid_memory_matches_that_process() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdin=subprocess.DEVNULL)  # noqa: S603
    try:
        time.sleep(0.3)
        res = json.loads(await server.process_inspect(pid=proc.pid, verbosity="detail"))
        assert abs(res["memory"]["rss_kb"] - res["rss_kb"]) < 2048
        assert abs(res["rss_kb"] - _status_kb(proc.pid, "VmRSS")) < 2048
    finally:
        proc.kill()
        proc.wait()
