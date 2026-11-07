"""ONT-41 TA3: compare/decide con cada motivo REJECT, barrera, selección de tests, base y verify_change."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from engine import threads
from engine import threads_verify as tv

REPO = Path(__file__).resolve().parent.parent


def _sum(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"root": "r" * 64, "gaps": [], "codep": [], "hashes": {}, "public": [], "direct": []}
    base.update(kw)
    return base


BASE = _sum(gaps=["g1", "g2"], hashes={"fn:a.f": "h1", "fn:a._p": "p1"}, public=["fn:a.f"], direct=["fn:a.f"])


def _good_new(**kw: Any) -> dict[str, Any]:
    return _sum(
        **{
            **{"gaps": ["g2"], "hashes": {"fn:a.f": "h1", "fn:a._p": "p1"}, "public": ["fn:a.f"], "direct": ["fn:a.f"]},
            **kw,
        }
    )


GREEN = {"ran": 3, "passed": 3, "failed": 0, "errors": 0}


def test_compare_reports_fixed_introduced_and_uncovered() -> None:
    new = _sum(
        gaps=["g2", "g3"],
        codep=["m:x"],
        hashes={"fn:a.f": "CHANGED", "fn:a._p": "CHANGED", "fn:a.new": "n"},
        public=["fn:a.f", "fn:a.new"],
        direct=["fn:a.f"],
    )
    cmp = tv.compare(BASE, new)
    assert cmp["fixed"] == ["g1"]
    assert cmp["introduced"] == ["g3"]
    assert cmp["codep"] == ["m:x"]
    assert cmp["uncovered_public"] == ["fn:a.new"]
    assert cmp["uncovered_private"] == ["fn:a._p"]
    assert (cmp["gaps_base"], cmp["gaps_new"]) == (2, 2)


def test_decide_accept_when_monotone_and_green() -> None:
    out = tv.decide(tv.compare(BASE, _good_new()), tests=GREEN)
    assert out["verdict"] == tv.ACCEPT
    assert out["reasons"] == []
    assert out["fixed"] == 1


def test_accept_without_tests_warns() -> None:
    out = tv.decide(tv.compare(BASE, _good_new()))
    assert out["verdict"] == tv.ACCEPT
    assert "no tests executed" in out["warnings"]


def test_reject_new_gaps() -> None:
    out = tv.decide(tv.compare(BASE, _good_new(gaps=["g2", "g9"])))
    assert tv.NEW_GAPS in out["reasons"]
    assert out["verdict"] == tv.REJECT
    assert out["detail"]["introduced"] == {"items": ["g9"], "total": 1}


def test_reject_no_progress_generic_and_targeted() -> None:
    same = _good_new(gaps=["g1", "g2"])
    assert tv.decide(tv.compare(BASE, same))["reasons"] == [tv.NO_PROGRESS]
    other_fixed = tv.compare(BASE, _good_new())  # arregla g1
    assert tv.decide(other_fixed, target_gap="g2")["reasons"] == [tv.NO_PROGRESS]
    assert tv.decide(other_fixed, target_gap="g1")["verdict"] == tv.ACCEPT


def test_reject_codep() -> None:
    out = tv.decide(tv.compare(BASE, _good_new(codep=["c1"])))
    assert out["reasons"] == [tv.CODEP]


def test_reject_no_direct_coverage_public_but_private_only_warns() -> None:
    pub = tv.compare(BASE, _good_new(hashes={"fn:a.f": "X", "fn:a._p": "p1"}, direct=[]))
    assert tv.decide(pub)["reasons"] == [tv.NO_DIRECT_COVERAGE]
    priv = tv.compare(BASE, _good_new(hashes={"fn:a.f": "h1", "fn:a._p": "X"}))
    out = tv.decide(priv)
    assert out["verdict"] == tv.ACCEPT
    assert any("private changed" in w for w in out["warnings"])


def test_reject_tests_fail_on_failures_errors_and_timeout() -> None:
    cmp = tv.compare(BASE, _good_new())
    for bad in ({"failed": 1}, {"errors": 2}, {"timeout": True}):
        assert tv.decide(cmp, tests={**GREEN, **bad})["reasons"] == [tv.TESTS_FAIL]


def test_reject_budget() -> None:
    cmp = tv.compare(BASE, _good_new())
    out = tv.decide(cmp, budgets=[{"id": "b1", "limit": 400, "observed": 401}, {"id": "b2", "limit": 5, "observed": 5}])
    assert out["reasons"] == [tv.BUDGET]
    assert out["detail"]["budget_over"] == ["b1"]


def test_reject_base_unavailable() -> None:
    assert tv.decide(None)["reasons"] == [tv.BASE_UNAVAILABLE]
    assert tv.decide(tv.compare(BASE, _good_new()), base_available=False)["reasons"] == [tv.BASE_UNAVAILABLE]


def test_reject_sandbox_unavailable_variants() -> None:
    cmp = tv.compare(BASE, _good_new())
    assert tv.decide(cmp, sandbox_available=False)["reasons"] == [tv.SANDBOX_UNAVAILABLE]
    assert tv.decide(cmp, tests={"available": False})["reasons"] == [tv.SANDBOX_UNAVAILABLE]
    # árbol no confiable: una ejecución sin jaula no vale; en el árbol propio vale y se marca
    assert tv.decide(cmp, tests={**GREEN, "unsandboxed": True}, trusted=False)["reasons"] == [tv.SANDBOX_UNAVAILABLE]
    own = tv.decide(cmp, tests={**GREEN, "unsandboxed": True}, trusted=True)
    assert own["verdict"] == tv.ACCEPT
    assert "unsandboxed" in own["warnings"]


def test_barrier_reasons_serving_lkg_blocked_pending() -> None:
    assert tv.barrier_reasons(None) == []
    assert tv.barrier_reasons(tv.BarrierState()) == []
    assert tv.barrier_reasons(tv.BarrierState(serving_lkg=True)) == [tv.SERVING_LKG]
    assert tv.barrier_reasons(tv.BarrierState(reload_error="ImportError")) == [tv.RELOAD_BLOCKED]
    transient = tv.BarrierState(reload_error="EAGAIN", reload_error_deterministic=False)
    assert tv.barrier_reasons(transient) == [tv.RELOAD_PENDING]
    assert tv.barrier_reasons(tv.BarrierState(generation_advanced=False)) == [tv.RELOAD_PENDING]
    assert tv.barrier_reasons(tv.BarrierState(fingerprints_match=False)) == [tv.RELOAD_PENDING]


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (tv.BarrierState(serving_lkg=True), tv.SERVING_LKG),
        (tv.BarrierState(reload_error="boom"), tv.RELOAD_BLOCKED),
        (tv.BarrierState(generation_advanced=False), tv.RELOAD_PENDING),
    ],
)
def test_decide_rejects_on_barrier(state: tv.BarrierState, reason: str) -> None:
    out = tv.decide(tv.compare(BASE, _good_new()), barrier=state, tests=GREEN)
    assert out["verdict"] == tv.REJECT
    assert reason in out["reasons"]


def test_reasons_are_reported_in_fixed_order() -> None:
    cmp = tv.compare(BASE, _good_new(gaps=["g1", "g2", "g9"], codep=["c"]))
    out = tv.decide(
        cmp,
        tests={"failed": 1},
        budgets=[{"id": "b", "limit": 1, "observed": 2}],
        barrier=tv.BarrierState(serving_lkg=True),
    )
    assert out["reasons"] == [tv.SERVING_LKG, tv.NEW_GAPS, tv.CODEP, tv.NO_PROGRESS, tv.TESTS_FAIL, tv.BUDGET]
    assert set(out["reasons"]) <= set(tv.REJECT_REASONS)


def test_decide_pending_for_async_tests_but_reject_wins() -> None:
    cmp = tv.compare(BASE, _good_new())
    assert tv.decide(cmp, tests={"status": "PENDING", "job": "7"})["verdict"] == tv.PENDING
    bad = tv.compare(BASE, _good_new(gaps=["g1", "g2"]))
    assert tv.decide(bad, tests={"status": "PENDING"})["verdict"] == tv.REJECT


def test_await_barrier_polls_with_injected_clock_and_sleep() -> None:
    states = iter([tv.BarrierState(generation_advanced=False)] * 2 + [tv.BarrierState()])
    now = [0.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    state, timed_out = tv.await_barrier(
        lambda: next(states), timeout_s=10, poll_s=1.0, clock=lambda: now[0], sleep=sleep
    )
    assert state == tv.BarrierState()
    assert timed_out is False
    assert slept == [1.0, 1.0]


def test_await_barrier_times_out() -> None:
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    state, timed_out = tv.await_barrier(
        lambda: tv.BarrierState(fingerprints_match=False), timeout_s=3, poll_s=1.0, clock=lambda: now[0], sleep=sleep
    )
    assert timed_out is True
    assert not state.fingerprints_match


def test_plan_tests_sync_async_thresholds() -> None:
    names = [f"t{i}" for i in range(tv.TESTS_PER_ITERATION)]
    assert tv.plan_tests(names)["mode"] == "sync"
    assert tv.plan_tests([*names, "extra"])["mode"] == "async"
    assert tv.plan_tests(names[:5], estimate_s=61)["mode"] == "async"
    assert tv.plan_tests(names[:5], estimate_s=60)["mode"] == "sync"
    assert tv.plan_tests(["b", "a", "a"])["tests"] == ["a", "b"]


def test_verify_change_runs_selected_tests_when_static_is_clean() -> None:
    seen: list[list[str]] = []

    def run(tests: list[str]) -> dict[str, Any]:
        seen.append(tests)
        return dict(GREEN)

    out = tv.verify_change(BASE, _good_new(), impacted_tests=["t2", "t1"], run_tests=run)
    assert out["verdict"] == tv.ACCEPT
    assert seen == [["t1", "t2"]]
    assert out["tests"]["mode"] == "sync"


def test_verify_change_skips_tests_when_static_rejects() -> None:
    def run(tests: list[str]) -> dict[str, Any]:
        raise AssertionError("must not run")

    out = tv.verify_change(BASE, _good_new(gaps=["g1", "g2", "g9"]), impacted_tests=["t1"], run_tests=run)
    assert out["verdict"] == tv.REJECT
    assert out["tests"] == {"selected": 0}


def test_verify_change_skips_tests_when_barrier_blocks() -> None:
    out = tv.verify_change(
        BASE,
        _good_new(),
        impacted_tests=["t1"],
        run_tests=lambda t: pytest.fail("must not run"),
        barrier=tv.BarrierState(reload_error="SyntaxError"),
    )
    assert out["reasons"] == [tv.RELOAD_BLOCKED]


def test_verify_change_no_impacted_tests_accepts_with_warning() -> None:
    out = tv.verify_change(BASE, _good_new(), impacted_tests=[])
    assert out["verdict"] == tv.ACCEPT
    assert "no tests executed" in out["warnings"]


def test_verify_change_async_returns_pending_with_job() -> None:
    names = [f"t{i}" for i in range(21)]
    out = tv.verify_change(
        BASE, _good_new(), impacted_tests=names, dispatch_job=lambda t: {"job": "42", "queued": len(t)}
    )
    assert out["verdict"] == tv.PENDING
    assert out["job"] == "42"
    assert out["tests"]["mode"] == "async"


def test_verify_change_missing_runner_is_sandbox_unavailable() -> None:
    sync = tv.verify_change(BASE, _good_new(), impacted_tests=["t1"])
    assert sync["reasons"] == [tv.SANDBOX_UNAVAILABLE]
    names = [f"t{i}" for i in range(21)]
    assert tv.verify_change(BASE, _good_new(), impacted_tests=names, run_tests=lambda t: GREEN)["reasons"] == [
        tv.SANDBOX_UNAVAILABLE
    ]


def test_verify_change_base_none_is_base_unavailable() -> None:
    out = tv.verify_change(None, _good_new(), impacted_tests=["t1"])
    assert out["reasons"] == [tv.BASE_UNAVAILABLE]


def test_verify_change_failing_tests_reject() -> None:
    out = tv.verify_change(BASE, _good_new(), impacted_tests=["t1"], run_tests=lambda t: {**GREEN, "failed": 1})
    assert out["reasons"] == [tv.TESTS_FAIL]


# --- base: git archive / snapshot / BASE_UNAVAILABLE -----------------------------------------------------


def _git_repo(path: Path) -> None:
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["add", "."],
        ["commit", "-q", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def test_base_tree_from_git_archive_is_head_not_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "server.py").write_text("def f():\n    return 1\n")
    _git_repo(repo)
    (repo / "server.py").write_text("def f():\n    return 2\n")  # cambio sin commit: la base no lo ve
    with tv.base_tree(repo) as tree:
        assert tree is not None
        assert "return 1" in (tree / "server.py").read_text()
        kept = tree
    assert not kept.exists()  # tmpdir limpiado


def test_base_tree_without_git_is_none(tmp_path: Path) -> None:
    (tmp_path / "server.py").write_text("x = 1\n")
    with tv.base_tree(tmp_path) as tree:
        assert tree is None
    with tv.base_tree(tmp_path, git_bin="definitely-not-a-binary") as tree:
        assert tree is None


def test_base_tree_snapshot_and_missing_snapshot(tmp_path: Path) -> None:
    with tv.base_tree(REPO, snapshot=tmp_path) as tree:
        assert tree == tmp_path
    with tv.base_tree(REPO, snapshot=tmp_path / "nope") as tree:
        assert tree is None


def test_summarize_real_tree_and_compare_with_itself() -> None:
    analysis = threads.analyze(REPO)
    s = tv.summarize(analysis)
    assert s["root"] == analysis.root_hash
    assert s["gaps"] == sorted(g.id for g in analysis.gaps)
    assert "fn:engine.threads_verify.decide" in s["public"]
    cmp = tv.compare(s, s)
    assert cmp["fixed"] == [] and cmp["introduced"] == [] and cmp["changed"] == []
    assert tv.decide(cmp)["reasons"] == [tv.NO_PROGRESS]  # sin cambios no hay progreso


def test_summarize_detects_a_real_fix_in_a_tmp_tree(tmp_path: Path) -> None:
    (tmp_path / "server.py").write_text("def pub():\n    return 1\n")
    before = tv.summarize(threads.analyze(tmp_path, use_cache=False))
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("from server import pub\n\n\ndef test_pub():\n    assert pub() == 1\n")
    after = tv.summarize(threads.analyze(tmp_path, use_cache=False))
    cmp = tv.compare(before, after)
    assert "omission:fn:server.pub:in:covers" in cmp["fixed"]
    assert tv.decide(cmp, target_gap="omission:fn:server.pub:in:covers")["verdict"] == tv.ACCEPT


def _tar(path: Path, members: list[tuple[str, bytes | str, str]]) -> None:
    import io
    import tarfile

    with tarfile.open(path, "w") as tf:
        for name, payload, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = str(payload)
                tf.addfile(info)
            else:
                data = payload if isinstance(payload, bytes) else payload.encode()
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))


def test_safe_extract_accepts_regular_members_and_skips_links(tmp_path: Path) -> None:
    arc, dest = tmp_path / "a.tar", tmp_path / "d"
    dest.mkdir()
    _tar(arc, [("ok/x.py", b"x=1\n", "file"), ("lnk", "/etc/passwd", "symlink")])
    assert tv.safe_extract(arc, dest) == 1
    assert (dest / "ok" / "x.py").read_text() == "x=1\n"
    assert not (dest / "lnk").exists() and not (dest / "lnk").is_symlink()


@pytest.mark.parametrize("name", ["../evil.py", "a/../../evil.py", "/abs/evil.py"])
def test_safe_extract_rejects_traversal_and_absolute(tmp_path: Path, name: str) -> None:
    arc, dest = tmp_path / "a.tar", tmp_path / "d"
    dest.mkdir()
    _tar(arc, [(name, b"boom", "file")])
    with pytest.raises(ValueError):
        tv.safe_extract(arc, dest)
    assert not (tmp_path / "evil.py").exists()


def test_extract_head_returns_none_on_malicious_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **_k: Any) -> subprocess.CompletedProcess[bytes]:
        _tar(Path(argv[argv.index("-o") + 1]), [("../evil.py", b"boom", "file")])
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(tv.subprocess, "run", fake_run)
    assert tv._extract_head(tmp_path, tmp_path, "git") is None
    assert not (tmp_path.parent / "evil.py").exists()
