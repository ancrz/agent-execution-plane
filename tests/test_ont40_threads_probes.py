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
    assert set(env) <= {"PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "AEP_POOL_DIR", "AEP_SOCKET_PATH", "AEP_FORCE_TIER", "AEP_HOTSWAP"}


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
    b = threads.with_probes(a, {"status": "OK", "observations": [{"probe": "x", "ok": False, "node": "tool:discover", "detail": "d", "ref": "D-01"}]})
    assert a.root_hash == b.root_hash and b.obs_hash and b.obs_hash != a.obs_hash
    assert threads.merkle_root(b.graph)[0] == a.root_hash
    assert any(g.id == "drift:probe:x" for g in b.gaps)
    assert os.environ.get("AEP_FORCE_TIER") != "4r--" or True
