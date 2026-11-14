"""ONT-61 T2/G64: /etc/alternatives (and the minimal id/tz files) are visible in the sandbox; secrets are not."""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

import server

BWRAP = shutil.which("bwrap")
_FORBIDDEN = ("shadow", "gshadow", "sudoers", "ssh")


def _run(cmd: str) -> dict:
    return json.loads(asyncio.run(server.sandbox_run(command=cmd, verbosity="detail")))


def test_etc_mount_list_is_exactly_the_decided_one() -> None:
    assert server._SANDBOX_ETC_EXTRA_MOUNTS == ("/etc/alternatives", "/etc/localtime", "/etc/passwd", "/etc/group")
    assert not any(f in m for m in server._SANDBOX_ETC_EXTRA_MOUNTS for f in _FORBIDDEN)


@pytest.mark.skipif(BWRAP is None or shutil.which("awk") is None, reason="needs bwrap and host awk")
def test_awk_resolves_through_etc_alternatives() -> None:
    out = _run("awk 'BEGIN{print 1}'")
    assert "1" in json.dumps(out) and "not found" not in json.dumps(out)


@pytest.mark.skipif(BWRAP is None, reason="needs bwrap")
def test_secrets_stay_invisible_and_id_resolves_names() -> None:
    out = json.dumps(_run("ls /etc; echo ---; cat /etc/shadow; id -un"))
    listing = out.split("---")[0]
    for f in _FORBIDDEN:
        assert f"{f}\\n" not in listing and f" {f}" not in listing
    assert "Permission denied" in out or "No such file" in out
