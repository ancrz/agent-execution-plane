"""
Engine: threads_field.py (ONT-43: field report, cuarentena y promocion por reproduccion)

Conecta fallos reales de herramientas ("mi tool no funciona con X") con el bucle autoevol SIN confiar en el texto.

Modelo de amenaza: el texto de error/observacion es DATO NO CONFIABLE (puede traer prompt injection). Un reporte solo
nunca abre un ciclo ni toca codigo. Estados (derivados del JSONL de eventos de autoevol, append-only):

    CANDIDATE --(repro test XFAIL real en sandbox)--> PROMOTED
    CANDIDATE --(repro pasa / no colecta)-----------> REJECTED_NO_REPRO  (reintentable con otro repro)

  - `record_report` (tier >= 5r-x): solo escribe el JSONL. Texto libre saneado (`sanitize_dict`) y truncado (300 c/u),
    guardado como dato y nunca re-emitido en respuestas. Dedupe por `sig` (+1 ocurrencia, sin candidato nuevo).
    Tope `AEP_FIELD_MAX_REPORTS` (defecto 20 sigs nuevas / 24 h); sobre el tope => `CAPPED`, no se guarda nada.
  - `promote` (tier >= 6rw-): el repro debe ser `tests/field/test_fr_<sig>.py::<nombre>` con
    `@pytest.mark.xfail(strict=True, reason="FR-<sig> ...")` del MISMO sig; se ejecuta SOLO ese test en el sandbox
    inyectado (`run_repro`) y debe dar XFAIL (falla de verdad). Solo entonces el sig entra en `promoted_sigs`, que
    alimenta `threads.field_discrepancies`. Abrir un ciclo sigue exigiendo el opt-in y el tope de reconcile.

Politica de repro (O1/O2): UN solo archivo autocontenido. `tests/field` solo puede contener archivos regulares
`test_fr_<12hex>.py` (nada de subdirectorios, `__init__.py`, helpers, symlinks ni otros tipos) y el repro no puede
importar modulos hermanos de `tests/field` ni usar imports relativos: los repros multi-archivo estan FUERA de politica.
Enlace falla<->clase de error (O2): el candidato guarda `error_class` (normalizada como en `telemetry`) y el marcador
debe ser `xfail(strict=True, reason="FR-<sig> ...", raises=<Clase>)` con `Clase` == `error_class`. Se eligio la via AST
sobre parsear el resumen de pytest: `-rx` imprime la razon del marcador, no la excepcion real, y con `raises=` +
`strict=True` pytest ya falla el test (no XFAIL) si la excepcion es de otra clase, asi que XFAIL real implica clase real.
El sig se VERIFICA al registrar: `field_sig(tool, action, status, error_class)` debe reproducir el sig (O3), asi
`error_class` no puede mentirse. `telemetry` importa `field_sig` de aqui (hoja: sin ciclo).
Un candidato sin `error_class` (registrado antes de O2) no promueve: REJECTED_NO_REPRO, hay que re-registrarlo.

Nota de rotacion: el JSONL conserva el actual y `.1`; con tier >= 6rw- el servidor lo espeja al ledger.

Topos: depende solo de `engine.threads_events` y `engine.security`; NO importa `server` ni otros `threads_*`.
El sandbox llega inyectado (`run_repro`).
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine import threads_events as ev
from engine.security import sanitize_dict

ENV_MAX_REPORTS = "AEP_FIELD_MAX_REPORTS"
DEFAULT_MAX_REPORTS = 20
WINDOW_SECONDS = 24 * 3600
TEXT_MAX = 300
MIN_RECORD_OCTAL = 5
MIN_PROMOTE_OCTAL = 6
REPRO_MAX_BYTES = 256 * 1024
LIST_MAX = 50

CANDIDATE, PROMOTED, REJECTED = "CANDIDATE", "PROMOTED", "REJECTED_NO_REPRO"
EV_CANDIDATE, EV_OCCURRENCE = "field.candidate", "field.occurrence"
EV_PROMOTED, EV_REJECTED = "field.promoted", "field.rejected"
_EVENT_KINDS = frozenset({EV_CANDIDATE, EV_OCCURRENCE, EV_PROMOTED, EV_REJECTED})

SIG_RE = re.compile(r"^[0-9a-f]{12}$")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_NON_WORD_RE = re.compile(r"[^a-z0-9_]+")  # igual que telemetry.normalize_error_class (sin importarlo: Topos)
ERROR_CLASS_MAX = 40
FIELD_SIG_LEN = 12
_FIELD_FILE_RE = re.compile(r"^test_fr_[0-9a-f]{12}\.py$")
NO_ERROR_CLASS_REASON = "candidate has no error_class; re-record"
_REPRO_RE = re.compile(r"^tests/field/(test_fr_([0-9a-f]{12}))\.py::(?:([A-Za-z_]\w*)::)?([A-Za-z_]\w*)$")

Clock = Callable[[], float]
# run_repro([nodeid]) -> conteos de pytest (ran/passed/failed/errors/xfailed/xpassed/exit_code) | {"available": False}
RunRepro = Callable[[list[str]], dict[str, Any]]


def max_reports() -> int:
    """`AEP_FIELD_MAX_REPORTS`: entero >= 1; ausente o invalido => 20."""
    try:
        value = int(os.environ.get(ENV_MAX_REPORTS, ""))
    except ValueError:
        return DEFAULT_MAX_REPORTS
    return value if value >= 1 else DEFAULT_MAX_REPORTS


def norm_error_class(value: Any) -> str:
    """Misma normalizacion que `telemetry.normalize_error_class`: ultimo segmento tras '.', minusculas, [a-z0-9_]."""
    if isinstance(value, type):
        value = value.__name__
    return _NON_WORD_RE.sub("", str(value or "").lower().split(".")[-1].split(":")[0])[:ERROR_CLASS_MAX]


def field_sig(tool: str, action: str, status: str, error_class: str) -> str:
    """sha256(tool|action|status|error_class)[:12]. Pura; ningun texto de mensaje participa. Unica fuente del sig."""
    key = "|".join((tool, str(action).strip().lower()[:32], str(status).upper(), error_class))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:FIELD_SIG_LEN]


def clean_text(value: Any) -> str:
    """Dato inerte: saneado (secretos), sin caracteres de control y truncado. Jamas se interpreta."""
    text = sanitize_dict(str(value if value is not None else ""))
    return _CTRL_RE.sub("", str(text))[:TEXT_MAX]


def fold(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Estado por sig a partir de los eventos `field.*` en orden. Tolerante: lo mal formado se ignora."""
    state: dict[str, dict[str, Any]] = {}
    for e in events:
        kind = e.get("kind")
        sig = str(e.get("sig", ""))
        if kind not in _EVENT_KINDS or not SIG_RE.match(sig):
            continue
        rec = state.get(sig)
        ts = float(e.get("ts", 0) or 0)
        if kind == EV_CANDIDATE:
            if rec is None:
                state[sig] = {
                    "sig": sig,
                    "state": CANDIDATE,
                    "occurrences": 1,
                    "tool": clean_text(e.get("tool")),
                    "action": clean_text(e.get("action")),
                    "error_class": norm_error_class(e.get("error_class")),
                    "first_ts": ts,
                    "last_ts": ts,
                }
            else:  # candidato duplicado (carrera): cuenta como ocurrencia
                rec["occurrences"] += 1
                rec["last_ts"] = ts
        elif rec is None:
            continue  # evento huerfano: sin candidato no hay estado
        elif kind == EV_OCCURRENCE:
            rec["occurrences"] += 1
            rec["last_ts"] = ts
            if not rec["error_class"]:  # re-registro de un candidato previo a O2
                rec["error_class"] = norm_error_class(e.get("error_class"))
        elif kind == EV_PROMOTED:
            rec["state"] = PROMOTED
            rec["test"] = clean_text(e.get("test"))
        elif kind == EV_REJECTED and rec["state"] != PROMOTED:
            rec["state"] = REJECTED
    return state


def _state(base_dir: Path | str | None) -> dict[str, dict[str, Any]]:
    return fold(ev.read_events(base_dir=base_dir))


def list_candidates(*, base_dir: Path | str | None = None, state: str | None = None) -> list[dict[str, Any]]:
    """Reportes conocidos (sin texto libre: solo sig, tool, action, estado, ocurrencias), mas recientes primero."""
    rows = sorted(_state(base_dir).values(), key=lambda r: (-r["last_ts"], r["sig"]))
    return [
        {k: r[k] for k in ("sig", "state", "occurrences", "tool", "action")}
        for r in rows
        if state in (None, r["state"])
    ][:LIST_MAX]


def promoted_sigs(*, base_dir: Path | str | None = None) -> set[str]:
    """Sigs promovidos por reproduccion: unica entrada a `threads.field_discrepancies`."""
    return {sig for sig, r in _state(base_dir).items() if r["state"] == PROMOTED}


def record_report(
    sig: str,
    tool: str,
    action: str,
    input_summary: str,
    expected: str,
    observed: str,
    *,
    octal: int,
    status: str = "",
    error_class: str = "",
    base_dir: Path | str | None = None,
    clock: Clock = time.time,
) -> dict[str, Any]:
    """Registra un candidato (o suma una ocurrencia). Solo JSONL; nunca abre ciclos ni modifica codigo."""
    if octal < MIN_RECORD_OCTAL:
        return {"status": "PERMISSION_DENIED", "error": "report requiere tier >= 5r-x."}
    sig = str(sig or "").strip().lower()
    if not SIG_RE.match(sig):
        return {"status": "ERROR", "error": "sig invalido (12 hex)."}
    known = _state(base_dir)
    now = clock()
    eclass = norm_error_class(error_class)
    if not (str(tool).strip() and str(action).strip() and str(status).strip() and eclass):
        return {"status": "ERROR", "error": "report requires tool, action, status and error_class.", "sig": sig}
    if field_sig(str(tool), str(action), str(status), eclass) != sig:  # O3: el sig se recomputa, no se confia
        return {"status": "ERROR", "error": "sig does not match report components", "sig": sig}
    if sig in known:
        res = ev.append_event(EV_OCCURRENCE, {"sig": sig, "error_class": eclass}, base_dir=base_dir, clock=clock)
        if not res.get("appended"):
            return {"status": "ERROR", "error": "event log unavailable", "sig": sig}
        rec = known[sig]
        return {"status": "DEDUPED", "sig": sig, "state": rec["state"], "occurrences": rec["occurrences"] + 1}
    fresh = sum(1 for r in known.values() if r["first_ts"] > now - WINDOW_SECONDS)
    cap = max_reports()
    if fresh >= cap:
        return {"status": "CAPPED", "sig": sig, "used": fresh, "max": cap}
    data = {
        "sig": sig,
        "tool": clean_text(tool),
        "action": clean_text(action),
        "input_summary": clean_text(input_summary),
        "expected": clean_text(expected),
        "observed": clean_text(observed),
        "error_class": eclass,
    }
    res = ev.append_event(EV_CANDIDATE, data, base_dir=base_dir, clock=clock)
    if not res.get("appended"):
        return {"status": "ERROR", "error": "event log unavailable", "sig": sig}
    return {"status": "RECORDED", "sig": sig, "state": CANDIDATE, "occurrences": 1}


# ---------------------------------------------------------------------------
# Promocion por reproduccion
# ---------------------------------------------------------------------------


def _chain_tail(node: ast.AST) -> str:
    return node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else ""


def _fr_marker(fn: ast.AST, sig: str) -> ast.Call | None:
    """Decorador `xfail(strict=True, reason="FR-<sig> ...")` de `fn`, o None."""
    for dec in getattr(fn, "decorator_list", []):
        if not (isinstance(dec, ast.Call) and _chain_tail(dec.func) == "xfail"):
            continue
        strict = any(
            k.arg == "strict" and isinstance(k.value, ast.Constant) and k.value.value is True for k in dec.keywords
        )
        for k in dec.keywords:
            if (
                strict
                and k.arg == "reason"
                and isinstance(k.value, ast.Constant)
                and re.match(rf"\s*FR-{sig}(?![0-9a-f])", str(k.value.value))
            ):
                return dec
    return None


def _has_strict_fr_marker(fn: ast.AST, sig: str) -> bool:
    return _fr_marker(fn, sig) is not None


def _marker_raises(marker: ast.Call) -> str | None:
    """Clase unica de `raises=` (Name o Attribute), normalizada; None si falta o es tupla/expresion."""
    for k in marker.keywords:
        if k.arg == "raises" and isinstance(k.value, ast.Name | ast.Attribute):
            return norm_error_class(_chain_tail(k.value))
    return None


def _raises_node(marker: ast.Call) -> ast.expr | None:
    for k in marker.keywords:
        if k.arg == "raises" and isinstance(k.value, ast.Name | ast.Attribute):
            return k.value
    return None


_COMPOUND = (ast.If, ast.Try, ast.With, ast.For, ast.While)


def _module_bindings(module: ast.Module) -> dict[str, set[str]]:
    """Nombre -> tipos de binding a nivel de modulo (def/class/assign/import/from); entra en if/try/with, no en defs."""
    out: dict[str, set[str]] = {}

    def add(name: str, kind: str) -> None:
        out.setdefault(name, set()).add(kind)

    stack: list[ast.stmt] = list(module.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            add(node.name, "def")
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                        add(n.id, "assign")
        elif isinstance(node, ast.Import):
            for a in node.names:
                add(a.asname or a.name.split(".")[0], "import")
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                add(a.asname or a.name, "from")
        elif isinstance(node, _COMPOUND):
            for field in ("body", "orelse", "finalbody"):
                stack.extend(getattr(node, field, []))
            for h in getattr(node, "handlers", []):
                stack.extend(h.body)
    return out


def _shadows_raises(module: ast.Module, node: ast.expr) -> bool:
    """R1: el repro no puede rebindear el nombre de `raises=` ni usar como raiz algo que no sea builtins/modulo importado."""
    bound = _module_bindings(module)
    if isinstance(node, ast.Name):
        return node.id in bound
    root: ast.expr = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return True
    kinds = bound.get(root.id, set())
    if root.id == "builtins":
        return bool(kinds - {"import"})
    return not kinds or kinds != {"import"}


def _imports_sibling(module: ast.Module, field_dir: Path) -> bool:
    """O1: import relativo o de un modulo/paquete hermano bajo tests/field (repro multi-archivo = fuera de politica)."""
    stems = {p.stem for p in field_dir.iterdir()} | {p.name for p in field_dir.iterdir()}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 or (node.module or "").split(".")[0] in stems:
                return True
        elif isinstance(node, ast.Import) and any(a.name.split(".")[0] in stems for a in node.names):
            return True
    return False


def _field_dir_clean(field_dir: Path) -> bool:
    """O1: tests/field solo contiene archivos regulares `test_fr_<12hex>.py` (sin symlinks ni subdirectorios)."""
    return all(_FIELD_FILE_RE.match(p.name) and not p.is_symlink() and p.is_file() for p in field_dir.iterdir())


def _declares_pytest_plugins(module: ast.Module) -> bool:
    """F3: asignacion a nivel de modulo de `pytest_plugins` (carga plugins arbitrarios al colectar)."""
    for node in module.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        for t in targets:
            names = [n.id for n in ast.walk(t) if isinstance(n, ast.Name)]
            if "pytest_plugins" in names:
                return True
    return False


def validate_repro(sig: str, repro_test: str, tree: Path | str, error_class: str | None = None) -> tuple[bool, str]:
    """Ruta bajo `tests/field/` con el MISMO sig, archivo regular dentro del arbol y marcador xfail estricto FR-<sig>."""
    m = _REPRO_RE.match(str(repro_test or "").strip())
    if m is None:
        return False, "repro_test must be tests/field/test_fr_<sig>.py::<name>"
    if m.group(2) != sig:
        return False, "sig mismatch between repro_test path and sig"
    base = Path(tree).resolve()
    path = base / "tests" / "field" / f"{m.group(1)}.py"
    # F3: solo el archivo repro validado por AST puede ejecutarse; ningun conftest.py bajo tests/field (autoload).
    field_dir = base / "tests" / "field"
    try:
        if any(field_dir.rglob("conftest.py")):
            return False, "conftest.py is not allowed under tests/field"
        if not _field_dir_clean(field_dir):  # O1: allowlist estricta
            return False, "only test_fr_<sig>.py files are allowed under tests/field"
    except OSError:
        return False, "tests/field unreadable"
    try:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base / "tests" / "field"):
            return False, "repro file missing or not a regular file under tests/field"
        if path.stat().st_size > REPRO_MAX_BYTES:
            return False, "repro file too large"
        module = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=path.name)
    except OSError, SyntaxError, ValueError:
        return False, "repro file unreadable or does not parse"
    if _declares_pytest_plugins(module):
        return False, "pytest_plugins is not allowed in a repro file"
    try:
        if _imports_sibling(module, field_dir):
            return False, "repro must be a single self-contained file (no sibling or relative imports)"
    except OSError:
        return False, "tests/field unreadable"
    name = m.group(4)
    for fn in ast.walk(module):
        if not (isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and fn.name == name):
            continue
        marker = _fr_marker(fn, sig)
        if marker is None:
            continue
        raises_node = _raises_node(marker)
        if raises_node is not None and _shadows_raises(module, raises_node):
            return False, "repro must not shadow the bound exception name"
        if error_class is None:
            return True, "ok"
        raised = _marker_raises(marker)
        if raised is None:
            return False, "xfail marker must declare raises=<ExceptionClass> bound to the reported error_class"
        if raised != norm_error_class(error_class):
            return False, "xfail raises= class does not match the candidate error_class"
        return True, "ok"
    return False, f"test {name} lacks @pytest.mark.xfail(strict=True, reason='FR-{sig} ...')"


def _is_real_xfail(res: dict[str, Any]) -> bool:
    """Exactamente un test, que fallo de verdad (XFAIL). XPASS estricto cuenta como failed; no colectar, como errors."""
    ints = {k: int(res.get(k, 0) or 0) for k in ("xfailed", "passed", "failed", "errors", "xpassed")}
    return ints["xfailed"] == 1 and not (ints["passed"] or ints["failed"] or ints["errors"] or ints["xpassed"])


def promote_report(
    sig: str,
    repro_test: str,
    tree: Path | str,
    run_repro: RunRepro,
    *,
    octal: int,
    base_dir: Path | str | None = None,
    clock: Clock = time.time,
) -> dict[str, Any]:
    """CANDIDATE|REJECTED_NO_REPRO -> PROMOTED (repro XFAIL real) | REJECTED_NO_REPRO. Solo corre el test dado."""
    if octal < MIN_PROMOTE_OCTAL:
        return {"status": "PERMISSION_DENIED", "error": "promover un reporte requiere tier >= 6rw-."}
    sig = str(sig or "").strip().lower()
    if not SIG_RE.match(sig):
        return {"status": "ERROR", "error": "sig invalido (12 hex)."}
    rec = _state(base_dir).get(sig)
    if rec is None:
        return {"status": "NOT_FOUND", "sig": sig, "error": "no candidate for this sig; record it first."}
    if rec["state"] == PROMOTED:
        return {"status": "PROMOTED", "sig": sig, "state": PROMOTED, "already": True}
    if not rec.get("error_class"):
        ev.append_event(EV_REJECTED, {"sig": sig, "reason": NO_ERROR_CLASS_REASON}, base_dir=base_dir, clock=clock)
        return {"status": REJECTED, "sig": sig, "state": REJECTED, "reason": NO_ERROR_CLASS_REASON}
    ok, reason = validate_repro(sig, repro_test, tree, rec["error_class"])
    if not ok:
        return {"status": "INVALID_REPRO", "sig": sig, "state": rec["state"], "reason": reason}
    nodeid = str(repro_test).strip()
    res = run_repro([nodeid])
    if res.get("available") is False or res.get("wrong_tree") or res.get("timeout"):
        return {"status": "SANDBOX_UNAVAILABLE", "sig": sig, "state": rec["state"]}
    if _is_real_xfail(res):
        ev.append_event(EV_PROMOTED, {"sig": sig, "test": nodeid}, base_dir=base_dir, clock=clock)
        return {"status": PROMOTED, "sig": sig, "state": PROMOTED, "test": nodeid}
    why = "errors" if res.get("errors") else "xpass_or_failed" if res.get("failed") or res.get("xpassed") else "passed"
    ev.append_event(EV_REJECTED, {"sig": sig, "test": nodeid, "reason": why}, base_dir=base_dir, clock=clock)
    return {"status": REJECTED, "sig": sig, "state": REJECTED, "reason": why}
