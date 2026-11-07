"""
Engine: threads_evolve.py (ONT-42c C1-C3: maquina de estados de `autoevol(evolve)`)

    PLAN -> PATCH_AWAITED -> JUDGED(ACCEPT) -> COMMITTED -> MERGED -> PUSHED        (BLOCKED_GIT es lateral)

Contrato (Ontos, condiciones 2, 7-9, 11-13):
  - Re-entrante, como `fix_test`: cada llamada avanza lo que pueda y devuelve `state` + `awaiting`.
  - LEE el almacen de ciclos de `fix_test` (solo lectura: no borra ni escribe); su propio estado vive en `evolve_<hash>.json`
    del mismo directorio de estado y en el JSONL de eventos (`evolve.committed|merged|pushed|blocked`).
    `threads_ops` / `threads_verify` NO importan este modulo (arista dep unidireccional).
  - Git entra por el Protocol `GitPort`, inyectado desde `server.py`. Este modulo no importa `server` ni `aep_front`.
  - Gating por tier (condicion 11): push y ff-merge SOLO con etiqueta FULL y octal 7; 6rw- o DIMINISHED = commit local en
    `autoevol/<ciclo>`; 5r-x y 4r-- = solo plan (cero escrituras). `apply=False` = plan en seco.
  - Git es la fuente de verdad, el estado local es un indice (condicion 13): al re-entrar se reconcilia leyendo las ramas.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from engine import threads_events as ev
from engine import threads_gate as tg
from engine import threads_ledger as tl
from engine import threads_verify as tv

PLAN = "PLAN"
PATCH_AWAITED = "PATCH_AWAITED"
JUDGED = "JUDGED"
COMMITTED = "COMMITTED"
MERGED = "MERGED"
PUSHED = "PUSHED"
BLOCKED_GIT = "BLOCKED_GIT"
REVERTED = "REVERTED"
BRANCH_PREFIX = "autoevol/"
DEV_BRANCH = "dev"
MIN_EVOLVE_OCTAL = 6  # por debajo de 6rw- (5r-x, 4r--) solo hay plan
FULL_LABEL = "FULL"
FULL_OCTAL = 7
STEPS = ("fix_test:ACCEPT", "commit:autoevol/<cycle>", "ff-merge:dev", "push:dev+branch")
_REASON_MAX = 60


class GitPort(Protocol):
    """Superficie git que necesita evolve. La implementa `engine.threads_gitport.GitCli` (o un doble en tests)."""

    def current_branch(self) -> str: ...
    def rev_parse(self, ref: str) -> str | None: ...
    def tree_of(self, ref: str) -> str | None: ...
    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...
    def dirty_tracked(self, ref_a: str, ref_b: str) -> list[str]: ...
    def remote_reachable(self) -> bool: ...
    def candidate_tree(self) -> str | None: ...
    def work_root(self) -> str: ...
    def commit_branch(self, branch: str, tree: str, message: str) -> tuple[bool, str]: ...
    def export_tree(self, ref: str, dest: Path | str) -> bool: ...
    def revert(self, sha: str) -> tuple[bool, str]: ...
    def merge_ff(self, branch: str) -> tuple[bool, str]: ...
    def push(self, ref: str) -> tuple[bool, str]: ...


LiveCheck = Callable[[], dict[str, Any]]  # {"stale": bool, "loaded": str, "disk": str}


@dataclass
class GateKit:
    """Ejecutores inyectados desde `server.py` (sandbox_run). Sin kit no hay gate y, por tanto, no hay merge."""

    collect: tg.Collect
    run_batch: tg.RunBatch
    summarize: Callable[[Any], dict[str, Any]] | None = (
        None  # C7: resumen del grafo (`root`, `gaps`, `codep`) de un arbol
    )
    post_verify: Callable[[dict[str, Any]], dict[str, Any]] | None = None  # C6: {"ok": bool, "reason": str}


def gating(octal: int, label: str) -> str:
    """`plan` (sin escrituras) | `local` (commit local) | `full` (commit + ff-merge + push). Condicion 11."""
    if octal < MIN_EVOLVE_OCTAL:
        return "plan"
    if label == FULL_LABEL and octal == FULL_OCTAL:
        return "full"
    return "local"


def branch_name(cycle: str) -> str:
    return f"{BRANCH_PREFIX}{cycle}"


# ---------------------------------------------------------------------------
# Almacenes: lectura del ciclo de fix_test (solo lectura) y estado propio de evolve
# ---------------------------------------------------------------------------


def read_cycle(
    cycle: str, *, base_dir: Path | str | None = None, uid: int | None = None, now: float | None = None
) -> dict[str, Any] | None:
    """Registro del ciclo de fix_test SIN efectos (a diferencia de `CycleStore.load`, no borra vencidos).

    Devuelve None si no existe y `{"state": "EXPIRED"}` si vencio su TTL.
    """
    if not tv.valid_cycle_id(cycle):
        return None
    name = tv.cycle_file_name(os.geteuid() if uid is None else int(uid), cycle)
    with ev.state_dir(base_dir) as dfd:
        raw = ev.read_file(dfd, name)
    if raw is None:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    clock = time.time() if now is None else now
    if clock - float(rec.get("updated", 0)) > tv.CYCLE_TTL_SECONDS:
        return {"cycle_id": cycle, "state": tv.EXPIRED}
    return rec


def evolve_file_name(uid: int, cycle: str) -> str:
    if not tv.valid_cycle_id(cycle):
        raise ValueError("invalid cycle_id")
    return "evolve_" + hashlib.sha256(f"{uid}|{cycle}".encode()).hexdigest()[:16] + ".json"


class EvolveStore:
    """Estado de evolve por ciclo (indice; la verdad es git)."""

    def __init__(
        self, *, base_dir: Path | str | None = None, uid: int | None = None, ledger: tl.EvolveLedger | None = None
    ) -> None:
        self._dir = base_dir
        self._uid = os.geteuid() if uid is None else int(uid)
        self.ledger = ledger  # C5: indice SQLite (git manda). Sin ledger no hay commit: fail-closed en `_commit`.

    def load(self, cycle: str) -> dict[str, Any] | None:
        with ev.state_dir(self._dir) as dfd:
            raw = ev.read_file(dfd, evolve_file_name(self._uid, cycle))
        if raw is None:
            return None
        try:
            rec = json.loads(raw)
        except ValueError:
            return None
        return rec if isinstance(rec, dict) else None

    def save(self, cycle: str, rec: dict[str, Any]) -> None:
        blob = json.dumps(rec, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with ev.state_dir(self._dir) as dfd:
            ev.write_file_atomic(dfd, evolve_file_name(self._uid, cycle), blob)

    def event(self, kind: str, data: dict[str, Any]) -> None:
        ev.append_event(kind, data, base_dir=self._dir)
        self.ledger_event(kind, data)

    def ledger_event(self, kind: str, data: dict[str, Any]) -> None:
        """Evento `evolve.*` solo en el ledger (p. ej. progreso del gate). Fail-soft: el ledger es el indice, no la verdad."""
        if self.ledger is None:
            return
        try:
            self.ledger.event(kind, str(data.get("cycle", "")), data)
        except sqlite3.Error, OSError:
            return

    def sync_state(self, cycle: str, state: str) -> None:
        """Reconcilia el indice con el estado real (git) del ciclo."""
        if self.ledger is None:
            return
        try:
            self.ledger.set_state(cycle, state)
        except sqlite3.Error, OSError:
            return


# ---------------------------------------------------------------------------
# Maquina de estados
# ---------------------------------------------------------------------------


def _blocked(store: EvolveStore, cycle: str, rec: dict[str, Any], reason: str) -> dict[str, Any]:
    reason = reason[:_REASON_MAX]
    rec["blocked"] = reason
    store.save(cycle, rec)
    store.event("evolve.blocked", {"cycle": cycle, "state": rec["state"], "reason": reason})
    return {"status": BLOCKED_GIT, "reason": reason, "state": rec["state"], "cycle": cycle, "branch": rec["branch"]}


def _plan(mode: str, state: str, cycle: str | None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "OK", "state": state, "gating": mode, "steps": list(STEPS), "applied": False}
    if cycle:
        out["cycle"] = cycle
    out.update(extra or {})
    return out


def run_evolve(
    store: EvolveStore,
    git: GitPort,
    live_check: LiveCheck,
    *,
    cycle: str | None,
    gap: str | None,
    apply: bool,
    octal: int,
    label: str,
    cycle_dir: Path | str | None = None,
    kit: GateKit | None = None,
) -> dict[str, Any]:
    """`autoevol(evolve)`: avanza el ciclo de `fix_test` aceptado hasta donde permitan el tier y git. Re-entrante."""
    mode = gating(octal, label)
    if not cycle:
        return _plan(
            mode,
            PLAN,
            None,
            {"awaiting": "fix_test", "gap": gap, "next": "autoevol(fix_test) until ACCEPT, then evolve(cycle=...)"},
        )
    if not tv.valid_cycle_id(cycle):
        return {"status": "ERROR", "error": "invalid cycle"}
    rec = store.load(
        cycle
    )  # si evolve ya tiene registro, ese registro manda (el TTL del ciclo de fix_test ya no aplica)
    fix = read_cycle(cycle, base_dir=cycle_dir) if rec is None else {"state": tv.ACCEPTED, "gap": rec.get("gap")}
    if fix is None:
        return {"status": "NOT_FOUND", "cycle": cycle[:16]}
    fstate = fix.get("state")
    if fstate == tv.EXPIRED:
        return {"status": tv.EXPIRED, "cycle": cycle}
    if fstate == tv.EXHAUSTED:
        return {"status": "CLOSED", "state": tv.EXHAUSTED, "cycle": cycle}
    if fstate != tv.ACCEPTED:
        return _plan(mode, PATCH_AWAITED, cycle, {"awaiting": "fix_test", "fix_state": fstate})
    if mode == "plan" or not apply:
        return _plan(
            mode,
            (rec or {}).get("state", JUDGED),
            cycle,
            {"gap": fix.get("gap"), "awaiting": "apply" if not apply else "tier"},
        )
    branch = branch_name(cycle)
    rec = rec or {"cycle": cycle, "gap": fix.get("gap"), "state": JUDGED, "branch": branch, "sha": "", "tree": ""}
    if (
        "judged_tree" not in rec
    ):  # D-EV-1: copia del arbol/raiz juzgados en el ACCEPT (ausente => fail-closed en _commit)
        judged = fix.get("judged") or {}
        rec["judged_tree"] = judged.get("tree", "")
        rec["judged_root"] = judged.get("root", "")
        base = fix.get("base") if isinstance(fix.get("base"), dict) else {}
        rec["base_root"] = str(base.get("root", ""))  # C5/C7: R de la generacion base (clave de idempotencia)
        rec["base_gaps"] = sorted(str(g) for g in base.get("gaps", []))  # C7: Gaps(G)
    rec = _reconcile(git, rec, branch)
    store.sync_state(cycle, rec["state"])  # C5: git manda, el ledger se reconcilia en cada reentrada
    if rec["state"] == REVERTED:  # C6: dev quedo adelantado a origin por el revert; solo el usuario decide
        return {
            "status": BLOCKED_GIT,
            "reason": "dev_dirty_by_revert",
            "state": REVERTED,
            "cycle": cycle,
            "branch": branch,
        }
    if rec["state"] == JUDGED:
        done = _commit(store, git, kit, cycle, rec, branch)
        if done is not None:
            return done
    if rec["state"] == COMMITTED and mode == "full":
        done = _gate(store, git, kit, cycle, rec, branch)  # C4: suite completa sobre el commit, antes del ff-merge
        if done is not None:
            return done
        done = _merge(store, git, cycle, rec, branch)
        if done is not None:
            return done
    if rec["state"] == MERGED and mode == "full":
        if not _merged_witnessed(store, git, cycle, rec, branch):
            return _unverified(
                store, cycle, rec
            )  # DK-1: MERGED sin evento del ledger (estado forjado o ledger perdido)
        done = _post_verify(
            store, git, kit, live_check, cycle, rec, branch
        )  # C6: verify post-merge; si falla, revert antes del push
        if done is not None:
            return done
        done = _push(store, git, live_check, cycle, rec, branch)
        if done is not None:
            return done
    store.save(cycle, rec)
    store.sync_state(cycle, rec["state"])
    out: dict[str, Any] = {
        "status": "OK",
        "state": rec["state"],
        "cycle": cycle,
        "branch": branch,
        "sha": rec["sha"][:12],
        "gating": mode,
        "applied": True,
    }
    if mode == "local" and rec["state"] == COMMITTED:
        out["local_only"] = True  # 6rw- / DIMINISHED: sin ff-merge ni push
    return out


def _reconcile(git: GitPort, rec: dict[str, Any], branch: str) -> dict[str, Any]:
    """Git manda: si la rama ya existe (o ya esta dentro de dev), el estado avanza aunque el indice local no lo sepa."""
    sha = git.rev_parse(branch)
    if sha is None:
        return rec
    if rec["state"] == COMMITTED and git.is_ancestor(branch, DEV_BRANCH):
        rec["state"] = MERGED  # el merge ocurrio aunque el proceso cayera antes de anotarlo
    return rec


def _commit(
    store: EvolveStore, git: GitPort, kit: GateKit | None, cycle: str, rec: dict[str, Any], branch: str
) -> dict[str, Any] | None:
    if not rec.get("judged_tree") or not rec.get("judged_root"):
        return _blocked(store, cycle, rec, "no_judged_tree")  # ciclo previo a D-EV-1: sin ACCEPT implicito
    if os.path.realpath(git.work_root()) != rec["judged_root"]:
        return _blocked(store, cycle, rec, "root_mismatch")
    tree = git.candidate_tree()
    if not tree:
        return _blocked(store, cycle, rec, "no_changes")
    if tree != rec["judged_tree"]:
        return _blocked(store, cycle, rec, "tree_changed_after_accept")  # re-juzgar con un nuevo fix_test
    cascade = _cascade(kit, git, rec)
    if cascade is not None:
        return _reject(store, cycle, rec, cascade)
    if store.ledger is None:
        return _blocked(store, cycle, rec, "no_ledger")
    try:
        claim = store.ledger.claim(
            str(rec.get("gap", "")),
            str(rec.get("base_root", "")),
            tree,
            cycle,
            r_before=str(rec.get("base_root", "")),
            r_after=str(rec.get("r_after", "")),
        )
    except sqlite3.Error, OSError:
        return _blocked(store, cycle, rec, "ledger_unavailable")
    if claim.get("capped"):
        return _reject(store, cycle, rec, "max_cycles", used=claim["used"], max=claim["max"])  # condicion 14
    row = claim.get("row")
    if row is not None and row["cycle"] != cycle:  # misma (gap, base_R, tree): ya promovida por otro ciclo
        return {"status": "OK", "state": row["state"], "cycle": cycle, "duplicate_of": row["cycle"], "applied": False}
    ok, info = git.commit_branch(branch, tree, f"feat(autoevol): evolve {rec.get('gap', '')} [{cycle}]")
    if not ok:
        existing = git.tree_of(branch)
        if info == "branch_exists" and existing == tree:  # idempotente: misma rama, mismo arbol
            rec.update(state=COMMITTED, sha=git.rev_parse(branch) or "", tree=tree)
            return None
        return _blocked(store, cycle, rec, "branch_other_tree" if info == "branch_exists" else info)
    rec.update(state=COMMITTED, sha=info, tree=tree)
    store.save(cycle, rec)
    store.event(
        "evolve.committed",
        {
            "cycle": cycle,
            "branch": branch,
            "sha": info[:12],
            "tree": tree[:12],
            "r_before": str(rec.get("base_root", ""))[:16],
            "r_after": str(rec.get("r_after", ""))[:16],
        },
    )
    return None


def _unverified(store: EvolveStore, cycle: str, rec: dict[str, Any]) -> dict[str, Any]:
    return _blocked(store, cycle, rec, "state_unverified")  # DK-1: el JSON de /dev/shm es cache, no autoridad


def _gate_witnessed(store: EvolveStore, cycle: str, tree: str) -> bool:
    """DK-1: el ledger SQLite tiene un `evolve.gate` green sobre exactamente este arbol."""
    if store.ledger is None or not tree:
        return False
    try:
        return store.ledger.confirm("evolve.gate", cycle, verdict=tg.GREEN, tree=tree)
    except sqlite3.Error, OSError:
        return False


def _merged_witnessed(store: EvolveStore, git: GitPort, cycle: str, rec: dict[str, Any], branch: str) -> bool:
    """DK-1: `MERGED` exige un `evolve.merged` del ledger con el mismo sha completo. Si el proceso cayo entre el ff-merge y
    el evento, git lo prueba (rama ancestro de dev, sha coincide) y hay testigo de gate verde: se registra el evento."""
    if store.ledger is None:
        return False
    sha = str(rec.get("sha", ""))
    tree = git.tree_of(branch)
    if not sha or tree is None or git.rev_parse(branch) != sha:
        return False
    try:
        if store.ledger.confirm("evolve.merged", cycle, sha_full=sha):
            return True
        if _gate_witnessed(store, cycle, tree) and git.is_ancestor(branch, DEV_BRANCH):
            store.event(
                "evolve.merged", {"cycle": cycle, "branch": branch, "sha": sha[:12], "sha_full": sha, "recovered": True}
            )
            return True
    except sqlite3.Error, OSError:
        return False
    return False


def _reject(store: EvolveStore, cycle: str, rec: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    reason = reason[:_REASON_MAX]
    rec["blocked"] = reason
    store.save(cycle, rec)
    store.event("evolve.blocked", {"cycle": cycle, "state": rec["state"], "reason": reason})
    return {
        "status": "REJECT",
        "reason": reason,
        "state": rec["state"],
        "cycle": cycle,
        "branch": rec["branch"],
        **extra,
    }


def _gate(
    store: EvolveStore, git: GitPort, kit: GateKit | None, cycle: str, rec: dict[str, Any], branch: str
) -> dict[str, Any] | None:
    """C4 (condicion 10): suite completa por lotes en sandbox sobre el arbol commiteado. None = verde, seguir al merge."""
    gate = rec.get("gate")
    committed_tree = git.tree_of(branch)
    if committed_tree is None or committed_tree != rec.get("judged_tree"):
        return _blocked(store, cycle, rec, "gate_tree_mismatch")  # el commit no es el arbol juzgado
    if gate is not None and gate.get("tree") != committed_tree:
        gate = None
    if gate is not None and gate["verdict"] == tg.GREEN:
        return None if _gate_witnessed(store, cycle, committed_tree) else _unverified(store, cycle, rec)
    if gate is not None and gate["verdict"] == tg.RED:
        return _reject(store, cycle, rec, "gate_failed", gate_reason=gate.get("reason", ""))
    if kit is None:
        return _blocked(store, cycle, rec, "no_gate_kit")
    tmp = tempfile.mkdtemp(prefix="aep_gate_")
    try:
        if not git.export_tree(branch, tmp):
            return _blocked(store, cycle, rec, "export_failed")
        if gate is None:
            found = kit.collect(Path(tmp))
            if found.get("wrong_tree"):
                return _reject(store, cycle, rec, "wrong_tree", gate="0/0")  # rojo determinista, no ambiental
            files = found.get("files") if found.get("available") is not False else None
            if not files:
                return _reject(store, cycle, rec, "sandbox_unavailable", gate="0/0")
            gate = tg.new_state(files, committed_tree)
            rec["gate"] = gate
        tg.step(gate, Path(tmp), kit.run_batch)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    store.save(cycle, rec)
    store.ledger_event(
        "evolve.gate",
        {"cycle": cycle, "progress": tg.progress(gate), "verdict": gate["verdict"], "tree": committed_tree},
    )  # C10: gate i/n; DK-1: el ledger es el testigo del veredicto
    if gate["verdict"] == tg.GREEN:
        return None if _gate_witnessed(store, cycle, committed_tree) else _unverified(store, cycle, rec)
    if gate["verdict"] == tg.RED:
        return _reject(store, cycle, rec, "gate_failed", gate_reason=gate.get("reason", ""))
    if gate["verdict"] == tg.UNAVAILABLE:
        return _reject(store, cycle, rec, "sandbox_unavailable", gate=tg.progress(gate))
    return {
        "status": "OK",
        "state": COMMITTED,
        "cycle": cycle,
        "branch": branch,
        "awaiting": "gate",
        "gate": tg.progress(gate),
    }


def _cascade(kit: GateKit | None, git: GitPort, rec: dict[str, Any]) -> str | None:
    """C7: Gaps(G') estrictamente dentro de Gaps(G), sin gaps nuevos ni co-dependencias. Fija `r_after`. None = cumple."""
    if kit is None or kit.summarize is None:
        return "no_summarize"  # fail-closed: sin recomputar R no hay garantia de cascada
    after = kit.summarize(Path(git.work_root()))
    rec["r_after"] = str(after.get("root", ""))
    base, new = set(rec.get("base_gaps", [])), {str(g) for g in after.get("gaps", [])}
    if new - base:
        return tv.NEW_GAPS.lower()  # X1 -> X2: el arreglo introduce un gap que antes no existia
    if after.get("codep"):
        return "codep"
    if not new < base:
        return "no_gap_progress"
    return None


def _merge(store: EvolveStore, git: GitPort, cycle: str, rec: dict[str, Any], branch: str) -> dict[str, Any] | None:
    """Precondiciones C3 (7, 8, 9, 12, 13) antes del ff-merge. `--ff-only` es el arbitro final."""
    if not _gate_witnessed(store, cycle, git.tree_of(branch) or ""):
        return _unverified(store, cycle, rec)  # DK-1: sin testigo green del ledger no hay ff-merge
    if git.current_branch() != DEV_BRANCH:
        return _blocked(store, cycle, rec, "not_on_dev")
    if not git.is_ancestor(DEV_BRANCH, branch):
        return _blocked(store, cycle, rec, "dev_ahead")
    if git.rev_parse(branch) != rec.get("sha"):
        return _blocked(store, cycle, rec, "sha_mismatch")
    dirty = git.dirty_tracked(DEV_BRANCH, branch)
    if dirty:
        return _blocked(store, cycle, rec, f"dirty_tree:{len(dirty)}")
    if not git.remote_reachable():
        return _blocked(store, cycle, rec, "remote_unreachable")
    ok, info = git.merge_ff(branch)
    if not ok:
        return _blocked(store, cycle, rec, info)  # fence_held | ff_rejected
    rec["state"] = MERGED
    rec.pop("blocked", None)
    store.save(cycle, rec)
    store.event("evolve.merged", {"cycle": cycle, "branch": branch, "sha": rec["sha"][:12], "sha_full": rec["sha"]})
    return None


def _plane_ready(live: dict[str, Any]) -> bool:
    loaded = live.get("loaded")
    return not live.get("stale") and bool(loaded) and loaded == live.get("disk") and live.get("serving_from") != "lkg"


def _post_verify(
    store: EvolveStore,
    git: GitPort,
    kit: GateKit | None,
    live_check: LiveCheck,
    cycle: str,
    rec: dict[str, Any],
    branch: str,
) -> dict[str, Any] | None:
    """C6 (condicion 15): el verify post-merge falla tras el ff y antes del push => `git revert` nuevo, sin push."""
    if rec.get("post_verified") or kit is None or kit.post_verify is None:
        return None
    res = kit.post_verify(rec)
    if res.get("ok"):
        if _plane_ready(
            live_check()
        ):  # DK-4: solo se fija con el plano vivo cargado y fuera del LKG; si no, se re-evalua
            rec["post_verified"] = True
            store.save(cycle, rec)
        return None
    why = str(res.get("reason", "post_verify_failed"))
    if git.current_branch() != DEV_BRANCH or git.rev_parse(DEV_BRANCH) != rec.get("sha"):
        return _blocked(store, cycle, rec, "revert_head_moved")  # dev avanzo: no se revierte a ciegas
    ok, info = git.revert(rec["sha"])
    if not ok:
        return _blocked(store, cycle, rec, f"{info}:post_verify")
    rec.update(state=REVERTED, revert_sha=info, post_verify_reason=why[:_REASON_MAX])
    store.save(cycle, rec)
    if store.ledger is not None:
        store.ledger.mark_reverted(cycle)
    store.event(
        "evolve.reverted",
        {"cycle": cycle, "branch": branch, "sha": rec["sha"][:12], "revert": info[:12], "why": why[:_REASON_MAX]},
    )
    return {
        "status": BLOCKED_GIT,
        "reason": "dev_dirty_by_revert",
        "state": REVERTED,
        "cycle": cycle,
        "branch": branch,
        "revert_sha": info[:12],
        "why": why[:_REASON_MAX],
    }


def _push(
    store: EvolveStore, git: GitPort, live_check: LiveCheck, cycle: str, rec: dict[str, Any], branch: str
) -> dict[str, Any] | None:
    if store.ledger is not None and store.ledger.revert_pending():
        return _blocked(store, cycle, rec, "dev_dirty_by_revert")  # un revert sin decision del usuario: dev esta sucio
    live = live_check()
    if live.get("stale") or not live.get("loaded") or live.get("loaded") != live.get("disk"):
        # El plano vivo aun no cargo lo mergeado (hot-swap en curso): se espera, no es un fallo.
        store.save(cycle, rec)
        return {"status": "OK", "state": MERGED, "cycle": cycle, "awaiting": "reload", "stale": bool(live.get("stale"))}
    if not git.remote_reachable():
        return _blocked(store, cycle, rec, "remote_unreachable")
    for ref in (DEV_BRANCH, branch):
        ok, info = git.push(ref)
        if not ok:
            return _blocked(store, cycle, rec, f"{info}:{ref}")  # sin reintento creativo
    rec["state"] = PUSHED
    rec.pop("blocked", None)
    store.save(cycle, rec)
    store.event("evolve.pushed", {"cycle": cycle, "branch": branch, "sha": rec["sha"][:12]})
    return None
