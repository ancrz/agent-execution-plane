"""Backlog post ONT-42: rama `recovered:true` de `_merged_witnessed` (caida entre el ff-merge y el evento `evolve.merged`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import threads_evolve as te
from engine import threads_events as ev
from engine import threads_gitport as gp
from tests._evolve_support import Rig, make_rig, sh


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


class _CrashAfterMerge(gp.GitCli):
    """ff-merge real y despues cae el proceso: ni el save de MERGED ni el evento `evolve.merged` llegan a ocurrir."""

    def merge_ff(self, branch: str) -> tuple[bool, str]:
        super().merge_ff(branch)
        raise RuntimeError("simulated crash after ff-merge")


def _run_until_crash(r: Rig) -> None:
    port = _CrashAfterMerge(r.work, r.canon, r.fence)
    for _ in range(20):  # el gate es por lotes: re-entra hasta que llega al merge y cae
        try:
            out = te.run_evolve(
                r.store(), port, lambda: dict(r.live), cycle=r.cycle, gap="D-88", apply=True,
                octal=7, label="FULL", cycle_dir=r.state, kit=r.fake.kit(),
            )
        except RuntimeError as exc:
            assert "simulated crash" in str(exc)
            r.fence.unlink(missing_ok=True)  # el proceso caido no libero el fence
            return
        assert out.get("awaiting") == "gate", out
    pytest.fail("evolve never reached the ff-merge")


def _merged_events(r: Rig) -> list[dict]:
    return [e for e in ev.read_events(base_dir=r.state) if e["kind"] == "evolve.merged"]


def test_crash_between_ff_merge_and_event_recovers_with_flag(rig: Rig) -> None:
    _run_until_crash(rig)
    assert _merged_events(rig) == []
    assert rig.port().is_ancestor(te.branch_name(rig.cycle), "dev")  # git ya tiene el merge
    out = rig.run()  # reentrada: git manda y el ledger conserva el testigo green del gate
    assert out["status"] == "OK" and out["state"] == te.PUSHED, out
    merged = _merged_events(rig)
    assert len(merged) == 1 and merged[0]["recovered"] is True
    assert merged[0]["sha_full"] == sh(rig.canon, "rev-parse", "dev")


def test_crash_after_merge_without_green_gate_witness_is_state_unverified(rig: Rig) -> None:
    _run_until_crash(rig)
    (rig.state / "ledger.db").unlink()  # ledger perdido: sin testigo green no hay recuperacion
    out = rig.run()
    assert out["reason"] == "state_unverified", out
    assert _merged_events(rig) == []
