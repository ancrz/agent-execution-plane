"""ONT-42b B4 (AE-5): clase de prioridad como clave primaria de sort_gaps; R no depende del orden de gaps."""

from __future__ import annotations

from pathlib import Path

from engine import threads as th
from engine.threads_model import Gap

REPO = Path(__file__).resolve().parent.parent


def _g(gid: str, kind: str, score: float, sev: float = 0.5) -> Gap:
    return Gap(gid, kind, "n", sev, "x", score=score)


def test_open_discrepancy_and_drift_precede_higher_scored_omissions() -> None:
    gaps = [
        _g("omission:a", "omission", 9.0),
        _g("syntax:b", "syntax_error", 8.0),
        _g("drift:claim:c", "claim_drift", 0.1),
        _g("drift:open:d", "open_discrepancy", 0.2),
        _g("omission:e", "omission", 7.0),
    ]
    assert [g.id for g in th.sort_gaps(gaps)] == [
        "drift:open:d",
        "drift:claim:c",
        "omission:a",
        "syntax:b",
        "omission:e",
    ]


def test_within_class_keeps_score_then_severity_then_id() -> None:
    gaps = [_g("b", "omission", 1.0), _g("a", "omission", 1.0), _g("c", "omission", 2.0), _g("d", "omission", 1.0, 0.9)]
    assert [g.id for g in th.sort_gaps(gaps)] == ["c", "d", "a", "b"]


def test_real_repo_top_gap_is_priority_class_and_r_ignores_gap_order(tmp_path: Path) -> None:
    analysis = th.analyze(REPO, use_cache=False)
    classes = [th.gap_class(g) for g in analysis.gaps]
    assert classes == sorted(classes)
    reordered = th.merkle_root(analysis.graph)[0]
    assert reordered == analysis.root_hash  # merkle_root solo hashea nodos y aristas, nunca gaps

    # G3: fixture sintetico con open_discrepancy + omission para verificar top_gap sin depender de D-01b en REPO
    (tmp_path / "engine").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "engine" / "mod.py").write_text("def pub_fn():\n    return 1\n\ndef uncov_fn():\n    return 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text(
        "import pytest\nfrom engine import mod\n\n"
        "@pytest.mark.xfail(strict=True, reason='D-99')\n"
        "def test_discrepancy():\n    assert mod.pub_fn() == 1\n",
        encoding="utf-8",
    )
    syn = th.analyze(tmp_path, use_cache=False)
    assert syn.gaps and syn.gaps[0].kind == "open_discrepancy" and syn.gaps[0].ref == "D-99"
    assert [th.gap_class(g) for g in syn.gaps] == sorted(th.gap_class(g) for g in syn.gaps)
