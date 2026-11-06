"""
Unit and integration tests for Milestone ONT-35 / Fix:
Version Stamp Integrity (GAP-RT-04), Multi-Harness Sync (GAP-RT-03) & Sandbox Ergonomics.

Verifies:
  a) discover(action="capabilities"|"version") exposes loaded_commit, repo_head, and stale (bool).
  b) When loaded_commit == repo_head, stale is False and severity is INFO.
  c) Simulation of drift (LOADED_COMMIT != repo_head): stale is True, severity is WARN,
     next_action contains PID and repo_head, summary details the drift.
  d) _parse_ruff_output structures output of both format and check (would_reformat, reformatted, violations, fixable).
  e) sandbox_run in brief mode truncates long stdout to stdout_tail, emits stdout_bytes and truncated: True.
  f) sandbox_run docstring explicitly documents env={...} recommendation over shell env prefix.
  g) sandbox_run auto-mounts uv and uv cache when working_dir contains uv.lock or pyproject.toml.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest.mock as mock
from pathlib import Path

import pytest

import server

# ==============================================================================
# a) & b) discover exposes loaded_commit, repo_head, stale (bool)
# ==============================================================================


def test_discover_capabilities_and_version_stamp_integrity() -> None:
    """discover(action="capabilities"|"version") exposes loaded_commit, repo_head, stale."""
    for act in ("capabilities", "version"):
        raw = asyncio.run(server.discover(action=act, verbosity="detail", force_refresh=True))
        data = json.loads(raw)
        assert "loaded_commit" in data, f"loaded_commit missing in action={act}"
        assert "repo_head" in data, f"repo_head missing in action={act}"
        assert "stale" in data, f"stale missing in action={act}"
        assert isinstance(data["stale"], bool), f"stale must be boolean in action={act}"
        assert data["git_commit"] == data["loaded_commit"], f"git_commit must equal loaded_commit in action={act}"
        assert data["loaded_commit"] == server.LOADED_COMMIT
        if data["loaded_commit"] != "unknown" and data["repo_head"] != "unknown":
            if data["loaded_commit"] == data["repo_head"]:
                assert data["stale"] is False
                assert data.get("severity") == "INFO"


def test_discover_stale_false_when_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    """When loaded_commit == repo_head, stale is False and severity is INFO."""
    monkeypatch.setattr(server, "LOADED_COMMIT", "a1b2c3d")
    monkeypatch.setattr(server, "_read_git_head_commit", lambda: "a1b2c3d")

    raw = asyncio.run(server.discover(action="capabilities", verbosity="summary", force_refresh=True))
    data = json.loads(raw)

    assert data["loaded_commit"] == "a1b2c3d"
    assert data["repo_head"] == "a1b2c3d"
    assert data["stale"] is False
    assert data.get("severity") == "INFO"
    assert "AEP process is STALE" not in data.get("summary", "")


# ==============================================================================
# c) Simulation of drift (LOADED_COMMIT != repo_head) -> WARN & next_action
# ==============================================================================


def test_discover_drift_simulation_warn_and_next_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulated drift causes stale=True, severity=WARN, and restart instructions with PID and hash."""
    monkeypatch.setattr(server, "LOADED_COMMIT", "old1111")
    monkeypatch.setattr(server, "_read_git_head_commit", lambda: "new2222")
    # D-25 (ONT-42a): a commit alone is informational; stale needs a code fingerprint change.
    monkeypatch.setattr(server, "LOADED_FINGERPRINT", "loaded-fp-0000")

    raw = asyncio.run(server.discover(action="capabilities", verbosity="detail", force_refresh=True))
    data = json.loads(raw)

    assert data["stale"] is True
    assert data["loaded_commit"] == "old1111"
    assert data["repo_head"] == "new2222"
    assert data.get("severity") == "WARN"

    summary = data.get("summary", "")
    assert "AEP process is STALE" in summary
    assert "old1111" in summary
    assert "new2222" in summary

    next_act = data.get("next_action", "")
    assert str(os.getpid()) in next_act
    assert "new2222" in next_act
    assert "Restart this AEP instance" in next_act


# ==============================================================================
# d) _parse_ruff_output format and check ergonomics
# ==============================================================================


def test_parse_ruff_output_check_only() -> None:
    """_parse_ruff_output parses lint violations and fixable counts into structured check dict."""
    raw_clean_check = "All checks passed!"
    parsed_clean_check = server._parse_ruff_output(raw_clean_check)
    assert parsed_clean_check is not None
    assert parsed_clean_check["tool"] == "ruff"
    assert parsed_clean_check["violations"] == 0
    assert parsed_clean_check["fixable"] == 0
    assert parsed_clean_check["check"] == {"violations": 0, "fixable": 0}
    assert "format" not in parsed_clean_check

    raw_err = "Found 7 errors (3 fixable)."
    parsed_err = server._parse_ruff_output(raw_err)
    assert parsed_err is not None
    assert parsed_err["violations"] == 7
    assert parsed_err["fixable"] == 3
    assert parsed_err["check"] == {"violations": 7, "fixable": 3}
    assert "format" not in parsed_err


def test_parse_ruff_output_format_only() -> None:
    """_parse_ruff_output parses would_reformat and reformatted counts into structured format dict."""
    raw_wf = "2 files would be reformatted, 15 files left unchanged"
    parsed_wf = server._parse_ruff_output(raw_wf)
    assert parsed_wf is not None
    assert parsed_wf["tool"] == "ruff"
    assert parsed_wf["format"] == {"would_reformat": 2}
    assert parsed_wf["violations"] == 2
    assert "check" not in parsed_wf

    raw_rf = "3 files reformatted"
    parsed_rf = server._parse_ruff_output(raw_rf)
    assert parsed_rf is not None
    assert parsed_rf["format"] == {"reformatted": 3}
    assert "check" not in parsed_rf


def test_parse_ruff_output_composite_check_and_format() -> None:
    """_parse_ruff_output distinguishes both check and format subcommands without hiding either."""
    raw_comp = "Found 4 errors (2 fixable)\n1 file would be reformatted, 10 files left unchanged"
    parsed = server._parse_ruff_output(raw_comp)
    assert parsed is not None
    assert parsed["tool"] == "ruff"
    assert parsed["check"] == {"violations": 4, "fixable": 2}
    assert parsed["format"] == {"would_reformat": 1}
    assert parsed["violations"] == 4
    assert parsed["fixable"] == 2


# ==============================================================================
# e) sandbox_run brief capping of long stdout
# ==============================================================================


def test_sandbox_run_brief_truncates_long_stdout() -> None:
    """sandbox_run in brief mode truncates long stdout (>1000 chars or >20 lines) to stdout_tail."""
    long_output = "\n".join(f"line_{i:02d}_" + ("x" * 30) for i in range(50))
    mock_proc = mock.Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = long_output
    mock_proc.stderr = ""

    with mock.patch("server.subprocess.run", return_value=mock_proc):
        raw = asyncio.run(server.sandbox_run(cmd="dummy", verbosity="brief"))
        data = json.loads(raw)

        assert data.get("status") == "SUCCESS"
        assert data.get("truncated") is True
        assert "stdout_tail" in data
        assert "stdout_bytes" in data
        assert data["stdout_bytes"] == len(long_output)
        tail_lines = data["stdout_tail"].splitlines()
        assert len(tail_lines) == 20
        assert "line_49_" in tail_lines[-1]
        assert data.get("stdout") == ""


def test_sandbox_run_brief_short_stdout_not_truncated() -> None:
    """sandbox_run in brief mode does not truncate short stdout (<=1000 chars and <=20 lines)."""
    mock_proc = mock.Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = "hello world"
    mock_proc.stderr = ""

    with mock.patch("server.subprocess.run", return_value=mock_proc):
        raw = asyncio.run(server.sandbox_run(cmd="dummy", verbosity="brief"))
        data = json.loads(raw)

        assert data.get("status") == "SUCCESS"
        assert data.get("truncated") is False
        assert data.get("stdout") == "hello world"
        assert "stdout_tail" not in data


# ==============================================================================
# f) sandbox_run docstring env={...} recommendation
# ==============================================================================


def test_sandbox_run_docstring_env_recommendation() -> None:
    """sandbox_run docstring documents preference for env={...} over shell env prefix."""
    doc = server.sandbox_run.__doc__ or ""
    assert "- env:" in doc
    assert "Preferir env={...} sobre prefijar comandos con shell 'env'" in doc


# ==============================================================================
# g) sandbox_run uv auto-mount
# ==============================================================================


def test_sandbox_run_uv_auto_mount() -> None:
    """sandbox_run mounts ~/.local/bin/uv and ~/.cache/uv when working_dir has a uv project."""
    proj_dir = str(server.PROJECT_DIR)
    mock_proc = mock.Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = "/usr/bin/uv"
    mock_proc.stderr = ""

    with mock.patch("server.subprocess.run", return_value=mock_proc) as m_run:
        raw = asyncio.run(
            server.sandbox_run(
                cmd="command -v uv",
                working_dir=proj_dir,
                verbosity="detail",
            )
        )
        data = json.loads(raw)
        assert data.get("status") == "SUCCESS"
        bwrap_args = m_run.call_args[0][0]
        uv_host = Path.home() / ".local" / "bin" / "uv"
        if uv_host.exists():
            assert str(uv_host.resolve()) in bwrap_args
            assert str(uv_host.resolve()) in data.get("ro_mounts", [])
        uv_cache = Path.home() / ".cache" / "uv"
        if uv_cache.exists():
            assert str(uv_cache.resolve()) in bwrap_args
            assert "UV_CACHE_DIR" in bwrap_args
