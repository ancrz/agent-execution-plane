"""Cobertura conductual de kanban_board / artifact_catalog / artifact_lint_and_build / playbook_run.

Todo el estado vive en bases SQLite de tmp (kanban + catalogo comparten archivo para que la ponderacion de
artefactos sea real). El embedder se sustituye por uno determinista local (sin descargas ni ONNX).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import server
from engine import catalog as catalog_mod
from engine.catalog import ArtifactCatalog
from engine.kanban import KanbanBoard
from engine.playbook import PlaybookStore
from engine.privilege import _PrivilegeCache

DIM = 384


class _FakeEmbedder:
    """Embedder determinista: mismo texto -> mismo vector; sin red ni modelo."""

    is_available = True

    def embed(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode()).digest()
        return [(seed[i % len(seed)] - 128) / 128.0 for i in range(DIM)]


def _j(coro: Awaitable[str]) -> dict[str, Any]:
    async def _await() -> str:
        return await coro

    data = json.loads(asyncio.run(_await()))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def tier(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    def _set(value: str) -> None:
        monkeypatch.setenv("AEP_FORCE_TIER", value)
        _PrivilegeCache.reset()

    yield _set
    _PrivilegeCache.reset()


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Catalogo + kanban sobre la MISMA db tmp; playbooks en otra db tmp."""
    monkeypatch.setattr(catalog_mod, "get_instance", _FakeEmbedder)
    db = tmp_path / "artifacts.db"
    monkeypatch.setattr(server, "catalog", ArtifactCatalog(db_path=db))
    monkeypatch.setattr(server, "kanban", KanbanBoard(db_path=db))
    monkeypatch.setattr(server, "playbook_store", PlaybookStore(db_path=tmp_path / "playbooks.db"))
    return db


def _register(name: str, intent: str = "inspect open sockets", category: str = "net") -> str:
    return server.catalog.register_artifact(
        name=name, intent=intent, category=category, cue_contract="{}", go_source="package main\nfunc main() {}\n"
    )


def _artifact_row(db: Path, name: str) -> sqlite3.Row:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    return row


def _lane_of(board: dict[str, Any], task_id: int) -> str | None:
    for lane, cards in board["lanes"].items():
        if any(c["task_id"] == task_id for c in cards):
            return lane
    return None


# --------------------------------------------------------------------------- kanban: ciclo de vida completo
def test_kanban_create_promote_demote_lifecycle(state: Path, tier) -> None:
    tier("6rw-")
    _register("cov_promo")
    created = _j(server.kanban_board(action="create", title="promote me", artifact_name="cov_promo", intent="x"))
    task_id = created["task_id"]
    assert created["state"] == "BACKLOG"

    # Sin senal de calidad la promocion se rechaza y no cambia el estado.
    rejected = _j(server.kanban_board(action="promote", task_id=task_id))
    assert rejected["status"] == "REJECTED"
    assert rejected["threshold"] == 0.75 and rejected["promotion_score"] < 0.75
    reusable_before = _artifact_row(state, "cov_promo")["reusable"]
    assert _artifact_row(state, "cov_promo")["promotion_score"] == 0.0

    adv = _j(
        server.kanban_board(action="advance", task_id=task_id, to_state="CANARY", lint_passed=True, canary_passed=True)
    )
    assert adv["eligible_for_promotion"] is True

    promoted = _j(server.kanban_board(action="promote", task_id=task_id))
    assert promoted["status"] == "PROMOTED" and promoted["verdict"] == "TRUST"
    assert promoted["promotion_score"] >= 0.75
    row = _artifact_row(state, "cov_promo")
    assert (
        reusable_before in (0, 1)
        and row["reusable"] == 1
        and row["promotion_score"] == pytest.approx(promoted["promotion_score"])
    )
    assert _lane_of(_j(server.kanban_board(action="board")), task_id) == "PROMOTED"

    demoted = _j(server.kanban_board(action="demote", task_id=task_id, reason="regresion", target_state="LINTED"))
    assert demoted["status"] == "DEMOTED" and demoted["task_state"] == "LINTED"
    assert demoted["reason"] == "regresion" and demoted["artifact_name"] == "cov_promo"
    assert _artifact_row(state, "cov_promo")["reusable"] == 0
    assert _lane_of(_j(server.kanban_board(action="board")), task_id) == "LINTED"


def test_kanban_demote_by_artifact_name_and_unknown_artifact(state: Path, tier) -> None:
    tier("6rw-")
    _register("cov_demote_me")
    with server.catalog._get_rw_conn() as conn:
        conn.execute("UPDATE artifacts SET reusable=1 WHERE name='cov_demote_me'")
    ok = _j(server.kanban_board(action="demote", artifact_name="cov_demote_me", reason="manual"))
    assert ok["status"] == "DEMOTED" and ok["reason"] == "manual"
    assert _artifact_row(state, "cov_demote_me")["reusable"] == 0
    missing = _j(server.kanban_board(action="demote", artifact_name="cov_ghost"))
    assert missing["status"] == "ERROR" and "cov_ghost" in missing["error"]


def test_kanban_reevaluate_demotes_only_demonstrated_failures(state: Path, tier) -> None:
    tier("6rw-")
    _register("cov_bad")
    _register("cov_good")
    with server.catalog._get_rw_conn() as conn:
        conn.execute("UPDATE artifacts SET reusable=1, success_rate=0.2, execution_count=10 WHERE name='cov_bad'")
        conn.execute("UPDATE artifacts SET reusable=1, success_rate=1.0, execution_count=10 WHERE name='cov_good'")
    res = _j(server.kanban_board(action="reevaluate"))
    assert res["status"] == "OK" and res["reevaluated"] == 2
    assert res["demoted_count"] == 1 and res["kept_trusted"] == 1
    assert [d["name"] for d in res["demoted"]] == ["cov_bad"]
    assert _artifact_row(state, "cov_bad")["reusable"] == 0  # el campo reusable CAMBIO
    good = _artifact_row(state, "cov_good")
    assert good["reusable"] == 1 and good["promotion_score"] > 0.0  # score recalculado


def test_kanban_archive_dry_run_apply_and_unarchive_roundtrip(state: Path, tier) -> None:
    tier("6rw-")
    task_id = _j(server.kanban_board(action="create", title="stale"))["task_id"]
    _j(server.kanban_board(action="advance", task_id=task_id, to_state="REJECTED", note="no sirve"))

    dry = _j(server.kanban_board(action="archive"))
    assert dry["status"] == "DRY_RUN" and dry["applied"] is False
    assert [c["task_id"] for c in dry["candidates"]] == [task_id]
    assert _lane_of(_j(server.kanban_board(action="board")), task_id) == "REJECTED"  # dry-run no archiva

    done = _j(server.kanban_board(action="archive", apply=True))
    assert done["status"] == "ARCHIVED" and done["candidate_count"] == 1
    assert _lane_of(_j(server.kanban_board(action="board")), task_id) is None
    assert _lane_of(_j(server.kanban_board(action="board", include_archived=True)), task_id) == "REJECTED"

    back = _j(server.kanban_board(action="unarchive", task_id=task_id))
    assert back["status"] == "OK" and back["archived"] is False and back["state"] == "REJECTED"
    assert _lane_of(_j(server.kanban_board(action="board")), task_id) == "REJECTED"


def test_kanban_archive_never_touches_promoted_tasks(state: Path, tier) -> None:
    tier("6rw-")
    task_id = _j(server.kanban_board(action="create", title="keeper"))["task_id"]
    _j(server.kanban_board(action="advance", task_id=task_id, to_state="PROMOTED"))
    res = _j(server.kanban_board(action="archive", states=["PROMOTED", "REJECTED"], max_score=2.0, apply=True))
    assert res["candidate_count"] == 0 and "PROMOTED" in res["protected_states"]
    assert _lane_of(_j(server.kanban_board(action="board")), task_id) == "PROMOTED"


def test_kanban_actions_validate_params_and_unknown_tasks(state: Path, tier) -> None:
    tier("6rw-")
    for res in (
        _j(server.kanban_board(action="promote")),
        _j(server.kanban_board(action="unarchive")),
        _j(server.kanban_board(action="demote")),
    ):
        assert res["status"] == "PARAM_ERROR" and "requiere" in res["error"]
    assert _j(server.kanban_board(action="promote", task_id=9999))["status"] == "ERROR"
    assert _j(server.kanban_board(action="unarchive", task_id=9999))["status"] == "ERROR"


def test_kanban_mutations_are_degraded_in_read_only_tiers(state: Path, tier) -> None:
    tier("5r-x")
    for res, act in (
        (_j(server.kanban_board(action="promote", task_id=1)), "promote"),
        (_j(server.kanban_board(action="demote", artifact_name="x")), "demote"),
        (_j(server.kanban_board(action="reevaluate")), "reevaluate"),
        (_j(server.kanban_board(action="archive", apply=True)), "archive"),
        (_j(server.kanban_board(action="unarchive", task_id=1)), "unarchive"),
    ):
        assert res["status"] == "DEGRADED" and res["action"] == act and res["chmod_tier"] == "5r-x"
    assert _j(server.kanban_board(action="board"))["status"] == "OK"  # la lectura sigue permitida


# --------------------------------------------------------------------------- artifact_catalog: query / reindex
def test_catalog_query_miss_then_hit_after_registration(state: Path, tier) -> None:
    tier("6rw-")
    miss = _j(server.artifact_catalog(action="query", intent="inspect open sockets", category="net"))
    assert miss["status"] == "CACHE_MISS" and miss["available_templates"]
    assert _j(server.artifact_catalog(action="query"))["status"] == "PARAM_ERROR"

    art_id = _register("cov_sockets")
    hit = _j(server.artifact_catalog(action="query", intent="inspect open sockets", category="net"))
    assert hit["status"] == "CACHE_HIT" and hit["name"] == "cov_sockets" and hit["artifact_id"] == art_id
    assert hit["retrieval_mode"] == "exact_hash"


def test_catalog_reindex_embeds_missing_rows_and_reports_coverage(state: Path, tier) -> None:
    tier("6rw-")
    if not server.catalog._vec_available:
        pytest.skip("sqlite-vec no disponible")
    _register("cov_vec_a", intent="alpha intent")
    _register("cov_vec_b", intent="beta intent")
    with server.catalog._get_rw_conn() as conn:
        conn.execute("DELETE FROM vec_artifacts")  # simula filas registradas por otra via sin indexar
    res = _j(server.artifact_catalog(action="reindex"))
    assert res["status"] == "OK"
    assert res["coverage_before"]["missing"] == 2
    assert res["reindex"]["indexed"] == 2
    assert res["coverage_after"]["missing"] == 0 and res["coverage_after"]["indexed"] == 2
    again = _j(server.artifact_catalog(action="reindex"))
    assert again["reindex"]["indexed"] == 0 and again["reindex"]["skipped"] == 2  # idempotente
    forced = _j(server.artifact_catalog(action="reindex", force=True))
    assert forced["reindex"]["indexed"] == 2


def test_catalog_force_reindex_failed_row_keeps_previous_vector(state: Path, tier, monkeypatch) -> None:
    tier("6rw-")
    if not server.catalog._vec_available:
        pytest.skip("sqlite-vec no disponible")
    _register("cov_sp_a", intent="alpha intent")
    _register("cov_sp_b", intent="beta intent")
    _register("cov_sp_c", intent="gamma intent")

    def _vecs() -> dict[str, bytes]:
        with server.catalog._get_ro_conn() as conn:
            return {
                r["artifact_id"]: bytes(r["intent_embedding"])
                for r in conn.execute("SELECT artifact_id, intent_embedding FROM vec_artifacts")
            }

    before = _vecs()
    assert len(before) == 3
    victim_text = "beta intent"
    new_embed = _FakeEmbedder()
    orig_embed = new_embed.embed
    # New vectors differ from the stored ones so a re-embed is observable.
    new_embed.embed = lambda text: [-x for x in orig_embed(text)]  # type: ignore[method-assign]
    monkeypatch.setattr(catalog_mod, "get_instance", lambda: new_embed)

    real_serialize = catalog_mod.sqlite_vec.serialize_float32

    def _flaky(vec: list[float]) -> bytes:
        if vec == new_embed.embed(victim_text):
            raise sqlite3.OperationalError("simulated insert failure")
        return real_serialize(vec)

    monkeypatch.setattr(catalog_mod.sqlite_vec, "serialize_float32", _flaky)
    # The serialize call sits inside the DELETE+INSERT block, i.e. after the DELETE already ran.
    res = server.catalog.reindex(force=True)
    after = _vecs()
    assert res["indexed"] == 2 and res["total"] == 3
    assert set(after) == set(before)  # failed row's previous vector still exists
    changed = [k for k in before if before[k] != after[k]]
    assert len(changed) == 2
    victim_id = next(k for k in before if k not in changed)
    with server.catalog._get_ro_conn() as conn:
        name = conn.execute("SELECT name FROM artifacts WHERE id = ?", (victim_id,)).fetchone()["name"]
    assert name == "cov_sp_b"


def test_catalog_reindex_is_degraded_in_read_only_tier(state: Path, tier) -> None:
    tier("4r--")
    res = _j(server.artifact_catalog(action="reindex"))
    assert res["status"] == "DEGRADED" and res["chmod_tier"] == "4r--"
    assert "coverage_before" not in res  # no se toco el indice


# --------------------------------------------------------------------------- artifact_lint_and_build: hydrate / select
def test_lint_and_build_select_ranks_templates_by_intent(state: Path, tier) -> None:
    tier("4r--")
    res = _j(server.artifact_lint_and_build(action="select", intent="disk usage of mounted filesystems", limit=3))
    assert res["status"] == "OK" and res["intent"] == "disk usage of mounted filesystems"
    assert 1 <= len(res["matches"]) <= 3
    top = res["matches"][0]
    assert top["name"] == "disk-usage"
    bad = _j(server.artifact_lint_and_build(action="select", intent="  "))
    assert bad["status"] == "PARAM_ERROR" and "intent" in bad["error"]


def test_lint_and_build_hydrate_renders_go_source_and_validates_params(state: Path, tier) -> None:
    tier("4r--")
    ok = _j(server.artifact_lint_and_build(action="hydrate", template_name="disk-usage"))
    assert ok["status"] == "SUCCESS" and ok["template_name"] == "disk-usage"
    assert ok["go_source"].lstrip().startswith(("package main", "//")) and "func main" in ok["go_source"]
    assert "{{" not in ok["go_source"]  # no quedan marcadores sin hidratar
    missing = _j(server.artifact_lint_and_build(action="hydrate"))
    assert missing["status"] == "PARAM_ERROR" and "template_name" in missing["error"]
    unknown = _j(server.artifact_lint_and_build(action="hydrate", template_name="no-such-template"))
    assert unknown["status"] != "SUCCESS"


# --------------------------------------------------------------------------- playbook_run: prune
_STEPS: list[dict[str, Any]] = [{"id": "caps", "tool": "discover", "params": {"action": "capabilities"}}]


def test_playbook_prune_dry_run_then_apply_removes_only_failed(state: Path, tier) -> None:
    tier("6rw-")
    for nm in ("pb_flaky", "pb_solid"):
        assert _j(server.playbook_run(action="create", name=nm, description=nm, steps=_STEPS))["status"] == "OK"
    for _ in range(4):
        server.playbook_store.record_run("pb_flaky", False)
        server.playbook_store.record_run("pb_solid", True)

    dry = _j(server.playbook_run(action="prune"))
    assert dry["status"] == "DRY_RUN" and dry["count"] == 1
    assert dry["candidates"][0]["name"] == "pb_flaky" and dry["candidates"][0]["reason"] == "FAILED"
    assert server.playbook_store.get("pb_flaky") is not None  # dry-run no borra

    done = _j(server.playbook_run(action="prune", apply=True))
    assert done["status"] == "PRUNED" and done["removed"] == ["pb_flaky"]
    names = [p["name"] for p in _j(server.playbook_run(action="list"))["playbooks"]]
    assert names == ["pb_solid"]


def test_playbook_prune_explicit_names_and_auditor_tier_gate(state: Path, tier) -> None:
    tier("6rw-")
    _j(server.playbook_run(action="create", name="pb_named", description="d", steps=_STEPS))
    explicit = _j(server.playbook_run(action="prune", names=["pb_named"]))
    assert explicit["candidates"][0]["reason"] == "EXPLICIT_NAME"
    tier("4r--")
    denied = _j(server.playbook_run(action="prune", names=["pb_named"], apply=True))
    assert denied["status"] == "DEGRADED" and denied["chmod_tier"] == "4r--"
    assert server.playbook_store.get("pb_named") is not None
