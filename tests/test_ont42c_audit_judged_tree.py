"""Auditoria Dokimos ONT-42c C1-C3, condicion 9: el ACCEPT debe estar atado al arbol juzgado. Solo repos temporales."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._evolve_support import make_rig, sh


@pytest.mark.xfail(strict=True, reason="D-EV-1: evolve commitea candidate_tree() actual, no el arbol juzgado en el ACCEPT (sin judged_tree)")
def test_edit_after_accept_is_not_committed(tmp_path: Path) -> None:
    r = make_rig(tmp_path)  # ciclo ACCEPTED sobre el parche original
    (r.work / "a.txt").write_text("EVIL edited after ACCEPT\n", encoding="utf-8")
    (r.work / "payload.py").write_text("print('never judged')\n", encoding="utf-8")
    out = r.run(octal=6, label="DIMINISHED")
    committed = sh(r.canon, "show", f"autoevol/{r.cycle}:a.txt", check=False)
    assert out.get("status") == "BLOCKED_GIT" and "EVIL" not in committed
