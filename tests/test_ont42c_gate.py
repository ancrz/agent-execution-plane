"""ONT-42c C4: gate final por lotes re-entrantes sobre el arbol commiteado. Suites sinteticas, git real solo en temporales."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine import threads_evolve as te
from engine import threads_gate as tg
from tests._evolve_support import Rig, make_rig, sh

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def test_red_gate_blocks_merge_and_push(rig: Rig) -> None:
    rig.fake.results["tests/test_b.py"] = {"ran": 2, "passed": 1, "failed": 1, "errors": 0, "exit_code": 1}
    out = rig.drive()
    assert out["status"] == "REJECT" and out["reason"] == "gate_failed", out
    assert out["state"] == te.COMMITTED
    assert sh(rig.canon, "rev-parse", "dev") == sh(rig.bare, "rev-parse", "dev")  # dev intacto
    assert sh(rig.canon, "branch", "--list", te.branch_name(rig.cycle))  # la rama commiteada permanece
    again = rig.run()  # el rojo es persistente: no re-ejecuta ni mergea
    assert again["reason"] == "gate_failed"
    assert not (rig.canon / "new.txt").exists()


def test_green_gate_merges_and_runs_batches_reentrantly(tmp_path: Path) -> None:
    r = make_rig(tmp_path)
    r.fake.files = {f"tests/test_{i}.py": 100 for i in range(3)}  # 3 lotes (100 + 100 > BATCH_TESTS)
    first = r.run()
    assert first["awaiting"] == "gate" and first["gate"] == "1/3" and first["state"] == te.COMMITTED
    second = r.run()
    assert second["gate"] == "2/3"
    final = r.run()
    assert final["state"] == te.PUSHED, final
    assert len(r.fake.calls) == 3
    assert (r.canon / "new.txt").exists()


def test_gate_runs_on_exported_committed_tree_not_the_editable_worktree(rig: Rig) -> None:
    rig.drive()
    assert rig.fake.trees and all(t != rig.work and not str(t).startswith(str(rig.work)) for t in rig.fake.trees)
    assert all(not t.exists() for t in rig.fake.trees)  # el checkout temporal se limpia


def test_gate_blocks_when_committed_tree_differs_from_judged(rig: Rig) -> None:
    rig.run(octal=6, label="DIMINISHED")  # commit local
    rec = rig.store().load(rig.cycle)
    assert rec is not None
    rec["judged_tree"] = "0" * 40
    rig.store().save(rig.cycle, rec)
    out = rig.run()
    assert out["status"] == "BLOCKED_GIT" and out["reason"] in ("tree_changed_after_accept", "gate_tree_mismatch")
    assert not (rig.canon / "new.txt").exists()


def test_ran_lt_selected_is_red(rig: Rig) -> None:
    rig.fake.results["tests/test_a.py"] = {"ran": 1, "failed": 0, "errors": 0, "exit_code": 0}
    out = rig.drive()
    assert out["status"] == "REJECT" and out["gate_reason"] == "ran_lt_selected"


def test_unsandboxed_and_wrong_tree_are_red(rig: Rig, tmp_path: Path) -> None:
    rig.fake.results["tests/test_a.py"] = {"ran": 3, "failed": 0, "errors": 0, "exit_code": 0, "unsandboxed": True}
    assert rig.drive()["gate_reason"] == "unsandboxed"
    r2 = make_rig(tmp_path / "two")
    r2.fake.results["tests/test_a.py"] = {"wrong_tree": True}
    assert r2.drive()["gate_reason"] == "wrong_tree"


def test_sandbox_unavailable_is_not_green_and_is_retryable(rig: Rig) -> None:
    rig.fake.collect_result = {"available": False}
    out = rig.run()
    assert out["status"] == "REJECT" and out["reason"] == "sandbox_unavailable"
    assert sh(rig.canon, "rev-parse", "dev") == sh(rig.bare, "rev-parse", "dev")
    rig.fake.collect_result = None  # el entorno vuelve: se reintenta y pasa
    assert rig.drive()["state"] == te.PUSHED


def test_no_kit_means_no_merge(rig: Rig) -> None:
    out = te.run_evolve(
        rig.store(),
        rig.port(),
        lambda: dict(rig.live),
        cycle=rig.cycle,
        gap="D-88",
        apply=True,
        octal=7,
        label="FULL",
        cycle_dir=rig.state,
        kit=None,
    )
    assert out["status"] == "BLOCKED_GIT" and out["reason"] == "no_gate_kit"
    assert not (rig.canon / "new.txt").exists()


def test_timeout_of_multi_file_batch_splits_and_single_file_timeout_is_red(rig: Rig) -> None:
    rig.fake.timeout_over = 1
    out = rig.drive()
    assert out["state"] == te.PUSHED, out  # el lote de 3 archivos se parte hasta archivos sueltos
    assert any(len(c) == 1 for c in rig.fake.calls)
    r = make_rig(rig.root / "slow")
    r.fake.results["tests/test_a.py"] = {"timeout": True, "failed": 0, "errors": 0}
    r.fake.files = {"tests/test_a.py": 1}
    assert r.drive()["gate_reason"] == "batch_timeout"


def test_plan_batches_is_deterministic_and_bounded() -> None:
    files = {f"tests/t{i}.py": 50 for i in range(5)}
    batches = tg.plan_batches(files, batch_tests=100)
    assert [len(b["files"]) for b in batches] == [2, 2, 1]
    assert tg.plan_batches(files, batch_tests=100) == batches
    assert tg.plan_batches({"tests/big.py": 500}, batch_tests=100)[0]["selected"] == 500


def test_gate_never_runs_unsandboxed_in_server_kit() -> None:
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    body = src[src.index("def _autoevol_gate_kit") :]
    body = body[: body.index("\ndef _autoevol_swap_fence")]
    assert "_autoevol_test_runner(tree, False," in body and "plain" not in body
    assert re.search(r"_AUTOEVOL_GATE_TIMEOUT_S\s*=\s*100\b", src)
