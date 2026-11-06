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


def test_real_repo_top_gap_is_priority_class_and_r_ignores_gap_order() -> None:
    analysis = th.analyze(REPO, use_cache=False)
    classes = [th.gap_class(g) for g in analysis.gaps]
    assert classes == sorted(classes)
    assert analysis.gaps[0].kind == "open_discrepancy"  # D-01b abierto hasta B9
    reordered = th.merkle_root(analysis.graph)[0]
    assert reordered == analysis.root_hash  # merkle_root solo hashea nodos y aristas, nunca gaps
