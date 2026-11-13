"""
Engine: threads_model.py (ONT-40 T1: Thread Graph Model)

Modelo del grafo de hilos de `autoevol`: tipos de nodo, tipos de arista, conjunto requerido de
aristas `Req(t)` (omisión como completitud) y el contenedor `ThreadGraph`.

Topos: hoja pura (solo stdlib). Cero importaciones internas, cero ciclos.

Decisiones de modelado (SDD ONT-40):
  - `consumes` y `contract` forman la relación de dependencia: son las únicas aristas que entran en
    la condensación SCC y en el hash Merkle (HASH_EDGE_KINDS).
  - `observes` (observaciones de probes, DQ-2/F6) queda FUERA de SCC y de Merkle por construcción:
    ninguna consulta de dependencia la ve.
  - `alias_of` (D-23): acción alias -> acción canónica. No entra en SCC ni Merkle (como `observes`, no es
    dependencia). El alias no tiene Req propio y la canónica hereda las aristas entrantes de sus alias.
  - `module` es un tipo adicional al SDD §1.1: la clasificación Topos (dependencia / interdependencia /
    co-dependencia) se aplica a módulos, y el plan (sección 4) clasifica módulos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NODE_TYPES: tuple[str, ...] = (
    "tool",
    "action",
    "capability",
    "function",
    "state",
    "test",
    "claim",
    "budget",
    "module",
)

EDGE_KINDS: tuple[str, ...] = (
    "consumes",
    "contract",
    "writes",
    "reads",
    "covers",
    "asserts",
    "routes",
    "layer",
    "implemented_by",
    "privileged_by",
    "observes",
    "alias_of",
)

# Aristas que definen la dependencia estructural: SCC (Tarjan) y Merkle solo ven estas.
HASH_EDGE_KINDS: frozenset[str] = frozenset({"consumes", "contract"})
SCC_EDGE_KINDS: frozenset[str] = HASH_EDGE_KINDS
# Aristas explícitamente excluidas de SCC y Merkle (observaciones de probes, fuera de R).
OBSERVATION_EDGE_KINDS: frozenset[str] = frozenset({"observes"})

# Req(t): aristas requeridas por tipo. ("out", k) = arista saliente de tipo k; ("in", k) = entrante.
# SDD §2.3: Gap(n) = Req(tipo(n)) \ tipos(aristas(n)); una omisión es una arista faltante.
REQ: dict[str, tuple[tuple[str, str], ...]] = {
    "tool": (
        ("out", "implemented_by"),
        ("in", "covers"),
        ("in", "asserts"),
        ("in", "routes"),
        ("out", "privileged_by"),
    ),
    "action": (
        ("out", "implemented_by"),
        ("in", "covers"),
        ("in", "asserts"),
        ("in", "routes"),
        ("out", "privileged_by"),
    ),
    "capability": (("out", "routes"),),
    "function": (("in", "covers"),),
    "state": (("in", "writes"),),
    "test": (("out", "covers"),),
    "budget": (("out", "asserts"),),
    "claim": (),
    "module": (),
}

# Severidad por arista faltante: fija el peso del gap en el ranking (score = sev x centralidad x alcance).
OMISSION_SEVERITY: dict[tuple[str, str], float] = {
    ("out", "implemented_by"): 1.0,
    ("out", "privileged_by"): 0.9,
    ("in", "covers"): 0.6,
    ("in", "routes"): 0.5,
    ("in", "asserts"): 0.4,
    ("out", "routes"): 0.7,
    ("out", "covers"): 0.1,
    ("out", "asserts"): 0.3,
    ("in", "writes"): 0.2,
}
# La cobertura de tests pesa distinto según el tipo del nodo.
COVERS_SEVERITY_BY_TYPE: dict[str, float] = {"tool": 0.8, "action": 0.6, "function": 0.3}


@dataclass(slots=True)
class Node:
    """Hilo con identidad estable (`id`) y hash de contenido semántico (`content_hash`)."""

    type: str
    id: str
    content_hash: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Edge:
    """Arista tipada. `lazy` marca imports dentro de funciones (calibración T0).

    `weak` (ONT-46): resolución por nombre único sin tipo del receptor (`obj.metodo` con receptor
    desconocido). Cuenta para cobertura y alcance (conservador) pero nunca para la clasificación SCC.
    """

    src: str
    dst: str
    kind: str
    lazy: bool = False
    weak: bool = False


@dataclass(slots=True)
class Gap:
    """Brecha detectada por omisión, drift o violación estructural."""

    id: str
    kind: str
    node: str
    severity: float
    detail: str
    ref: str = ""
    reach: int = 1
    score: float = 0.0


class ThreadGraph:
    """Contenedor dirigido con aristas tipadas. Toda iteración expuesta es determinista (ordenada)."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self._edges: set[Edge] = set()
        self._out: dict[str, list[Edge]] = {}
        self._in: dict[str, list[Edge]] = {}

    def add_node(self, node: Node) -> None:
        if node.type not in NODE_TYPES:
            raise ValueError(f"unknown node type: {node.type}")
        self.nodes[node.id] = node

    def add_edge(self, src: str, dst: str, kind: str, *, lazy: bool = False, weak: bool = False) -> bool:
        """Añade una arista si ambos extremos existen. Devuelve False si se descarta o ya existía.

        Una arista precisa sustituye a su gemela débil (misma src/dst/kind/lazy); una débil nunca desplaza a
        una precisa ya presente.
        """
        if kind not in EDGE_KINDS:
            raise ValueError(f"unknown edge kind: {kind}")
        if src not in self.nodes or dst not in self.nodes:
            return False
        edge = Edge(src, dst, kind, lazy, weak)
        if edge in self._edges:
            return False
        if weak:
            if Edge(src, dst, kind, lazy, False) in self._edges:
                return False
        else:
            twin = Edge(src, dst, kind, lazy, True)
            if twin in self._edges:
                self._edges.discard(twin)
                self._out[src].remove(twin)
                self._in[dst].remove(twin)
        self._edges.add(edge)
        self._out.setdefault(src, []).append(edge)
        self._in.setdefault(dst, []).append(edge)
        return True

    def edges(self, kinds: frozenset[str] | set[str] | None = None) -> list[Edge]:
        pool = self._edges if kinds is None else (e for e in self._edges if e.kind in kinds)
        return sorted(pool, key=lambda e: (e.src, e.dst, e.kind, e.lazy, e.weak))

    def out_edges(self, node_id: str, kind: str | None = None) -> list[Edge]:
        return [e for e in self._out.get(node_id, []) if kind is None or e.kind == kind]

    def in_edges(self, node_id: str, kind: str | None = None) -> list[Edge]:
        return [e for e in self._in.get(node_id, []) if kind is None or e.kind == kind]

    def nodes_of(self, node_type: str) -> list[Node]:
        return sorted((n for n in self.nodes.values() if n.type == node_type), key=lambda n: n.id)

    def edge_count(self) -> int:
        return len(self._edges)

    def type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self.nodes.values():
            counts[n.type] = counts.get(n.type, 0) + 1
        return dict(sorted(counts.items()))


def required_edges(node_type: str) -> tuple[tuple[str, str], ...]:
    """Req(t) para un tipo de nodo."""
    return REQ.get(node_type, ())


def missing_edges(graph: ThreadGraph, node: Node) -> list[tuple[str, str]]:
    """Gap(n) = Req(tipo(n)) \\ aristas presentes. Lista ordenada de (dirección, tipo de arista)."""
    missing: list[tuple[str, str]] = []
    for direction, kind in required_edges(node.type):
        edges = graph.out_edges(node.id, kind) if direction == "out" else graph.in_edges(node.id, kind)
        if not edges:
            missing.append((direction, kind))
    return sorted(missing)


def alias_members(graph: ThreadGraph, node_id: str) -> list[str]:
    """Alias que apuntan (`alias_of`) a `node_id`: su cobertura, doc y routing se heredan a la acción canónica."""
    return sorted(e.src for e in graph.in_edges(node_id, "alias_of"))


def is_alias(graph: ThreadGraph, node_id: str) -> bool:
    """Un alias no es un nodo con Req propio: delega en su acción canónica."""
    return bool(graph.out_edges(node_id, "alias_of"))


def copy_graph(graph: ThreadGraph) -> ThreadGraph:
    """Copia superficial del grafo (nodos compartidos, aristas nuevas): permite añadir `observes` sin tocar la caché."""
    clone = ThreadGraph()
    for node in graph.nodes.values():
        clone.nodes[node.id] = node
    for edge in graph.edges():
        clone.add_edge(edge.src, edge.dst, edge.kind, lazy=edge.lazy, weak=edge.weak)
    return clone
