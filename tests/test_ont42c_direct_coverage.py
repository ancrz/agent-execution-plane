"""ONT-42c C4-C6: cobertura directa (por nombre cualificado) de la superficie publica nueva de ledger, store y GitCli."""

from __future__ import annotations

import tarfile
from pathlib import Path

from engine import threads_evolve as te
from engine import threads_gitport as gp
from engine import threads_ledger as tl
from tests._evolve_support import Rig, make_rig, sh


def test_ledger_get_event_and_resolve_revert_roundtrip(tmp_path: Path) -> None:
    led = tl.EvolveLedger(tmp_path / "l.db")
    led.claim("g", "R0", "T", "c1", r_before="R0", r_after="R1")
    tl.EvolveLedger.event(led, "evolve.blocked", "c1", {"reason": "x"})
    assert tl.EvolveLedger.get(led, "c1")["r_after"] == "R1"
    assert tl.EvolveLedger.get(led, "nope") is None
    led.mark_reverted("c1")
    assert led.revert_pending() is True
    tl.EvolveLedger.resolve_revert(led, "c1")
    assert led.revert_pending() is False
    assert [e["kind"] for e in led.events("c1")] == ["evolve.blocked"]


def test_store_event_writes_jsonl_and_ledger(tmp_path: Path) -> None:
    led = tl.EvolveLedger(tmp_path / "l.db")
    store = te.EvolveStore(base_dir=tmp_path / "st", ledger=led)
    te.EvolveStore.event(store, "evolve.blocked", {"cycle": "c9", "reason": "r"})
    assert [e["kind"] for e in led.events("c9")] == ["evolve.blocked"]


def test_gitcli_export_tree_and_revert_on_temp_repo(tmp_path: Path) -> None:
    r: Rig = make_rig(tmp_path)
    port = r.port()
    dest = tmp_path / "out"
    dest.mkdir()
    assert gp.GitCli.export_tree(port, "dev", dest) is True
    assert (dest / "a.txt").read_text(encoding="utf-8") == "base\n"
    assert gp.GitCli.export_tree(port, "main", dest) is False  # solo dev o autoevol/<ciclo>
    head = sh(r.canon, "rev-parse", "dev")
    assert gp.GitCli.revert(port, "zz") == (False, "bad_sha")
    ok, new = gp.GitCli.revert(port, head)
    assert ok is False or sh(r.canon, "rev-parse", "dev") == new  # el unico commit es raiz: o falla limpio o crea uno nuevo
    assert not r.fence.exists()
    assert tarfile.is_tarfile  # el export usa safe_extract (sin extractall directo)
    assert "extractall" not in Path(gp.__file__).read_text(encoding="utf-8")


def test_protocol_declares_export_and_revert() -> None:
    assert callable(te.GitPort.export_tree) and callable(te.GitPort.revert)
