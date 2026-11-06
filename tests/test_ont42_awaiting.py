"""ONT-42b B6 (AE-4): `awaiting` derivado de la causa, barrera "n/a" para root no confiable, `env_left`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import threads_ops as ops
from engine import threads_verify as tv
from tests.test_ont41_ops import GAP, GREEN, _fix, isolated_home, trees  # noqa: F401  (fixtures)


@pytest.mark.parametrize(
    ("reasons", "expected"),
    [
        ([tv.RELOAD_PENDING], "reload"),
        ([tv.SERVING_LKG], "reload"),
        ([tv.RELOAD_BLOCKED], "reload"),
        ([tv.BASE_UNAVAILABLE], "base"),
        ([tv.SANDBOX_UNAVAILABLE], "env"),
        ([tv.WRONG_TREE], "env"),
        ([tv.BASE_UNAVAILABLE, tv.SANDBOX_UNAVAILABLE], "base"),
        ([tv.SANDBOX_UNAVAILABLE, tv.RELOAD_PENDING], "reload"),
    ],
)
def test_awaiting_is_derived_from_the_cause(reasons: list[str], expected: str) -> None:
    assert ops.awaiting_for(reasons) == expected


def test_sandbox_unavailable_awaits_env_with_env_left(trees: tuple[Path, Path]) -> None:  # noqa: F811
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    cid = _fix(store, base, gap=GAP)["cycle"]
    out = _fix(store, new, cycle=cid, run_tests=lambda t: {"available": False})
    assert out["reasons"] == [tv.SANDBOX_UNAVAILABLE] and out["awaiting"] == "env"
    assert out["consumed"] is False and out["iterations_left"] == tv.MAX_ITERATIONS
    assert out["env_left"] == tv.MAX_ENV_RETRIES - 1


def test_wrong_tree_awaits_env_and_second_one_exhausts(trees: tuple[Path, Path]) -> None:  # noqa: F811
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    cid = _fix(store, base, gap=GAP)["cycle"]
    wrong = {"wrong_tree": True}
    first = _fix(store, new, cycle=cid, run_tests=lambda t: wrong)
    assert first["reasons"] == [tv.WRONG_TREE] and first["awaiting"] == "env"
    second = _fix(store, new, cycle=cid, run_tests=lambda t: wrong)
    assert second["state"] == tv.EXHAUSTED and second["reasons"] == [tv.WRONG_TREE]
    assert _fix(store, new, cycle=cid)["status"] == "CLOSED"


def test_untrusted_root_reports_barrier_na_and_ignores_the_live_barrier(trees: tuple[Path, Path]) -> None:  # noqa: F811
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    cid = _fix(store, base, gap=GAP)["cycle"]
    pending = {"state": "RELOAD_PENDING", "retry_after_s": 2.0}
    env = _fix(store, new, cycle=cid, trusted=False, barrier=pending, run_tests=lambda t: {"available": False})
    assert env["barrier"] == ops.BARRIER_NA and env["awaiting"] == "env"
    assert tv.RELOAD_PENDING not in env["reasons"]  # la barrera viva no gobierna un arbol ajeno
    done = _fix(store, new, cycle=cid, trusted=False, barrier=pending)
    assert done["barrier"] == ops.BARRIER_NA and done["verdict"] == tv.ACCEPT


def test_outputs_stay_within_budgets(trees: tuple[Path, Path]) -> None:  # noqa: F811
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    cid = _fix(store, base, gap=GAP)["cycle"]
    pending = {"state": "RELOAD_PENDING", "retry_after_s": 2.0, "reason": "x" * 300}
    for terse, budget in ((True, ops.TERSE_BUDGET), (False, ops.SUMMARY_BUDGET)):
        out = _fix(store, new, cycle=cid, terse=terse, barrier=pending, run_tests=lambda t: GREEN)
        assert ops.estimated_tokens(out) <= budget - ops.ENVELOPE_RESERVE + 10, (terse, json.dumps(out))
