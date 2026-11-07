"""ONT-42c: cobertura directa (referencias calificadas) de GitCli, GitPort, EvolveStore y de la accion `evolve`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import server
from engine import threads_evolve as te
from engine import threads_gitport as gp
from engine.privilege import _PrivilegeCache
from tests._evolve_support import Rig, make_rig


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    r = make_rig(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AEP_AUTOEVOL_DIR", str(r.state))
    monkeypatch.setenv("AEP_SWAP_FENCE_PATH", str(r.fence))
    monkeypatch.setattr(server, "REPO_ROOT", r.canon)
    monkeypatch.setenv("AEP_FORCE_TIER", "4r--")
    _PrivilegeCache.reset()
    yield r
    _PrivilegeCache.reset()


def test_evolve_action_direct_invocation(rig: Rig) -> None:
    res = json.loads(asyncio.run(server.autoevol(action="evolve", gap="D-88", root=str(rig.work))))
    assert res["state"] == "PLAN"


def test_direct_references_to_port_and_store(rig: Rig) -> None:
    port, store = rig.port(), rig.store()
    assert gp.GitCli.current_branch(port) == "dev"
    head = gp.GitCli.rev_parse(port, "dev")
    assert head and gp.GitCli.tree_of(port, "dev")
    assert gp.GitCli.is_ancestor(port, "dev", "dev")
    assert gp.GitCli.dirty_tracked(port, "dev", "dev") == []
    assert gp.GitCli.remote_reachable(port) and gp.GitCli.remote_head(port, "dev") == head
    tree = gp.GitCli.candidate_tree(port)
    assert tree
    ok, sha = gp.GitCli.commit_branch(port, f"autoevol/{rig.cycle}", tree, "m")
    assert ok and sha
    assert gp.GitCli.merge_ff(port, f"autoevol/{rig.cycle}") == (True, "merged")
    assert gp.GitCli.push(port, "dev") == (True, "pushed")
    assert te.EvolveStore.load(store, rig.cycle) is None
    te.EvolveStore.save(store, rig.cycle, {"state": "X"})
    assert te.EvolveStore.load(store, rig.cycle) == {"state": "X"}
    assert te.evolve_file_name(0, rig.cycle).startswith("evolve_")
    protocol = (te.GitPort.current_branch, te.GitPort.rev_parse, te.GitPort.tree_of, te.GitPort.is_ancestor,
                te.GitPort.dirty_tracked, te.GitPort.remote_reachable, te.GitPort.candidate_tree,
                te.GitPort.commit_branch, te.GitPort.merge_ff, te.GitPort.push)
    assert all(callable(p) for p in protocol)
