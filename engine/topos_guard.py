"""
Engine: topos_guard.py
Description: Guardián ontológico y detector de co-dependencias (Topos Circuit Breaker).
Audita secuencias de tareas y artefactos antes de su despacho a ejecución para garantizar
que el grafo de dependencias permanezca coherente y sin ciclos bloqueantes (A <-> B sin interfaz).
Analiza también condiciones de Bernstein sobre recursos compartidos (GAP-OM-17).
"""

from __future__ import annotations

from typing import Any


class ToposVerdict:
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    WARN = "WARN"


class ToposGuard:
    @staticmethod
    def audit_task_dag(
        tasks: list[str],
        dependencies: dict[str, list[str]],
        resources: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[str, list[str]]:
        """
        Valida que el grafo de tareas sea un Grafo Dirigido Acíclico (DAG).
        Si existe un ciclo (co-dependencia), bloquea la ejecución y reporta
        el ciclo exacto para su descomposición ontológica.
        Analiza también condiciones de Bernstein sobre recursos compartidos (GAP-OM-17).
        """
        # Construir adyacencia
        adj: dict[str, list[str]] = {t: [] for t in tasks}
        for task, deps in dependencies.items():
            if task not in adj:
                adj[task] = []
            for d in deps:
                if d in adj:
                    adj[task].append(d)

        # 1. Análisis de Bernstein y acoplamiento mutuo sobre recursos mutables (GAP-OM-17)
        warn_logs: list[str] = []
        if resources and isinstance(resources, dict):
            for r_name, r_data in resources.items():
                if not isinstance(r_data, dict):
                    continue
                writers = [str(w) for w in r_data.get("writers", []) if str(w) in adj or str(w) in tasks]
                contract = r_data.get("contract")

                if len(writers) >= 2:
                    # Condición 2: Escritores mutuamente acoplados sin nodo de interfaz
                    for i, w1 in enumerate(writers):
                        for w2 in writers[i + 1:]:
                            def _reaches(src: str, dst: str) -> bool:
                                q = [src]
                                seen = {src}
                                while q:
                                    cur = q.pop(0)
                                    for nxt in adj.get(cur, []):
                                        if nxt == dst:
                                            return True
                                        if nxt not in seen:
                                            if "interface" in nxt.lower():
                                                continue
                                            seen.add(nxt)
                                            q.append(nxt)
                                return False

                            if _reaches(w1, w2) and _reaches(w2, w1):
                                return (
                                    ToposVerdict.BLOCKED,
                                    [
                                        f"Shared mutable state co-dependency detected on resource '{r_name}': writers {sorted([w1, w2])} mutually couple without an interface node.",
                                        "Axioma Topos violado: No se permiten relaciones co-dependientes sin descomposición de interfaz.",
                                    ],
                                )

                    # Condición 1: Write-Write hazard sin contrato declarado
                    if not contract:
                        warn_logs.append(
                            f"Shared write-set hazard on resource '{r_name}': writers {sorted(writers)} without declared contract."
                        )

        # 2. Detección de ciclos estándar DFS
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycle_nodes: list[str] = []

        def dfs(node: str, path: list[str]) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor, path):
                        return True
                elif neighbor in rec_stack:
                    # Ciclo detectado
                    cycle_start = path.index(neighbor)
                    cycle_nodes.extend(path[cycle_start:])
                    cycle_nodes.append(neighbor)
                    return True

            rec_stack.remove(node)
            path.pop()
            return False

        for t in tasks:
            if t not in visited:
                if dfs(t, []):
                    cycle_repr = " -> ".join(cycle_nodes)
                    return (
                        ToposVerdict.BLOCKED,
                        [
                            f"Co-dependencia circular detectada: [{cycle_repr}].",
                            "Axioma Topos violado: No se permiten relaciones co-dependientes sin descomposición de interfaz.",
                        ],
                    )

        if warn_logs:
            return (ToposVerdict.WARN, warn_logs)

        return (ToposVerdict.APPROVED, ["Grafo coherente: Cero co-dependencias detectadas."])
