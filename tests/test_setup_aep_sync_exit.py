"""aep-sync must exit 0 on a clean machine (no agent CLIs)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import server

ROOT = Path(__file__).resolve().parent.parent


def test_aep_sync_exits_zero_without_agent_clis(tmp_path) -> None:
    """validate()'s RETURN trap must not leak (set -u -> 'err_compile: unbound variable')."""
    home = tmp_path / "home"
    venv_bin = home / ".local" / "share" / "agent-os" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    wrapper = venv_bin / "python"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    wrapper.chmod(0o755)
    # Minimal PATH with only the tools the script needs and no agent CLI (claude/agy/codex/gemini).
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("bash", "env", "dirname", "chmod", "mktemp", "rm", "cat", "grep", "sh", "head", "tail", "sed"):
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    env = {"HOME": str(home), "PATH": str(bindir), "TMPDIR": str(tmp_path)}
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts" / "aep-sync.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if "Validación superada" not in proc.stdout:
        pytest.skip(f"validation not reachable here: {proc.stdout[-300:]} {proc.stderr[-300:]}")
    assert len(server.mcp._tool_manager._tools) == 17  # the count aep-sync's smoke import asserts
    assert "unbound variable" not in proc.stderr
    assert proc.returncode == 0, proc.stderr
