#!/usr/bin/env python3
"""
Agent Execution Plane (AEP) - Unified FastMCP Server
Exposes deterministic system execution, in-memory Go artifact lifecycle,
asynchronous job queues (Pueue), crash forensics, and Topos DAG auditing to AI agents.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from engine import headless_display
from engine.catalog import ArtifactCatalog
from engine.crash_router import CrashRouter
from engine.hydrator import TemplateHydrator, hydrate_struct, resolve_params
from engine.kanban import KanbanBoard
from engine.playbook import PlaybookStore
from engine.template_registry import TemplateRegistry
from engine import matcher
from engine.privilege import (
    capability_manifest,
    capability_tier,
    privilege_mode,
    privilege_prefix,
)
from engine.topos_guard import ToposGuard

_INSTRUCTIONS = (
    "AEP (Agent Execution Plane): plano de ejecución para GESTIONAR LA AUTONOMÍA de agentes "
    "de IA sobre Ubuntu. Transmuta primitivas de herramientas ofensivas (ejecución en RAM, "
    "sandbox, eBPF, introspección de procesos, forense de crashes) en capacidades agénticas "
    "gobernadas por privilegio en dos niveles: FULL (root/sudo -n -> alcance de sistema/kernel) "
    "y DIMINISHED (usuario -> alcance acotado, fail-soft). PRIMERA LLAMADA RECOMENDADA: "
    "`aep_capabilities()` devuelve un manifiesto estilo chmod/777 (r=sensar, w=actuar, "
    "x=ejecutar por caminos no-tradicionales) con lo que PUEDES hacer ahora mismo. Para un caso "
    "de uso concreto, `discover(use_case)` enruta a qué reutilizar/sintetizar/automatizar."
)

mcp = FastMCP("Agent-Execution-Plane", instructions=_INSTRUCTIONS)
catalog = ArtifactCatalog()
hydrator = TemplateHydrator()
crash_router = CrashRouter()
kanban = KanbanBoard()
playbook_store = PlaybookStore()
template_registry = TemplateRegistry()

# docs_vectorizer se instancia perezosamente (SPEC-OM-4): no crear system_docs.db al arrancar.
_docs_vectorizer = None


def _get_docs_vectorizer():
    global _docs_vectorizer
    if _docs_vectorizer is None:
        from engine.docs_vectorizer import ManPagesVectorizer

        _docs_vectorizer = ManPagesVectorizer()
    return _docs_vectorizer


# Rutas base
PROJECT_DIR = Path(__file__).resolve().parent
TEMP_BIN_DIR = Path.home() / ".local" / "share" / "agent-os" / "bin"
AEP_CTL = PROJECT_DIR / "scripts" / "aep-ctl"
TEMP_BIN_DIR.mkdir(parents=True, exist_ok=True)


@mcp.tool()
def aep_capabilities() -> str:
    """
    [AUTO-DESCRIPCIÓN] Manifiesto de autonomía en primera vista. Devuelve, en códigos estilo
    chmod/777 (r=sensar, w=actuar, x=ejecutar por caminos no-tradicionales), qué puede hacer
    el agente AHORA según el nivel de privilegio (FULL/DIMINISHED) y qué desbloquea FULL.
    Llamar primero para entender que este MCP gestiona autonomía agéntica.
    """
    return json.dumps(capability_manifest(), indent=2, ensure_ascii=False)


@mcp.tool()
def topos_audit_dag(tasks: List[str], dependencies: Dict[str, List[str]]) -> str:
    """
    [TOPOS INTEGRITY PROTOCOL] Audita un grafo de tareas antes de su despacho.
    Detecta co-dependencias circulares (A <-> B) que bloquearían al agente.
    Retorna APPROVED o BLOCKED con el camino de remediación.
    """
    verdict, logs = ToposGuard.audit_task_dag(tasks, dependencies)
    return json.dumps({"verdict": verdict, "details": logs}, indent=2)


@mcp.tool()
def discover(use_case: str, limit: int = 3) -> str:
    """
    [ORIENTACIÓN] Primera parada: traduce un caso de uso en lenguaje natural a QUÉ hacer.
    Enruta con un único llamado a: capacidad sugerida + artefactos REUTILIZABLES (ya construidos,
    ponderados) + PLANTILLAS a sintetizar + PLAYBOOKS a automatizar, todo rankeado. Responde
    "¿qué busco para gestionar esto?" sin que el agente adivine qué tool llamar.
    """
    try:
        caps = capability_manifest().get("capabilities", {})
        # tags = tools (EN) + keywords bilingües -> cierra la colisión ES/EN (descriptions en ES,
        # queries a menudo en EN). El matcher pondera tags x2, dando anclaje léxico language-aligned.
        cap_docs = [{"name": k,
                     "tags": list(v.get("tools", [])) + v.get("keywords", "").split(),
                     "description": v.get("description", "")}
                    for k, v in caps.items()]
        cap = matcher.rank(use_case, cap_docs, limit=2)
        reuse = catalog.browse(query=use_case, limit=limit)
        fb = catalog.template_feedback([t["name"] for t in template_registry.templates])
        synth = template_registry.select(use_case, limit=limit, feedback=fb)
        pb_docs = [{"name": p["name"], "tags": [], "description": p.get("description", "")}
                   for p in playbook_store.list()]
        automate = matcher.rank(use_case, pb_docs, limit=limit)
        return json.dumps({
            "status": "OK", "use_case": use_case,
            "suggested_capability": [{"capability": c["name"], "relevance": c["relevance"]} for c in cap],
            "reuse_artifacts": [{"name": a.get("name"), "category": a.get("category"),
                                 "promotion_score": a.get("promotion_score"),
                                 "semantic_distance": a.get("semantic_distance")} for a in reuse],
            "synthesize_templates": [{"name": t["name"], "capability": t.get("capability"),
                                      "relevance": t["relevance"],
                                      "proven": t.get("proven")} for t in synth],
            "automate_playbooks": [{"name": p["name"], "relevance": p["relevance"]} for p in automate],
            "hint": "Reutiliza un artefacto si encaja (ya ponderado); si no, sintetiza desde una "
                    "plantilla; para un flujo multi-paso, un playbook; para GC seguro, artifact_catalog(action='prune') o playbook_run(action='prune').",
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def artifact_catalog(
    action: str = "browse",
    category: Optional[str] = None,
    query: Optional[str] = None,
    intent: Optional[str] = None,
    limit: int = 10,
    force: bool = False,
    apply: bool = False,
) -> str:
    """
    [MEMORIA SEMÁNTICA UNIFICADA] Punto único para descubrir, consultar en caché,
    auto-indexar (sqlite-vec) y podar (GC seguro) el catálogo de artefactos.
    action:
      - 'browse' (default): lista/busca artefactos (con `query` -> top-K semántico; sin `query` -> ranking por confianza).
      - 'query': busca un artefacto validado para `intent` (o `query`) y `category` -> CACHE_HIT / CACHE_MISS.
      - 'reindex': sana el índice vectorial sqlite-vec (force=True re-embebe todos) y devuelve cobertura antes/después.
      - 'prune': poda destructiva segura de artefactos degradados (reusable=0), protegiendo plantillas base (apply=False -> DRY_RUN).
    """
    try:
        act = (action or "browse").strip().lower()
        if act == "browse":
            items = catalog.browse(category=category, query=query or intent, limit=limit)
            return json.dumps(
                {
                    "status": "OK",
                    "capability_tier": capability_tier(),
                    "count": len(items),
                    "artifacts": items,
                },
                indent=2,
                ensure_ascii=False,
            )
        elif act == "query":
            eff_intent = (intent or query or "").strip()
            if not eff_intent or not category:
                return json.dumps(
                    {
                        "status": "PARAM_ERROR",
                        "error": "Acción 'query' requiere los parámetros 'intent' (o 'query') y 'category'.",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            hit = catalog.find_hybrid(eff_intent, category)
            if hit:
                return json.dumps(
                    {
                        "status": "CACHE_HIT",
                        "artifact_id": hit["id"],
                        "name": hit["name"],
                        "category": hit["category"],
                        "version": hit["version"],
                        "success_rate": hit["success_rate"],
                        "execution_count": hit["execution_count"],
                        # Campos aditivos (no rompen consumidores previos):
                        "retrieval_mode": hit.get("retrieval_mode", "exact_hash"),
                        "semantic_distance": hit.get("semantic_distance"),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "status": "CACHE_MISS",
                    "message": "No se encontró artefacto en caché. Proceder a hidratar o sintetizar.",
                    "available_templates": hydrator.list_available_templates(),
                    "semantic_available": catalog._vec_available,
                },
                indent=2,
                ensure_ascii=False,
            )
        elif act == "reindex":
            before = catalog.index_coverage()
            result = catalog.reindex(force=force)
            after = catalog.index_coverage()
            return json.dumps(
                {
                    "status": result.get("status", "OK"),
                    "reindex": result,
                    "coverage_before": before,
                    "coverage_after": after,
                },
                indent=2,
                ensure_ascii=False,
            )
        elif act == "prune":
            protect = {t["name"] for t in template_registry.catalog()} | {"socket_monitor", "fd_rescuer"}
            return json.dumps(
                catalog.prune(protect=protect, apply=apply),
                indent=2,
                ensure_ascii=False,
            )
        else:
            return json.dumps(
                {
                    "status": "INVALID_ACTION",
                    "error": f"Acción '{action}' no reconocida. Acciones válidas: 'browse', 'query', 'reindex', 'prune'.",
                },
                indent=2,
                ensure_ascii=False,
            )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def artifact_lint_and_build(
    action: str = "build",
    name: Optional[str] = None,
    intent: Optional[str] = None,
    category: Optional[str] = None,
    go_source: Optional[str] = None,
    template_name: Optional[str] = None,
    source_template: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    cue_contract: str = "",
    limit: int = 5,
) -> str:
    """
    [PICO-JENKINS / QUALITY GATE & ARTIFACT SYNTHESIS]
    Herramienta polimórfica unificada para la síntesis, selección, hidratación y compilación de artefactos Go.
    Acciones soportadas ('action'):
      - 'build' (default): Compila Go estático (CGO_ENABLED=0), ejecuta análisis estático (go vet + golangci-lint)
        y lo registra en el catálogo. Soporta ATAJO DE 1 PASO: si no se provee go_source pero sí template_name
        (o source_template), hidrata la plantilla automáticamente antes de compilar.
      - 'catalog': Tabla descriptiva de plantillas base disponibles con capacidades, tags y redundancias.
      - 'select': Rankea plantillas por relevancia a 'intent' mediante scoring multi-señal (BM25F + jaccard + fuzzy).
      - 'hydrate': Instancia una plantilla Go con 'params', generando el código fuente final.
    """
    try:
        act = (action or "build").strip().lower()

        if act == "catalog":
            fb = catalog.template_feedback([t["name"] for t in template_registry.templates])
            return json.dumps(
                {
                    "status": "OK",
                    "templates": template_registry.catalog(feedback=fb),
                    "redundancy": template_registry.redundancy(),
                },
                indent=2,
                ensure_ascii=False,
            )

        if act == "select":
            if not intent or not intent.strip():
                return json.dumps(
                    {
                        "status": "PARAM_ERROR",
                        "error": "El parámetro 'intent' es obligatorio para la acción 'select'.",
                    },
                    indent=2,
                )
            fb = catalog.template_feedback([t["name"] for t in template_registry.templates])
            matches = template_registry.select(intent.strip(), limit=limit, feedback=fb)
            return json.dumps(
                {"status": "OK", "intent": intent.strip(), "matches": matches},
                indent=2,
                ensure_ascii=False,
            )

        if act == "hydrate":
            tpl = (template_name or source_template or name or "").strip()
            if not tpl:
                return json.dumps(
                    {
                        "status": "PARAM_ERROR",
                        "error": "Debe proporcionar 'template_name' (o 'source_template') para hidratar.",
                    },
                    indent=2,
                )
            contract = template_registry.get_contract(tpl)
            source_code = hydrator.hydrate(tpl, params or {}, contract=contract)
            return json.dumps(
                {"status": "SUCCESS", "template_name": tpl, "go_source": source_code},
                indent=2,
            )

        if act == "build":
            missing = []
            if not name or not name.strip():
                missing.append("name")
            if not intent or not intent.strip():
                missing.append("intent")
            if not category or not category.strip():
                missing.append("category")
            if missing:
                return json.dumps(
                    {
                        "status": "PARAM_ERROR",
                        "error": f"Faltan parámetros obligatorios para la acción 'build': {', '.join(missing)}",
                    },
                    indent=2,
                )

            art_name = name.strip()
            art_intent = intent.strip()
            art_cat = category.strip()
            art_src_tpl = (source_template or template_name or "").strip()
            effective_src = (go_source or "").strip()

            # 1-Step Template-to-Binary Compilation Shortcut
            if not effective_src:
                if art_src_tpl:
                    try:
                        contract = template_registry.get_contract(art_src_tpl)
                        effective_src = hydrator.hydrate(art_src_tpl, params or {}, contract=contract)
                    except Exception as he:
                        return json.dumps(
                            {
                                "status": "HYDRATE_ERROR",
                                "error": f"Error al auto-hidratar la plantilla '{art_src_tpl}': {str(he)}",
                            },
                            indent=2,
                        )
                else:
                    return json.dumps(
                        {
                            "status": "PARAM_ERROR",
                            "error": "Debe proporcionar 'go_source' o 'template_name'/'source_template' para compilar.",
                        },
                        indent=2,
                    )

            with tempfile.TemporaryDirectory() as tmpdir:
                src_file = Path(tmpdir) / f"{art_name}.go"
                src_file.write_text(effective_src, encoding="utf-8")
                bin_file = TEMP_BIN_DIR / art_name

                # 1. Validación estática con go vet
                vet_res = subprocess.run(["go", "vet", str(src_file)], capture_output=True, text=True)
                if vet_res.returncode != 0:
                    return json.dumps(
                        {
                            "status": "LINT_ERROR",
                            "error": vet_res.stderr.strip(),
                            "recommendation": "Corrija los tipos y llamadas en el código Go antes de compilar.",
                        },
                        indent=2,
                    )

                # 1.5. golangci-lint ADVISORY (no bloqueante). go vet sigue siendo el gate duro.
                lint_warnings: List[str] = []
                try:
                    gcl = subprocess.run(
                        ["golangci-lint", "run", str(src_file)],
                        capture_output=True, text=True, cwd=tmpdir, timeout=30,
                    )
                    if gcl.returncode != 0:
                        out = (gcl.stdout or gcl.stderr or "").strip()
                        if out:
                            lint_warnings = out.splitlines()[:20]
                except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
                    lint_warnings = []

                # 2. Compilación estática pura (CGO_ENABLED=0)
                start_time = time.time()
                env = os.environ.copy()
                env["CGO_ENABLED"] = "0"
                build_res = subprocess.run(
                    ["go", "build", "-ldflags=-s -w", "-o", str(bin_file), str(src_file)],
                    capture_output=True,
                    text=True,
                    env=env,
                )
                compile_latency_ms = round((time.time() - start_time) * 1000, 2)

                if build_res.returncode != 0:
                    return json.dumps(
                        {
                            "status": "BUILD_ERROR",
                            "error": build_res.stderr.strip(),
                        },
                        indent=2,
                    )

                binary_bytes = bin_file.read_bytes()
                artifact_id = catalog.register_artifact(
                    name=art_name,
                    intent=art_intent,
                    category=art_cat,
                    cue_contract=cue_contract or "package schema",
                    go_source=effective_src,
                    binary_blob=binary_bytes,
                    source_template=art_src_tpl,
                )

                kanban_task_id = None
                try:
                    kt = kanban.create_task(title=f"build:{art_name}", intent=art_intent, category=art_cat, artifact_name=art_name)
                    kanban_task_id = kt["task_id"]
                    kanban.advance(kanban_task_id, "LINTED", lint_passed=True,
                                   note=f"go vet OK; {len(lint_warnings)} avisos golangci-lint")
                except Exception:
                    pass

                return json.dumps(
                    {
                        "status": "SUCCESS",
                        "artifact_id": artifact_id,
                        "name": art_name,
                        "source_template": art_src_tpl or None,
                        "binary_path": str(bin_file),
                        "binary_size_bytes": len(binary_bytes),
                        "compile_time_ms": compile_latency_ms,
                        "lint_warnings": lint_warnings,
                        "kanban_task_id": kanban_task_id,
                    },
                    indent=2,
                )

        return json.dumps(
            {
                "status": "INVALID_ACTION",
                "error": f"Acción '{act}' no válida para artifact_lint_and_build.",
                "valid_actions": ["build", "catalog", "select", "hydrate"],
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def artifact_execute_in_ram(name: str, args: Optional[List[str]] = None) -> str:
    """
    [CAMINO A / MEMFD EXECUTION] Carga un binario Go del catálogo o de bin/
    y lo inyecta directamente en memoria RAM vía memfd_create sin tocar almacenamiento secundario.
    """
    bin_file = TEMP_BIN_DIR / name
    elf_bytes: Optional[bytes] = None
    if bin_file.exists():
        elf_bytes = bin_file.read_bytes()
    else:
        blob = catalog.get_binary_blob(name)
        if blob:
            elf_bytes = blob
            try:
                bin_file.write_bytes(blob)
                bin_file.chmod(0o755)
            except Exception:
                pass

    if not elf_bytes:
        return json.dumps({"status": "ERROR", "error": f"Binario no encontrado: {name}"})
    cmd_args = args or []

    start_time = time.time()
    fd = None
    try:
        fd = os.memfd_create(f"anon_{name}", 0)
        os.write(fd, elf_bytes)
        os.lseek(fd, 0, os.SEEK_SET)

        try:
            res = subprocess.run(
                [f"/proc/self/fd/{fd}"] + cmd_args,
                capture_output=True,
                text=True,
                pass_fds=(fd,),
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "status": "TIMEOUT",
                    "error": f"Artefacto '{name}' excedió el timeout de 30s (posible proceso daemonizado con descriptores abiertos).",
                },
                indent=2,
                ensure_ascii=False,
            )

        latency_ms = round((time.time() - start_time) * 1000, 2)

        stdout_parsed: Any = res.stdout.strip()
        try:
            stdout_parsed = json.loads(res.stdout)
        except Exception:
            pass

        # Cierra el lazo de telemetría: cada ejecución alimenta success_rate/execution_count,
        # que ponderan la reutilización del artefacto (dimensiones reliability/experience).
        recorded = catalog.record_execution_by_name(
            name, res.returncode, latency_ms,
            error_message=(res.stderr.strip()[:500] if res.returncode != 0 and res.stderr else None),
        )
        kanban_canary = kanban.record_canary_by_artifact(name, res.returncode == 0)

        return json.dumps(
            {
                "status": "SUCCESS" if res.returncode == 0 else "EXEC_FAILED",
                "exit_code": res.returncode,
                "latency_ms": latency_ms,
                "output": stdout_parsed,
                "stderr": res.stderr.strip() if res.stderr else None,
                "metric_recorded": recorded,  # True si alimentó la ponderación del catálogo
                "kanban_canary": kanban_canary,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass


def _ensure_pueue_daemon() -> Optional[str]:
    """
    Localiza el binario pueue y verifica si pueued responde.
    Si el daemon no responde, lo inicia en segundo plano completamente desacoplado
    (stdin/stdout/stderr=DEVNULL, close_fds=True, start_new_session=True) para evitar bloqueos
    o herencia de descriptores de archivo en el servidor FastMCP.
    """
    pueue_bin = shutil.which("pueue") or (
        str(Path.home() / ".local/bin/pueue") if (Path.home() / ".local/bin/pueue").exists() else None
    )
    if not pueue_bin:
        return None

    try:
        res = subprocess.run(
            [pueue_bin, "status", "--json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            close_fds=True,
            timeout=5,
        )
        if res.returncode == 0:
            return pueue_bin
    except Exception:
        pass

    # El daemon no responde o no está corriendo; intentar auto-inicio desacoplado
    pueued_bin = shutil.which("pueued") or (
        str(Path.home() / ".local/bin/pueued") if (Path.home() / ".local/bin/pueued").exists() else None
    )
    if not pueued_bin:
        return None

    try:
        subprocess.Popen(
            [pueued_bin, "-d"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        # Esperar hasta 2 segundos a que el socket UNIX responda
        for _ in range(6):
            time.sleep(0.3)
            try:
                chk = subprocess.run(
                    [pueue_bin, "status", "--json"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    close_fds=True,
                    timeout=2,
                )
                if chk.returncode == 0:
                    return pueue_bin
            except Exception:
                pass
    except Exception:
        return None

    return pueue_bin


@mcp.tool()
def async_job_dispatch(
    action: str = "dispatch",
    command: Optional[str] = None,
    label: Optional[str] = None,
    group: str = "default",
    working_dir: Optional[str] = None,
    task_id: Optional[int] = None,
    lines: int = 50,
) -> str:
    """
    [CAMINO B / PUEUE] Despacho e inspección unificada de tareas asíncronas en Pueue.
    action: 'dispatch' (default), 'inspect', 'status', 'log'.
    - 'dispatch': Encola un comando de larga duración en segundo plano (requiere 'command').
    - 'inspect' / 'status': Consulta el estado global de la cola o logs si se especifica 'task_id'.
    - 'log': Extrae el log aislado del 'task_id' especificado ('lines' por defecto 50).
    Devuelve inmediatamente JSON tipado con fail-soft sin bloquear el loop del agente.
    """
    act = (action or "dispatch").strip().lower()

    try:
        if act == "dispatch":
            if not command or not command.strip():
                return json.dumps(
                    {
                        "status": "PARAM_ERROR",
                        "error": "Acción 'dispatch' requiere 'command' no vacío.",
                    },
                    indent=2,
                    ensure_ascii=False,
                )

            pueue_bin = _ensure_pueue_daemon()
            if not pueue_bin:
                return json.dumps(
                    {
                        "status": "DEGRADED",
                        "message": "pueue binary is not installed on host or daemon is unavailable. Camino B requires pueue daemon.",
                        "command": command,
                    },
                    indent=2,
                    ensure_ascii=False,
                )

            cmd = [pueue_bin, "add", "--print-task-id", "--group", group]
            if label:
                cmd.extend(["--label", label])
            if working_dir:
                cmd.extend(["--working-directory", working_dir])
            cmd.extend(["--", command])

            res = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                close_fds=True,
                timeout=10,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return json.dumps(
                    {
                        "status": "DEGRADED",
                        "message": "Failed to dispatch async task to pueue daemon",
                        "stderr": res.stderr.strip(),
                        "exit_code": res.returncode,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            try:
                tid = int(res.stdout.strip())
            except ValueError:
                tid = res.stdout.strip()
            return json.dumps(
                {"status": "queued", "task_id": tid, "group": group, "command": command},
                indent=2,
                ensure_ascii=False,
            )

        elif act in ("inspect", "status", "log"):
            if act == "log" and task_id is None:
                return json.dumps(
                    {
                        "status": "PARAM_ERROR",
                        "error": "Acción 'log' requiere 'task_id'.",
                    },
                    indent=2,
                    ensure_ascii=False,
                )

            pueue_bin = _ensure_pueue_daemon()
            if not pueue_bin:
                return json.dumps(
                    {
                        "status": "DEGRADED",
                        "message": "pueue binary is not installed on host or daemon is unavailable",
                    },
                    indent=2,
                    ensure_ascii=False,
                )

            if task_id is not None:
                res = subprocess.run(
                    [pueue_bin, "log", str(task_id), "--lines", str(lines), "--json"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    close_fds=True,
                    timeout=10,
                )
                if res.returncode != 0 or not res.stdout.strip():
                    return json.dumps(
                        {
                            "status": "DEGRADED",
                            "message": f"Failed to retrieve log for task {task_id}",
                            "stderr": res.stderr.strip(),
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                return res.stdout
            else:
                res = subprocess.run(
                    [pueue_bin, "status", "--json"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    close_fds=True,
                    timeout=10,
                )
                if res.returncode != 0 or not res.stdout.strip():
                    return json.dumps(
                        {
                            "status": "DEGRADED",
                            "message": "Failed to connect to pueue daemon",
                            "stderr": res.stderr.strip(),
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                return res.stdout

        else:
            return json.dumps(
                {
                    "status": "INVALID_ACTION",
                    "error": f"Acción '{action}' no válida para async_job_dispatch.",
                    "valid_actions": ["dispatch", "inspect", "status", "log"],
                },
                indent=2,
                ensure_ascii=False,
            )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2, ensure_ascii=False)


@mcp.tool()
def diagnose_system_crashes(
    action: str = "diagnose",
    limit: int = 5,
    resolve_after_report: bool = False,
) -> str:
    """
    [FORENSE DE CRASHES UNIFICADO] Diagnóstico estructurado de volcados de memoria
    (systemd-coredump), errores de journald y enrutamiento proactivo de tickets.
    action:
      - 'diagnose' (default): inspecciona coredumps recientes y errores críticos del journal.
      - 'alerts' (alias 'check'): enrutador proactivo de fallos; diffea coredumps contra el catálogo.
    """
    try:
        if action == "diagnose":
            # FAIL-SOFT: en hosts sin systemd-coredump/journald (contenedores, no-systemd) los
            # binarios pueden faltar. Devolvemos JSON tipado degradado, nunca una excepción.
            # Nivel FULL: prefijo sudo -n para ver coredumps/errores de TODO el sistema; DIMINISHED
            # (sin escalada) ve solo lo propio. Ambos fail-soft.
            prefix = privilege_prefix() or []

            def _safe_run(cmd: List[str]) -> Optional[subprocess.CompletedProcess]:
                try:
                    return subprocess.run(
                        prefix + cmd,
                        capture_output=True,
                        text=True,
                        stdin=subprocess.DEVNULL,
                        close_fds=True,
                        timeout=15,
                    )
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    return None

            unavailable = []

            coredumps_raw = _safe_run(["coredumpctl", "list", "--json=short", "-n", str(limit)])
            recent_coredumps = []
            if coredumps_raw is None:
                unavailable.append("coredumpctl")
            elif coredumps_raw.returncode == 0 and coredumps_raw.stdout.strip():
                try:
                    recent_coredumps = json.loads(coredumps_raw.stdout)
                except Exception:
                    pass

            journal_errs = _safe_run(["journalctl", "-p", "err", "-n", str(limit), "-o", "json"])
            recent_errors = []
            if journal_errs is None:
                unavailable.append("journalctl")
            else:
                for line in journal_errs.stdout.splitlines():
                    if line.strip():
                        try:
                            recent_errors.append(json.loads(line))
                        except Exception:
                            pass

            return json.dumps(
                {
                    "status": "DEGRADED" if unavailable else "OK",
                    "capability_tier": capability_tier(),
                    "scope": "system" if prefix else "user",
                    "recent_coredumps": recent_coredumps,
                    "recent_systemd_errors": recent_errors,
                    "unavailable_sources": unavailable,
                },
                indent=2,
            )

        elif action in ("alerts", "check"):
            return json.dumps(crash_router.check(resolve_after_report), indent=2)

        else:
            return json.dumps(
                {
                    "status": "INVALID_ACTION",
                    "error": f"Acción desconocida '{action}'",
                    "valid_actions": ["diagnose", "alerts", "check"],
                },
                indent=2,
                ensure_ascii=False,
            )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2, ensure_ascii=False)


@mcp.tool()
def sandbox_run(command: str, share_net: bool = True) -> str:
    """
    [BUBBLEWRAP SANDBOX] Ejecuta comandos en un sandbox efímero con bwrap
    aislando el sistema de archivos contra efectos secundarios destructivos.
    """
    bwrap_cmd = [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/sbin", "/sbin",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--unshare-pid",
    ]
    if not share_net:
        bwrap_cmd.append("--unshare-net")
    bwrap_cmd.extend(["--", "sh", "-c", command])

    try:
        res = subprocess.run(bwrap_cmd, capture_output=True, text=True)
        return json.dumps(
            {
                "exit_code": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def aep_ctl(domain: str, action: str, name: Optional[str] = None) -> str:
    """
    [SPEC-OM-1 / UNIFIED CONTROL PLANE] Plano de control determinista del sistema.
    domain: service|network|storage|package. Salida JSON tipada, no-interactiva.
    Ej: aep_ctl("network","listeners") | aep_ctl("package","check","nginx").
    """
    if not AEP_CTL.exists():
        return json.dumps({"status": "ERROR", "error": f"aep-ctl no encontrado en {AEP_CTL}"}, indent=2)
    cmd = ["python3", str(AEP_CTL), domain, action]
    if name:
        cmd.append(name)
    cmd.append("--json")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return res.stdout.strip() or json.dumps(
            {"status": "ERROR", "stderr": res.stderr.strip()}, indent=2
        )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


def check_crash_alerts(resolve_after_report: bool = False) -> str:
    """
    [SPEC-OM-2 / PROACTIVE CRASH ROUTING] Enrutador proactivo de fallos: diffea los
    coredumps recientes contra el catálogo y entrega los nuevos tickets estructurados
    antes de que el agente actúe. (Des-registrado de MCP en Fase 6; unificado en diagnose_system_crashes).
    """
    return diagnose_system_crashes(action="alerts", resolve_after_report=resolve_after_report)


@mcp.tool()
def query_system_docs(query: str, limit: int = 3, ingest_command: Optional[str] = None) -> str:
    """
    [SPEC-OM-4 / DOCS VECTORIZER] Memoria semántica local de man-pages (sqlite-vec).
    Devuelve la sintaxis exacta de herramientas del sistema sin alucinar ni navegar la web.
    `ingest_command`: ingiere la man-page de un comando extra on-demand antes de consultar.
    """
    try:
        dv = _get_docs_vectorizer()
        if ingest_command:
            dv.ingest_command(ingest_command)
        return json.dumps(dv.query(query, limit), indent=2)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def visual_inspect(
    url: str,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    selector: Optional[str] = None,
    full_page: bool = True,
) -> str:
    """
    [SPEC-OM-5 / HEADLESS DISPLAY] Renderiza una URL (http(s):// o file://) en Chromium
    headless y captura un screenshot en RAM (/dev/shm), devuelto en base64. Para validar
    layouts/UI en servidores sin pantalla. FAIL-SOFT si no hay navegador.
    """
    try:
        return json.dumps(
            headless_display.visual_inspect(
                url, viewport_width, viewport_height, selector, full_page
            ),
            indent=2,
        )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


_BPFTRACE_MODES = {
    # eBPF (rootkit/sniffer ofensivo) -> observabilidad de kernel no-invasiva.
    "syscall_count": "tracepoint:raw_syscalls:sys_enter {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "file_opens": "tracepoint:syscalls:sys_enter_openat {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "tcp_connect": "kprobe:tcp_connect {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
}


@mcp.tool()
def kernel_trace(mode: str = "syscall_count", duration_sec: int = 3) -> str:
    """
    [eBPF / KERNEL OBSERVABILITY] Telemetría de kernel no-invasiva vía bpftrace.
    modes: syscall_count | file_opens | tcp_connect. Muestrea `duration_sec` y auto-sale.
    FAIL-SOFT: sin bpftrace o sin privilegios (CAP_BPF/root) devuelve DEGRADED, no explota.
    """
    if mode not in _BPFTRACE_MODES:
        return json.dumps({"status": "ERROR", "error": f"mode inválido: {mode}",
                           "valid": list(_BPFTRACE_MODES)}, indent=2)
    if not Path("/usr/bin/bpftrace").exists() and not shutil.which("bpftrace"):
        return json.dumps({"status": "DEGRADED", "message": "bpftrace no instalado."}, indent=2)
    # bpftrace exige root. Modalidad de escalada no-interactiva: usar sudo -n si no somos root.
    prefix = privilege_prefix()
    if prefix is None:
        return json.dumps({
            "status": "DEGRADED",
            "capability_tier": "DIMINISHED",
            "message": "bpftrace requiere root (CAP_BPF) y no hay sudo -n disponible.",
        }, indent=2)
    pmode = privilege_mode()
    script = _BPFTRACE_MODES[mode].format(d=max(1, min(duration_sec, 30)))
    try:
        # El script proviene de _BPFTRACE_MODES (curado, solo-lectura), nunca de entrada libre.
        res = subprocess.run(
            prefix + ["bpftrace", "-f", "json", "-e", script],
            capture_output=True, text=True, timeout=max(5, duration_sec + 10),
        )
        if res.returncode != 0:
            return json.dumps({
                "status": "DEGRADED",
                "capability_tier": "FULL",
                "privilege_mode": pmode,
                "message": "bpftrace falló pese a la escalada.",
                "stderr": res.stderr.strip()[:300],
            }, indent=2)
        counts = {}
        for line in res.stdout.splitlines():
            try:
                obj = json.loads(line)
                if obj.get("type") == "map":
                    for _, m in obj.get("data", {}).items():
                        if isinstance(m, dict):
                            counts.update(m)
            except Exception:
                pass
        return json.dumps({"status": "OK", "capability_tier": "FULL", "mode": mode,
                           "duration_sec": duration_sec, "privilege_mode": pmode,
                           "counts": counts}, indent=2)
    except Exception as e:
        return json.dumps({"status": "DEGRADED", "error": str(e)}, indent=2)


@mcp.tool()
def kanban_board(
    action: str = "board",
    include_archived: bool = False,
    task_id: Optional[int] = None,
    title: str = "",
    intent: str = "",
    category: str = "",
    artifact_name: Optional[str] = None,
    to_state: str = "",
    lint_passed: Optional[bool] = None,
    canary_passed: Optional[bool] = None,
    note: Optional[str] = None,
    reason: Optional[str] = None,
    states: Optional[List[str]] = None,
    max_score: Optional[float] = None,
    apply: bool = False,
) -> str:
    """
    [PICO-KANBAN UNIFICADO] Tablero de estados abstracto y ponderación agéntica (transparente al usuario).
    action:
      - 'board' (default): vista del tablero por lanes (BACKLOG/SYNTHESIZED/LINTED/CANARY/PROMOTED/REJECTED).
      - 'create' (o 'task_create'): crea una tarea atómica en BACKLOG (requiere `title`).
      - 'advance': mueve una tarea de estado y recalcula su ponderación (requiere `task_id` y `to_state`).
      - 'promote': promueve el artefacto ligado como reutilizable si alcanza TRUST (requiere `task_id`).
      - 'demote': degrada explícitamente un artefacto a reusable=0 (requiere `artifact_name`).
      - 'reevaluate': re-pondera artefactos reusables y degrada solo los que tienen fallo demostrado.
      - 'archive': archiva (soft, reversible) tareas estancadas (apply=False -> DRY_RUN).
      - 'unarchive': reactiva una tarea archivada (requiere `task_id`).
    """
    try:
        act = (action or "board").strip().lower()
        if act == "board":
            return json.dumps(kanban.board(include_archived=include_archived), indent=2, ensure_ascii=False)
        elif act in ("create", "task_create"):
            if not (title or "").strip():
                return json.dumps({
                    "status": "PARAM_ERROR",
                    "error": "Acción 'create' requiere 'title'."
                }, indent=2, ensure_ascii=False)
            return json.dumps(kanban.create_task(title.strip(), intent, category, artifact_name), indent=2, ensure_ascii=False)
        elif act == "advance":
            if task_id is None or not (to_state or "").strip():
                return json.dumps({
                    "status": "PARAM_ERROR",
                    "error": "Acción 'advance' requiere 'task_id' y 'to_state'."
                }, indent=2, ensure_ascii=False)
            return json.dumps(kanban.advance(task_id, to_state.strip(), lint_passed, canary_passed, note), indent=2, ensure_ascii=False)
        elif act == "promote":
            if task_id is None:
                return json.dumps({
                    "status": "PARAM_ERROR",
                    "error": "Acción 'promote' requiere 'task_id'."
                }, indent=2, ensure_ascii=False)
            return json.dumps(kanban.promote(task_id), indent=2, ensure_ascii=False)
        elif act == "demote":
            if not (artifact_name or "").strip():
                return json.dumps({
                    "status": "PARAM_ERROR",
                    "error": "Acción 'demote' requiere 'artifact_name'."
                }, indent=2, ensure_ascii=False)
            return json.dumps(kanban.demote(artifact_name.strip(), reason), indent=2, ensure_ascii=False)
        elif act == "reevaluate":
            return json.dumps(kanban.reevaluate(), indent=2, ensure_ascii=False)
        elif act == "archive":
            return json.dumps(kanban.archive(states=states, max_score=max_score, apply=apply), indent=2, ensure_ascii=False)
        elif act == "unarchive":
            if task_id is None:
                return json.dumps({
                    "status": "PARAM_ERROR",
                    "error": "Acción 'unarchive' requiere 'task_id'."
                }, indent=2, ensure_ascii=False)
            return json.dumps(kanban.unarchive(task_id), indent=2, ensure_ascii=False)
        else:
            return json.dumps({
                "status": "INVALID_ACTION",
                "error": f"Acción '{action}' no reconocida. Acciones válidas: 'board', 'create', 'advance', 'promote', 'demote', 'reevaluate', 'archive', 'unarchive'.",
                "valid_actions": ["board", "create", "advance", "promote", "demote", "reevaluate", "archive", "unarchive"],
            }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


# Whitelist de tools encadenables en un playbook (solo lectura/ejecución acotada; sin
# meta-tools ni recursión). Define el blast radius de la automatización (P1).
def _playbook_dispatch() -> Dict[str, Any]:
    return {
        "artifact_query": lambda intent="", category="", **kw: artifact_catalog(action="query", intent=intent, category=category, **kw),
        "artifact_catalog": artifact_catalog,
        "artifact_execute_in_ram": artifact_execute_in_ram,
        "async_job_dispatch": async_job_dispatch,
        "async_job_inspect": lambda task_id=None, lines=50, **kw: async_job_dispatch(action="inspect", task_id=task_id, lines=lines, **kw),
        "sandbox_run": sandbox_run,
        "aep_ctl": aep_ctl,
        "check_crash_alerts": lambda resolve_after_report=False, **kw: diagnose_system_crashes(action="alerts", resolve_after_report=resolve_after_report, **kw),
        "diagnose_system_crashes": diagnose_system_crashes,
        "query_system_docs": query_system_docs,
        "visual_inspect": visual_inspect,
        "kernel_trace": kernel_trace,
        "topos_audit_dag": topos_audit_dag,
    }

_PLAYBOOK_FAIL = {"ERROR", "EXEC_FAILED", "BUILD_ERROR", "LINT_ERROR",
                  "DISPLAY_UNAVAILABLE", "BLOCKED", "SELECTOR_NOT_FOUND"}


@mcp.tool()
def playbook_run(
    action: str = "run",
    name: Optional[str] = None,
    vars: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    stop_on_error: bool = True,
    description: Optional[str] = None,
    intent_description: Optional[str] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    params_contract: Optional[List[Dict[str, Any]]] = None,
    names: Optional[List[str]] = None,
    apply: bool = False,
) -> str:
    """
    [PICO-PLAYBOOK UNIFICADO] Orquestación y ejecución de automatizaciones DAG parametrizables.
    action:
      - 'run' (default): instancia y ejecuta un playbook en orden topológico (requiere `name`; `vars` o `params` hidrata marcadores `${var}`).
      - 'create': define una automatización parametrizable y valida su DAG (requiere `name`, `description` y `steps`).
      - 'list': lista los playbooks guardados con su tasa de éxito, número de pasos y contratos.
      - 'prune': poda destructiva segura de playbooks con fallo demostrado (éxito < 0.70) o explícitos en `names` (apply=False -> DRY_RUN).
    """
    act = (action or "run").strip().lower()
    effective_vars = vars if vars is not None else (params or {})
    effective_desc = (description or intent_description or "").strip()
    try:
        if act == "run":
            if not (name or "").strip():
                return json.dumps({
                    "status": "PARAM_ERROR",
                    "error": "Acción 'run' requiere 'name'."
                }, indent=2, ensure_ascii=False)
            pb = playbook_store.get(name.strip())
            if not pb:
                return json.dumps({
                    "status": "ERROR",
                    "error": f"playbook '{name.strip()}' no existe"
                }, indent=2, ensure_ascii=False)

            try:
                resolved = resolve_params(pb.get("params_contract") or [], effective_vars)
                hydrated_steps = hydrate_struct(pb["steps"], resolved, strict=True)
            except ValueError as e:
                return json.dumps({
                    "status": "PARAM_ERROR",
                    "error": str(e),
                    "contract": pb.get("params_contract") or []
                }, indent=2, ensure_ascii=False)

            v = PlaybookStore.validate_and_order(hydrated_steps)
            if not v.get("ok"):
                return json.dumps({
                    "status": "BLOCKED",
                    "verdict": v.get("verdict"),
                    "logs": v.get("logs")
                }, indent=2, ensure_ascii=False)

            dispatch = _playbook_dispatch()
            results: List[Dict[str, Any]] = []
            all_ok = True
            for step in v["ordered_steps"]:
                tool, step_params = step["tool"], step.get("params", {})
                fn = dispatch.get(tool)
                if fn is None:
                    results.append({"id": step["id"], "tool": tool, "status": "NOT_ALLOWED", "ok": False})
                    all_ok = False
                    if stop_on_error:
                        break
                    continue
                try:
                    raw = fn(**step_params)
                    out = json.loads(raw) if isinstance(raw, str) else raw
                    st = out.get("status", "OK") if isinstance(out, dict) else "OK"
                except Exception as e:
                    st, out = "ERROR", {"error": str(e)}
                ok = st not in _PLAYBOOK_FAIL
                results.append({"id": step["id"], "tool": tool, "status": st, "ok": ok, "output": out})
                if not ok:
                    all_ok = False
                    if stop_on_error:
                        break

            playbook_store.record_run(name.strip(), all_ok)
            return json.dumps({
                "status": "OK" if all_ok else "PARTIAL",
                "playbook": name.strip(),
                "all_ok": all_ok,
                "steps_run": len(results),
                "results": results
            }, indent=2, ensure_ascii=False)

        elif act == "create":
            if not (name or "").strip() or not effective_desc or not steps:
                return json.dumps({
                    "status": "PARAM_ERROR",
                    "error": "Acción 'create' requiere 'name', 'description' y 'steps'."
                }, indent=2, ensure_ascii=False)
            allowed = set(_playbook_dispatch())
            bad = sorted({s.get("tool") for s in steps if isinstance(s, dict) and s.get("tool") not in allowed})
            if bad:
                return json.dumps({
                    "status": "LINT_ERROR",
                    "invalid_tools": bad,
                    "allowed_tools": sorted(allowed)
                }, indent=2, ensure_ascii=False)
            return json.dumps(
                playbook_store.create(name.strip(), effective_desc, steps, params_contract),
                indent=2, ensure_ascii=False
            )

        elif act == "list":
            return json.dumps({"status": "OK", "playbooks": playbook_store.list()}, indent=2, ensure_ascii=False)

        elif act == "prune":
            return json.dumps(playbook_store.prune(names=names, apply=apply), indent=2, ensure_ascii=False)

        else:
            return json.dumps({
                "status": "INVALID_ACTION",
                "error": f"Acción '{action}' no reconocida. Acciones válidas: 'run', 'create', 'list', 'prune'.",
                "valid_actions": ["run", "create", "list", "prune"]
            }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


if __name__ == "__main__":
    mcp.run()
