"""
Engine: notices.py (ONT-66: AEP "ruidoso" — lo que detecta, lo anuncia)

Fuente unica de "cosas que notificar al agente de turno": gaps del analisis en cache (TODOS los tipos, omisiones
incluidas) y senales del plano vivo. Cada aviso tiene id estable, severidad (INFO/WARN/ERROR), resumen <= 120 B y
`next_action` concreto. El registro lleva el estado por sesion de servidor (new -> seen -> acked); un aviso resuelto
desaparece solo cuando el analisis ya no lo ve, y uno nuevo tras un ack vuelve a aparecer.

Tambien aloja el analisis caliente (`start_hot_analysis`): un hilo daemon que puebla la cache de `engine.threads`
tras cada carga del backend, fuera del camino critico y fail-soft.

Garantias: solo lectura (nunca abre la BD ni escribe en disco); el bloque `aep_notice` <= 350 B; los resumenes pasan
por `sanitize` (secretos enmascarados, rutas vetadas sustituidas). Sin avisos no se emite nada (`block` -> None), asi
que las respuestas quedan byte-identicas a las previas a ONT-66.

Topos: depende de `engine.security` (mask_secrets) y, perezosamente, de `engine.privilege` y `engine.threads`;
nunca importa `server`, `aep_front` ni `aep_backend`.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("aep.notices")

BLOCK_MAX_BYTES = 350
SUMMARY_MAX = 120
LABEL_MAX = 44
TOP_MAX = 3
NEW, SEEN, ACKED = "new", "seen", "acked"
INFO, WARN, ERROR = "INFO", "WARN", "ERROR"
_RANK = {INFO: 0, WARN: 1, ERROR: 2}
ACK_HINT = "autoevol(action='ack', all=True)"
ASK_TEMPLATE = "AEP reporta: {items}. ¿Quieres mejorarlo?"
# Respuestas que ya tratan de los avisos (o del gap) y no duplican el bloque.
QUIET_ACTIONS = frozenset({("autoevol", "ack"), ("autoevol", "notices"), ("autoevol", "gaps"), ("autoevol", "spec")})

_SECRET_DIRS = ("/.ssh", "/.gnupg", "/.aws", "/.kube")  # credenciales de cualquier usuario, no solo el actual
_PATH_RE = re.compile(r"(?<![\w.])/[^\s,;:'\"()\[\]]+")
_DRIFT_RE = re.compile(r"^(\w+): declared (.+?), observed (.+?) \((.+?):\d+\)$")


@dataclass(frozen=True)
class Notice:
    id: str
    severity: str
    summary: str
    label: str
    next_action: str


def _clip(text: str, limit: int) -> str:
    """Recorta a `limit` BYTES utf-8 sin partir un caracter."""
    raw = " ".join(str(text).split())
    data = raw.encode("utf-8")
    if len(data) <= limit:
        return raw
    return data[: max(limit - 3, 0)].decode("utf-8", errors="ignore").rstrip() + "..."


def sanitize(text: str) -> str:
    """Enmascara secretos y sustituye rutas vetadas por `<path>`: un aviso nunca debe filtrar ni apuntar a lo protegido."""
    from engine.primitives_orient import _is_vetoed
    from engine.security import mask_secrets

    masked = mask_secrets(str(text))

    def _sub(m: re.Match[str]) -> str:
        path = m.group(0)
        return "<path>" if _is_vetoed(path) or any(seg in path for seg in _SECRET_DIRS) else path

    return _PATH_RE.sub(_sub, masked)


def gap_severity(gap: Any) -> str:
    """Severidad del aviso a partir de la del gap (0..1): >= 0.9 ERROR, >= 0.5 WARN, resto INFO."""
    sev = float(getattr(gap, "severity", 0.0) or 0.0)
    if sev >= 0.9:
        return ERROR
    return WARN if sev >= 0.5 else INFO


def _gap_label(gap: Any) -> str:
    detail = str(getattr(gap, "detail", ""))
    m = _DRIFT_RE.match(detail)
    if getattr(gap, "kind", "") == "claim_drift" and m:
        kind, declared, observed, where = m.groups()
        return _clip(f"claim_drift {where.rsplit('/', 1)[-1]} {kind} {declared}≠{observed}", LABEL_MAX)
    return _clip(f"{gap.kind} {str(gap.node).split(':', 1)[-1]}", LABEL_MAX)


def from_gaps(gaps: Iterable[Any]) -> list[Notice]:
    """Un aviso por gap (todos los tipos), ids estables = id del gap, orden de entrada (ya rankeado por score)."""
    out: list[Notice] = []
    for gap in gaps:
        summary = sanitize(f"{gap.kind} {gap.detail}")
        out.append(
            Notice(
                id=str(gap.id),
                severity=gap_severity(gap),
                summary=_clip(summary, SUMMARY_MAX),
                label=sanitize(_gap_label(gap)),
                next_action=f"autoevol(action='spec', gap='{gap.id}')",
            )
        )
    return out


def from_plane(plane: dict[str, Any], *, reconnect: str = "") -> list[Notice]:
    """Avisos del plano vivo: front viejo, codigo cargado != disco, error de recarga y servicio desde LKG."""
    out: list[Notice] = []
    if plane.get("front_stale"):
        out.append(
            Notice(
                "plane:front_stale", WARN, "aep_front.py changed on disk: reconnect (/mcp) to apply",
                "front_stale: reconnect", reconnect or "aep_ctl(domain='ipc', action='harness_reconnect')",
            )
        )  # fmt: skip
    elif plane.get("stale") and plane.get("serving_from") != "lkg":
        out.append(
            Notice(
                "plane:code_stale", WARN, "loaded code != disk: reload or hot-swap pending",
                "code_stale: reload pending", "discover(action='capabilities', verbosity='terse')",
            )
        )  # fmt: skip
    if plane.get("reload_error"):
        out.append(
            Notice(
                "plane:reload_error", ERROR, "last hot-swap reload failed: serving previous code",
                "reload_error: swap failed", "discover(action='capabilities', verbosity='terse')",
            )
        )  # fmt: skip
    if plane.get("serving_from") == "lkg":
        out.append(
            Notice(
                "plane:serving_lkg", ERROR, "serving last-known-good code, not the working tree",
                "serving_lkg: code reverted", "autoevol(action='heal')",
            )
        )  # fmt: skip
    return out


class NoticeRegistry:
    """Estado por sesion de servidor: id -> (severidad, estado). Hilo-seguro; nunca toca disco ni BD."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, Notice] = {}
        self._state: dict[str, str] = {}
        self._pushed: dict[str, str] = {}

    def update(self, notices: Iterable[Notice]) -> list[Notice]:
        """Sincroniza con la observacion actual. Resueltos desaparecen; severidad que sube reabre un aviso acked."""
        incoming = {n.id: n for n in notices}
        with self._lock:
            for nid in list(self._state):
                if nid not in incoming:
                    del self._state[nid]
                    self._items.pop(nid, None)
                    self._pushed.pop(nid, None)
            for nid, notice in incoming.items():
                prev = self._items.get(nid)
                if nid not in self._state or (prev is not None and _RANK[notice.severity] > _RANK[prev.severity]):
                    self._state[nid] = NEW
                self._items[nid] = notice
            return list(incoming.values())

    def active(self) -> list[Notice]:
        """Avisos no reconocidos, mas graves primero (orden de entrada dentro de cada severidad)."""
        with self._lock:
            pending = [n for nid, n in self._items.items() if self._state.get(nid) != ACKED]
        return sorted(pending, key=lambda n: -_RANK[n.severity])

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"id": n.id, "severity": n.severity, "state": self._state.get(n.id, NEW), "summary": n.summary,
                 "next_action": n.next_action}
                for n in self._items.values()
            ]  # fmt: skip

    def mark_seen(self, ids: Iterable[str]) -> None:
        with self._lock:
            for nid in ids:
                if self._state.get(nid) == NEW:
                    self._state[nid] = SEEN

    def ack(self, ids: Iterable[str] | None = None, *, all_: bool = False) -> list[str]:
        """Marca acked los `ids` (o todos). Devuelve los ids realmente reconocidos."""
        with self._lock:
            targets = list(self._items) if all_ else [i for i in (ids or []) if i in self._items]
            for nid in targets:
                self._state[nid] = ACKED
            return targets

    def push_event(self) -> dict[str, Any] | None:
        """Datos de UNA notificacion MCP por cambio: id nuevo o severidad que sube entre los no reconocidos."""
        with self._lock:
            live = {nid: self._items[nid] for nid, st in self._state.items() if st != ACKED and nid in self._items}
            changed = any(
                nid not in self._pushed or _RANK[n.severity] > _RANK[self._pushed[nid]] for nid, n in live.items()
            )
            self._pushed = {nid: n.severity for nid, n in live.items()}
        if not changed or not live:
            return None
        ordered = sorted(live.values(), key=lambda n: -_RANK[n.severity])
        blk = build_block(ordered)
        if blk is None:
            return None
        return {
            "level": "error" if blk["severity"] == ERROR else "warning",
            "logger": "aep.notice",
            "data": {k: blk[k] for k in ("count", "severity", "ask_user", "next_action")},
        }


def build_block(notices: list[Notice]) -> dict[str, Any] | None:
    """Bloque `aep_notice` <= 350 B para `notices` (ya ordenados por gravedad); None si no hay ninguno."""
    if not notices:
        return None
    sev = max((n.severity for n in notices), key=lambda s: _RANK[s])
    head = notices[0]
    for k in range(min(TOP_MAX, len(notices)), 0, -1):
        for width in (LABEL_MAX, 32, 22):
            labels = [_clip(n.label, width) for n in notices[:k]]
            block = {
                "count": len(notices),
                "top": labels,
                "severity": sev,
                "ask_user": ASK_TEMPLATE.format(items=", ".join(labels[:-1]) + (" o " if k > 1 else "") + labels[-1]),
                "next_action": head.next_action,
                "ack": ACK_HINT,
            }
            if len(json.dumps(block, ensure_ascii=False).encode("utf-8")) <= BLOCK_MAX_BYTES:
                return block
    minimal = {"count": len(notices), "severity": sev, "ask_user": ASK_TEMPLATE.format(items=_clip(head.label, 30)),
               "ack": ACK_HINT}  # fmt: skip
    return minimal


def is_quiet(tool: str, action: str) -> bool:
    return (tool, str(action).strip().lower()) in QUIET_ACTIONS


# --- analisis caliente (T1) ----------------------------------------------------------------------------------

_HOT_LOCK = threading.Lock()
_HOT: dict[str, Any] = {"thread": None, "elapsed_ms": None, "error": None, "runs": 0}


def hot_state() -> dict[str, Any]:
    with _HOT_LOCK:
        return {k: v for k, v in _HOT.items() if k != "thread"} | {"running": _hot_running()}


def _hot_running() -> bool:
    t = _HOT["thread"]
    return bool(t is not None and t.is_alive())


def start_hot_analysis(
    analyze: Callable[[], Any],
    *,
    on_done: Callable[[], None] | None = None,
) -> threading.Thread | None:
    """Lanza `analyze()` en un hilo daemon (no bloquea, fail-soft). Idempotente mientras haya uno corriendo.

    El hilo nunca escribe en la BD (el analisis es estatico) y libera sus descriptores al terminar: un error se
    registra en `hot_state` y se traga. `on_done` corre al final (tambien tras error)."""
    with _HOT_LOCK:
        if _hot_running():
            return None

        def _run() -> None:
            t0 = time.perf_counter()
            err: str | None = None
            try:
                analyze()
            except Exception as exc:  # noqa: BLE001 - fail-soft: el analisis caliente jamas afecta al servidor
                err = type(exc).__name__
                logger.warning("hot analysis failed: %s", err)
            with _HOT_LOCK:
                _HOT.update(elapsed_ms=round((time.perf_counter() - t0) * 1000, 1), error=err, runs=_HOT["runs"] + 1)
            if on_done is not None:
                try:
                    on_done()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("hot analysis on_done failed: %s", type(exc).__name__)

        thread = threading.Thread(target=_run, name="aep_hot_analysis", daemon=True)
        _HOT["thread"] = thread
        thread.start()
        return thread
