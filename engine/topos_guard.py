"""
Engine: topos_guard.py
Description: Guardián ontológico y detector de co-dependencias (Topos Circuit Breaker).
Audita secuencias de tareas y artefactos antes de su despacho a ejecución para garantizar
que el grafo de dependencias permanezca coherente y sin ciclos bloqueantes (A <-> B sin interfaz).
"""


class ToposVerdict:
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


class ToposGuard:
    @staticmethod
    def audit_task_dag(tasks: list[str], dependencies: dict[str, list[str]]) -> tuple[str, list[str]]:
        """
        Valida que el grafo de tareas sea un Grafo Dirigido Acíclico (DAG).
        Si existe un ciclo (co-dependencia), bloquea la ejecución y reporta
        el ciclo exacto para su descomposición ontológica.
        """
        # Construir adyacencia
        adj: dict[str, list[str]] = {t: [] for t in tasks}
        for task, deps in dependencies.items():
            if task not in adj:
                adj[task] = []
            for d in deps:
                if d in adj:
                    adj[task].append(d)

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

        return (ToposVerdict.APPROVED, ["Grafo coherente: Cero co-dependencias detectadas."])
