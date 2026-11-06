"""
Engine: threads_verify.py (ONT-41 TA3: compuerta de monotonía y ciclo fix -> test)

`autoevol(verify)` es el juez, no el creador: compara la generación base con el árbol parcheado y devuelve
ACCEPT / REJECT / PENDING con motivos de rechazo tipificados. Garantía (SDD §2.6):

    Gaps(G') ⊊ Gaps(G)  y  SCC_codep(G') = ∅  y  tests verdes  y  presupuestos cumplidos.

Diseño:
  - Núcleo PURO sobre resúmenes (`summarize(analysis)` -> dict serializable): `compare`, `decide`.
  - Efectos inyectados: `run_tests`, `dispatch_job`, `clock`, `sleep`, `read_barrier`. `threads_verify` NO importa
    `server` ni ningún runner (F9: la arista `threads -> server` está prohibida).
  - Los estados de la barrera de recarga son DATOS de entrada (`BarrierState`): los evalúa el llamante (el front/
    servidor), este módulo solo los traduce a motivos.
  - Base (m3): `git archive HEAD` a un tmpdir + `analyze`, o un snapshot, o `BASE_UNAVAILABLE`. Nunca se inventa una base.
  - Ciclo (`CycleStore`): estado en `/dev/shm/aep_autoevol/cycle_<sha256(uid|cycle_id)[:16]>.json` (0700/0600,
    `O_EXCL|O_NOFOLLOW`, `st_uid == euid`), `cycle_id = secrets.token_hex(6)` generado por el servidor y validado por regex,
    máximo 3 iteraciones -> EXHAUSTED y bloqueo de 10 min por (uid, gap) salvo `restart`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine import threads_events as ev

# --- Veredictos y motivos ---------------------------------------------------------------------------------
ACCEPT = "ACCEPT"
REJECT = "REJECT"
PENDING = "PENDING"

NEW_GAPS = "NEW_GAPS"
NO_PROGRESS = "NO_PROGRESS"
CODEP = "CODEP"
TESTS_FAIL = "TESTS_FAIL"
BUDGET = "BUDGET"
NO_DIRECT_COVERAGE = "NO_DIRECT_COVERAGE"
RELOAD_BLOCKED = "RELOAD_BLOCKED"
RELOAD_PENDING = "RELOAD_PENDING"
SERVING_LKG = "SERVING_LKG"
SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
BASE_UNAVAILABLE = "BASE_UNAVAILABLE"
NO_TESTS_EXECUTED = "NO_TESTS_EXECUTED"
ENV_RETRIES_EXHAUSTED = "ENV_RETRIES_EXHAUSTED"

REJECT_REASONS: tuple[str, ...] = (
    BASE_UNAVAILABLE,
    SERVING_LKG,
    RELOAD_BLOCKED,
    RELOAD_PENDING,
    SANDBOX_UNAVAILABLE,
    NEW_GAPS,
    CODEP,
    NO_PROGRESS,
    NO_DIRECT_COVERAGE,
    NO_TESTS_EXECUTED,
    TESTS_FAIL,
    BUDGET,
    ENV_RETRIES_EXHAUSTED,
)

# --- Presupuestos (T0 cerrado) ----------------------------------------------------------------------------
TESTS_PER_ITERATION = 20
SYNC_MAX_SECONDS = 60.0
EST_SECONDS_PER_TEST = 2.5  # spike T0: 42 s para 19 tests dentro de bwrap
MAX_ITERATIONS = 3
MAX_ENV_RETRIES = 10  # rechazos ambientales por ciclo antes de cerrarlo (no consumen iteracion)
LOCK_SECONDS = 600.0
CYCLE_TTL_SECONDS = 3600.0
LIST_CAP = 10
BASE_ARCHIVE_TIMEOUT_S = 30

CYCLE_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_GAP_ID_MAX = 200

# Estados del ciclo
OPEN = "OPEN"
CYCLE_PENDING = "PENDING"
ACCEPTED = "ACCEPTED"
EXHAUSTED = "EXHAUSTED"
EXPIRED = "EXPIRED"
TERMINAL_STATES: frozenset[str] = frozenset({ACCEPTED, EXHAUSTED})

_SUMMARY_TYPES = ("function", "action", "tool", "state", "test")
_HASH_LEN = 12


# ---------------------------------------------------------------------------
# Resumen serializable de una generación (la base se congela en la iteración 0)
# ---------------------------------------------------------------------------


def summarize(analysis: Any) -> dict[str, Any]:
    """Resumen JSON-serializable de un `Analysis`: raíz R, ids de gaps, hashes de contenido, públicas y directas."""
    graph = analysis.graph
    hashes: dict[str, str] = {}
    public: list[str] = []
    direct: list[str] = []
    for ntype in _SUMMARY_TYPES:
        for node in graph.nodes_of(ntype):
            hashes[node.id] = node.content_hash[:_HASH_LEN]
            if ntype != "function":
                continue
            if node.attrs.get("public"):
                public.append(node.id)
            if any(graph.nodes[e.src].type == "test" for e in graph.in_edges(node.id, "covers")):
                direct.append(node.id)
    return {
        "root": analysis.root_hash,
        "gaps": sorted(g.id for g in analysis.gaps),
        "gap_meta": {g.id: [g.ref, g.score] for g in analysis.gaps if g.ref},
        "codep": sorted(c[0] for c in analysis.scc.codependencies if c),
        "hashes": hashes,
        "public": sorted(public),
        "direct": sorted(direct),
    }


def _capped(items: list[str]) -> dict[str, Any]:
    return {"items": items[:LIST_CAP], "total": len(items)}


def compare(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Diferencia entre dos resúmenes: gaps arreglados/nuevos, co-dependencias y funciones cambiadas sin test directo."""
    base_gaps, new_gaps = set(base.get("gaps", [])), set(new.get("gaps", []))
    base_hash: dict[str, str] = base.get("hashes", {})
    new_hash: dict[str, str] = new.get("hashes", {})
    changed = sorted(i for i, h in new_hash.items() if base_hash.get(i) != h)
    public, direct = set(new.get("public", [])), set(new.get("direct", []))
    changed_fns = [i for i in changed if i.startswith("fn:")]
    return {
        "root_base": str(base.get("root", ""))[:16],
        "root_new": str(new.get("root", ""))[:16],
        "gaps_base": len(base_gaps),
        "gaps_new": len(new_gaps),
        "fixed": sorted(base_gaps - new_gaps),
        "introduced": sorted(new_gaps - base_gaps),
        "codep": sorted(new.get("codep", [])),
        "changed": changed,
        "changed_tests": [i for i in changed if i.startswith("test:")],
        "touches_public": any(i in public for i in changed),
        "uncovered_public": sorted(i for i in changed_fns if i in public and i not in direct),
        "uncovered_private": sorted(i for i in changed_fns if i not in public and i not in direct),
    }


# ---------------------------------------------------------------------------
# Barrera de recarga (los estados los evalúa el llamante; aquí solo se traducen)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarrierState:
    """Estado observado del plano vivo tras el parche."""

    generation_advanced: bool = True
    fingerprints_match: bool = True
    reload_error: str = ""
    reload_error_deterministic: bool = True
    serving_lkg: bool = False


def barrier_reasons(state: BarrierState | None) -> list[str]:
    """Motivos de rechazo derivados de la barrera. `None` = sin plano vivo que esperar (análisis puramente estático)."""
    if state is None:
        return []
    reasons: list[str] = []
    if state.serving_lkg:
        reasons.append(SERVING_LKG)  # M-2: prohibido `verify` mientras se sirve desde LKG
    if state.reload_error and state.reload_error_deterministic:
        reasons.append(RELOAD_BLOCKED)  # el fix falló en la importación: no se prueba
    elif state.reload_error or not state.generation_advanced or not state.fingerprints_match:
        reasons.append(RELOAD_PENDING)  # nunca se prueba código viejo
    return reasons


def await_barrier(
    read_barrier: Callable[[], BarrierState],
    *,
    timeout_s: float = 30.0,
    poll_s: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[BarrierState, bool]:
    """Sondea `read_barrier` hasta que no haya motivos pendientes o venza el plazo. Devuelve (estado, agotó_plazo)."""
    deadline = clock() + timeout_s
    state = read_barrier()
    while RELOAD_PENDING in barrier_reasons(state) and clock() < deadline:
        sleep(poll_s)
        state = read_barrier()
    return state, RELOAD_PENDING in barrier_reasons(state)


# ---------------------------------------------------------------------------
# Selección de tests y decisión
# ---------------------------------------------------------------------------


def plan_tests(tests: list[str], *, estimate_s: float | None = None) -> dict[str, Any]:
    """Modo de ejecución: sync hasta N=20 tests y 60 s estimados; por encima, async (PENDING + job)."""
    ordered = sorted(set(tests))
    est = float(estimate_s) if estimate_s is not None else len(ordered) * EST_SECONDS_PER_TEST
    mode = "async" if len(ordered) > TESTS_PER_ITERATION or est > SYNC_MAX_SECONDS else "sync"
    return {"mode": mode, "tests": ordered, "estimate_s": round(est, 1)}


def _tests_reasons(
    tests: dict[str, Any] | None, *, trusted: bool, selected: int | None = None
) -> tuple[list[str], bool]:
    """(motivos, pendiente). `tests` es el resultado del runner inyectado; `selected` = tests que debian correr."""
    if tests is None:
        return [], False
    if str(tests.get("status", "")).upper() == PENDING:
        return [], True
    if tests.get("available") is False or (tests.get("unsandboxed") and not trusted):
        return [SANDBOX_UNAVAILABLE], False
    failed = int(tests.get("failed", 0) or 0) + int(tests.get("errors", 0) or 0)
    if tests.get("timeout") or failed > 0:
        return [TESTS_FAIL], False
    ran = int(tests.get("ran", 0) or 0)
    exit_code = tests.get("exit_code")
    # F5: verde = pytest salio 0 y corrio al menos todo lo seleccionado; 0 tests ejecutados nunca es verde.
    if (exit_code not in (None, 0)) or (selected and ran < selected):
        return [TESTS_FAIL], False
    return [], False


def _budget_over(budgets: list[dict[str, Any]] | None) -> list[str]:
    return sorted(
        str(b.get("id", "?")) for b in (budgets or []) if float(b.get("observed", 0)) > float(b.get("limit", 0))
    )


def decide(
    cmp: dict[str, Any] | None,
    *,
    target_gap: str | None = None,
    tests: dict[str, Any] | None = None,
    budgets: list[dict[str, Any]] | None = None,
    barrier: BarrierState | None = None,
    base_available: bool = True,
    sandbox_available: bool = True,
    trusted: bool = True,
    selected: int | None = None,
    no_tests: bool = False,
) -> dict[str, Any]:
    """Veredicto. Acumula TODOS los motivos aplicables, en el orden fijo de `REJECT_REASONS`."""
    reasons: list[str] = []
    detail: dict[str, Any] = {}
    warnings: list[str] = []
    if not base_available or cmp is None:
        reasons.append(BASE_UNAVAILABLE)
    reasons.extend(barrier_reasons(barrier))
    if not sandbox_available:
        reasons.append(SANDBOX_UNAVAILABLE)
    pending = False
    if cmp is not None:
        if cmp["introduced"]:
            reasons.append(NEW_GAPS)
            detail["introduced"] = _capped(cmp["introduced"])
        if cmp["codep"]:
            reasons.append(CODEP)
            detail["codep"] = _capped(cmp["codep"])
        progressed = (target_gap in cmp["fixed"]) if target_gap else bool(cmp["fixed"])
        if not progressed:
            reasons.append(NO_PROGRESS)
        if cmp["uncovered_public"]:
            reasons.append(NO_DIRECT_COVERAGE)
            detail["uncovered_public"] = _capped(cmp["uncovered_public"])
        if cmp["uncovered_private"]:
            warnings.append(f"private changed without direct test: {len(cmp['uncovered_private'])}")
    test_reasons, pending = _tests_reasons(tests, trusted=trusted, selected=selected)
    reasons.extend(test_reasons)
    if tests is not None and tests.get("unsandboxed") and trusted:
        warnings.append("unsandboxed")
    if no_tests:
        reasons.append(NO_TESTS_EXECUTED)
    over = _budget_over(budgets)
    if over:
        reasons.append(BUDGET)
        detail["budget_over"] = over[:LIST_CAP]
    ordered = [r for r in REJECT_REASONS if r in set(reasons)]
    if ordered:
        verdict = REJECT
    elif pending:
        verdict = PENDING
    else:
        verdict = ACCEPT
    if verdict == ACCEPT and tests is None:
        warnings.append("no tests executed")
    out: dict[str, Any] = {"verdict": verdict, "reasons": ordered}
    if cmp is not None:
        out["fixed"] = len(cmp["fixed"])
        out["gaps"] = [cmp["gaps_base"], cmp["gaps_new"]]
    if detail:
        out["detail"] = detail
    if warnings:
        out["warnings"] = warnings
    return out


def verify_change(
    base: dict[str, Any] | None,
    new: dict[str, Any],
    *,
    impacted_tests: list[str],
    target_gap: str | None = None,
    run_tests: Callable[[list[str]], dict[str, Any]] | None = None,
    dispatch_job: Callable[[list[str]], dict[str, Any]] | None = None,
    barrier: BarrierState | None = None,
    budgets: list[dict[str, Any]] | None = None,
    estimate_s: float | None = None,
    trusted: bool = True,
) -> dict[str, Any]:
    """Una iteración completa: barrera -> comparación estática -> (solo si es limpia) tests -> veredicto.

    Si la estática o la barrera ya rechazan, los tests NO se ejecutan (nunca se prueba código que no puede aceptarse).
    """
    if base is None:
        return decide(None, barrier=barrier, base_available=False)
    cmp = compare(base, new)
    static = decide(cmp, target_gap=target_gap, barrier=barrier, budgets=budgets, trusted=trusted)
    if static["verdict"] == REJECT:
        static["tests"] = {"selected": 0}
        return static
    if not impacted_tests:
        static["tests"] = {"selected": 0}
        # F1: un parche que toca tests/ o un nodo publico sin ningun test ejecutado no puede aceptarse.
        if cmp["changed_tests"] or cmp["touches_public"]:
            return decide(cmp, target_gap=target_gap, barrier=barrier, budgets=budgets, trusted=trusted, no_tests=True) | {
                "tests": {"selected": 0}
            }
        return static
    plan = plan_tests(impacted_tests, estimate_s=estimate_s)
    runner = dispatch_job if plan["mode"] == "async" else run_tests
    if runner is None:
        return decide(
            cmp, target_gap=target_gap, barrier=barrier, budgets=budgets, sandbox_available=False, trusted=trusted
        )
    result = runner(plan["tests"])
    if plan["mode"] == "async" and result.get("available") is not False:
        result = {**result, "status": PENDING}
    out = decide(
        cmp,
        target_gap=target_gap,
        tests=result,
        barrier=barrier,
        budgets=budgets,
        trusted=trusted,
        selected=len(plan["tests"]),
    )
    out["tests"] = {"mode": plan["mode"], "selected": len(plan["tests"]), "estimate_s": plan["estimate_s"]}
    if plan["mode"] == "async":
        out["job"] = result.get("job")
    return out


# ---------------------------------------------------------------------------
# Base: git archive HEAD a un tmpdir + analyze, o un snapshot, o BASE_UNAVAILABLE
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def base_tree(
    repo_root: Path | str, *, snapshot: Path | str | None = None, git_bin: str = "git"
) -> Iterator[Path | None]:
    """Directorio con la base. `snapshot` si se pasa; si no, `git archive HEAD` a un tmpdir limpiado siempre.

    Devuelve None (-> `BASE_UNAVAILABLE`) cuando no hay git, no hay HEAD o el archivo es inseguro. No se inventa base.
    """
    if snapshot is not None:
        snap = Path(snapshot)
        yield snap if snap.is_dir() else None
        return
    tmp = Path(tempfile.mkdtemp(prefix="aep_autoevol_base_"))
    try:
        yield _extract_head(Path(repo_root), tmp, git_bin)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _extract_head(repo_root: Path, tmp: Path, git_bin: str) -> Path | None:
    archive = tmp / "base.tar"
    try:
        res = subprocess.run(
            [git_bin, "-C", str(repo_root), "archive", "--format=tar", "-o", str(archive), "HEAD"],
            capture_output=True,
            timeout=BASE_ARCHIVE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0 or not archive.is_file():
        return None
    dest = tmp / "tree"
    dest.mkdir()
    try:
        safe_extract(archive, dest)
    except (tarfile.TarError, OSError, ValueError):
        return None
    return dest


def safe_extract(archive: Path, dest: Path) -> int:
    """Extrae miembro a miembro tras validarlo. Devuelve cuántos se extrajeron.

    Rutas absolutas, `..` o que escapen de `dest` abortan con ValueError. Enlaces simbólicos/duros y dispositivos
    NO se extraen (se omiten): el análisis estático no los necesita y no pueden usarse para escapar.
    """
    root = dest.resolve()
    count = 0
    with tarfile.open(archive) as tf:
        for member in tf:
            name = member.name
            if os.path.isabs(name) or ".." in Path(name).parts:
                raise ValueError(f"unsafe member path: {name!r}")
            target = (root / name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"member escapes destination: {name!r}")
            if not (member.isfile() or member.isdir()):
                continue
            tf.extract(member, root, filter="data")  # nosemgrep: tarfile-extractall-traversal  # miembro ya validado arriba
            count += 1
    return count


# ---------------------------------------------------------------------------
# Ciclo fix -> test: máquina de estados + almacén seguro
# ---------------------------------------------------------------------------


def new_cycle_id() -> str:
    """`cycle_id` generado por el servidor (nunca por el cliente)."""
    return secrets.token_hex(6)


def valid_cycle_id(cycle_id: Any) -> bool:
    return isinstance(cycle_id, str) and bool(CYCLE_ID_RE.fullmatch(cycle_id))


def cycle_file_name(uid: int, cycle_id: str) -> str:
    """`cycle_<sha256(uid|cycle_id)[:16]>.json`. Valida el id por regex antes de tocar el sistema de archivos."""
    if not valid_cycle_id(cycle_id):
        raise ValueError("invalid cycle_id")
    return "cycle_" + hashlib.sha256(f"{uid}|{cycle_id}".encode()).hexdigest()[:16] + ".json"


def lock_file_name(uid: int, gap: str) -> str:
    return "lock_" + hashlib.sha256(f"{uid}|{gap}".encode()).hexdigest()[:16] + ".json"


def next_state(state: str, verdict: str, iteration: int, *, max_iterations: int = MAX_ITERATIONS) -> tuple[str, int]:
    """Transición pura. ACCEPT cierra; PENDING no consume iteración; el REJECT número `max` agota el ciclo."""
    if state in TERMINAL_STATES:
        raise ValueError(f"cycle already closed: {state}")
    if verdict == ACCEPT:
        return ACCEPTED, iteration + 1
    if verdict == PENDING:
        return CYCLE_PENDING, iteration
    nxt = iteration + 1
    return (EXHAUSTED if nxt >= max_iterations else OPEN), nxt


class CycleStore:
    """Estado del ciclo en un directorio privado. Reloj, uid y directorio inyectables (tests)."""

    _GUARD = threading.Lock()

    def __init__(
        self,
        *,
        base_dir: Path | str | None = None,
        clock: Callable[[], float] = time.time,
        uid: int | None = None,
    ) -> None:
        self._dir = base_dir
        self._clock = clock
        self._uid = os.geteuid() if uid is None else int(uid)

    def _read_json(self, dfd: int, name: str) -> dict[str, Any] | None:
        raw = ev.read_file(dfd, name)
        if raw is None:
            return None
        try:
            obj = json.loads(raw)
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None

    def _put(self, dfd: int, name: str, obj: dict[str, Any]) -> None:
        ev.write_file_atomic(dfd, name, json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def open_cycle(self, gap: str, base: dict[str, Any], *, restart: bool = False) -> dict[str, Any]:
        """Abre un ciclo para `gap` con la base congelada. Rechaza durante el bloqueo de 10 min salvo `restart`."""
        if not gap or len(gap) > _GAP_ID_MAX:
            return {"status": "INVALID_GAP"}
        now = self._clock()
        with self._GUARD, ev.state_dir(self._dir) as dfd:
            lock_name = lock_file_name(self._uid, gap)
            if restart:
                ev.remove_file(dfd, lock_name)
            else:
                lock = self._read_json(dfd, lock_name)
                if lock and float(lock.get("until", 0)) > now:
                    return {"status": "LOCKED", "retry_after_s": round(float(lock["until"]) - now, 1)}
            for _ in range(8):
                cycle_id = new_cycle_id()
                record = {
                    "v": 1,
                    "cycle_id": cycle_id,
                    "uid": self._uid,
                    "gap": gap,
                    "state": OPEN,
                    "iteration": 0,
                    "max_iterations": MAX_ITERATIONS,
                    "created": now,
                    "updated": now,
                    "base": base,
                    "history": [],
                    "job": None,
                }
                blob = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if ev.create_file_exclusive(dfd, cycle_file_name(self._uid, cycle_id), blob):
                    return {"status": "OK", "cycle_id": cycle_id, "state": OPEN, "iteration": 0}
        return {"status": "ERROR", "error": "cycle id collision"}

    def load(self, cycle_id: str) -> dict[str, Any] | None:
        """Ciclo vigente o None. Un ciclo vencido (TTL 1 h) se borra y devuelve `{"state": "EXPIRED"}`."""
        if not valid_cycle_id(cycle_id):
            return None
        name = cycle_file_name(self._uid, cycle_id)
        with self._GUARD, ev.state_dir(self._dir) as dfd:
            rec = self._read_json(dfd, name)
            if rec is None:
                return None
            if self._clock() - float(rec.get("updated", 0)) > CYCLE_TTL_SECONDS:
                ev.remove_file(dfd, name)
                return {"cycle_id": cycle_id, "state": EXPIRED}
            return rec

    def note_environmental(self, cycle_id: str, reasons: list[str]) -> dict[str, Any]:
        """Cuenta un rechazo ambiental (no consume iteracion). Al pasar de MAX_ENV_RETRIES cierra el ciclo (EXHAUSTED)."""
        rec = self.load(cycle_id)
        if rec is None or rec.get("state") in (EXPIRED, *TERMINAL_STATES):
            return {"count": 0, "exhausted": False}
        count = int(rec.get("env_retries", 0)) + 1
        rec["env_retries"] = count  # `updated` no se refresca: el TTL de 1 h sigue acotando el ciclo
        exhausted = count > MAX_ENV_RETRIES
        if exhausted:
            rec["state"] = EXHAUSTED
            rec["history"].append(
                {"it": rec["iteration"], "verdict": REJECT, "reasons": [ENV_RETRIES_EXHAUSTED, *reasons][:LIST_CAP], "ts": self._clock()}
            )
        with self._GUARD, ev.state_dir(self._dir) as dfd:
            self._put(dfd, cycle_file_name(self._uid, cycle_id), rec)
        if exhausted:
            ev.append_event(
                "cycle_terminal",
                {
                    "cycle_id": cycle_id,
                    "gap": rec["gap"],
                    "state": EXHAUSTED,
                    "iterations": rec["iteration"],
                    "reasons": [ENV_RETRIES_EXHAUSTED],
                },
                base_dir=self._dir,
                clock=self._clock,
            )
        return {"count": count, "exhausted": exhausted}

    def record(self, cycle_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        """Aplica un veredicto de `decide`/`verify_change`. EXHAUSTED/ACCEPTED son terminales y se anotan en el JSONL."""
        if not valid_cycle_id(cycle_id):
            return {"status": "INVALID_CYCLE"}
        rec = self.load(cycle_id)
        if rec is None:
            return {"status": "NOT_FOUND"}
        if rec["state"] == EXPIRED:
            return {"status": EXPIRED}
        if rec["state"] in TERMINAL_STATES:
            return {"status": "CLOSED", "state": rec["state"]}
        verdict = str(decision.get("verdict", REJECT))
        now = self._clock()
        state, iteration = next_state(rec["state"], verdict, rec["iteration"], max_iterations=rec["max_iterations"])
        rec["history"].append(
            {"it": iteration, "verdict": verdict, "reasons": list(decision.get("reasons", []))[:LIST_CAP], "ts": now}
        )
        rec.update(state=state, iteration=iteration, updated=now, job=decision.get("job") if verdict == PENDING else None)
        name = cycle_file_name(self._uid, cycle_id)
        with self._GUARD, ev.state_dir(self._dir) as dfd:
            self._put(dfd, name, rec)
            if state == EXHAUSTED:
                self._put(dfd, lock_file_name(self._uid, rec["gap"]), {"until": now + LOCK_SECONDS, "cycle_id": cycle_id})
        if state in TERMINAL_STATES:
            ev.append_event(
                "cycle_terminal",
                {
                    "cycle_id": cycle_id,
                    "gap": rec["gap"],
                    "state": state,
                    "iterations": iteration,
                    "reasons": list(decision.get("reasons", []))[:LIST_CAP],
                },
                base_dir=self._dir,
                clock=self._clock,
            )
        out = {"status": "OK", "cycle_id": cycle_id, "state": state, "iteration": iteration}
        if state == EXHAUSTED:
            out["retry_after_s"] = LOCK_SECONDS
        return out
