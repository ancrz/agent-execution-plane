"""ONT-42c C6: rollback por `git revert` (commit NUEVO, dentro del fence, sin push). Solo repos temporales con remoto bare."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from engine import threads_evolve as te
from tests._evolve_support import Rig, make_rig, sh


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def _run_with(rig: Rig, post_verify: Any) -> dict[str, Any]:
    kit = rig.fake.kit()
    kit.post_verify = post_verify
    return te.run_evolve(
        rig.store(),
        rig.port(),
        lambda: dict(rig.live),
        cycle=rig.cycle,
        gap="D-88",
        apply=True,
        octal=7,
        label="FULL",
        cycle_dir=rig.state,
        kit=kit,
    )


def test_failed_post_merge_verify_reverts_with_new_commit_and_never_pushes(rig: Rig) -> None:
    origin_before = sh(rig.bare, "rev-parse", "dev")
    merged_sha = ""

    def bad(rec: dict[str, Any]) -> dict[str, Any]:
        nonlocal merged_sha
        merged_sha = rec["sha"]
        return {"ok": False, "reason": "serving_lkg"}

    out = _run_with(rig, bad)
    assert out["status"] == "BLOCKED_GIT" and out["reason"] == "dev_dirty_by_revert" and out["state"] == te.REVERTED, (
        out
    )
    # historia intacta: base -> parche -> revert (commit nuevo); el parche sigue siendo ancestro de dev
    assert sh(rig.canon, "rev-list", "--count", "dev") == "3"
    assert sh(rig.canon, "log", "-1", "--format=%s", "dev").startswith('Revert "')
    assert sh(rig.canon, "rev-parse", "dev^") == merged_sha
    assert not (rig.canon / "new.txt").exists()  # el contenido del parche se deshizo
    assert sh(rig.bare, "rev-parse", "dev") == origin_before  # sin push
    assert not rig.fence.exists()  # fence liberado en finally
    assert "evolve.reverted" in rig.events() and "evolve.pushed" not in rig.events()


def test_after_revert_every_reentry_stays_blocked_until_the_user_decides(rig: Rig) -> None:
    _run_with(rig, lambda rec: {"ok": False, "reason": "x"})
    for _ in range(2):
        again = rig.run()
        assert again["status"] == "BLOCKED_GIT" and again["reason"] == "dev_dirty_by_revert"
    assert sh(rig.canon, "rev-list", "--count", "dev") == "3"  # no hubo segundo revert


def test_revert_holds_the_fence_and_respects_a_held_one(rig: Rig) -> None:
    seen: list[bool] = []

    class Spy:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

        def revert(self, sha: str) -> tuple[bool, str]:
            seen.append(rig.fence.exists() is False)
            return self.inner.revert(sha)

    kit = rig.fake.kit()
    kit.post_verify = lambda rec: {"ok": False, "reason": "x"}
    te.run_evolve(
        rig.store(),
        Spy(rig.port()),
        lambda: dict(rig.live),
        cycle=rig.cycle,
        gap="D-88",
        apply=True,
        octal=7,
        label="FULL",
        cycle_dir=rig.state,
        kit=kit,
    )
    assert seen == [True]  # el fence lo toma la implementacion del puerto, no la maquina
    # fence tomado por otro: el revert se niega y no toca dev
    r2 = make_rig(rig.root / "two")
    r2.fence.write_text("", encoding="utf-8")
    port = r2.port()
    head = sh(r2.canon, "rev-parse", "dev")
    assert port.revert(head) == (False, "fence_held")
    assert r2.fence.exists() and sh(r2.canon, "rev-parse", "dev") == head


def test_dev_moved_before_revert_is_blocked_without_touching_history(rig: Rig) -> None:
    def moves_dev(rec: dict[str, Any]) -> dict[str, Any]:
        (rig.canon / "z.txt").write_text("z\n", encoding="utf-8")
        sh(rig.canon, "add", "z.txt")
        sh(rig.canon, "commit", "-q", "-m", "otra cosa")
        return {"ok": False, "reason": "x"}

    out = _run_with(rig, moves_dev)
    assert out["status"] == "BLOCKED_GIT" and out["reason"] == "revert_head_moved"
    assert sh(rig.canon, "log", "-1", "--format=%s", "dev") == "otra cosa"


def test_passing_post_merge_verify_pushes(rig: Rig) -> None:
    out = _run_with(rig, lambda rec: {"ok": True})
    assert out["state"] == te.PUSHED
    assert sh(rig.bare, "rev-parse", "dev") == sh(rig.canon, "rev-parse", "dev")


def test_dev_ahead_blocks_without_rebase(rig: Rig) -> None:
    assert te.run_evolve  # cobertura directa del grafo
    (rig.canon / "b.txt").write_text("advance\n", encoding="utf-8")
    sh(rig.canon, "commit", "-q", "-am", "dev avanza")
    out = rig.drive()
    assert out["status"] == "BLOCKED_GIT" and out["reason"] == "dev_ahead"
    assert sh(rig.canon, "log", "-1", "--format=%s", "dev") == "dev avanza"
