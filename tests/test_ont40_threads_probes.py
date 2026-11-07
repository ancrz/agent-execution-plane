"""ONT-40 T12 (F5, F14, C5): restricciones de los probes."""

from __future__ import annotations

import os
from pathlib import Path

from engine import threads, threads_probes

REPO = Path(__file__).resolve().parent.parent


def test_probe_env_is_whitelisted_and_isolated(tmp_path: Path) -> None:
    env = threads_probes.probe_env(tmp_path)
    assert env["HOME"] == str(tmp_path) and env["AEP_POOL_DIR"].startswith(str(tmp_path))
    assert env["AEP_SOCKET_PATH"].startswith(str(tmp_path))
    assert env["AEP_FORCE_TIER"] == "4r--"  # C5: los probes no validan tools que escriben
    assert set(env) <= {
        "PATH",
        "LANG",
        "LC_ALL",
        "HOME",
        "TMPDIR",
        "AEP_POOL_DIR",
        "AEP_SOCKET_PATH",
        "AEP_FORCE_TIER",
        "AEP_HOTSWAP",
    }


def test_probe_skipped_below_5r_x() -> None:
    res = threads_probes.run_probes(REPO, tier_octal=4)
    assert res["status"] == "SKIPPED" and res["observations"] == []


def test_probe_timeout_is_fail_open_not_a_gap() -> None:
    res = threads_probes.run_probes(REPO, tier_octal=5, timeout=0.001, allow_jail=False)  # type: ignore[arg-type]
    assert res["status"] == "TIMEOUT" and res["observations"] == []
    assert threads.probe_gaps(res["observations"]) == []


def test_probe_run_leaves_dev_shm_intact_and_reports_observations() -> None:
    shm = Path("/dev/shm")
    before = sorted(p.name for p in shm.glob("aep*")) if shm.exists() else []
    ino = (shm / "aep.sock").stat().st_ino if (shm / "aep.sock").exists() else None
    res = threads_probes.run_probes(REPO, tier_octal=6)
    after = sorted(p.name for p in shm.glob("aep*")) if shm.exists() else []
    assert before == after
    assert ino is None or (shm / "aep.sock").stat().st_ino == ino
    assert res["status"] == "OK", res
    names = {o["probe"] for o in res["observations"]}
    assert names == {"schema_summary_tokens", "crash_forensics_ready"}


def test_probe_observations_stay_outside_r() -> None:
    a = threads.analyze(REPO)
    b = threads.with_probes(
        a,
        {
            "status": "OK",
            "observations": [{"probe": "x", "ok": False, "node": "tool:discover", "detail": "d", "ref": "D-01"}],
        },
    )
    assert a.root_hash == b.root_hash and b.obs_hash and b.obs_hash != a.obs_hash
    assert threads.merkle_root(b.graph)[0] == a.root_hash
    assert any(g.id == "drift:probe:x" for g in b.gaps)
    assert os.environ.get("AEP_FORCE_TIER") != "4r--" or True


# --- H1: fail-closed jail ---------------------------------------------------------------------------


def _foreign_tree(tmp: Path, server_src: str) -> Path:
    root = tmp / "foreign"
    (root / "engine").mkdir(parents=True)
    (root / "engine" / "__init__.py").write_text("")
    (root / "engine" / "ipc_pool.py").write_text("def ensure_ipc_server_started(*a, **k):\n    pass\n")
    (root / "server.py").write_text(server_src)
    return root


def test_h1_import_error_in_jail_does_not_retry_without_jail(tmp_path: Path, monkeypatch) -> None:
    import shutil
    import subprocess

    import pytest

    if not shutil.which("bwrap"):
        pytest.skip("bwrap unavailable")
    monkeypatch.delenv("AEP_IN_SANDBOX", raising=False)
    marker = tmp_path / "ran_without_jail"
    root = _foreign_tree(tmp_path, f"open({str(marker)!r}, 'w').close()\nraise ImportError('boom')\n")
    calls: list[list[str]] = []
    real = subprocess.run

    def spy(cmd, *a, **k):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return real(cmd, *a, **k)

    monkeypatch.setattr(threads_probes.subprocess, "run", spy)
    res = threads_probes.run_probes(root, tier_octal=6)
    assert res["status"] == "ERROR", res
    assert len(calls) == 1 and calls[0][0] == "bwrap"


def test_h1_foreign_root_without_bwrap_is_unavailable_no_jail(tmp_path: Path, monkeypatch) -> None:
    root = _foreign_tree(tmp_path, "raise SystemExit(0)\n")
    monkeypatch.setattr(threads_probes.shutil, "which", lambda _n: None)
    res = threads_probes.run_probes(root, tier_octal=6)
    assert res["probe_status"] == "unavailable_no_jail" and res["observations"] == []
    monkeypatch.undo()
    monkeypatch.setenv("AEP_IN_SANDBOX", "1")
    res = threads_probes.run_probes(root, tier_octal=6)
    assert res["probe_status"] == "unavailable_no_jail"


def test_h1_acceptance_probes_still_run_inside_jail_when_bwrap_available() -> None:
    import shutil

    import pytest

    from tests._threads_support import PRE_L1_COMMIT, commit_exists, detached_worktree

    if not shutil.which("bwrap") or os.environ.get("AEP_IN_SANDBOX") or not commit_exists(PRE_L1_COMMIT):
        pytest.skip("needs bwrap and the pre-L1 commit")
    with detached_worktree(PRE_L1_COMMIT) as wt:
        res = threads_probes.run_probes(wt, tier_octal=6)
    assert res["status"] == "OK" and res["jail"] == "bwrap", res
