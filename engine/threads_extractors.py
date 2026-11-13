"""
Engine: threads_extractors.py (ONT-40 T4..T7: static extractors of the Thread Graph)

Extractores estáticos (ast, re, hashlib, tomllib no: solo regex sobre pyproject) que construyen el
`ThreadGraph` sin ejecutar código del árbol destino:

  - módulos, funciones, consumes (imports y referencias resueltas) y escrituras/lecturas SQL;
  - tools y acciones (registro FastMCP por decorador, comparaciones de `action`/`mode`, `CONTROL_PLANE_SCHEMA`);
  - capacidades (`_CAPABILITIES`), matriz de degradación y llamadas canónicas;
  - tests (colección por AST), presupuestos de tokens y xfail estrictos (discrepancias abiertas);
  - claims (README y textos del código) con marcador histórico (DQ-5).

Topos: depende solo de `threads_model` (hoja). Sin imports de server, db, security ni privilege.
Determinismo (F11): todo conjunto se ordena antes de usarse; ningún hash incluye rutas absolutas.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import builtins
import collections
import concurrent.futures
import contextvars
import hashlib
import io
import logging
import pathlib
import queue
import re
import select
import socket
import sqlite3
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.threads_model import Node, ThreadGraph

HIST_MARKERS: tuple[str, ...] = ("(histórico)", "(historical)", "<!-- aep:hist -->")
# Acciones previstas fuera de ONT-40: no generan nodos (plan T4, `_PLANNED_ACTIONS` sin nodos).
PLANNED_ACTIONS_NAME = "_PLANNED_ACTIONS"
ACTION_VARS: frozenset[str] = frozenset({"action", "act", "mode"})
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_.\-]{0,31}$")

_TOOL_COUNT_RE = re.compile(
    r"\b(\d{1,3})(?:[ -](?:fast ?mcp|mcp|rpc|typed|json-rpc|polymorphic|polimórficas?|polimórficos?)){0,3}"
    r"[ -](?:tools?|herramientas)\b",
    re.IGNORECASE,
)
_CAP_COUNT_RE = re.compile(r"\b(\d{1,3}) (?:capabilit(?:y|ies)|capacidades)\b", re.IGNORECASE)
_WF_RANGE_RE = re.compile(r"WF-(\d{1,3})\.\.WF-(\d{1,3})")
_VERSION_RE = re.compile(r"server_version[^\n]{0,24}?v?(\d+\.\d+\.\d+)")

_SQL_WRITE_RES = (
    re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+(\w+)\s+SET\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+(\w+)", re.IGNORECASE),
)
_SQL_READ_RES = (
    re.compile(r"\bFROM\s+(\w+)", re.IGNORECASE),
    re.compile(r"\bJOIN\s+(\w+)", re.IGNORECASE),
)
_SQL_CREATE_RE = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(", re.IGNORECASE)
_DDL_RE = re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\(", re.IGNORECASE)


def sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Lectura de insumos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ParsedFile:
    relpath: str
    text: str
    tree: ast.Module | None
    error: str = ""


@dataclass(slots=True)
class Sources:
    """Insumos leídos del árbol: la huella `inputs_hash` es la clave de caché de `analyze`."""

    root: Path
    code: dict[str, ParsedFile] = field(default_factory=dict)  # server.py, aep_*.py, engine/**/*.py
    tests: dict[str, ParsedFile] = field(default_factory=dict)  # tests/*.py
    texts: dict[str, str] = field(default_factory=dict)  # README.md, schemas/database.sql, pyproject.toml

    def inputs_hash(self) -> str:
        parts: list[str] = []
        for group in (self.code, self.tests):
            for rel in sorted(group):
                parts.append(f"{rel}:{sha(group[rel].text)}")
        for rel in sorted(self.texts):
            parts.append(f"{rel}:{sha(self.texts[rel])}")
        return sha(*parts)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse(rel: str, text: str) -> ParsedFile:
    try:
        return ParsedFile(rel, text, ast.parse(text, filename=rel))
    except (SyntaxError, ValueError, RecursionError) as exc:
        line = getattr(exc, "lineno", 0) or 0
        return ParsedFile(rel, text, None, f"{type(exc).__name__}: line {line}")


def read_sources(root: Path | str) -> Sources:
    """Lee código, tests y textos del árbol `root`. Solo lectura. Rutas relativas y ordenadas."""
    base = Path(root).resolve()
    src = Sources(root=base)
    code_files: list[Path] = []
    top_level = {"server.py", "aep_front.py", "aep_backend.py"}
    # TA0 (ONT-41): todo `aep_*.py` de nivel superior entra en el grafo (p. ej. aep_lkg.py); su ausencia se tolera.
    try:
        top_level.update(p.name for p in base.glob("aep_*.py") if p.is_file() and not p.is_symlink())
    except OSError:
        pass
    for name in sorted(top_level):
        p = base / name
        if p.is_file():
            code_files.append(p)
    engine_dir = base / "engine"
    if engine_dir.is_dir():
        code_files.extend(p for p in engine_dir.rglob("*.py") if "__pycache__" not in p.parts and p.is_file())
    for p in sorted(code_files, key=lambda f: f.relative_to(base).as_posix()):
        rel = p.relative_to(base).as_posix()
        src.code[rel] = _parse(rel, _read(p))
    tests_dir = base / "tests"
    if tests_dir.is_dir():
        # ONT-43: `tests/field/` aloja los repros de reportes de campo (xfail estrictos FR-<sig>).
        test_files = [*tests_dir.glob("*.py"), *(tests_dir / "field").glob("*.py")]
        for p in sorted(test_files, key=lambda f: f.relative_to(base).as_posix()):
            if p.is_symlink():
                continue
            rel = p.relative_to(base).as_posix()
            src.tests[rel] = _parse(rel, _read(p))
    for rel in ("README.md", "schemas/database.sql", "pyproject.toml"):
        p = base / rel
        if p.is_file():
            src.texts[rel] = _read(p)
    return src


# ---------------------------------------------------------------------------
# Utilidades AST
# ---------------------------------------------------------------------------


def module_name(relpath: str) -> str:
    parts = relpath.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _dump_hash(node: ast.AST) -> str:
    return sha(ast.dump(node))


def _chain(node: ast.AST) -> list[str] | None:
    """Aplana `a.b.c` en ['a','b','c']; None si la base no es un Name."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return list(reversed(parts))
    return None


def _is_type_checking(test: ast.AST) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _docstring_node(fn: ast.AST) -> ast.AST | None:
    body = getattr(fn, "body", [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            return body[0]
    return None


def _string_constants(fn: ast.AST) -> list[str]:
    """Constantes de texto (y fragmentos constantes de f-strings) sin el docstring."""
    skip = _docstring_node(fn)
    out: list[str] = []
    for node in ast.walk(fn):
        if node is skip:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    # el docstring es un Constant dentro de un Expr: se excluye por identidad del Expr
    if skip is not None:
        doc = skip.value.value  # type: ignore[attr-defined]
        if doc in out:
            out.remove(doc)
    return out


def literal_dict_best_effort(node: ast.AST | None) -> dict[str, Any]:
    """literal_eval de un dict; si falla por valores no literales, evalúa entrada a entrada lo que pueda.

    D-AE-1: recursa en `ast.Dict` anidados, salta las claves `None` (`**spread`) y las entradas no literales
    (comprensiones, llamadas), para que un dominio con una entrada dinámica no desaparezca entero.
    """
    if not isinstance(node, ast.Dict):
        return {}
    try:
        value = ast.literal_eval(node)
        return value if isinstance(value, dict) else {}
    except ValueError, SyntaxError:
        out: dict[str, Any] = {}
        for k, v in zip(node.keys, node.values, strict=True):
            if k is None or not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            try:
                out[k.value] = ast.literal_eval(v)
            except ValueError, SyntaxError:
                out[k.value] = literal_dict_best_effort(v) if isinstance(v, ast.Dict) else None
        return out


def find_module_assign(tree: ast.Module, name: str) -> ast.AST | None:
    """Valor asignado a `name` a nivel de módulo (Assign o AnnAssign)."""
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == name:
            return stmt.value
    return None


# ---------------------------------------------------------------------------
# T5: módulos, funciones, consumes, estado SQL
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Imports:
    """Mapa nombre-local -> ('module', modname) | ('symbol', modname, symbol)."""

    names: dict[str, tuple[str, ...]] = field(default_factory=dict)


class _FnIndex(set):
    """Conjunto de ids de función con índice de métodos de nombre único (resolución débil `obj.metodo`)."""

    uniq: dict[str, str]

    def __init__(self, funcs: dict[str, Any]) -> None:
        super().__init__(funcs)
        counts: dict[str, list[str]] = {}
        for fid in sorted(funcs):
            counts.setdefault(fid.rsplit(".", 1)[-1], []).append(fid)
        self.uniq = {
            name: ids[0] for name, ids in counts.items() if len(ids) == 1 and not name.startswith("_") and len(name) > 4
        }

    def weak(self, chain: list[str]) -> str | None:
        """`obj.metodo` con `metodo` único en el proyecto (cobertura/consumo débil, sin tipos)."""
        return self.uniq.get(chain[-1]) if len(chain) >= 2 else None


@dataclass(slots=True)
class _FuncInfo:
    node_id: str
    module: str
    qual: str
    cls: str
    tree: ast.AST


def _resolve_from(current: str, level: int, module: str | None, is_pkg: bool) -> str:
    """Resuelve el módulo de un `from` (con puntos relativos) a nombre absoluto."""
    if level == 0:
        return module or ""
    pkg_parts = current.split(".") if is_pkg else current.split(".")[:-1]
    keep = pkg_parts[: len(pkg_parts) - (level - 1)] if level > 1 else pkg_parts
    return ".".join([*keep, *([module] if module else [])])


def _collect_imports(
    body: list[ast.stmt], current: str, is_pkg: bool, project: set[str], *, nested: bool = False
) -> list[tuple[str, tuple[str, ...], bool]]:
    """Imports de un cuerpo: (nombre local, destino, lazy). Salta bloques `if TYPE_CHECKING`."""
    found: list[tuple[str, tuple[str, ...], bool]] = []

    def visit(stmts: list[ast.stmt], lazy: bool) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    if alias.asname:
                        found.append((alias.asname, ("module", alias.name), lazy))
                    else:
                        found.append((alias.name.split(".")[0], ("module", alias.name.split(".")[0]), lazy))
                        found.append(("\0" + alias.name, ("module", alias.name), lazy))
            elif isinstance(stmt, ast.ImportFrom):
                base = _resolve_from(current, stmt.level, stmt.module, is_pkg)
                for alias in stmt.names:
                    local = alias.asname or alias.name
                    sub = f"{base}.{alias.name}" if base else alias.name
                    if sub in project:
                        found.append((local, ("module", sub), lazy))
                    else:
                        found.append((local, ("symbol", base, alias.name), lazy))
            elif isinstance(stmt, ast.If):
                if _is_type_checking(stmt.test):
                    visit(stmt.orelse, lazy)
                    continue
                visit(stmt.body, lazy)
                visit(stmt.orelse, lazy)
            elif isinstance(stmt, (ast.Try, ast.With, ast.For, ast.While)):
                for sub_body in (
                    getattr(stmt, "body", []),
                    getattr(stmt, "orelse", []),
                    getattr(stmt, "finalbody", []),
                    *[h.body for h in getattr(stmt, "handlers", [])],
                ):
                    visit(sub_body, lazy)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(stmt.body, True)
            elif isinstance(stmt, ast.ClassDef):
                visit(stmt.body, lazy)

    visit(body, nested)
    return found


@dataclass(slots=True)
class ExtractionInfo:
    py_version: str = ""
    errors: list[dict[str, str]] = field(default_factory=list)
    lazy_edges: int = 0
    planned_actions: list[str] = field(default_factory=list)
    weak_edges: int = 0  # ONT-46: aristas creadas por nombre único sin tipo de receptor
    external_skipped: int = 0  # ONT-46: resoluciones descartadas por receptor externo/builtin
    type_index: Any = field(default=None, repr=False, compare=False)


def _project_modules(code: dict[str, ParsedFile]) -> set[str]:
    return {module_name(rel) for rel in code}


def extract_code(graph: ThreadGraph, src: Sources, info: ExtractionInfo) -> dict[str, _FuncInfo]:
    """Nodos módulo y función, aristas consumes (módulo y función) y escrituras/lecturas SQL."""
    project = _project_modules(src.code)
    funcs: dict[str, _FuncInfo] = {}
    class_names: dict[str, set[str]] = {}
    module_imports: dict[str, _Imports] = {}
    is_pkg_of: dict[str, bool] = {}

    # Pasada 1: nodos módulo, funciones y clases.
    for rel, pf in src.code.items():
        mod = module_name(rel)
        is_pkg_of[mod] = rel.endswith("__init__.py")
        attrs: dict[str, Any] = {"path": rel}
        if pf.tree is None:
            attrs["syntax_error"] = pf.error
            info.errors.append({"file": rel, "error": pf.error})
            graph.add_node(Node("module", f"module:{mod}", sha("syntax_error", pf.text), attrs))
            continue
        graph.add_node(Node("module", f"module:{mod}", _dump_hash(pf.tree), attrs))
        class_names[mod] = set()
        for stmt in pf.tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _add_function(graph, funcs, mod, stmt, stmt.name, "")
            elif isinstance(stmt, ast.ClassDef):
                class_names[mod].add(stmt.name)
                for sub in stmt.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        _add_function(graph, funcs, mod, sub, f"{stmt.name}.{sub.name}", stmt.name)

    # Estado: tablas del DDL y tablas creadas en código.
    tables = extract_state(graph, src)

    # Pasada 2: aristas.
    for rel, pf in src.code.items():
        if pf.tree is None:
            continue
        mod = module_name(rel)
        imports = _Imports()
        for local, target, lazy in _collect_imports(pf.tree.body, mod, is_pkg_of[mod], project):
            if not lazy:
                imports.names[local] = target
            _add_module_edges(graph, mod, target, lazy, project, info)
        # Los imports perezosos aportan aristas de módulo (lazy=True) y nombres para resolver referencias.
        lazy_names = {
            local: target
            for local, target, lazy in _collect_imports(pf.tree.body, mod, is_pkg_of[mod], project)
            if lazy
        }
        for local, target in lazy_names.items():
            imports.names.setdefault(local, target)
        module_imports[mod] = imports

    fn_ids = _FnIndex(funcs)
    types = build_type_index(src, funcs)
    info.type_index = types
    for fn in funcs.values():
        ctx_imports = module_imports.get(fn.module, _Imports())
        _add_function_edges(graph, fn, ctx_imports, fn_ids, class_names, project, tables, types)
    return funcs


def _add_function(
    graph: ThreadGraph, funcs: dict[str, _FuncInfo], mod: str, node: ast.AST, qual: str, cls: str
) -> None:
    node_id = f"fn:{mod}.{qual}"
    if node_id in funcs:
        return
    parts = qual.split(".")
    public = not any(p.startswith("_") for p in parts)
    attrs = {"module": mod, "qual": qual, "public": public, "line": getattr(node, "lineno", 0)}
    graph.add_node(Node("function", node_id, _dump_hash(node), attrs))
    funcs[node_id] = _FuncInfo(node_id, mod, qual, cls, node)


def _add_module_edges(
    graph: ThreadGraph, mod: str, target: tuple[str, ...], lazy: bool, project: set[str], info: ExtractionInfo
) -> None:
    candidates: list[str] = []
    if target[0] == "module":
        name = target[1]
        parts = name.split(".")
        for k in range(len(parts), 0, -1):
            if ".".join(parts[:k]) in project:
                candidates.append(".".join(parts[:k]))
                break
    else:
        base = target[1]
        if base in project:
            candidates.append(base)
    for cand in candidates:
        if cand != mod and graph.add_edge(f"module:{mod}", f"module:{cand}", "consumes", lazy=lazy) and lazy:
            info.lazy_edges += 1


def _expand(chain: list[str], fn: _FuncInfo, imports: _Imports, project: set[str]) -> list[str] | None:
    """Expande una cadena a su ruta absoluta usando los imports; None si es local o desconocida."""
    return _expand_parts(chain, fn.module, fn.cls, imports)


def _expand_parts(chain: list[str], module: str, cls: str, imports: _Imports) -> list[str]:
    """Núcleo de `_expand` sin `_FuncInfo` (lo reutiliza el tipado de receptores, ONT-46)."""
    first = chain[0]
    if first == "self" and cls:
        return [*module.split("."), cls, *chain[1:]]
    if first in imports.names:
        target = imports.names[first]
        if target[0] == "module":
            return [*target[1].split("."), *chain[1:]]
        return [*target[1].split("."), target[2], *chain[1:]] if target[1] else [target[2], *chain[1:]]
    return [*module.split("."), *chain]


def _resolve_fn(
    expanded: list[str], fn_ids: set[str], class_names: dict[str, set[str]], project: set[str]
) -> str | None:
    for k in range(len(expanded) - 1, 0, -1):
        mod = ".".join(expanded[:k])
        if mod not in project:
            continue
        qual = ".".join(expanded[k:])
        cand = f"fn:{mod}.{qual}"
        if cand in fn_ids:
            return cand
        if qual in class_names.get(mod, set()):
            ctor = f"fn:{mod}.{qual}.__init__"
            if ctor in fn_ids:
                return ctor
        return None
    return None


# ---------------------------------------------------------------------------
# ONT-46: tipado barato y determinista del receptor (`obj.metodo`)
# ---------------------------------------------------------------------------

EXT = "<external>"  # el valor es de un tipo externo al proyecto (builtin, stdlib o terceros)
REF = "<ref>"  # el valor es un módulo, clase o función del proyecto como objeto (no una instancia)

_BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins))
# Anotaciones que no informan del tipo concreto.
_OPAQUE_TYPES: frozenset[str] = frozenset({"Any", "object", "Self", "TypeVar", "NoReturn", "Never"})
_UNWRAP_ANNOTATIONS: frozenset[str] = frozenset(
    {"Optional", "ClassVar", "Final", "Annotated", "Required", "NotRequired"}
)
_GENERATOR_ANNOTATIONS: frozenset[str] = frozenset(
    {"Iterator", "Generator", "AsyncIterator", "AsyncGenerator", "Iterable", "AsyncIterable"}
)
# Fixtures integradas de pytest: su valor es externo al proyecto.
_PYTEST_EXTERNAL_FIXTURES: frozenset[str] = frozenset(
    {"tmp_path", "tmp_path_factory", "monkeypatch", "capsys", "capfd", "caplog", "request", "recwarn", "pytestconfig"}
)


def _build_external_methods() -> frozenset[str]:
    """Nombres públicos de métodos de tipos builtin y de clases stdlib usadas por el proyecto.

    Un receptor de tipo desconocido cuyo método se llama así NO se resuelve por nombre único: casi seguro es
    un objeto externo (`items.append`, `proc.terminate`, `conn.execute`). Se construye una vez por intérprete.
    """
    types: tuple[type, ...] = (
        object, list, dict, set, frozenset, str, bytes, bytearray, tuple, int, float, bool, range, slice, type,
        BaseException,
        subprocess.Popen, threading.Thread, threading.Lock, threading.RLock, threading.Event, threading.Condition,
        threading.Semaphore, pathlib.Path, sqlite3.Connection, sqlite3.Cursor, io.TextIOWrapper, io.BytesIO,
        io.StringIO, socket.socket, logging.Logger, asyncio.AbstractEventLoop, asyncio.Task, asyncio.Future,
        asyncio.Queue, asyncio.Event, asyncio.Lock, queue.Queue, collections.deque, collections.OrderedDict,
        collections.Counter, collections.defaultdict, contextvars.ContextVar, concurrent.futures.Future,
        concurrent.futures.ThreadPoolExecutor, argparse.ArgumentParser,
    )  # fmt: skip
    names: set[str] = set()
    for t in types:
        names.update(n for n in dir(t) if not n.startswith("_"))
    names.update(n for n in dir(select) if not n.startswith("_"))
    return frozenset(names)


_EXTERNAL_METHODS: frozenset[str] = _build_external_methods()


@dataclass(slots=True)
class _Scope:
    """Ámbito de tipado: módulo, clase, imports y los tipos de locales y globales (None = desconocido)."""

    mod: str
    cls: str
    imports: _Imports
    locals: dict[str, str | None]
    globals: dict[str, str | None]


@dataclass(slots=True)
class _TypedCtx:
    """Paquete de tipado que viaja con el extractor de tests."""

    types: _TypeIndex
    globals: dict[str, str | None]
    fixtures: dict[str, str | None]


def _imports_for(pf: ParsedFile, mod: str, is_pkg: bool, project: set[str]) -> _Imports:
    """Mapa de imports de un módulo (idéntico al que usa `extract_code`: no perezosos y luego perezosos)."""
    imports = _Imports()
    if pf.tree is None:
        return imports
    collected = _collect_imports(pf.tree.body, mod, is_pkg, project)
    for local, target, lazy in collected:
        if not lazy:
            imports.names[local] = target
    lazy_names = {local: target for local, target, lazy in collected if lazy}
    for local, target in lazy_names.items():
        imports.names.setdefault(local, target)
    return imports


def _is_none_const(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _store_names(target: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]


def _agree(types: list[str | None]) -> str | None:
    """Tipo común a todas las asignaciones; None si hay conflicto, desconocido o ninguna."""
    if not types:
        return None
    first = types[0]
    return first if first is not None and all(t == first for t in types) else None


def _is_property(fn: ast.AST) -> bool:
    for dec in getattr(fn, "decorator_list", []):
        chain = _chain(dec)
        if chain and chain[-1] in ("property", "cached_property"):
            return True
    return False


def _is_fixture(fn: ast.AST) -> bool:
    for dec in getattr(fn, "decorator_list", []):
        chain = _chain(dec.func if isinstance(dec, ast.Call) else dec)
        if chain and chain[-1] == "fixture":
            return True
    return False


class _TypeIndex:
    """Inferencia barata de tipos de receptor sobre el AST (sin ejecutar código ni dependencias nuevas).

    Alimenta `resolve`: `obj.metodo` se resuelve por el tipo de `obj` (constructor, anotación, atributo de
    clase, global de módulo, fixture) y solo cae a la resolución por nombre único cuando el receptor es
    DESCONOCIDO (arista `weak`). Receptores externos o builtin jamás producen aristas.
    """

    def __init__(self, src: Sources, funcs: dict[str, _FuncInfo]) -> None:
        self.funcs = funcs
        self.fn_ids = _FnIndex(funcs)
        self.project = _project_modules(src.code)
        self.class_names: dict[str, set[str]] = {}
        self.imports: dict[str, _Imports] = {}
        self.trees: dict[str, ast.Module] = {}
        self.module_types: dict[str, dict[str, str | None]] = {}
        self.class_attrs: dict[str, dict[str, str | None]] = {}
        self.class_bases: dict[str, list[str]] = {}
        self.external_skipped = 0
        self.root = src.root
        self._returns: dict[str, str | None] = {}
        self._local_tops: dict[str, bool] = {}
        for rel, pf in src.code.items():
            if pf.tree is None:
                continue
            mod = module_name(rel)
            self.trees[mod] = pf.tree
            self.imports[mod] = _imports_for(pf, mod, rel.endswith("__init__.py"), self.project)
            self.class_names[mod] = {s.name for s in pf.tree.body if isinstance(s, ast.ClassDef)}
        for mod in sorted(self.trees):
            for stmt in self.trees[mod].body:
                if isinstance(stmt, ast.ClassDef):
                    bases = [self.name_class(c, mod, self.imports[mod]) for b in stmt.bases if (c := _chain(b))]
                    self.class_bases[f"{mod}.{stmt.name}"] = [b for b in bases if b and b not in (EXT, REF)]
        for _ in range(3):
            before = (self.module_types, self.class_attrs)
            self.module_types = {m: self.module_globals(self.trees[m], m, self.imports[m]) for m in sorted(self.trees)}
            self.class_attrs = {}
            for mod in sorted(self.trees):
                for stmt in self.trees[mod].body:
                    if isinstance(stmt, ast.ClassDef):
                        self.class_attrs[f"{mod}.{stmt.name}"] = self._scan_class(mod, stmt)
            if before == (self.module_types, self.class_attrs):
                break

    # -- nombres, clases y anotaciones ------------------------------------------------------------

    def lookup(self, expanded: list[str]) -> tuple[str, str] | None:
        """('class', 'mod.Cls') o ('fn', 'fn:mod.q') para una ruta absoluta del proyecto."""
        for k in range(len(expanded) - 1, 0, -1):
            mod = ".".join(expanded[:k])
            if mod not in self.project:
                continue
            qual = ".".join(expanded[k:])
            if qual in self.class_names.get(mod, ()):
                return ("class", f"{mod}.{qual}")
            fid = f"fn:{mod}.{qual}"
            return ("fn", fid) if fid in self.fn_ids else None
        return None

    def _is_local_code(self, top: str) -> bool:
        """El paquete raíz vive en el árbol analizado (p. ej. `tests._evolve_support`): ni proyecto ni externo."""
        if top not in self._local_tops:
            self._local_tops[top] = (self.root / top).is_dir() or (self.root / f"{top}.py").is_file()
        return self._local_tops[top]

    def _defined_in(self, name: str, mod: str) -> bool:
        return name in self.class_names.get(mod, ()) or f"fn:{mod}.{name}" in self.fn_ids

    def name_class(self, chain: list[str], mod: str, imports: _Imports) -> str | None:
        """Clase del proyecto (`mod.Cls`), EXT si el nombre es externo/builtin, None si no se sabe."""
        expanded = _expand_parts(chain, mod, "", imports)
        hit = self.lookup(expanded)
        if hit:
            return hit[1] if hit[0] == "class" else None
        first = chain[0]
        if first in imports.names:
            has_project = any(".".join(expanded[:k]) in self.project for k in range(1, len(expanded) + 1))
            return None if has_project or self._is_local_code(expanded[0]) else EXT
        if len(chain) == 1 and first in _BUILTIN_NAMES and not self._defined_in(first, mod):
            return EXT
        return None

    def ann_type(self, ann: ast.AST | None, mod: str, imports: _Imports, depth: int = 0) -> str | None:
        """Tipo declarado por una anotación (`T`, `"T"`, `T | None`, `Optional[T]`, `Union[...]`)."""
        if ann is None or depth > 4:
            return None
        if isinstance(ann, ast.Constant):
            if isinstance(ann.value, str):
                try:
                    inner = ast.parse(ann.value.strip(), mode="eval").body
                except SyntaxError, ValueError:
                    return None
                return self.ann_type(inner, mod, imports, depth + 1)
            return None
        if isinstance(ann, (ast.Name, ast.Attribute)):
            chain = _chain(ann)
            if not chain or chain[-1] in _OPAQUE_TYPES:
                return None
            return self.name_class(chain, mod, imports)
        if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
            parts: list[ast.AST] = []
            stack: list[ast.AST] = [ann]
            while stack:
                cur = stack.pop()
                if isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.BitOr):
                    stack.extend((cur.right, cur.left))
                else:
                    parts.append(cur)
            return self._union(parts, mod, imports, depth)
        if isinstance(ann, ast.Subscript):
            head = _chain(ann.value)
            name = head[-1] if head else ""
            elts = list(ann.slice.elts) if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            if name in _UNWRAP_ANNOTATIONS:
                return self.ann_type(elts[0], mod, imports, depth + 1)
            if name == "Union":
                return self._union(elts, mod, imports, depth)
            base = self.ann_type(ann.value, mod, imports, depth + 1)
            return base if base == EXT or (base and base in self.class_bases) else None
        return None

    def _union(self, parts: list[ast.AST], mod: str, imports: _Imports, depth: int) -> str | None:
        kept = [p for p in parts if not _is_none_const(p)]
        return _agree([self.ann_type(p, mod, imports, depth + 1) for p in kept])

    def fn_return(self, fid: str) -> str | None:
        """Tipo de retorno anotado de una función del proyecto."""
        if fid not in self._returns:
            fn = self.funcs.get(fid)
            ret = getattr(fn.tree, "returns", None) if fn else None
            self._returns[fid] = self.ann_type(ret, fn.module, self.imports.get(fn.module, _Imports())) if fn else None
        return self._returns[fid]

    # -- herencia y atributos de clase ------------------------------------------------------------

    def mro(self, key: str) -> list[str]:
        out: list[str] = []

        def visit(k: str) -> None:
            if k in out:
                return
            out.append(k)
            for b in self.class_bases.get(k, []):
                visit(b)

        visit(key)
        return out

    def find_method(self, cls_key: str, name: str) -> str | None:
        for k in self.mro(cls_key):
            fid = f"fn:{k}.{name}"
            if fid in self.fn_ids:
                return fid
        return None

    def attr_type(self, cls_key: str, attr: str) -> str | None:
        for k in self.mro(cls_key):
            attrs = self.class_attrs.get(k)
            if attrs and attr in attrs:
                return attrs[attr]
        return None

    # -- tipo de expresiones ----------------------------------------------------------------------

    def value_type(self, chain: list[str], scope: _Scope) -> str | None:
        """Tipo del valor `chain` (sin llamarlo): clase del proyecto, EXT, REF o None (desconocido)."""
        root, rest = chain[0], chain[1:]
        t: str | None
        if root == "self" and scope.cls and root not in scope.locals:
            t = f"{scope.mod}.{scope.cls}"
        elif root in scope.locals:
            t = scope.locals[root]
        elif root in scope.globals:
            t = scope.globals[root]
        elif root in scope.imports.names:
            expanded = _expand_parts(chain, scope.mod, scope.cls, scope.imports)
            for k in range(len(expanded), 0, -1):
                mod = ".".join(expanded[:k])
                if mod in self.project:
                    break
            else:
                return None if self._is_local_code(expanded[0]) else EXT
            tail = expanded[k:]
            if not tail:
                return REF
            known = self.module_types.get(mod, {})
            if tail[0] not in known:
                return REF
            t, rest = known[tail[0]], tail[1:]
        elif self._defined_in(root, scope.mod):
            t = REF
        elif root in _BUILTIN_NAMES:
            t = EXT
        else:
            t = None
        for attr in rest:
            if t is None or t == REF:
                return None
            if t == EXT:
                return EXT
            t = self.attr_type(t, attr)
        return t

    def _method_result(self, receiver: str | None, name: str) -> str | None:
        if receiver == EXT:
            return EXT
        if receiver is None or receiver == REF:
            return None
        fid = self.find_method(receiver, name)
        return self.fn_return(fid) if fid else None

    def call_type(self, call: ast.Call, scope: _Scope) -> str | None:
        """Tipo del resultado de una llamada: constructor del proyecto, retorno anotado o EXT."""
        func = call.func
        chain = _chain(func)
        if chain:
            if chain[0] not in scope.locals:
                hit = self.lookup(_expand_parts(chain, scope.mod, scope.cls, scope.imports))
                if hit:
                    return hit[1] if hit[0] == "class" else self.fn_return(hit[1])
            if len(chain) == 1:
                root = chain[0]
                if root in scope.imports.names:
                    return self.name_class(chain, scope.mod, scope.imports)
                if root in _BUILTIN_NAMES and root not in scope.locals and not self._defined_in(root, scope.mod):
                    return EXT
                return None
            return self._method_result(self.value_type(chain[:-1], scope), chain[-1])
        if isinstance(func, ast.Attribute):
            return self._method_result(self.expr_type(func.value, scope), func.attr)
        return None

    def expr_type(self, node: ast.AST | None, scope: _Scope) -> str | None:
        """Tipo de una expresión; REF se degrada a desconocido (un objeto-clase no es una instancia)."""
        t = self._expr_type(node, scope)
        return None if t == REF else t

    def _expr_type(self, node: ast.AST | None, scope: _Scope) -> str | None:
        if isinstance(node, ast.Call):
            return self.call_type(node, scope)
        if isinstance(node, ast.Await):
            return self._expr_type(node.value, scope)
        if isinstance(node, (ast.Name, ast.Attribute)):
            chain = _chain(node)
            return self.value_type(chain, scope) if chain else None
        if isinstance(node, ast.Constant):
            return None if node.value is None else EXT
        if isinstance(
            node,
            (ast.List, ast.Dict, ast.Set, ast.Tuple, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp),
        ):
            return EXT
        if isinstance(node, (ast.JoinedStr, ast.Lambda)):
            return EXT
        if isinstance(node, ast.IfExp):
            return self._pick([node.body, node.orelse], scope)
        if isinstance(node, ast.BoolOp):
            return self._pick(list(node.values), scope)
        return None

    def _pick(self, nodes: list[ast.AST], scope: _Scope) -> str | None:
        kept = [n for n in nodes if not _is_none_const(n)]
        return _agree([self.expr_type(n, scope) for n in kept])

    # -- ámbitos: globales de módulo, atributos de clase y locales ---------------------------------

    def module_globals(self, tree: ast.Module, mod: str, imports: _Imports) -> dict[str, str | None]:
        """Tipo de los nombres asignados a nivel de módulo (`X = Ctor()`, `X: T = ...`)."""
        scope = _Scope(mod, "", imports, {}, self.module_types.get(mod, {}))
        cands: dict[str, list[str | None]] = {}

        def add(name: str, t: str | None) -> None:
            cands.setdefault(name, []).append(t)

        def visit(stmts: list[ast.stmt]) -> None:
            for st in stmts:
                if isinstance(st, ast.Assign):
                    if not _is_none_const(st.value):
                        t = self.expr_type(st.value, scope)
                        for tgt in st.targets:
                            names = [tgt.id] if isinstance(tgt, ast.Name) else _store_names(tgt)
                            for n in names:
                                add(n, t if isinstance(tgt, ast.Name) else None)
                elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    t = self.ann_type(st.annotation, mod, imports) or self.expr_type(st.value, scope)
                    add(st.target.id, t)
                elif isinstance(st, ast.AugAssign) and isinstance(st.target, ast.Name):
                    add(st.target.id, None)
                elif isinstance(st, (ast.For, ast.AsyncFor)):
                    for n in _store_names(st.target):
                        add(n, None)
                    visit(st.body)
                    visit(st.orelse)
                elif isinstance(st, ast.While):
                    visit(st.body)
                    visit(st.orelse)
                elif isinstance(st, ast.If):
                    visit(st.body)
                    visit(st.orelse)
                elif isinstance(st, (ast.With, ast.AsyncWith)):
                    for item in st.items:
                        if item.optional_vars is not None:
                            for n in _store_names(item.optional_vars):
                                add(n, None)
                    visit(st.body)
                elif isinstance(st, ast.Try):
                    visit(st.body)
                    visit(st.orelse)
                    visit(st.finalbody)
                    for h in st.handlers:
                        visit(h.body)

        visit(tree.body)
        # `global X; X = Ctor()` dentro de funciones (singletons perezosos).
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            declared = {n for g in ast.walk(fn) if isinstance(g, ast.Global) for n in g.names}
            if not declared:
                continue
            for a in ast.walk(fn):
                if isinstance(a, ast.Assign) and not _is_none_const(a.value):
                    for tgt in a.targets:
                        if isinstance(tgt, ast.Name) and tgt.id in declared:
                            add(tgt.id, self.expr_type(a.value, scope))
        return {name: _agree(ts) for name, ts in sorted(cands.items())}

    def _scan_class(self, mod: str, cls: ast.ClassDef) -> dict[str, str | None]:
        imports = self.imports[mod]
        globals_ = self.module_types.get(mod, {})
        mscope = _Scope(mod, "", imports, {}, globals_)
        cands: dict[str, list[str | None]] = {}

        def add(name: str, t: str | None) -> None:
            cands.setdefault(name, []).append(t)

        def self_attr(t: ast.AST) -> str | None:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                return t.attr
            return None

        for st in cls.body:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                add(st.target.id, self.ann_type(st.annotation, mod, imports) or self.expr_type(st.value, mscope))
            elif isinstance(st, ast.Assign) and not _is_none_const(st.value):
                t = self.expr_type(st.value, mscope)
                for tgt in st.targets:
                    if isinstance(tgt, ast.Name):
                        add(tgt.id, t)
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_property(st):
                    add(st.name, self.ann_type(st.returns, mod, imports))
                env = self.local_env(st, mod, cls.name, imports, globals_)
                scope = _Scope(mod, cls.name, imports, env, globals_)
                for n in ast.walk(st):
                    if isinstance(n, ast.Assign) and not _is_none_const(n.value):
                        t = self.expr_type(n.value, scope)
                        for tgt in n.targets:
                            attr = self_attr(tgt)
                            if attr:
                                add(attr, t)
                            elif isinstance(tgt, (ast.Tuple, ast.List)):
                                for el in tgt.elts:
                                    sub = self_attr(el)
                                    if sub:
                                        add(sub, None)
                    elif isinstance(n, ast.AnnAssign):
                        attr = self_attr(n.target)
                        if attr:
                            add(attr, self.ann_type(n.annotation, mod, imports) or self.expr_type(n.value, scope))
        return {name: _agree(ts) for name, ts in sorted(cands.items())}

    def local_env(
        self,
        fn: ast.AST,
        mod: str,
        cls: str,
        imports: _Imports,
        globals_: dict[str, str | None],
        fixtures: dict[str, str | None] | None = None,
    ) -> dict[str, str | None]:
        """Tipo de los nombres locales de `fn` (params anotados, `x = Ctor()`, `with Ctor() as x`, fixtures).

        Un nombre con asignaciones de tipos distintos o desconocidos queda en None (desconocido).
        """
        skip_first = bool(cls) and not any(
            (_chain(d) or [""])[-1] == "staticmethod" for d in getattr(fn, "decorator_list", [])
        )
        names: set[str] = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                names.add(n.id)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                names.add(n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = n.args
                every = [
                    *a.posonlyargs,
                    *a.args,
                    *a.kwonlyargs,
                    *([a.vararg] if a.vararg else []),
                    *([a.kwarg] if a.kwarg else []),
                ]
                names.update(x.arg for x in every)
        if skip_first:
            args = getattr(fn, "args", None)
            first = (args.posonlyargs + args.args) if args else []
            if first:
                names.discard(first[0].arg)
        env: dict[str, str | None] = dict.fromkeys(names)
        for _ in range(3):
            scope = _Scope(mod, cls, imports, env, globals_)
            cands: dict[str, list[str | None]] = {}

            def add(name: str, t: str | None) -> None:
                cands.setdefault(name, []).append(t)

            for n in ast.walk(fn):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    a = n.args
                    is_root = n is fn
                    for i, x in enumerate([*a.posonlyargs, *a.args, *a.kwonlyargs]):
                        if is_root and skip_first and i == 0:
                            continue
                        ann = getattr(x, "annotation", None)
                        if ann is not None:
                            add(x.arg, self.ann_type(ann, mod, imports))
                        elif is_root and fixtures is not None and x.arg in fixtures:
                            add(x.arg, fixtures[x.arg])
                        else:
                            add(x.arg, None)
                    if a.vararg:
                        add(a.vararg.arg, EXT)
                    if a.kwarg:
                        add(a.kwarg.arg, EXT)
                elif isinstance(n, ast.Assign):
                    if _is_none_const(n.value):
                        continue
                    t = self.expr_type(n.value, scope)
                    for tgt in n.targets:
                        if isinstance(tgt, ast.Name):
                            add(tgt.id, t)
                        else:
                            for nm in _store_names(tgt) if isinstance(tgt, (ast.Tuple, ast.List)) else []:
                                add(nm, None)
                elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                    add(n.target.id, self.ann_type(n.annotation, mod, imports) or self.expr_type(n.value, scope))
                elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                    add(n.target.id, None)
                elif isinstance(n, (ast.For, ast.AsyncFor)):
                    for nm in _store_names(n.target):
                        add(nm, None)
                elif isinstance(n, ast.comprehension):
                    for nm in _store_names(n.target):
                        add(nm, None)
                elif isinstance(n, (ast.With, ast.AsyncWith)):
                    for item in n.items:
                        var = item.optional_vars
                        if isinstance(var, ast.Name):
                            add(var.id, self._with_type(item.context_expr, scope))
                        elif var is not None:
                            for nm in _store_names(var):
                                add(nm, None)
                elif isinstance(n, ast.NamedExpr):
                    add(n.target.id, None)
                elif isinstance(n, ast.ExceptHandler) and n.name:
                    add(n.name, None)
            new = {name: _agree(cands.get(name, [])) for name in sorted(names)}
            if new == env:
                break
            env = new
        return env

    def _with_type(self, ctx: ast.AST, scope: _Scope) -> str | None:
        """`with Ctor(...) as x`: retorno anotado de `__enter__` si existe; si no, el propio tipo."""
        t = self.expr_type(ctx, scope)
        if t is None or t == EXT:
            return t
        enter = self.find_method(t, "__enter__")
        return self.fn_return(enter) if enter else t

    def fixture_types(
        self, tree: ast.Module, mod: str, imports: _Imports, globals_: dict[str, str | None],
        inherited: dict[str, str | None],
    ) -> dict[str, str | None]:  # fmt: skip
        """Tipo de las fixtures de pytest de un archivo: `-> T`, o `return/yield Ctor(...)` concordantes."""
        defs: list[ast.AST] = [
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fixture(n)
        ]
        out: dict[str, str | None] = dict(inherited)
        for _ in range(2):
            for fn in sorted(defs, key=lambda d: (d.lineno, d.name)):  # type: ignore[attr-defined]
                ann = fn.returns  # type: ignore[attr-defined]
                if isinstance(ann, ast.Subscript) and (_chain(ann.value) or [""])[-1] in _GENERATOR_ANNOTATIONS:
                    sl = ann.slice
                    ann = sl.elts[0] if isinstance(sl, ast.Tuple) and sl.elts else sl
                t = self.ann_type(ann, mod, imports)
                if t is None:
                    env = self.local_env(fn, mod, "", imports, globals_, out)
                    scope = _Scope(mod, "", imports, env, globals_)
                    vals: list[ast.AST | None] = []
                    for n in ast.walk(fn):
                        if isinstance(n, ast.Return) and n.value is not None:
                            vals.append(n.value)
                        elif isinstance(n, (ast.Yield,)) and n.value is not None:
                            vals.append(n.value)
                    t = _agree([self.expr_type(v, scope) for v in vals]) if vals else None
                out[fn.name] = t  # type: ignore[attr-defined]
        return out

    # -- resolución de una cadena -----------------------------------------------------------------

    def resolve(
        self, chain: list[str], ctx: _FuncInfo, imports: _Imports, scope: _Scope, class_names: dict[str, set[str]]
    ) -> tuple[str | None, bool]:
        """(destino, weak) para una cadena `a.b.c`.

        1. ruta absoluta por imports (precisa); 2. tipo del receptor (precisa); 3. receptor externo o clase del
        proyecto sin ese método: sin arista; 4. receptor DESCONOCIDO y nombre no externo: nombre único (weak).
        """
        expanded = _expand(chain, ctx, imports, self.project)
        target = _resolve_fn(expanded, self.fn_ids, class_names, self.project) if expanded else None
        if target:
            return target, False
        if len(chain) < 2:
            return None, False
        receiver = self.value_type(chain[:-1], scope)
        if receiver == EXT:
            self.external_skipped += 1
            return None, False
        if receiver == REF:
            return None, False
        if receiver is not None:
            return self.find_method(receiver, chain[-1]), False
        if chain[-1] in _EXTERNAL_METHODS:
            self.external_skipped += 1
            return None, False
        weak = self.fn_ids.weak(chain)
        return (weak, True) if weak else (None, False)


def build_type_index(src: Sources, funcs: dict[str, _FuncInfo]) -> _TypeIndex:
    """Índice de tipos del proyecto (una vez por análisis; compartido por consumes y covers)."""
    return _TypeIndex(src, funcs)


def _add_function_edges(
    graph: ThreadGraph,
    fn: _FuncInfo,
    imports: _Imports,
    fn_ids: _FnIndex,
    class_names: dict[str, set[str]],
    project: set[str],
    tables: set[str],
    types: _TypeIndex,
) -> None:
    globals_ = types.module_types.get(fn.module, {})
    scope = _Scope(fn.module, fn.cls, imports, types.local_env(fn.tree, fn.module, fn.cls, imports, globals_), globals_)
    for node in ast.walk(fn.tree):
        chain: list[str] | None = None
        if isinstance(node, ast.Attribute):
            chain = _chain(node)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            chain = [node.id]
        if not chain:
            continue
        expanded = _expand(chain, fn, imports, project)
        if expanded is None:
            continue
        target, weak = types.resolve(chain, fn, imports, scope, class_names)
        if target and target != fn.node_id:
            graph.add_edge(fn.node_id, target, "consumes", weak=weak)
    # SQL: escrituras y lecturas sobre tablas conocidas.
    writes: set[str] = set()
    reads: set[str] = set()
    for text in _string_constants(fn.tree):
        if len(text) < 12:
            continue
        for rx in _SQL_WRITE_RES:
            writes.update(m.group(1).lower() for m in rx.finditer(text))
        for rx in _SQL_READ_RES:
            reads.update(m.group(1).lower() for m in rx.finditer(text))
    for table in sorted(writes & tables):
        graph.add_edge(fn.node_id, f"state:{table}", "writes")
    for table in sorted((reads - writes) & tables):
        graph.add_edge(fn.node_id, f"state:{table}", "reads")


def extract_state(graph: ThreadGraph, src: Sources) -> set[str]:
    """Nodos `state` desde el DDL de `schemas/database.sql` y desde `CREATE TABLE` en el código."""
    tables: set[str] = set()
    ddl = src.texts.get("schemas/database.sql", "")
    stripped = re.sub(r"--[^\n]*", "", ddl)
    for m in _DDL_RE.finditer(stripped):
        name = m.group(1).lower()
        end = stripped.find("\n);", m.end())
        stmt = stripped[m.start() : (end + 3 if end != -1 else len(stripped))]
        graph.add_node(Node("state", f"state:{name}", sha(" ".join(stmt.split())), {"kind": "table", "source": "ddl"}))
        tables.add(name)
    for pf in src.code.values():
        if pf.tree is None:
            continue
        for node in ast.walk(pf.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "CREATE" in node.value:
                for m in _SQL_CREATE_RE.finditer(node.value):
                    name = m.group(1).lower()
                    if name not in tables:
                        graph.add_node(
                            Node("state", f"state:{name}", sha("code", name), {"kind": "table", "source": "code"})
                        )
                        tables.add(name)
    return tables


# ---------------------------------------------------------------------------
# T4: tools, acciones, capacidades
# ---------------------------------------------------------------------------


def _is_mcp_tool_decorator(dec: ast.AST) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    chain = _chain(target)
    return bool(chain) and chain[-1] == "tool" and chain[0] == "mcp"


def _str_values(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _planned_actions(src: Sources) -> list[str]:
    out: set[str] = set()
    for pf in src.code.values():
        if pf.tree is not None:
            val = find_module_assign(pf.tree, PLANNED_ACTIONS_NAME)
            if val is not None:
                out.update(_str_values(val))
    return sorted(out)


def _tool_actions(fn: ast.AST) -> set[str]:
    """Valores literales comparados con `action`/`act`/`mode` dentro de la tool, más el default de `action`."""
    found: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id in ACTION_VARS:
            for op, comp in zip(node.ops, node.comparators, strict=True):
                if isinstance(op, (ast.Eq, ast.In)):
                    found.update(v for v in _str_values(comp) if _ACTION_RE.match(v))
    args = getattr(fn, "args", None)
    if args is not None:
        names = [a.arg for a in args.args]
        for name, default in zip(names[len(names) - len(args.defaults) :], args.defaults, strict=True):
            if name in ACTION_VARS and isinstance(default, ast.Constant) and isinstance(default.value, str):
                if _ACTION_RE.match(default.value):
                    found.add(default.value)
    return found


def _action_compare(test: ast.AST) -> tuple[str, list[str]] | None:
    """`act in ("a", "b")` / `act == "a"` puro (sin BoolOp): (variable, valores literales); None si no aplica."""
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.left, ast.Name)):
        return None
    if test.left.id not in ACTION_VARS or not isinstance(test.ops[0], (ast.Eq, ast.In)):
        return None
    return test.left.id, [v for v in _str_values(test.comparators[0]) if _ACTION_RE.match(v)]


def _action_aliases(fn: ast.AST, actions: set[str], tables: dict[str, dict[str, str]]) -> dict[str, str]:
    """Alias -> acción canónica, de forma determinista.

    (a) Rama de despacho `if/elif act in ("a", "b", ...)` (test puro, sin BoolOp: una guarda de tier no
        despacha): todos los valores salvo el primero son alias del primero, porque la rama es un único
        cuerpo. Se excluye el valor que el cuerpo vuelve a distinguir (`act == "b"` dentro de la rama).
    (b) Tabla de alias de módulo `*ALIASES = {"alias": "canónica"}` que la tool referencia, cuando ambos
        extremos son acciones de la tool.
    """
    out: dict[str, str] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        parsed = _action_compare(node.test)
        if parsed is None or len(parsed[1]) < 2:
            continue
        _, values = parsed
        inner: set[str] = set()
        for stmt in node.body:
            for sub in ast.walk(stmt):
                inner_parsed = _action_compare(sub) if isinstance(sub, ast.Compare) else None
                if inner_parsed is not None:
                    inner.update(inner_parsed[1])
        canonical = values[0]
        for alias in values[1:]:
            if alias != canonical and alias not in inner and alias in actions and canonical in actions:
                out.setdefault(alias, canonical)
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    for name, table in sorted(tables.items()):
        if name not in used:
            continue
        for alias, canonical in sorted(table.items()):
            if alias in actions and canonical in actions and alias != canonical:
                out.setdefault(alias, canonical)
    # Resolver cadenas alias -> alias hasta la canónica (sin ciclos).
    for alias in sorted(out):
        seen = {alias}
        target = out[alias]
        while target in out and target not in seen:
            seen.add(target)
            target = out[target]
        out[alias] = target
    return {a: c for a, c in out.items() if a != c}


def _alias_tables(tree: ast.Module) -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Dict):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id.upper().endswith("ALIASES"):
                    table = {
                        k.value: v.value
                        for k, v in zip(stmt.value.keys, stmt.value.values, strict=True)
                        if isinstance(k, ast.Constant)
                        and isinstance(k.value, str)
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                    }
                    tables[tgt.id] = table
    return tables


def _default_action(fn: ast.AST) -> str:
    args = getattr(fn, "args", None)
    if args is None:
        return ""
    names = [a.arg for a in args.args]
    for name, default in zip(names[len(names) - len(args.defaults) :], args.defaults, strict=True):
        if name in ("action", "mode") and isinstance(default, ast.Constant) and isinstance(default.value, str):
            return default.value
    return ""


def extract_tools_actions(graph: ThreadGraph, src: Sources, info: ExtractionInfo) -> dict[str, dict[str, Any]]:
    """Tools FastMCP (decorador `@mcp.tool`) y sus acciones. Devuelve metadatos por tool."""
    info.planned_actions = _planned_actions(src)
    server = src.code.get("server.py")
    tools: dict[str, dict[str, Any]] = {}
    if server is None or server.tree is None:
        return tools
    schema_actions = _control_plane_actions(src)
    alias_tables = _alias_tables(server.tree)
    for stmt in server.tree.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_mcp_tool_decorator(d) for d in stmt.decorator_list):
            continue
        name = stmt.name
        chash = _dump_hash(stmt)
        graph.add_node(Node("tool", f"tool:{name}", chash, {"name": name, "module": "server"}))
        graph.add_edge(f"tool:{name}", f"fn:server.{name}", "implemented_by")
        if name == "aep_ctl" and schema_actions:
            actions = {f"{d}.{a}" for d, acts in schema_actions.items() for a in acts}
        else:
            actions = _tool_actions(stmt)
            if name == "autoevol":
                actions -= set(info.planned_actions)
        aliases = {} if name == "aep_ctl" and schema_actions else _action_aliases(stmt, actions, alias_tables)
        tools[name] = {"actions": sorted(actions), "default_action": _default_action(stmt), "aliases": aliases}
        for act in sorted(actions):
            aid = f"action:{name}:{act}"
            graph.add_node(Node("action", aid, sha(name, act), {"tool": name, "name": act, "module": "server"}))
            graph.add_edge(aid, f"fn:server.{name}", "implemented_by")
        for alias, canonical in sorted(aliases.items()):
            graph.add_edge(f"action:{name}:{alias}", f"action:{name}:{canonical}", "alias_of")
    return tools


def _control_plane_actions(src: Sources) -> dict[str, list[str]]:
    pf = src.code.get("engine/privilege.py")
    if pf is None or pf.tree is None:
        return {}
    value = literal_dict_best_effort(find_module_assign(pf.tree, "CONTROL_PLANE_SCHEMA"))
    out: dict[str, list[str]] = {}
    for domain, spec in value.items():
        if isinstance(spec, dict) and isinstance(spec.get("actions"), list):
            out[str(domain)] = sorted(str(a) for a in spec["actions"] if isinstance(a, str))
    return out


_CANON_CALL_RE = re.compile(r"^\s*(\w+)\((.*)\)\s*$", re.DOTALL)
_KW_RE = re.compile(r"\b(domain|action|mode)\s*=\s*[\"']([\w.\-]+)[\"']")


def extract_capabilities(graph: ThreadGraph, src: Sources, tools: dict[str, dict[str, Any]]) -> None:
    """Capacidades, rutas capacidad -> tool/acción y privilegio tool -> capacidad (matriz de degradación)."""
    pf = src.code.get("engine/privilege.py")
    if pf is None or pf.tree is None:
        return
    caps = literal_dict_best_effort(find_module_assign(pf.tree, "_CAPABILITIES"))
    tactical = literal_dict_best_effort(find_module_assign(pf.tree, "_CAP_TACTICAL"))
    matrix_node = find_module_assign(pf.tree, "CHMOD_DEGRADATION_MATRIX")
    matrix_tools: set[str] = set()
    if isinstance(matrix_node, ast.Dict):
        for k, v in zip(matrix_node.keys, matrix_node.values, strict=True):
            if isinstance(k, ast.Constant) and k.value == "tools" and isinstance(v, ast.Dict):
                matrix_tools = {
                    key.value for key in v.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
    for cap in sorted(caps):
        raw = caps[cap]
        graph.add_node(Node("capability", f"capability:{cap}", sha(cap, repr(raw)), {"name": cap}))
    for cap in sorted(caps):
        raw = caps[cap]
        cap_tools = [t for t in (raw[3] if isinstance(raw, tuple) and len(raw) > 3 else []) if isinstance(t, str)]
        for tool in sorted(cap_tools):
            if tool not in tools:
                continue
            graph.add_edge(f"capability:{cap}", f"tool:{tool}", "routes")
            privileged = tool in matrix_tools
            if privileged:
                graph.add_edge(f"tool:{tool}", f"capability:{cap}", "privileged_by")
            # La ruta y el privilegio de la tool se heredan a sus acciones (descubribles y gobernadas por tier).
            for act in tools[tool]["actions"]:
                aid = f"action:{tool}:{act}"
                graph.add_edge(f"capability:{cap}", aid, "routes")
                if privileged:
                    graph.add_edge(aid, f"capability:{cap}", "privileged_by")
    # Llamadas canónicas: ruta explícita capacidad -> acción.
    for cap in sorted(tactical):
        calls = tactical[cap].get("canonical_calls", []) if isinstance(tactical[cap], dict) else []
        for call in calls:
            m = _CANON_CALL_RE.match(str(call))
            if not m or m.group(1) not in tools:
                continue
            kws = dict(_KW_RE.findall(m.group(2)))
            tool = m.group(1)
            act = kws.get("action") or kws.get("mode") or tools[tool]["default_action"]
            if tool == "aep_ctl" and "domain" in kws:
                act = f"{kws['domain']}.{act}"
            graph.add_edge(f"capability:{cap}", f"action:{tool}:{act}", "routes")


# ---------------------------------------------------------------------------
# T7: tests y presupuestos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _TestRefs:
    fns: set[str] = field(default_factory=set)
    weak_fns: set[str] = field(default_factory=set)  # ONT-46: cobertura por nombre único sin tipo
    mods: set[str] = field(default_factory=set)
    tool_calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)  # (tool, kwargs constantes)
    budgets: list[tuple[str, dict[str, str], str, int]] = field(default_factory=list)  # tool, kw, op, limit


def _xfail_ref(fn: ast.AST) -> str:
    for dec in getattr(fn, "decorator_list", []):
        if isinstance(dec, ast.Call) and (_chain(dec.func) or [""])[-1] == "xfail":
            strict = any(
                k.arg == "strict" and isinstance(k.value, ast.Constant) and k.value.value for k in dec.keywords
            )
            for k in dec.keywords:
                if k.arg == "reason" and isinstance(k.value, ast.Constant) and strict:
                    m = re.match(r"\s*(D-\d{2}[a-z]?)", str(k.value.value))
                    if m:
                        return m.group(1)
    return ""


def _field_ref(fn: ast.AST) -> str:
    """ONT-43: `FR-<12hex>` de un xfail estricto (reporte de campo). Inerte hasta que el sig sea promovido."""
    for dec in getattr(fn, "decorator_list", []):
        if isinstance(dec, ast.Call) and (_chain(dec.func) or [""])[-1] == "xfail":
            strict = any(
                k.arg == "strict" and isinstance(k.value, ast.Constant) and k.value.value for k in dec.keywords
            )
            for k in dec.keywords:
                if k.arg == "reason" and isinstance(k.value, ast.Constant) and strict:
                    m = re.match(r"\s*FR-([0-9a-f]{12})(?![0-9a-f])", str(k.value.value))
                    if m:
                        return m.group(1)
    return ""


def _kw_constants(call: ast.Call) -> dict[str, str]:
    return {
        k.arg: str(k.value.value)
        for k in call.keywords
        if k.arg in ("action", "domain", "mode", "verbosity") and isinstance(k.value, ast.Constant)
    }


def _collect_test_refs(
    node: ast.AST,
    ctx: _FuncInfo,
    imports: _Imports,
    fn_ids: _FnIndex,
    class_names: dict[str, set[str]],
    project: set[str],
    tool_names: set[str],
    helpers: dict[str, ast.AST],
    seen: set[str],
    tc: _TypedCtx,
) -> _TestRefs:
    refs = _TestRefs()
    called: set[str] = set()
    env = tc.types.local_env(node, ctx.module, "", imports, tc.globals, tc.fixtures)
    scope = _Scope(ctx.module, "", imports, env, tc.globals)
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in helpers and n.func.id not in seen:
            # Sitio de llamada a helper local: recursar por sitio y fusionar sus kwargs constantes (D-E4-1).
            hname = n.func.id
            called.add(hname)
            sub = _collect_test_refs(
                helpers[hname], ctx, imports, fn_ids, class_names, project, tool_names, helpers, seen | {hname}, tc
            )
            site = _kw_constants(n)
            refs.fns |= sub.fns
            refs.weak_fns |= sub.weak_fns
            refs.mods |= sub.mods
            refs.tool_calls += [(t, {**site, **kws}) for t, kws in sub.tool_calls]
            refs.budgets += sub.budgets
    for n in ast.walk(node):
        chain: list[str] | None = None
        if isinstance(n, ast.Attribute):
            chain = _chain(n)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            chain = [n.id]
        if chain:
            if len(chain) == 1 and chain[0] in helpers and chain[0] not in seen and chain[0] not in called:
                seen.add(chain[0])
                sub = _collect_test_refs(
                    helpers[chain[0]], ctx, imports, fn_ids, class_names, project, tool_names, helpers, seen, tc
                )
                refs.fns |= sub.fns
                refs.weak_fns |= sub.weak_fns
                refs.mods |= sub.mods
                refs.tool_calls += sub.tool_calls
                refs.budgets += sub.budgets
            expanded = _expand(chain, ctx, imports, project)
            if expanded is not None:
                target, weak = tc.types.resolve(chain, ctx, imports, scope, class_names)
                if target:
                    (refs.weak_fns if weak else refs.fns).add(target)
                else:
                    for k in range(len(expanded), 0, -1):
                        if ".".join(expanded[:k]) in project:
                            refs.mods.add(".".join(expanded[:k]))
                            break
        if isinstance(n, ast.Call):
            callee = _chain(n.func)
            if callee:
                expanded = _expand(callee, ctx, imports, project)
                target = _resolve_fn(expanded, fn_ids, class_names, project) if expanded else None
                if target and target.startswith("fn:server."):
                    tname = target.removeprefix("fn:server.")
                    if tname in tool_names:
                        refs.tool_calls.append((tname, _kw_constants(n)))
        if isinstance(n, ast.Dict):
            _collect_dict_tool(n, tool_names, refs)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.endswith(".py"):
            # ONT-46: un test que lanza o toca un archivo del proyecto por ruta (`"aep_front.py"`) cubre su módulo.
            lit = n.value.strip()
            if lit.isascii() and " " not in lit and module_name(lit) in project:
                refs.mods.add(module_name(lit))
    # Presupuestos: `assert tok < N` junto a una llamada a tool dentro del mismo test.
    for n in ast.walk(node):
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id in ("tok", "tokens"):
            for op, comp in zip(n.ops, n.comparators, strict=True):
                if isinstance(op, (ast.Lt, ast.LtE)) and isinstance(comp, ast.Constant) and isinstance(comp.value, int):
                    for tool, kws in refs.tool_calls[:1]:
                        refs.budgets.append((tool, kws, "<=" if isinstance(op, ast.LtE) else "<", comp.value))
    return refs


def _collect_dict_tool(d: ast.Dict, tool_names: set[str], refs: _TestRefs) -> None:
    """Pasos de playbook `{"tool": "x", "params": {"action": "y"}}` cuentan como cobertura."""
    entries = {k.value: v for k, v in zip(d.keys, d.values, strict=True) if isinstance(k, ast.Constant)}
    tool_node = entries.get("tool")
    if not (isinstance(tool_node, ast.Constant) and tool_node.value in tool_names):
        return
    kws: dict[str, str] = {}
    pools = [entries]
    params = entries.get("params")
    if isinstance(params, ast.Dict):
        pools.append(
            {k.value: v for k, v in zip(params.keys, params.values, strict=True) if isinstance(k, ast.Constant)}
        )
    for pool in pools:
        for key in ("action", "domain", "mode"):
            val = pool.get(key)
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                kws[key] = val.value
    refs.tool_calls.append((str(tool_node.value), kws))


def extract_tests(
    graph: ThreadGraph,
    src: Sources,
    funcs: dict[str, _FuncInfo],
    tools: dict[str, dict[str, Any]],
    types: _TypeIndex | None = None,
) -> None:
    """Nodos `test`, aristas `covers` (test -> tool/acción/función) y nodos `budget`."""
    project = _project_modules(src.code)
    fn_ids = _FnIndex(funcs)
    types = types or build_type_index(src, funcs)
    conftest_fixtures = _conftest_fixtures(src, types, project)
    class_names: dict[str, set[str]] = {}
    for f in funcs.values():
        if f.cls:
            class_names.setdefault(f.module, set()).add(f.cls)
    tool_names = set(tools)
    budgets: dict[str, tuple[int, str, str, str, str]] = {}

    for rel, pf in src.tests.items():
        if pf.tree is None:
            continue
        mod = module_name(rel)
        imports = _Imports()
        for local, target, _lazy in _collect_imports(pf.tree.body, mod, False, project):
            imports.names.setdefault(local, target)
        helpers: dict[str, ast.AST] = {}
        test_defs: list[tuple[str, ast.AST]] = []
        for stmt in pf.tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                (test_defs if stmt.name.startswith("test_") else []).append((stmt.name, stmt))
                if not stmt.name.startswith("test_"):
                    helpers[stmt.name] = stmt
            elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
                for sub in stmt.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test_"):
                        test_defs.append((f"{stmt.name}::{sub.name}", sub))
        ctx = _FuncInfo("", mod, "", "", pf.tree)
        globals_ = types.module_globals(pf.tree, mod, imports)
        fixtures = {
            **dict.fromkeys(_PYTEST_EXTERNAL_FIXTURES, EXT),
            **types.fixture_types(pf.tree, mod, imports, globals_, conftest_fixtures),
        }
        tc = _TypedCtx(types, globals_, fixtures)
        for qual, node in test_defs:
            tid = f"test:{rel}::{qual}"
            attrs: dict[str, Any] = {"file": rel, "name": qual}
            ref = _xfail_ref(node)
            if ref:
                attrs["xfail_ref"] = ref
            fref = _field_ref(node)
            if fref:
                attrs["field_ref"] = fref
            graph.add_node(Node("test", tid, _dump_hash(node), attrs))
            refs = _collect_test_refs(node, ctx, imports, fn_ids, class_names, project, tool_names, helpers, set(), tc)
            for fid in sorted(refs.fns | refs.weak_fns):
                graph.add_edge(tid, fid, "covers", weak=fid not in refs.fns)
            for mname in sorted(refs.mods):
                graph.add_edge(tid, f"module:{mname}", "covers")
            for tool, kws in refs.tool_calls:
                graph.add_edge(tid, f"tool:{tool}", "covers")
                for aid in _call_action_ids(tool, kws, tools):
                    graph.add_edge(tid, aid, "covers")
            for tool, kws, op, limit in refs.budgets:
                act = _call_action_ids(tool, kws, tools)
                act_name = act[0].split(":", 2)[2] if act else "*"
                verb = kws.get("verbosity", "default")
                bid = f"budget:{tool}:{act_name}:{verb}"
                prev = budgets.get(bid)
                if prev is None or limit < prev[0]:
                    budgets[bid] = (limit, op, tool, act[0] if act else "", rel)
    for bid in sorted(budgets):
        limit, op, tool, act_id, rel = budgets[bid]
        graph.add_node(Node("budget", bid, sha(bid, op, str(limit)), {"limit": limit, "op": op, "file": rel}))
        graph.add_edge(bid, f"tool:{tool}", "asserts")
        if act_id:
            graph.add_edge(bid, act_id, "asserts")


def _conftest_fixtures(src: Sources, types: _TypeIndex, project: set[str]) -> dict[str, str | None]:
    """Tipos de las fixtures de `tests/conftest.py` (heredadas por todos los archivos de test)."""
    pf = src.tests.get("tests/conftest.py")
    if pf is None or pf.tree is None:
        return {}
    mod = module_name(pf.relpath)
    imports = _Imports()
    for local, target, _lazy in _collect_imports(pf.tree.body, mod, False, project):
        imports.names.setdefault(local, target)
    globals_ = types.module_globals(pf.tree, mod, imports)
    return types.fixture_types(pf.tree, mod, imports, globals_, dict.fromkeys(_PYTEST_EXTERNAL_FIXTURES, EXT))


def _call_action_ids(tool: str, kws: dict[str, str], tools: dict[str, dict[str, Any]]) -> list[str]:
    known = set(tools.get(tool, {}).get("actions", []))
    act = kws.get("action") or kws.get("mode") or tools.get(tool, {}).get("default_action", "")
    if tool == "aep_ctl":
        cand = f"{kws['domain']}.{act}" if "domain" in kws and act else ""
    else:
        cand = act
    return [f"action:{tool}:{cand}"] if cand and cand in known else []


# ---------------------------------------------------------------------------
# T6: claims
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _RawClaim:
    kind: str
    value: str
    file: str
    line: int
    text: str
    hist: bool
    source: str


def _line_claims(line: str, file: str, lineno: int, source: str) -> list[_RawClaim]:
    hist = any(m in line for m in HIST_MARKERS)
    out: list[_RawClaim] = []
    text = " ".join(line.split())[:140]
    for m in _TOOL_COUNT_RE.finditer(line):
        if int(m.group(1)) < 10:  # "4 tools" de un dominio no es el total de la suite
            continue
        out.append(_RawClaim("tool_count", m.group(1), file, lineno, text, hist, source))
    for m in _CAP_COUNT_RE.finditer(line):
        out.append(_RawClaim("capability_count", m.group(1), file, lineno, text, hist, source))
    ranges = [int(m.group(2)) for m in _WF_RANGE_RE.finditer(line)]
    if ranges:
        out.append(_RawClaim("wf_range", str(max(ranges)), file, lineno, text, hist, source))
    for m in _VERSION_RE.finditer(line):
        out.append(_RawClaim("version", m.group(1), file, lineno, text, hist, source))
    return out


def _text_claims(text: str, file: str, base_line: int, source: str) -> list[_RawClaim]:
    out: list[_RawClaim] = []
    for i, line in enumerate(text.splitlines()):
        out.extend(_line_claims(line, file, base_line + i, source))
    return out


def _server_version_literals(tree: ast.Module) -> list[tuple[str, int]]:
    """Literales `"server_version": "v0.2.8"` en dicts (versión declarada a mano, D-12)."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "server_version"
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                    and re.search(r"\d+\.\d+\.\d+", v.value)
                ):
                    found.append((v.value, getattr(v, "lineno", 0)))
    return found


def _doc_lines(src: Sources) -> list[tuple[str, int, str]]:
    """Líneas de documentación de cara al agente: README.md y la constante `_INSTRUCTIONS` del server."""
    lines: list[tuple[str, int, str]] = []
    readme = src.texts.get("README.md", "")
    for i, line in enumerate(readme.splitlines(), start=1):
        lines.append(("README.md", i, line))
    server = src.code.get("server.py")
    if server is not None and server.tree is not None:
        value = find_module_assign(server.tree, "_INSTRUCTIONS")
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for i, line in enumerate(value.value.splitlines()):
                lines.append(("server.py", getattr(value, "lineno", 0) + i, line))
    return lines


def extract_claims(graph: ThreadGraph, src: Sources, tools: dict[str, dict[str, Any]]) -> None:
    """Claims numéricos/de contrato (README y textos del código) y menciones de documentación."""
    raw: list[_RawClaim] = []
    readme = src.texts.get("README.md")
    if readme is not None:
        raw.extend(_text_claims(readme, "README.md", 1, "readme"))
    for rel, pf in src.code.items():
        if pf.tree is None or rel.startswith("engine/threads"):
            continue
        for node in ast.walk(pf.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 12:
                raw.extend(_text_claims(node.value, rel, getattr(node, "lineno", 0), "string"))
        for value, line in _server_version_literals(pf.tree):
            raw.append(
                _RawClaim("version", re.search(r"\d+\.\d+\.\d+", value).group(0), rel, line, value, False, "string")
            )
    seen: dict[str, int] = {}
    for c in sorted(raw, key=lambda r: (r.file, r.line, r.kind, r.value)):
        base = f"claim:{c.file}:{c.kind}:{sha(c.kind, c.value, c.text)[:8]}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        cid = base if n == 0 else f"{base}#{n + 1}"
        attrs = {
            "kind": c.kind,
            "value": c.value,
            "file": c.file,
            "line": c.line,
            "text": c.text,
            "hist": c.hist,
            "source": c.source,
        }
        graph.add_node(Node("claim", cid, sha(c.kind, c.value, c.file, str(c.hist), c.text), attrs))
    _extract_doc_mentions(graph, src, tools)


def _extract_doc_mentions(graph: ThreadGraph, src: Sources, tools: dict[str, dict[str, Any]]) -> None:
    patterns = {t: re.compile(rf"(?<![\w-]){re.escape(t)}(?![\w-])") for t in sorted(tools)}
    seen: dict[str, int] = {}
    for file, lineno, line in _doc_lines(src):
        mentioned = [t for t in sorted(tools) if patterns[t].search(line)]
        if not mentioned:
            continue
        text = " ".join(line.split())
        base = f"claim:{file}:doc:{sha(text)[:8]}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        cid = base if n == 0 else f"{base}#{n + 1}"
        attrs = {
            "kind": "doc",
            "value": "",
            "file": file,
            "line": lineno,
            "text": text[:140],
            "hist": False,
            "source": "doc",
        }
        graph.add_node(Node("claim", cid, sha("doc", file, text), attrs))
        for tool in mentioned:
            graph.add_edge(cid, f"tool:{tool}", "asserts")
            for act in tools[tool]["actions"]:
                last = act.split(".", 1)[-1]
                domain = act.split(".", 1)[0] if "." in act else ""
                quoted_act = re.search(rf"[\"'`]{re.escape(last)}[\"'`]", line)
                quoted_dom = re.search(rf"[\"'`]{re.escape(domain)}[\"'`]", line) if domain else True
                if quoted_act and quoted_dom:
                    graph.add_edge(cid, f"action:{tool}:{act}", "asserts")


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


def build_graph(src: Sources) -> tuple[ThreadGraph, ExtractionInfo]:
    """Construye el grafo completo a partir de los insumos. Pura y determinista."""
    graph = ThreadGraph()
    info = ExtractionInfo(py_version=sys.version.split()[0])
    funcs = extract_code(graph, src, info)
    tools = extract_tools_actions(graph, src, info)
    # tool/acción -> función `server.<tool>`: las aristas implemented_by exigen que exista el nodo función.
    for tool in sorted(tools):
        graph.add_edge(f"tool:{tool}", f"fn:server.{tool}", "implemented_by")
        for act in tools[tool]["actions"]:
            graph.add_edge(f"action:{tool}:{act}", f"fn:server.{tool}", "implemented_by")
    extract_capabilities(graph, src, tools)
    extract_tests(graph, src, funcs, tools, info.type_index)
    extract_claims(graph, src, tools)
    for rel, pf in src.tests.items():
        if pf.tree is None:
            info.errors.append({"file": rel, "error": pf.error})
    info.weak_edges = sum(1 for e in graph.edges() if e.weak)
    info.external_skipped = info.type_index.external_skipped if info.type_index is not None else 0
    return graph, info
