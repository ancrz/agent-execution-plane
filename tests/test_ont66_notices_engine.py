"""ONT-66 T2: engine.notices — registro de avisos, estados, bloque <= 350 B, sanitizado."""

from __future__ import annotations

import json

from engine import notices
from engine.threads_model import Gap


def _gap(i: str, kind: str = "omission", sev: float = 0.6, detail: str = "x", node: str = "fn:server.f") -> Gap:
    return Gap(id=i, kind=kind, node=node, severity=sev, detail=detail)


def _drift(i: str = "drift:claim:claim:README.md:3:tool_count") -> Gap:
    return _gap(
        i, "claim_drift", 0.7, "tool_count: declared 30, observed 17 (README.md:3)", "claim:README.md:3:tool_count"
    )


def test_from_gaps_covers_every_kind_with_stable_ids_and_severity() -> None:
    gaps = [_drift(), _gap("omission:a", sev=0.95), _gap("open:b", "open_discrepancy", 0.3, "xfail D-1")]
    out = notices.from_gaps(gaps)
    assert [n.id for n in out] == ["drift:claim:claim:README.md:3:tool_count", "omission:a", "open:b"]
    assert [n.severity for n in out] == [notices.WARN, notices.ERROR, notices.INFO]
    assert out[0].label == "claim_drift README.md tool_count 30≠17"
    assert out[0].next_action == "autoevol(action='spec', gap='drift:claim:claim:README.md:3:tool_count')"
    assert all(len(n.summary.encode()) <= notices.SUMMARY_MAX for n in out)


def test_sanitize_masks_secrets_and_vetoed_paths_but_keeps_project_paths() -> None:
    text = "token=abcdef1234567890SECRETVALUE read /etc/shadow and engine/x.py and /home/u/.ssh/id_rsa"
    out = notices.sanitize(text)
    assert "SECRETVALUE" not in out and "/etc/shadow" not in out and "id_rsa" not in out
    assert "engine/x.py" in out
    gap = _gap("g1", detail="password=hunter2hunter2 in /etc/shadow")
    n = notices.from_gaps([gap])[0]
    assert "hunter2" not in n.summary and "/etc/shadow" not in n.summary and "hunter2" not in n.label


def test_block_is_none_without_notices_and_bounded_with_many_long_ids() -> None:
    assert notices.build_block([]) is None
    many = notices.from_gaps([_gap("g:" + "z" * 70 + str(i), "claim_drift", 0.7, "k" * 90) for i in range(9)])
    blk = notices.build_block(many)
    assert blk is not None and blk["count"] == 9
    assert len(json.dumps(blk, ensure_ascii=False).encode()) <= notices.BLOCK_MAX_BYTES
    assert blk["ask_user"].startswith("AEP reporta: ") and blk["ask_user"].endswith("¿Quieres mejorarlo?")
    assert len(blk.get("top", [])) <= notices.TOP_MAX


def test_block_shape_for_a_drift_notice_is_small() -> None:
    blk = notices.build_block(notices.from_gaps([_drift()]))
    assert blk is not None
    assert blk["top"] == ["claim_drift README.md tool_count 30≠17"] and blk["severity"] == "WARN"
    assert blk["ask_user"] == "AEP reporta: claim_drift README.md tool_count 30≠17. ¿Quieres mejorarlo?"
    assert blk["ack"] == notices.ACK_HINT
    assert len(json.dumps(blk, ensure_ascii=False).encode()) <= notices.BLOCK_MAX_BYTES


def test_registry_lifecycle_new_seen_ack_resolve_reappear() -> None:
    reg = notices.NoticeRegistry()
    a, b = notices.from_gaps([_gap("a"), _gap("b")])
    reg.update([a, b])
    assert [s["state"] for s in reg.snapshot()] == ["new", "new"]
    reg.mark_seen(["a"])
    assert {s["id"]: s["state"] for s in reg.snapshot()} == {"a": "seen", "b": "new"}
    assert reg.ack(["a", "nope"]) == ["a"]
    assert [n.id for n in reg.active()] == ["b"]
    reg.update([a, b])  # el ack persiste mientras el aviso siga visible
    assert [n.id for n in reg.active()] == ["b"]
    c = notices.from_gaps([_gap("c")])[0]
    reg.update([a, b, c])  # aviso NUEVO tras un ack: aparece
    assert sorted(n.id for n in reg.active()) == ["b", "c"]
    assert sorted(reg.ack(all_=True)) == ["a", "b", "c"] and reg.active() == []
    reg.update([c])  # a y b resueltos: desaparecen del registro
    assert [s["id"] for s in reg.snapshot()] == ["c"]
    reg.update([a, c])  # a vuelve a aparecer tras resolverse: es nuevo otra vez
    assert [n.id for n in reg.active()] == ["a"]


def test_severity_rise_reopens_an_acked_notice() -> None:
    reg = notices.NoticeRegistry()
    reg.update(notices.from_gaps([_gap("a", sev=0.6)]))
    reg.ack(all_=True)
    reg.update(notices.from_gaps([_gap("a", sev=0.95)]))
    assert [n.severity for n in reg.active()] == ["ERROR"]


def test_push_event_fires_once_per_change() -> None:
    reg = notices.NoticeRegistry()
    assert reg.push_event() is None
    reg.update(notices.from_gaps([_gap("a")]))
    ev = reg.push_event()
    assert ev is not None and ev["logger"] == "aep.notice" and ev["level"] == "warning"
    assert ev["data"]["count"] == 1 and "ask_user" in ev["data"]
    assert reg.push_event() is None  # sin cambios: silencio
    reg.update(notices.from_gaps([_gap("a"), _gap("b", sev=0.95)]))
    ev2 = reg.push_event()
    assert ev2 is not None and ev2["level"] == "error" and ev2["data"]["count"] == 2
    assert reg.push_event() is None
    reg.ack(all_=True)
    assert reg.push_event() is None  # ack no empuja nada
    reg.update(notices.from_gaps([_gap("a"), _gap("b", sev=0.95), _gap("c")]))
    assert reg.push_event() is not None


def test_plane_notices_and_quiet_actions() -> None:
    out = notices.from_plane({"front_stale": True, "reload_error": True, "serving_from": "lkg", "stale": True})
    assert [n.id for n in out] == ["plane:front_stale", "plane:reload_error", "plane:serving_lkg"]
    assert [n.id for n in notices.from_plane({"stale": True})] == ["plane:code_stale"]
    assert notices.from_plane({}) == []
    assert notices.is_quiet("autoevol", "ack") and notices.is_quiet("autoevol", "spec")
    assert not notices.is_quiet("process_inspect", "default")
