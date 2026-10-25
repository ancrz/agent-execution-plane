#!/usr/bin/env python3
"""
Agent Execution Plane (AEP) - Unified FastMCP Server
Exposes deterministic system execution, in-memory Go artifact lifecycle,
asynchronous job queues (Pueue), crash forensics, and Topos DAG auditing to AI agents.
"""

import concurrent.futures
import inspect
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP

from engine import headless_display, matcher
from engine.backup import create_backup, get_backup_status, restore_backup, verify_and_auto_recover
from engine.catalog import ArtifactCatalog
from engine.crash_router import CrashRouter
from engine.hydrator import TemplateHydrator, hydrate_struct, resolve_params
from engine.kanban import KanbanBoard
from engine.playbook import PlaybookStore
from engine.privilege import (
    CapabilityGuard,
    PermissionDenied,
    capability_manifest,
    capability_tier,
    privilege_mode,
    privilege_prefix,
)
from engine.security import mask_pueue_output, record_audit_event, verify_audit_chain
from engine.template_registry import TemplateRegistry
from engine.topos_guard import ToposGuard

logger = logging.getLogger("aep.server")

_INSTRUCTIONS = (
    "AEP (Agent Execution Plane): plano de ejecución para GESTIONAR LA AUTONOMÍA de agentes "
    "de IA sobre Ubuntu. Transmuta primitivas de herramientas ofensivas (ejecución en RAM, "
    "sandbox, eBPF, introspección de procesos, forense de crashes) en capacidades agénticas "
    "gobernadas por privilegio en dos niveles: FULL (root/sudo -n -> alcance de sistema/kernel) "
    "y DIMINISHED (usuario -> alcance acotado, fail-soft). PRIMERA LLAMADA RECOMENDADA: "
    '`discover(action="capabilities")` devuelve un manifiesto estilo chmod/777 (r=sensar, w=actuar, '
    "x=ejecutar por caminos no-tradicionales) con lo que PUEDES hacer ahora mismo. Para un caso "
    "de uso concreto, `discover(use_case)` enruta a qué reutilizar/sintetizar/automatizar."
)


_display_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="aep_display")
mcp = FastMCP("Agent-Execution-Plane", instructions=_INSTRUCTIONS)
catalog = ArtifactCatalog()
hydrator = TemplateHydrator()
crash_router = CrashRouter()
kanban = KanbanBoard()
playbook_store = PlaybookStore()
template_registry = TemplateRegistry()


class _DocsHolder:
    instance: Any = None


def _get_docs_vectorizer() -> Any:
    if _DocsHolder.instance is None:
        from engine.docs_vectorizer import ManPagesVectorizer

        _DocsHolder.instance = ManPagesVectorizer()
    return _DocsHolder.instance


# Rutas base
PROJECT_DIR = Path(__file__).resolve().parent
TEMP_BIN_DIR = Path.home() / ".local" / "share" / "agent-os" / "bin"
AEP_CTL = PROJECT_DIR / "scripts" / "aep-ctl"
TEMP_BIN_DIR.mkdir(parents=True, exist_ok=True)


async def aep_capabilities(**kw: Any) -> str:
    """
    [AUTO-DESCRIPCIÓN / COMPAT] Forwarder interno hacia discover(action='capabilities').
    """
    return await discover(action="capabilities", **kw)


@mcp.tool()
async def topos_audit_dag(tasks: list[str], dependencies: dict[str, list[str]], agent_id: str = "default") -> str:
    """
    [TOPOS INTEGRITY PROTOCOL] Audita un grafo de tareas antes de su despacho.
    Detecta co-dependencias circulares (A <-> B) que bloquearían al agente.
    Retorna APPROVED o BLOCKED con el camino de remediación.
    """

    def _run() -> str:
        verdict, logs = ToposGuard.audit_task_dag(tasks, dependencies)
        return json.dumps({"verdict": verdict, "details": logs}, indent=2)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def discover(
    use_case: str = "",
    action: str = "discover",
    limit: int = 3,
    agent_id: str = "default",
) -> str:
    """
    [ORIENTACIÓN Y MANIFIESTO UNIFICADO] Primera parada: traduce un caso de uso en lenguaje natural a QUÉ hacer
    o devuelve el manifiesto de autonomía agéntica estilo chmod/777.
    action:
      - 'discover' (default): enruta caso de uso -> capacidad sugerida + artefactos reutilizables + plantillas + playbooks.
      - 'capabilities': devuelve el manifiesto estilo chmod/777 (r=sensar, w=actuar, x=ejecutar) y qué desbloquea FULL.
    """

    def _run() -> str:
        act = (action or "discover").strip().lower()
        if act == "capabilities":
            return json.dumps(capability_manifest(), indent=2, ensure_ascii=False)
        elif act == "discover":
            if not use_case.strip():
                return json.dumps(
                    {
                        "status": "PARAM_ERROR",
                        "error": "Acción 'discover' requiere el parámetro 'use_case' no vacío.",
                        "valid_actions": ["discover", "capabilities"],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            try:
                caps = capability_manifest().get("capabilities", {})
                # tags = tools (EN) + keywords bilingües -> cierra la colisión ES/EN (descriptions en ES,
                # queries a menudo en EN). El matcher pondera tags x2, dando anclaje léxico language-aligned.
                cap_docs = [
                    {
                        "name": k,
                        "tags": list(v.get("tools", [])) + v.get("keywords", "").split(),
                        "description": v.get("description", ""),
                    }
                    for k, v in caps.items()
                ]
                cap = matcher.rank(use_case, cap_docs, limit=2)
                reuse = catalog.browse(query=use_case, limit=limit)
                fb = catalog.template_feedback([t["name"] for t in template_registry.templates])
                synth = template_registry.select(use_case, limit=limit, feedback=fb)
                pb_docs = [
                    {"name": p["name"], "tags": [], "description": p.get("description", "")}
                    for p in playbook_store.list()
                ]
                automate = matcher.rank(use_case, pb_docs, limit=limit)
                return json.dumps(
                    {
                        "status": "OK",
                        "use_case": use_case,
                        "suggested_capability": [{"capability": c["name"], "relevance": c["relevance"]} for c in cap],
                        "reuse_artifacts": [
                            {
                                "name": a.get("name"),
                                "category": a.get("category"),
                                "promotion_score": a.get("promotion_score"),
                                "semantic_distance": a.get("semantic_distance"),
                            }
                            for a in reuse
                        ],
                        "synthesize_templates": [
                            {
                                "name": t["name"],
                                "capability": t.get("capability"),
                                "relevance": t["relevance"],
                                "proven": t.get("proven"),
                            }
                            for t in synth
                        ],
                        "automate_playbooks": [{"name": p["name"], "relevance": p["relevance"]} for p in automate],
                        "hint": "Reutiliza un artefacto si encaja (ya ponderado); si no, sintetiza desde una "
                        "plantilla; para un flujo multi-paso, un playbook; para GC seguro, artifact_catalog(action='prune') o playbook_run(action='prune').",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            except Exception as e:
                return json.dumps({"status": "ERROR", "error": str(e)}, indent=2, ensure_ascii=False)
        else:
            return json.dumps(
                {
                    "status": "INVALID_ACTION",
                    "error": f"Acción '{action}' no válida para discover.",
                    "valid_actions": ["discover", "capabilities"],
                },
                indent=2,
                ensure_ascii=False,
            )

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def artifact_catalog(
    action: str = "browse",
    category: str | None = None,
    query: str | None = None,
    intent: str | None = None,
    limit: int = 10,
    force: bool = False,
    apply: bool = False,
    agent_id: str = "default",
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

    def _run() -> str:
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
                eff_category = category.strip() if (category and category.strip()) else None
                if not eff_intent:
                    return json.dumps(
                        {
                            "status": "PARAM_ERROR",
                            "error": "Acción 'query' requiere el parámetro 'intent' (o 'query').",
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                hit = catalog.find_hybrid(eff_intent, category=eff_category)
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
                storage_tel = catalog.storage_telemetry()
                return json.dumps(
                    {
                        "status": result.get("status", "OK"),
                        "reindex": result,
                        "coverage_before": before,
                        "coverage_after": after,
                        "storage_engine": storage_tel,
                        "db_telemetry": storage_tel,
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

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def artifact_lint_and_build(
    action: str = "build",
    name: str | None = None,
    intent: str | None = None,
    category: str | None = None,
    go_source: str | None = None,
    template_name: str | None = None,
    source_template: str | None = None,
    params: dict[str, Any] | None = None,
    cue_contract: str = "",
    limit: int = 5,
    agent_id: str = "default",
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

    def _run() -> str:
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
                    vet_res = subprocess.run(
                        ["go", "vet", str(src_file)],
                        capture_output=True,
                        text=True,
                        check=False,  # check=False: returncode handled explicitly below
                    )
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
                    lint_warnings: list[str] = []
                    try:
                        gcl = subprocess.run(
                            ["golangci-lint", "run", str(src_file)],
                            capture_output=True,
                            text=True,
                            cwd=tmpdir,
                            timeout=30,
                            check=False,  # check=False: returncode handled explicitly below
                        )
                        if gcl.returncode != 0:
                            out = (gcl.stdout or gcl.stderr or "").strip()
                            if out:
                                lint_warnings = out.splitlines()[:20]
                    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
                        logger.debug("golangci-lint advisory run failed or unavailable: %s", e)
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
                        check=False,  # check=False: returncode handled explicitly below
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
                        kt = kanban.create_task(
                            title=f"build:{art_name}", intent=art_intent, category=art_cat, artifact_name=art_name
                        )
                        kanban_task_id = kt["task_id"]
                        kanban.advance(
                            kanban_task_id,
                            "LINTED",
                            lint_passed=True,
                            note=f"go vet OK; {len(lint_warnings)} avisos golangci-lint",
                        )
                    except Exception as e:
                        logger.debug("Kanban task advance failed for %s: %s", art_name, e)

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
                    "error": f"Acción '{action}' no reconocida. Acciones válidas: 'build', 'catalog', 'select', 'hydrate'.",
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def artifact_execute_in_ram(
    name: str, args: list[str] | None = None, agent_id: str = "default"
) -> str:
    """
    [CAMINO A / MEMFD EXECUTION] Carga un binario Go del catálogo o de bin/
    y lo inyecta directamente en memoria RAM vía memfd_create sin tocar almacenamiento secundario.
    """

    def _run() -> str:
        cmd_args = args or []

        # 1. Validación de autorización y blacklist
        try:
            CapabilityGuard.verify_action(agent_id, "cap_ram_exec", "ram_exec", target=name)
        except PermissionDenied as e:
            try:
                with catalog._get_rw_conn() as conn:
                    record_audit_event(
                        conn,
                        agent_id=agent_id,
                        tool_name="artifact_execute_in_ram",
                        action="ram_exec",
                        capability_tier=capability_tier(),
                        status="BLOCKED",
                        details={"name": name, "reason": e.message},
                        target=name,
                    )
            except Exception as log_err:
                logger.debug("Failed recording audit event: %s", log_err)
            return json.dumps(
                {
                    "status": "PERMISSION_DENIED",
                    "agent_id": agent_id,
                    "error": e.message,
                    "target": name,
                },
                indent=2,
                ensure_ascii=False,
            )

        for arg in cmd_args:
            if CapabilityGuard.is_path_blacklisted(arg):
                try:
                    with catalog._get_rw_conn() as conn:
                        record_audit_event(
                            conn,
                            agent_id=agent_id,
                            tool_name="artifact_execute_in_ram",
                            action="ram_exec",
                            capability_tier=capability_tier(),
                            status="BLOCKED",
                            details={"name": name, "reason": "Restricted path in arguments", "arg": arg},
                            target=arg,
                        )
                except Exception as log_err:
                    logger.debug("Failed recording audit event: %s", log_err)

                return json.dumps(
                    {
                        "status": "PERMISSION_DENIED",
                        "agent_id": agent_id,
                        "error": f"Acceso denegado a ruta restringida '{arg}' bajo capacidad 'cap_ram_exec'.",
                        "target": arg,
                    },
                    indent=2,
                    ensure_ascii=False,
                )

        bin_file = TEMP_BIN_DIR / name
        elf_bytes: bytes | None = None
        if bin_file.exists():
            elf_bytes = bin_file.read_bytes()
        else:
            blob = catalog.get_binary_blob(name)
            if blob:
                elf_bytes = blob
                try:
                    bin_file.write_bytes(blob)
                    bin_file.chmod(0o755)
                except Exception as e:
                    logger.debug("Failed writing binary cache %s: %s", bin_file, e)

        if not elf_bytes:
            return json.dumps({"status": "ERROR", "agent_id": agent_id, "error": f"Binario no encontrado: {name}"})

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
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                    timeout=30,
                    check=False,  # check=False: returncode handled explicitly below for telemetry and kanban recording
                )
            except subprocess.TimeoutExpired:
                return json.dumps(
                    {
                        "status": "TIMEOUT",
                        "agent_id": agent_id,
                        "error": f"Artefacto '{name}' excedió el timeout de 30s (posible proceso daemonizado con descriptores abiertos).",
                    },
                    indent=2,
                    ensure_ascii=False,
                )

            latency_ms = round((time.time() - start_time) * 1000, 2)

            stdout_parsed: Any = res.stdout.strip()
            try:
                stdout_parsed = json.loads(res.stdout)
            except Exception as e:
                logger.debug("Stdout was not json: %s", e)

            # Cierra el lazo de telemetría: cada ejecución alimenta success_rate/execution_count,
            # que ponderan la reutilización del artefacto (dimensiones reliability/experience).
            recorded = catalog.record_execution_by_name(
                name,
                res.returncode,
                latency_ms,
                error_message=(res.stderr.strip()[:500] if res.returncode != 0 and res.stderr else None),
                agent_id=agent_id,
            )
            kanban_canary = kanban.record_canary_by_artifact(name, res.returncode == 0)

            status_val = "SUCCESS" if res.returncode == 0 else "EXEC_FAILED"
            try:
                with catalog._get_rw_conn() as conn:
                    record_audit_event(
                        conn,
                        agent_id=agent_id,
                        tool_name="artifact_execute_in_ram",
                        action="ram_exec",
                        capability_tier=capability_tier(),
                        status=status_val,
                        details={
                            "latency_ms": latency_ms,
                            "exit_code": res.returncode,
                            "args": cmd_args,
                            "error": res.stderr.strip()[:200] if res.stderr else None,
                        },
                        target=name,
                    )
            except Exception as log_err:
                logger.debug("Failed recording audit event: %s", log_err)

            return json.dumps(
                {
                    "status": status_val,
                    "agent_id": agent_id,
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
            return json.dumps({"status": "ERROR", "agent_id": agent_id, "error": str(e)}, indent=2)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception as e:
                    logger.debug("Failed closing memfd %s: %s", fd, e)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def process_inspect(pid: int = 0, limit: int = 100, agent_id: str = "default") -> str:
    """
    [INTROSPECCIÓN DE PROCESOS] Inspecciona el estado, descriptores de archivo abiertos
    (/proc/PID/fd) y telemetría de recursos de un proceso.
    pid: 0 para auto-inspección del propio servidor (self); >0 para un PID específico.
    limit: número máximo de descriptores detallados en la lista (default 100).
    Salida JSON tipada clasificando descriptores (socket, pipe, device, anon_inode, file).
    Fail-soft: devuelve NOT_FOUND o PERMISSION_DENIED sin lanzar excepciones.
    """

    def _run() -> str:
        target_pid = os.getpid() if pid <= 0 else pid
        proc_dir = Path(f"/proc/{target_pid}")

        if not proc_dir.exists():
            return json.dumps(
                {
                    "status": "NOT_FOUND",
                    "pid": target_pid,
                    "error": f"Proceso {target_pid} no encontrado en /proc.",
                },
                indent=2,
                ensure_ascii=False,
            )

        comm_file = proc_dir / "comm"
        status_file = proc_dir / "status"

        name = "unknown"
        if comm_file.exists():
            try:
                name = comm_file.read_text(encoding="utf-8", errors="replace").strip()
            except Exception as e:
                logger.debug("Failed reading comm for pid %s: %s", target_pid, e)

        state = None
        threads = 1
        rss_kb = 0

        if status_file.exists():
            try:
                for line in status_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("State:"):
                        state = line.split(":", 1)[1].strip()
                    elif line.startswith("Threads:"):
                        try:
                            threads = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif line.startswith("VmRSS:"):
                        parts = line.split(":", 1)[1].strip().split()
                        if parts:
                            try:
                                rss_kb = int(parts[0])
                            except ValueError:
                                pass
            except Exception as e:
                logger.debug("Failed reading status for pid %s: %s", target_pid, e)

        fd_dir = proc_dir / "fd"
        if not fd_dir.exists():
            # Kernel threads do not expose /proc/PID/fd
            return json.dumps(
                {
                    "status": "OK",
                    "pid": target_pid,
                    "name": name,
                    "state": state,
                    "threads": threads,
                    "rss_kb": rss_kb,
                    "kernel_thread": True,
                    "fd_count": 0,
                    "summary_by_type": {},
                    "descriptors": [],
                },
                indent=2,
                ensure_ascii=False,
            )

        descriptors: list[dict[str, Any]] = []
        summary_by_type: dict[str, int] = {
            "socket": 0,
            "pipe": 0,
            "file": 0,
            "device": 0,
            "anon_inode": 0,
        }

        try:
            raw_entries = os.listdir(fd_dir)
        except PermissionError:
            return json.dumps(
                {
                    "status": "PERMISSION_DENIED",
                    "pid": target_pid,
                    "capability_tier": capability_tier(),
                    "error": f"Permiso denegado al inspeccionar descriptores en /proc/{target_pid}/fd.",
                },
                indent=2,
                ensure_ascii=False,
            )
        except (FileNotFoundError, ProcessLookupError):
            return json.dumps(
                {
                    "status": "NOT_FOUND",
                    "pid": target_pid,
                    "error": f"Proceso {target_pid} terminó durante la inspección.",
                },
                indent=2,
                ensure_ascii=False,
            )

        sorted_entries = sorted(raw_entries, key=lambda x: int(x) if x.isdigit() else x)

        for entry in sorted_entries:
            fd_num = int(entry) if entry.isdigit() else entry
            link_path = fd_dir / entry
            try:
                target = os.readlink(link_path)
            except (FileNotFoundError, ProcessLookupError, OSError):
                target = "[closed/unreachable]"

            if target.startswith("socket:"):
                dtype = "socket"
            elif target.startswith("pipe:"):
                dtype = "pipe"
            elif target.startswith("/dev/"):
                dtype = "device"
            elif target.startswith("anon_inode:"):
                dtype = "anon_inode"
            else:
                dtype = "file"

            summary_by_type[dtype] = summary_by_type.get(dtype, 0) + 1
            descriptors.append({"fd": fd_num, "type": dtype, "target": target})

        fd_count = len(descriptors)
        truncated = fd_count > limit
        reported_descriptors = descriptors[:limit]

        res_data: dict[str, Any] = {
            "status": "OK",
            "pid": target_pid,
            "name": name,
            "state": state,
            "threads": threads,
            "rss_kb": rss_kb,
            "fd_count": fd_count,
            "summary_by_type": summary_by_type,
            "descriptors": reported_descriptors,
        }
        if truncated:
            res_data["truncated"] = True

        return json.dumps(res_data, indent=2, ensure_ascii=False)

    return await anyio.to_thread.run_sync(_run)


def _ensure_pueue_daemon() -> str | None:
    """
    Localiza el binario pueue y verifica si pueued responde.
    Si no responde, intenta auto-iniciarlo en background ('pueued -d') de forma fail-soft.
    Devuelve la ruta al binario pueue si está listo; None si pueue no está instalado o falló.
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
            check=False,  # check=False: returncode verified immediately below
        )
        if res.returncode == 0:
            return pueue_bin
    except Exception as e:
        logger.debug("Pueue status check failed: %s", e)

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
                    check=False,  # check=False: returncode verified immediately below
                )
                if chk.returncode == 0:
                    return pueue_bin
            except Exception as e:
                logger.debug("Pueue status poll failed: %s", e)
    except Exception:
        return None

    return pueue_bin


@mcp.tool()
async def async_job_dispatch(
    action: str = "dispatch",
    command: str | None = None,
    label: str | None = None,
    group: str = "default",
    working_dir: str | None = None,
    task_id: int | None = None,
    lines: int = 50,
    agent_id: str = "default",
) -> str:
    """
    [CAMINO B / PUEUE] Despacho e inspección unificada de tareas asíncronas en Pueue.
    action: 'dispatch' (default), 'inspect', 'status', 'log'.
    - 'dispatch': Encola un comando de larga duración en segundo plano (requiere 'command').
    - 'inspect' / 'status': Consulta el estado global de la cola o logs si se especifica 'task_id'.
    - 'log': Extrae el log aislado del 'task_id' especificado ('lines' por defecto 50).
    Devuelve inmediatamente JSON tipado con fail-soft sin bloquear el loop del agente.
    """

    def _run() -> str:
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
                            "agent_id": agent_id,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )

                effective_group = f"agent_{agent_id}" if group == "default" and agent_id != "default" else group
                if effective_group != "default":
                    subprocess.run([pueue_bin, "group", "add", effective_group], capture_output=True, check=False)

                cmd = [pueue_bin, "add", "--print-task-id", "--group", effective_group]
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
                    check=False,  # check=False: returncode verified immediately below
                )

                if res.returncode != 0:
                    return json.dumps(
                        {
                            "status": "PUEUE_ERROR",
                            "error": res.stderr.strip() or res.stdout.strip(),
                            "command": command,
                            "agent_id": agent_id,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )

                # parsea task-id del output numérico
                out = res.stdout.strip()
                try:
                    tid = int(out.split()[-1])
                except (IndexError, ValueError):
                    tid = out

                return json.dumps(
                    {
                        "status": "queued",
                        "task_id": tid,
                        "group": effective_group,
                        "agent_id": agent_id,
                        "command": command,
                    },
                    indent=2,
                )

            elif act in ("inspect", "status"):
                pueue_bin = _ensure_pueue_daemon()
                if not pueue_bin:
                    return json.dumps(
                        {
                            "status": "DEGRADED",
                            "message": "pueue daemon unavailable.",
                            "agent_id": agent_id,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )

                if task_id is not None:
                    # inspección detallada de un task
                    res = subprocess.run(
                        [pueue_bin, "log", "--json", str(task_id)],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        close_fds=True,
                        timeout=10,
                        check=False,  # check=False: returncode verified below
                    )
                else:
                    # status global
                    res = subprocess.run(
                        [pueue_bin, "status", "--json"],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        close_fds=True,
                        timeout=10,
                        check=False,  # check=False: returncode verified below
                    )

                if res.returncode != 0:
                    return json.dumps(
                        {"status": "ERROR", "stderr": res.stderr.strip(), "agent_id": agent_id},
                        indent=2,
                        ensure_ascii=False,
                    )

                return mask_pueue_output(res.stdout)

            elif act == "log":
                if task_id is None:
                    return json.dumps(
                        {"status": "PARAM_ERROR", "error": "Acción 'log' requiere 'task_id'."},
                        indent=2,
                        ensure_ascii=False,
                    )

                pueue_bin = _ensure_pueue_daemon()
                if not pueue_bin:
                    return json.dumps(
                        {
                            "status": "DEGRADED",
                            "message": "pueue daemon unavailable.",
                            "agent_id": agent_id,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )

                res = subprocess.run(
                    [pueue_bin, "log", "--lines", str(lines), "--json", str(task_id)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    close_fds=True,
                    timeout=10,
                    check=False,  # check=False: returncode verified below
                )

                if res.returncode != 0:
                    return json.dumps(
                        {"status": "ERROR", "stderr": res.stderr.strip(), "agent_id": agent_id},
                        indent=2,
                        ensure_ascii=False,
                    )

                return mask_pueue_output(res.stdout)

            else:
                return json.dumps(
                    {
                        "status": "INVALID_ACTION",
                        "error": f"Acción '{action}' desconocida. Válidas: dispatch, inspect, status, log.",
                    },
                    indent=2,
                    ensure_ascii=False,
                )

        except Exception as e:
            return json.dumps({"status": "ERROR", "agent_id": agent_id, "error": str(e)}, indent=2, ensure_ascii=False)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def diagnose_system_crashes(
    action: str = "diagnose",
    limit: int = 5,
    resolve_after_report: bool = False,
    agent_id: str = "default",
) -> str:
    """
    [FORENSE DE CRASHES UNIFICADO] Diagnóstico del sistema y alertas de crashes activos.
    action:
      - 'diagnose' (default): ejecuta coredumpctl + journalctl (nivel FULL con sudo -n; DIMINISHED usuario).
      - 'alerts' (o 'check'): consulta crashes pendientes en artifacts.db; `resolve_after_report=True` los marca resueltos.
    """

    def _run() -> str:
        try:
            if action == "diagnose":
                prefix = privilege_prefix() or []

                def _safe_run(cmd: list[str]) -> subprocess.CompletedProcess | None:
                    try:
                        return subprocess.run(
                            prefix + cmd,
                            capture_output=True,
                            text=True,
                            stdin=subprocess.DEVNULL,
                            close_fds=True,
                            timeout=15,
                            check=False,  # check=False: returncode inspected below
                        )
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        return None

                unavailable = []
                recent_coredumps = []

                if not shutil.which("coredumpctl"):
                    unavailable.append("coredumpctl")
                else:
                    coredumps_raw = _safe_run(["coredumpctl", "list", "--json=short", "-n", str(limit)])
                    if coredumps_raw is None:
                        unavailable.append("coredumpctl")
                    elif coredumps_raw.returncode == 0:
                        if coredumps_raw.stdout.strip():
                            try:
                                recent_coredumps = json.loads(coredumps_raw.stdout)
                            except Exception:
                                recent_coredumps = []
                    elif coredumps_raw.returncode == 1 and (
                        "no coredumps found" in (coredumps_raw.stderr or coredumps_raw.stdout).lower()
                        or not coredumps_raw.stdout.strip()
                    ):
                        recent_coredumps = []
                    else:
                        unavailable.append("coredumpctl")

                journal_errs = None
                recent_errors = []
                if not shutil.which("journalctl"):
                    unavailable.append("journalctl")
                else:
                    journal_errs = _safe_run(["journalctl", "-p", "err", "-n", str(limit), "-o", "json"])
                    if journal_errs is None or journal_errs.returncode != 0:
                        unavailable.append("journalctl")
                    else:
                        for line in journal_errs.stdout.splitlines():
                            if line.strip():
                                try:
                                    recent_errors.append(json.loads(line))
                                except Exception as e:
                                    logger.debug("Failed parsing journal error line: %s", e)

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

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def sandbox_run(command: str, share_net: bool = True, agent_id: str = "default") -> str:
    """
    [BUBBLEWRAP SANDBOX] Ejecuta comandos en un sandbox efímero con bwrap
    aislando el sistema de archivos contra efectos secundarios destructivos.
    """

    def _run() -> str:
        bwrap_cmd = [
            "bwrap",
            "--unshare-all",
        ]
        if share_net:
            bwrap_cmd.append("--share-net")
        bwrap_cmd.extend([
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind-try",
            "/lib64",
            "/lib64",
            "--ro-bind-try",
            "/etc/ssl",
            "/etc/ssl",
            "--ro-bind-try",
            "/etc/pki",
            "/etc/pki",
            "--ro-bind-try",
            "/etc/resolv.conf",
            "/etc/resolv.conf",
            "--ro-bind-try",
            "/etc/hosts",
            "/etc/hosts",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/dev/shm",
            "--cap-drop",
            "ALL",
            "--die-with-parent",
            "--",
            "sh",
            "-c",
            command,
        ])

        try:
            res = subprocess.run(
                bwrap_cmd,
                capture_output=True,
                text=True,
                check=False,  # check=False: exit_code returned in JSON payload
            )
            return json.dumps(
                {
                    "status": "SUCCESS" if res.returncode == 0 else "EXEC_FAILED",
                    "agent_id": agent_id,
                    "exit_code": res.returncode,
                    "stdout": res.stdout.strip(),
                    "stderr": res.stderr.strip(),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"status": "ERROR", "agent_id": agent_id, "error": str(e)}, indent=2)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def aep_ctl(domain: str, action: str, name: str | None = None, agent_id: str = "default") -> str:
    """
    [SPEC-OM-1 / UNIFIED CONTROL PLANE] Plano de control determinista del sistema.
    domain: service|network|storage|package|backup|audit. Salida JSON tipada, no-interactiva.
    Ej: aep_ctl("network","listeners") | aep_ctl("package","check","nginx") | aep_ctl("backup","status").
    """

    def _run() -> str:
        d = (domain or "").strip().lower()
        a = (action or "").strip().lower()
        if d == "backup":
            if a == "backup":
                return json.dumps(create_backup(), indent=2)
            elif a == "restore":
                slot = 1
                if name and name.strip():
                    try:
                        slot = int(name.strip())
                    except ValueError:
                        return json.dumps({"status": "ERROR", "error": f"Número de slot inválido: {name}"}, indent=2)
                return json.dumps(restore_backup(slot_number=slot), indent=2)
            elif a in ("status", "backup_status"):
                return json.dumps(get_backup_status(), indent=2)
            elif a in ("auto_recover", "verify_and_auto_recover"):
                return json.dumps(verify_and_auto_recover(), indent=2)
            else:
                return json.dumps({"status": "ERROR", "error": f"Acción de backup desconocida: {a}"}, indent=2)
        elif d == "audit":
            if a == "verify":
                with catalog._get_ro_conn() as conn:
                    return json.dumps(verify_audit_chain(conn), indent=2)
            else:
                return json.dumps({"status": "ERROR", "error": f"Acción de audit desconocida: {a}"}, indent=2)

        if not AEP_CTL.exists():
            return json.dumps({"status": "ERROR", "error": f"aep-ctl no encontrado en {AEP_CTL}"}, indent=2)
        cmd = ["python3", str(AEP_CTL), domain, action]
        if name:
            cmd.append(name)
        cmd.append("--json")
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,  # check=False: returncode/stderr handled explicitly below
            )
            return res.stdout.strip() or json.dumps({"status": "ERROR", "stderr": res.stderr.strip()}, indent=2)
        except Exception as e:
            return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)

    return await anyio.to_thread.run_sync(_run)


async def check_crash_alerts(resolve_after_report: bool = False) -> str:
    """
    [COMPAT] Consulta crashes no resueltos en artifacts.db. Alerta proactiva
    antes de que el agente actúe. (Des-registrado de MCP en Fase 6; unificado en diagnose_system_crashes).
    """
    return await diagnose_system_crashes(action="alerts", resolve_after_report=resolve_after_report)


@mcp.tool()
async def query_system_docs(query: str, limit: int = 3, ingest_command: str | None = None, agent_id: str = "default") -> str:
    """
    [SPEC-OM-4 / DOCS VECTORIZER] Memoria semántica local de man-pages (sqlite-vec).
    Devuelve la sintaxis exacta de herramientas del sistema sin alucinar ni navegar la web.
    `ingest_command`: ingiere la man-page de un comando extra on-demand antes de consultar.
    """

    def _run() -> str:
        try:
            dv = _get_docs_vectorizer()
            if ingest_command:
                dv.ingest_command(ingest_command)
            return json.dumps(dv.query(query, limit), indent=2)
        except Exception as e:
            return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def visual_inspect(
    url: str,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    selector: str | None = None,
    full_page: bool = True,
    agent_id: str = "default",
) -> str:
    """
    [SPEC-OM-5 / HEADLESS DISPLAY] Renderiza una URL (http(s):// o file://) en Chromium
    headless y captura un screenshot en RAM (/dev/shm), devuelto en base64. Para validar
    layouts/UI en servidores sin pantalla. FAIL-SOFT si no hay navegador.
    """

    def _run() -> str:
        try:
            future = _display_executor.submit(
                headless_display.visual_inspect, url, viewport_width, viewport_height, selector, full_page
            )
            res = future.result(timeout=25)
            return json.dumps(res, indent=2)
        except concurrent.futures.TimeoutError:
            return json.dumps(
                {
                    "status": "DISPLAY_UNAVAILABLE",
                    "message": "Playwright timeout exceeded 25s",
                    "url": url,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)

    return await anyio.to_thread.run_sync(_run)


_BPFTRACE_MODES = {
    # eBPF (rootkit/sniffer ofensivo) -> observabilidad de kernel no-invasiva.
    "syscall_count": "tracepoint:raw_syscalls:sys_enter {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "file_opens": "tracepoint:syscalls:sys_enter_openat {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "tcp_connect": "kprobe:tcp_connect {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
}


@mcp.tool()
async def kernel_trace(mode: str = "syscall_count", duration_sec: int = 3, agent_id: str = "default") -> str:
    """
    [SPEC-OM-6 / KERNEL TRACE via eBPF] Observabilidad de kernel a bajo nivel (bpftrace).
    Requiere nivel FULL (sudo -n disponible); degrada limpiamente a DIMINISHED si no hay root.
    `mode`: 'syscall_count' (top syscalls por proceso), 'file_opens' (aperturas de archivo),
    'tcp_connect' (conexiones salientes).
    """

    def _run() -> str:
        if mode not in _BPFTRACE_MODES:
            return json.dumps(
                {
                    "status": "INVALID_MODE",
                    "error": f"Modo '{mode}' no soportado. Válidos: {list(_BPFTRACE_MODES.keys())}",
                },
                indent=2,
            )
        prefix = privilege_prefix()
        if prefix is None:
            return json.dumps(
                {
                    "status": "DEGRADED",
                    "capability_tier": "DIMINISHED",
                    "message": "bpftrace requiere root (CAP_BPF) y no hay sudo -n disponible.",
                },
                indent=2,
            )
        pmode = privilege_mode()
        script = _BPFTRACE_MODES[mode].format(d=max(1, min(duration_sec, 30)))
        try:
            # El script proviene de _BPFTRACE_MODES (curado, solo-lectura), nunca de entrada libre.
            res = subprocess.run(
                prefix + ["bpftrace", "-f", "json", "-e", script],
                capture_output=True,
                text=True,
                timeout=max(5, duration_sec + 10),
                check=False,  # check=False: returncode inspected below
            )
            if res.returncode != 0:
                return json.dumps(
                    {
                        "status": "DEGRADED",
                        "capability_tier": "FULL",
                        "privilege_mode": pmode,
                        "message": "bpftrace falló pese a la escalada.",
                        "stderr": res.stderr.strip()[:300],
                    },
                    indent=2,
                )
            counts = {}
            for line in res.stdout.splitlines():
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "map":
                        for _, m in obj.get("data", {}).items():
                            if isinstance(m, dict):
                                counts.update(m)
                except Exception as e:
                    logger.debug("Failed parsing bpftrace line: %s", e)
            return json.dumps(
                {
                    "status": "OK",
                    "capability_tier": "FULL",
                    "mode": mode,
                    "duration_sec": duration_sec,
                    "privilege_mode": pmode,
                    "counts": counts,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"status": "DEGRADED", "error": str(e)}, indent=2)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def kanban_board(
    action: str = "board",
    include_archived: bool = False,
    task_id: int | None = None,
    title: str = "",
    intent: str = "",
    category: str = "",
    artifact_name: str | None = None,
    to_state: str = "",
    lint_passed: bool | None = None,
    canary_passed: bool | None = None,
    note: str | None = None,
    reason: str | None = None,
    states: list[str] | None = None,
    max_score: float | None = None,
    apply: bool = False,
    target_state: str = "SYNTHESIZED",
    agent_id: str = "default",
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

    def _run() -> str:
        try:
            act = (action or "board").strip().lower()
            if act == "board":
                return json.dumps(kanban.board(include_archived=include_archived), indent=2, ensure_ascii=False)
            elif act in ("create", "task_create"):
                if not (title or "").strip():
                    return json.dumps(
                        {"status": "PARAM_ERROR", "error": "Acción 'create' requiere 'title'."},
                        indent=2,
                        ensure_ascii=False,
                    )
                return json.dumps(
                    kanban.create_task(title.strip(), intent, category, artifact_name, agent_id=agent_id), indent=2, ensure_ascii=False
                )
            elif act == "advance":
                if task_id is None or not (to_state or "").strip():
                    return json.dumps(
                        {"status": "PARAM_ERROR", "error": "Acción 'advance' requiere 'task_id' y 'to_state'."},
                        indent=2,
                        ensure_ascii=False,
                    )
                return json.dumps(
                    kanban.advance(task_id, to_state.strip(), lint_passed, canary_passed, note),
                    indent=2,
                    ensure_ascii=False,
                )
            elif act == "promote":
                if task_id is None:
                    return json.dumps(
                        {"status": "PARAM_ERROR", "error": "Acción 'promote' requiere 'task_id'."},
                        indent=2,
                        ensure_ascii=False,
                    )
                return json.dumps(kanban.promote(task_id), indent=2, ensure_ascii=False)
            elif act == "demote":
                if not (artifact_name or "").strip() and task_id is None:
                    return json.dumps(
                        {"status": "PARAM_ERROR", "error": "Acción 'demote' requiere 'artifact_name' o 'task_id'."},
                        indent=2,
                        ensure_ascii=False,
                    )
                return json.dumps(
                    kanban.demote(
                        artifact_name.strip() if artifact_name else None,
                        reason,
                        task_id=task_id,
                        target_state=target_state,
                    ),
                    indent=2,
                    ensure_ascii=False,
                )
            elif act == "reevaluate":
                return json.dumps(kanban.reevaluate(), indent=2, ensure_ascii=False)
            elif act == "archive":
                return json.dumps(
                    kanban.archive(states=states, max_score=max_score, apply=apply), indent=2, ensure_ascii=False
                )
            elif act == "unarchive":
                if task_id is None:
                    return json.dumps(
                        {"status": "PARAM_ERROR", "error": "Acción 'unarchive' requiere 'task_id'."},
                        indent=2,
                        ensure_ascii=False,
                    )
                return json.dumps(kanban.unarchive(task_id), indent=2, ensure_ascii=False)
            else:
                return json.dumps(
                    {
                        "status": "INVALID_ACTION",
                        "error": f"Acción '{action}' no reconocida. Acciones válidas: 'board', 'create', 'advance', 'promote', 'demote', 'reevaluate', 'archive', 'unarchive'.",
                        "valid_actions": [
                            "board",
                            "create",
                            "advance",
                            "promote",
                            "demote",
                            "reevaluate",
                            "archive",
                            "unarchive",
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception as e:
            return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)

    return await anyio.to_thread.run_sync(_run)


# Whitelist de tools encadenables en un playbook (solo lectura/ejecución acotada; sin
# meta-tools ni recursión). Define el blast radius de la automatización (P1).
def _playbook_dispatch() -> dict[str, Any]:
    return {
        "aep_capabilities": lambda **kw: discover(action="capabilities", **kw),
        "discover": discover,
        "process_inspect": process_inspect,
        "artifact_query": lambda intent="", category="", **kw: artifact_catalog(
            action="query", intent=intent, category=category, **kw
        ),
        "artifact_catalog": artifact_catalog,
        "artifact_execute_in_ram": artifact_execute_in_ram,
        "async_job_dispatch": async_job_dispatch,
        "async_job_inspect": lambda task_id=None, lines=50, **kw: async_job_dispatch(
            action="inspect", task_id=task_id, lines=lines, **kw
        ),
        "sandbox_run": sandbox_run,
        "aep_ctl": aep_ctl,
        "check_crash_alerts": lambda resolve_after_report=False, **kw: diagnose_system_crashes(
            action="alerts", resolve_after_report=resolve_after_report, **kw
        ),
        "diagnose_system_crashes": diagnose_system_crashes,
        "query_system_docs": query_system_docs,
        "visual_inspect": visual_inspect,
        "kernel_trace": kernel_trace,
        "topos_audit_dag": topos_audit_dag,
    }


_PLAYBOOK_FAIL = {
    "ERROR",
    "EXEC_FAILED",
    "BUILD_ERROR",
    "LINT_ERROR",
    "DISPLAY_UNAVAILABLE",
    "BLOCKED",
    "SELECTOR_NOT_FOUND",
}


@mcp.tool()
async def playbook_run(
    action: str = "run",
    name: str | None = None,
    vars: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    stop_on_error: bool = True,
    description: str | None = None,
    intent_description: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    params_contract: list[dict[str, Any]] | None = None,
    names: list[str] | None = None,
    apply: bool = False,
    agent_id: str = "default",
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
                return json.dumps(
                    {"status": "PARAM_ERROR", "error": "Acción 'run' requiere 'name'."}, indent=2, ensure_ascii=False
                )
            pb = playbook_store.get(name.strip())
            if not pb:
                return json.dumps(
                    {"status": "ERROR", "error": f"playbook '{name.strip()}' no existe"}, indent=2, ensure_ascii=False
                )

            try:
                resolved = resolve_params(pb.get("params_contract") or [], effective_vars)
                hydrated_steps = hydrate_struct(pb["steps"], resolved, strict=True)
            except ValueError as e:
                return json.dumps(
                    {"status": "PARAM_ERROR", "error": str(e), "contract": pb.get("params_contract") or []},
                    indent=2,
                    ensure_ascii=False,
                )

            v = PlaybookStore.validate_and_order(hydrated_steps)
            if not v.get("ok"):
                return json.dumps(
                    {"status": "BLOCKED", "verdict": v.get("verdict"), "logs": v.get("logs")},
                    indent=2,
                    ensure_ascii=False,
                )

            dispatch = _playbook_dispatch()
            results: list[dict[str, Any]] = []
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
                    if inspect.iscoroutine(raw):
                        raw = await raw
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
            return json.dumps(
                {
                    "status": "OK" if all_ok else "PARTIAL",
                    "playbook": name.strip(),
                    "all_ok": all_ok,
                    "steps_run": len(results),
                    "results": results,
                },
                indent=2,
                ensure_ascii=False,
            )

        elif act == "create":
            if not (name or "").strip() or not effective_desc or not steps:
                return json.dumps(
                    {"status": "PARAM_ERROR", "error": "Acción 'create' requiere 'name', 'description' y 'steps'."},
                    indent=2,
                    ensure_ascii=False,
                )
            allowed = set(_playbook_dispatch())
            bad = sorted({s.get("tool") for s in steps if isinstance(s, dict) and s.get("tool") not in allowed})
            if bad:
                return json.dumps(
                    {"status": "LINT_ERROR", "invalid_tools": bad, "allowed_tools": sorted(allowed)},
                    indent=2,
                    ensure_ascii=False,
                )
            return json.dumps(
                playbook_store.create(name.strip(), effective_desc, steps, params_contract),
                indent=2,
                ensure_ascii=False,
            )

        elif act == "list":
            return json.dumps({"status": "OK", "playbooks": playbook_store.list()}, indent=2, ensure_ascii=False)

        elif act == "prune":
            return json.dumps(playbook_store.prune(names=names, apply=apply), indent=2, ensure_ascii=False)

        else:
            return json.dumps(
                {
                    "status": "INVALID_ACTION",
                    "error": f"Acción '{action}' no reconocida. Acciones válidas: 'run', 'create', 'list', 'prune'.",
                    "valid_actions": ["run", "create", "list", "prune"],
                },
                indent=2,
                ensure_ascii=False,
            )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


if __name__ == "__main__":
    mcp.run()
