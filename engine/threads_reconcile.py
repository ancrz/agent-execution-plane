"""
Engine: threads_reconcile.py (E4: autohealing, reconciliacion acotada por tier al estilo controlador de Kubernetes)

Compara lo DESEADO (claims y presupuestos ya extraidos como nodos del grafo, specs cacheadas E2) con lo
OBSERVADO (gaps `claim_drift` / `probe_drift` / `open_discrepancy` / omisiones y el estado del plano vivo
inyectado: `serving_from`, `stale`) y produce PROPUESTAS deterministas
`{gap, kind, action: heal|spec|evolve|report, reason, tier_required}`.

Politica por tier (resuelta en cada llamada, nunca cacheada; `policy`):
  - 7rwx: ejecuta solo lo seguro por diseno: `heal` en dry-run (nunca apply) y abrir/continuar un ciclo
    fix_test + `evolve` con apply=False (plan). Sin commits, merges ni pushes: eso exige una llamada explicita
    de `evolve` con apply y su ciclo completo (gate, testigos del ledger).
  - 6rw-: igual, pero sin heal; abre/continua ciclos en plan. Sin escrituras git.
  - 5r-x y 4r--: solo informa. NO toca ledger, DB ni disco (el ledger ni se consulta).

Limites: por defecto reconcile solo PROPONE y continua ciclos ya vivos; ABRIR ciclos exige opt-in explicito
(`open_cycles=True` o env `AEP_RECONCILE_OPEN=1`). Presupuesto propio `AEP_RECONCILE_MAX_OPENS` (defecto 1 por
ventana de 24 h) que cuenta solo eventos `reconcile.opened`; como maximo UN ciclo nuevo por llamada. Idempotente: misma entrada = mismas
propuestas; un gap con ciclo vivo abierto por reconcile se continua, no se duplica. Eventos `reconcile.*` en el
ledger solo con tier >= 6rw-. Sin bucles ni timers: se dispara bajo demanda.

Topos: depende de `engine.threads` (sort_gaps); todos los efectos llegan inyectados; nunca importa `server`,
`aep_front` ni un puerto git.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from typing import Any

from engine import threads

MAX_PROPOSALS = 10
REASON_MAX = 80
TOP_MAX = 80
MIN_CYCLES_OCTAL = 6
HEAL_OCTAL = 7
READ_TIER = 4
DRIFT_KINDS = frozenset({"claim_drift", "probe_drift"})
LIVE_CYCLE_STATES = frozenset({"OPEN", "PENDING", "ACCEPTED"})
DEFAULT_MAX_OPENS = 1
ENV_OPEN = "AEP_RECONCILE_OPEN"
ENV_MAX_OPENS = "AEP_RECONCILE_MAX_OPENS"
EV_RUN = "reconcile.run"
EV_OPENED = "reconcile.opened"
EV_CAPPED = "reconcile.capped"
HEAL, SPEC, EVOLVE, REPORT = "heal", "spec", "evolve", "report"


def policy(octal: int) -> dict[str, Any]:
    """Politica del tier, recalculada en cada llamada."""
    if octal >= HEAL_OCTAL:
        return {"mode": "plan+heal_dry_run", "writes": True, "heal": True, "cycles": True}
    if octal >= MIN_CYCLES_OCTAL:
        return {"mode": "plan", "writes": True, "heal": False, "cycles": True}
    return {"mode": "report", "writes": False, "heal": False, "cycles": False}


def open_opted_in(explicit: bool = False) -> bool:
    """Opt-in para abrir ciclos: argumento explicito o `AEP_RECONCILE_OPEN=1`."""
    return bool(explicit) or os.environ.get(ENV_OPEN, "").strip() == "1"


def max_opens() -> int:
    """`AEP_RECONCILE_MAX_OPENS`: entero >= 1; ausente o invalido => 1."""
    try:
        value = int(os.environ.get(ENV_MAX_OPENS, ""))
    except ValueError:
        return DEFAULT_MAX_OPENS
    return value if value >= 1 else DEFAULT_MAX_OPENS


def _prop(gap: str, kind: str, action: str, reason: str, tier: int) -> dict[str, Any]:
    return {"gap": gap, "kind": kind, "action": action, "reason": reason[:REASON_MAX], "tier_required": tier}


def _plane_proposals(plane: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if plane.get("serving_from") == "lkg" or plane.get("reload_error"):
        out.append(_prop("plane:serving_lkg", "plane_degraded", HEAL, "plane serves LKG or reload failed: heal dry-run", READ_TIER))
    if plane.get("front_stale"):
        out.append(_prop("plane:front_stale", "front_stale", REPORT, "front stale: aep_ctl ipc harness_reconnect plan", READ_TIER))
    elif plane.get("stale") and plane.get("serving_from") != "lkg":
        out.append(_prop("plane:code_stale", "code_stale", REPORT, "loaded code != disk: reload or hot-swap", READ_TIER))
    return out


def _gap_proposal(gap: Any, cached: set[str]) -> dict[str, Any]:
    if gap.kind == "open_discrepancy":
        return _prop(gap.id, gap.kind, REPORT, f"known open discrepancy {gap.ref}: human decision", READ_TIER)
    if gap.id not in cached:
        return _prop(gap.id, gap.kind, SPEC, "no cached spec: autoevol(spec) first", READ_TIER)
    return _prop(gap.id, gap.kind, EVOLVE, "spec cached: open or continue fix_test/evolve plan", MIN_CYCLES_OCTAL)


def propose(
    gaps: list[Any],
    *,
    plane: dict[str, Any] | None = None,
    cached_specs: set[str] | frozenset[str] = frozenset(),
    include_omissions: bool = True,
) -> list[dict[str, Any]]:
    """Propuestas deterministas y ordenadas: primero el plano, luego los gaps por clase de prioridad y score."""
    out = _plane_proposals(plane or {})
    cached = set(cached_specs)
    for gap in threads.sort_gaps(list(gaps)):
        if gap.kind not in DRIFT_KINDS and gap.kind != "open_discrepancy" and not include_omissions:
            continue
        out.append(_gap_proposal(gap, cached))
    return out[:MAX_PROPOSALS]


def top(proposals: list[dict[str, Any]]) -> str | None:
    """Una sola propuesta, compacta, para `discover(capabilities, terse)`. None si no hay."""
    if not proposals:
        return None
    first = proposals[0]
    return f"{first['action']}:{first['gap']}"[:TOP_MAX]


def digest(proposals: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(proposals, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _handle_cycles(
    proposals: list[dict[str, Any]],
    ledger: Any,
    open_cycle: Callable[[str], dict[str, Any]],
    cycle_state: Callable[[str], str | None],
    evolve_plan: Callable[..., dict[str, Any]],
    *,
    may_open: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    opened = ledger.recent(EV_OPENED)
    by_gap = {str(e["data"].get("gap")): str(e["cycle"]) for e in opened}
    cap = {"used": len(opened), "max": max_opens()}
    executed: list[dict[str, Any]] = []
    new_opened = 0
    for prop in (p for p in proposals if p["action"] == EVOLVE):
        gap = prop["gap"]
        cycle = by_gap.get(gap)
        if cycle is not None and cycle_state(cycle) in LIVE_CYCLE_STATES:
            plan = evolve_plan(gap=gap, cycle=cycle, apply=False)
            executed.append(
                {"gap": gap, "action": EVOLVE, "cycle": cycle, "continued": True, "state": plan.get("state"), "applied": False}
            )
            continue
        if not may_open or new_opened >= 1:
            continue  # como maximo un ciclo nuevo por llamada
        if cap["used"] >= cap["max"]:
            executed.append({"gap": gap, "action": EVOLVE, "capped": True, **cap})
            ledger.event(EV_CAPPED, "reconcile", {"gap": gap, **cap})
            continue
        res = open_cycle(gap)
        if res.get("status") != "OK" or not res.get("cycle"):
            executed.append({"gap": gap, "action": EVOLVE, "status": res.get("status", "ERROR"), "applied": False})
            continue
        new_cycle = str(res["cycle"])
        ledger.event(EV_OPENED, new_cycle, {"gap": gap})
        new_opened += 1
        cap["used"] += 1
        plan = evolve_plan(gap=gap, cycle=new_cycle, apply=False)
        executed.append(
            {"gap": gap, "action": EVOLVE, "cycle": new_cycle, "opened": True, "state": plan.get("state"), "applied": False}
        )
    return executed, cap


def reconcile(
    gaps: list[Any],
    *,
    plane: dict[str, Any] | None,
    cached_specs: set[str] | frozenset[str],
    octal: int,
    ledger: Any | None = None,
    open_cycle: Callable[[str], dict[str, Any]] | None = None,
    cycle_state: Callable[[str], str | None] | None = None,
    evolve_plan: Callable[..., dict[str, Any]] | None = None,
    heal_dry_run: Callable[[], dict[str, Any]] | None = None,
    open_cycles: bool = False,
) -> dict[str, Any]:
    """Un paso del controlador. Con tier < 6rw- no se usa ningun efecto inyectado (ni el ledger)."""
    pol = policy(octal)
    proposals = propose(gaps, plane=plane, cached_specs=cached_specs)
    out: dict[str, Any] = {"status": "OK", "mode": pol["mode"], "proposals": proposals, "executed": [], "applied": False}
    if not pol["writes"] or ledger is None:
        return out
    executed: list[dict[str, Any]] = []
    if pol["heal"] and heal_dry_run is not None and any(p["action"] == HEAL for p in proposals):
        report = heal_dry_run()  # el cableado del servidor fija apply=False; aqui no existe parametro apply
        executed.append(
            {"action": HEAL, "dry_run": True, "status": report.get("status"), "total_threads": report.get("total_threads", 0)}
        )
    if pol["cycles"] and open_cycle and cycle_state and evolve_plan:
        cyc, cap = _handle_cycles(
            proposals, ledger, open_cycle, cycle_state, evolve_plan, may_open=open_opted_in(open_cycles)
        )
        executed.extend(cyc)
        out["cap"] = cap
    out["executed"] = executed
    dig = digest(proposals)
    last = ledger.recent(EV_RUN, window=False)
    if not last or last[-1]["data"].get("digest") != dig:  # idempotente: sin eventos duplicados si nada cambio
        ledger.event(EV_RUN, "reconcile", {"digest": dig, "proposals": len(proposals), "executed": len(executed)})
    return out
