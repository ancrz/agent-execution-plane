"""
Engine: threads_gate.py (ONT-42c C4: gate final de `evolve`, condicion Ontos 10)

Suite COMPLETA sobre el arbol COMMITEADO de `autoevol/<ciclo>` (exportado a un directorio temporal, no el worktree
editable), en lotes re-entrantes: cada llamada de `evolve` ejecuta UN lote (<= 100 s) y persiste el progreso `gate i/n`.
Mientras queden lotes la respuesta lleva `awaiting: "gate"`.

Veredicto del gate (rojo = sin merge):
  - fallos/errores, `exit_code != 0`, `ran < selected` o `unsandboxed` presente        -> rojo (persistente);
  - centinela WRONG_TREE (el interprete no resuelve `engine` bajo el arbol exportado)  -> rojo (determinista);
  - timeout de un lote de varios archivos                                              -> el lote se parte en dos;
  - timeout de un lote de un archivo                                                   -> rojo;
  - sandbox no disponible (bwrap/interprete caido)                                     -> `unavailable`: no rojo, reintentable.
El gate nunca se ejecuta sin sandbox: el ejecutor inyectado lo hace con `trusted=False` (sin caida a pytest plano).

Modulo puro: no importa `server`, `threads_evolve` ni git. Los ejecutores (`collect`, `run_batch`) son inyectados.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

BATCH_TESTS = 120  # tests por lote al planificar (~25 s medidos); el timeout parte lotes lentos
BATCH_TIMEOUT_S = 100
GREEN = "green"
RED = "red"
RUNNING = "running"
UNAVAILABLE = "unavailable"

# collect(tree) -> {"files": {"tests/test_x.py": n_tests, ...}} | {"available": False}
Collect = Callable[[Any], dict[str, Any]]
# run_batch(tree, files) -> conteos de pytest (ran/failed/errors/exit_code/...) | {"available": False} | {"wrong_tree": True}
RunBatch = Callable[[Any, list[str]], dict[str, Any]]


def plan_batches(files: dict[str, int], *, batch_tests: int = BATCH_TESTS) -> list[dict[str, Any]]:
    """Agrupa archivos de test en lotes de ~`batch_tests` tests (un archivo grande es su propio lote). Determinista."""
    batches: list[dict[str, Any]] = []
    cur: dict[str, Any] = {"files": [], "selected": 0, "counts": {}}
    for name in sorted(files):
        count = int(files[name])
        if cur["files"] and cur["selected"] + count > batch_tests:
            batches.append(cur)
            cur = {"files": [], "selected": 0, "counts": {}}
        cur["files"].append(name)
        cur["counts"][name] = count
        cur["selected"] += count
    if cur["files"]:
        batches.append(cur)
    return batches


def new_state(files: dict[str, int], tree_sha: str) -> dict[str, Any]:
    batches = plan_batches(files)
    return {
        "verdict": RUNNING,
        "tree": tree_sha,
        "pending": batches,
        "total": len(batches),
        "done": 0,
        "ran": 0,
        "selected": sum(b["selected"] for b in batches),
    }


def progress(state: dict[str, Any]) -> str:
    return f"{state['done']}/{state['total']}"


def step(state: dict[str, Any], tree: Any, run_batch: RunBatch) -> dict[str, Any]:
    """Ejecuta el siguiente lote y devuelve el estado actualizado (misma estructura, mutada)."""
    if state["verdict"] == UNAVAILABLE:  # entorno caido: se reintenta en la siguiente llamada
        state["verdict"] = RUNNING
    if state["verdict"] != RUNNING:
        return state
    if not state["pending"]:
        return _finish(state)
    batch = state["pending"][0]
    res = run_batch(tree, list(batch["files"]))
    if res.get("wrong_tree"):
        return _red(state, "wrong_tree")
    if res.get("available") is False:
        state["verdict"] = UNAVAILABLE
        state["reason"] = "sandbox_unavailable"
        return state
    if res.get("unsandboxed"):
        return _red(state, "unsandboxed")
    if res.get("timeout"):
        if len(batch["files"]) > 1:
            half = len(batch["files"]) // 2
            first, second = batch["files"][:half], batch["files"][half:]
            state["pending"][0:1] = [_sub(batch, first), _sub(batch, second)]
            state["total"] += 1
            state["verdict"] = RUNNING
            return state
        return _red(state, "batch_timeout")
    failed = int(res.get("failed", 0) or 0) + int(res.get("errors", 0) or 0)
    ran = int(res.get("ran", 0) or 0)
    if failed > 0 or res.get("exit_code") not in (None, 0) or ran < int(batch["selected"]):
        return _red(state, "tests_fail" if failed or res.get("exit_code") not in (None, 0) else "ran_lt_selected")
    state["ran"] += ran
    state["done"] += 1
    state["pending"].pop(0)
    state["verdict"] = RUNNING
    state.pop("reason", None)
    return _finish(state) if not state["pending"] else state


def _finish(state: dict[str, Any]) -> dict[str, Any]:
    if state["selected"] > 0 and state["ran"] >= state["selected"]:
        state["verdict"] = GREEN
    else:
        _red(state, "ran_lt_selected")
    return state


def _sub(batch: dict[str, Any], names: list[str]) -> dict[str, Any]:
    counts = {n: batch["counts"][n] for n in names}
    return {"files": names, "counts": counts, "selected": sum(counts.values())}


def _red(state: dict[str, Any], reason: str) -> dict[str, Any]:
    state["verdict"] = RED
    state["reason"] = reason
    return state
