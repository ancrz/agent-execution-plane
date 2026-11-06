"""ONT-42b B7 (AE-6): tests que "fijan" el contrato viejo de un nodo cambiado.

`impacted_tests` solo sigue aristas `covers`; un test que compara un golden value contra el resultado de una funcion
cambiada sin llamarla por un camino cubierto se pierde. `pinning_tests(graph, changed, root)` lo recupera por AST:

  - Escanea el CUERPO COMPLETO de cada funcion de test (no solo `assert`): los golden values suelen vivir en una
    variable (`expected = {...}`) comparada despues. Incluye decoradores (parametrize) y las constantes/helpers de
    modulo que el test referencia (cierre acotado a `_CLOSURE_DEPTH`).
  - Un identificador cambiado solo cuenta si es discriminante: stoplist de nombres genericos, longitud >= `_MIN_LEN`
    o forma calificada (`modulo.nombre`).
  - Se calcula al seleccionar y NO se guarda en el grafo: el esquema y la raiz R no cambian.
  - Cache por (ruta absoluta, mtime_ns, size) del arbol auditado: los 50+ archivos de tests se parsean una vez.

Solo lectura. Un archivo ilegible o con SyntaxError se ignora (fail-open: menos pins, nunca una excepcion).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from engine.threads_model import ThreadGraph

_MIN_LEN = 5
_CLOSURE_DEPTH = 2
_MAX_STR = 2000
_CACHE_MAX = 512
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

STOPLIST: frozenset[str] = frozenset(
    {
        "status", "get", "set", "summary", "run", "main", "name", "type", "data", "value", "values", "result",
        "results", "error", "errors", "items", "keys", "path", "paths", "file", "files", "list", "dict", "init",
        "self", "none", "true", "false", "text", "args", "kwargs", "json", "load", "loads", "dump", "dumps", "build",
        "create", "check", "parse", "format", "update", "read", "write", "open", "close", "start", "stop", "call",
        "test", "tests", "help", "info", "debug", "terse", "detail", "default", "action", "actions", "verbosity",
        "tool", "tools", "node", "nodes", "graph", "gaps", "root", "mode", "state", "count", "total", "reason",
        "reasons", "payload", "output", "input", "config", "level", "limit", "index", "table", "clear", "reset",
        "write_text", "read_text", "dumps", "append", "extend", "join", "split", "strip", "lower", "upper",
    }
)  # fmt: skip

_FileIndex = dict[str, frozenset[str]]  # qual del test ("test_x" | "Class::test_x") -> identificadores
_CACHE: dict[tuple[str, int, int], _FileIndex] = {}
_stats = {"parsed": 0, "hits": 0}


def cache_stats() -> dict[str, int]:
    return {**_stats, "entries": len(_CACHE)}


def clear_cache() -> None:
    _CACHE.clear()
    _stats.update(parsed=0, hits=0)


def _tokens(node: ast.AST) -> set[str]:
    """Name, Attribute (suelto y en cadena punteada) y cadenas (valor + identificadores contenidos)."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
            chain = _dotted(sub)
            if chain:
                out.add(chain)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            text = sub.value[:_MAX_STR]
            out.add(text)
            out.update(_IDENT_RE.findall(text))
    return out


def _dotted(node: ast.Attribute) -> str:
    parts: list[str] = [node.attr]
    cur: ast.AST = node.value
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _module_defs(tree: ast.Module) -> dict[str, ast.AST]:
    """Helpers y constantes de modulo (no tests) que un test puede referenciar."""
    defs: dict[str, ast.AST] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and not stmt.name.startswith("test_"):
            defs[stmt.name] = stmt
        elif isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    defs[tgt.id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            defs[stmt.target.id] = stmt.value
    return defs


def _closure(node: ast.AST, defs: dict[str, ast.AST]) -> set[str]:
    """Tokens del test mas los de las constantes/helpers de modulo que referencia (profundidad acotada)."""
    toks = _tokens(node)
    seen: set[str] = set()
    frontier = {t for t in toks if t in defs}
    for _ in range(_CLOSURE_DEPTH):
        nxt: set[str] = set()
        for name in sorted(frontier - seen):
            seen.add(name)
            extra = _tokens(defs[name])
            toks |= extra
            nxt |= {t for t in extra if t in defs and t not in seen}
        frontier = nxt
        if not frontier:
            break
    return toks


def _index_file(source: str) -> _FileIndex:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    defs = _module_defs(tree)
    out: _FileIndex = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("test_"):
            out[stmt.name] = frozenset(_closure(stmt, defs))
        elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
            for sub in stmt.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test_"):
                    out[f"{stmt.name}::{sub.name}"] = frozenset(_closure(sub, defs))
    return out


def _file_index(path: Path) -> _FileIndex:
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    hit = _CACHE.get(key)
    if hit is not None:
        _stats["hits"] += 1
        return hit
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _stats["parsed"] += 1
    index = _CACHE[key] = _index_file(source)
    return index


def _eligible(name: str) -> bool:
    return bool(name) and name.lower() not in STOPLIST and len(name) >= _MIN_LEN


def changed_names(graph: ThreadGraph, changed: Iterable[str]) -> tuple[set[str], set[str]]:
    """(simples, calificados) de los nodos cambiados. Un simple debe ser discriminante; un calificado siempre lo es."""
    simple: set[str] = set()
    qualified: set[str] = set()
    for cid in sorted(set(changed)):
        node = graph.nodes.get(cid)
        if node is None:
            continue
        attrs = node.attrs
        if node.type == "function":
            qual = str(attrs.get("qual", ""))
            last = qual.rsplit(".", 1)[-1]
            mod = str(attrs.get("module", ""))
            if _eligible(last):
                simple.add(last)
            elif last:
                qualified.add(f"{mod}.{last}")  # `server.get`: solo si el test lo califica con el modulo
            if "." in qual:
                qualified.add(qual)
        elif node.type == "tool":
            name = str(attrs.get("name", ""))
            if _eligible(name):
                simple.add(name)
        elif node.type == "action":
            name = str(attrs.get("name", ""))
            if _eligible(name):
                simple.add(name)
        elif node.type == "state":
            name = cid.removeprefix("state:")
            if _eligible(name):
                simple.add(name)
    return simple, qualified


def _matches(tokens: frozenset[str], simple: set[str], qualified: set[str]) -> bool:
    if not simple.isdisjoint(tokens):
        return True
    for q in qualified:
        if q in tokens or any(t.endswith("." + q) for t in tokens if "." in t):
            return True
    return False


def pinning_tests(graph: ThreadGraph, changed: Iterable[str], root: Path | str | None = None) -> list[str]:
    """Ids `test:...` cuyo cuerpo (y constantes/helpers de modulo que usa) referencia un nodo cambiado. Ordenado.

    `root` = arbol auditado (el parcheado, no el canonico). Sin `root` no hay donde leer: lista vacia.
    """
    if root is None:
        return []
    simple, qualified = changed_names(graph, changed)
    if not simple and not qualified:
        return []
    tests_dir = Path(root) / "tests"
    if not tests_dir.is_dir():
        return []
    pins: list[str] = []
    for path in sorted(tests_dir.glob("*.py"), key=lambda p: p.name):
        rel = f"tests/{path.name}"
        for qual, tokens in sorted(_file_index(path).items()):
            tid = f"test:{rel}::{qual}"
            if tid in graph.nodes and _matches(tokens, simple, qualified):
                pins.append(tid)
    return sorted(pins)
