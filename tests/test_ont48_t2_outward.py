"""ONT-48 T2 (G25): outward-facing commands need confirm=True + tier 7rwx; labels are auto-generated."""

from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

import server


def _dispatch(**kw) -> dict:
    return json.loads(asyncio.run(server.async_job_dispatch(action="dispatch", **kw)))


@pytest.fixture
def pueue(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **_k):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="42\n", stderr="")

    monkeypatch.setattr(server, "_ensure_pueue_daemon", lambda: "/usr/bin/pueue")
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server, "get_effective_chmod_tier", lambda *a, **k: {"tier": "7rwx"})
    events: list[dict] = []

    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(server.catalog, "_get_rw_conn", _Conn)
    monkeypatch.setattr(server, "record_audit_event", lambda conn, **kw: events.append(kw))
    return calls, events


@pytest.mark.parametrize(
    "cmd",
    [
        "git push origin main",
        "git -C /x push",
        "git tag -a v1 -m x && git push --tags",
        "docker push img:1",
        "gh pr merge 5",
        "gh release create v1",
        "npm publish",
        "twine upload dist/*",
        "uv publish",
        "cargo publish",
        "pip upload x",
    ],
)
def test_outward_patterns_match(cmd) -> None:
    assert server._match_outward_command(cmd) is not None


@pytest.mark.parametrize("cmd", ["git status", "git log --oneline", "pytest -q", "git tag -a v1 -m x"])
def test_non_outward_do_not_match(cmd) -> None:
    assert server._match_outward_command(cmd) is None


def test_confirm_required_does_not_execute(pueue) -> None:
    calls, events = pueue
    res = _dispatch(command="git push origin main")
    assert res["status"] == "CONFIRM_REQUIRED"
    assert res["matched"] == "git push"
    assert "hint" in res
    assert calls == [] and events == []


def test_permission_denied_below_7rwx(pueue, monkeypatch) -> None:
    calls, _ = pueue
    monkeypatch.setattr(server, "get_effective_chmod_tier", lambda *a, **k: {"tier": "6rw-"})
    res = _dispatch(command="npm publish", confirm=True)
    assert res["status"] == "PERMISSION_DENIED"
    assert calls == []


def test_confirmed_dispatch_records_event_and_autolabels(pueue) -> None:
    calls, events = pueue
    res = _dispatch(command="git push origin dev", confirm=True)
    assert res["status"] == "queued"
    assert res["label_generated"] is True
    assert res["label"].startswith("aep-git-")
    assert any("--label" in c for c in calls)
    assert [e["action"] for e in events] == ["job.outward_confirmed"]


def test_explicit_label_kept(pueue) -> None:
    res = _dispatch(command="pytest -q", label="mine")
    assert res["label"] == "mine"
    assert "label_generated" not in res
