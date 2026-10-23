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
    "x=ejecutar por caminos no-tradicionales) con lo que PUEDES hacer ahora mismo."
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
def artifact_query(intent: str, category: str) -> str:
    """
    [PICO-ANSIBLE / CATALOG] Consulta en SQLite si ya existe un artefacto validado
    para la intención solicitada. Si existe con alta tasa de éxito, lo retorna para reuso.
    """
    hit = catalog.find_hybrid(intent, category)
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
        )
    return json.dumps(
        {
            "status": "CACHE_MISS",
            "message": "No se encontró artefacto en caché. Proceder a hidratar o sintetizar.",
            "available_templates": hydrator.list_available_templates(),
            "semantic_available": catalog._vec_available,
        },
        indent=2,
    )


@mcp.tool()
def artifact_catalog(category: Optional[str] = None, query: Optional[str] = None,
                     limit: int = 10) -> str:
    """
    [DESCUBRIMIENTO] 'Qué soluciones tengo disponibles'. Lista/busca artefactos del catálogo
    para que el agente descubra qué puede reutilizar antes de sintetizar algo nuevo.
    - query: top-K semántico (embeddings auto-indexados), ordenado por cercanía.
    - sin query: ranking por confianza (reutilizable + ponderación + éxito).
    Incluye capability_tier (contexto de ejecución actual: FULL/DIMINISHED).
    """
    try:
        items = catalog.browse(category=category, query=query, limit=limit)
        return json.dumps(
            {"status": "OK", "capability_tier": capability_tier(),
             "count": len(items), "artifacts": items},
            indent=2, ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def artifact_reindex(force: bool = False) -> str:
    """
    [DESCUBRIMIENTO / AUTO-ÍNDICE] Sana el índice semántico: embebe en sqlite-vec todo artefacto
    sin embedding (o TODOS si force=True). Hace buscable lo que otros agentes registraron por
    otras vías o quedó sin indexar. Devuelve la cobertura antes/después. El embedder solo se
    carga si hay trabajo pendiente.
    """
    try:
        before = catalog.index_coverage()
        result = catalog.reindex(force=force)
        after = catalog.index_coverage()
        return json.dumps({"status": result.get("status", "OK"), "reindex": result,
                           "coverage_before": before, "coverage_after": after},
                          indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def template_catalog() -> str:
    """
    [PLANTILLAS] Tabla descriptiva de plantillas base disponibles (qué hay para sintetizar),
    con capacidad, categoría, tags, descripción y params. Punto de partida: elige una plantilla,
    hidrátala y constrúyela. Incluye candidatas redundantes (tags muy solapados).
    """
    try:
        return json.dumps({"status": "OK", "templates": template_registry.catalog(),
                           "redundancy": template_registry.redundancy()},
                          indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def template_select(intent: str, limit: int = 5) -> str:
    """
    [PLANTILLAS] ¿Qué plantilla para mi caso de uso? Rankea las plantillas por relevancia a
    `intent` con scoring multi-señal (exact/prefix/phrase + BM25F + jaccard de tags + fuzzy).
    Devuelve el top con `relevance` y `why` (qué señales dispararon) para decidir con transparencia.
    """
    try:
        matches = template_registry.select(intent, limit=limit)
        return json.dumps({"status": "OK", "intent": intent, "matches": matches},
                          indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def artifact_hydrate(template_name: str, params: Dict[str, Any]) -> str:
    """
    [PICO-ANSIBLE / HYDRATOR] Instancia una plantilla atómica Go con los parámetros
    especificados por el agente, generando el código fuente final.
    """
    try:
        source_code = hydrator.hydrate(template_name, params)
        return json.dumps({"status": "SUCCESS", "go_source": source_code}, indent=2)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def artifact_lint_and_build(
    name: str, intent: str, category: str, go_source: str, cue_contract: str = ""
) -> str:
    """
    [PICO-JENKINS / QUALITY GATE] Ejecuta análisis estático sobre el código Go generado
    (go vet / golangci-lint), compila un binario estático (CGO_ENABLED=0) y lo registra en el catálogo.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = Path(tmpdir) / f"{name}.go"
        src_file.write_text(go_source, encoding="utf-8")
        bin_file = TEMP_BIN_DIR / name

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
            lint_warnings = []  # golangci-lint ausente/fallo -> degradado a solo go vet

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
            name=name,
            intent=intent,
            category=category,
            cue_contract=cue_contract or "package schema",
            go_source=go_source,
            binary_blob=binary_bytes,
        )

        # Pico-Kanban: registra el ciclo del artefacto y lo pondera. go vet pasó -> lint_passed;
        # compilación/canary en RAM se confirma al ejecutarlo (kanban_advance CANARY).
        kanban_task_id = None
        try:
            kt = kanban.create_task(title=f"build:{name}", intent=intent, category=category, artifact_name=name)
            kanban_task_id = kt["task_id"]
            kanban.advance(kanban_task_id, "LINTED", lint_passed=True,
                           note=f"go vet OK; {len(lint_warnings)} avisos golangci-lint")
        except Exception:
            pass

        return json.dumps(
            {
                "status": "SUCCESS",
                "artifact_id": artifact_id,
                "name": name,
                "binary_path": str(bin_file),
                "binary_size_bytes": len(binary_bytes),
                "compile_time_ms": compile_latency_ms,
                "lint_warnings": lint_warnings,  # advisory golangci-lint (no bloqueó la build)
                "kanban_task_id": kanban_task_id,  # avanzar a CANARY tras ejecutar; promover cuando pondere
            },
            indent=2,
        )


@mcp.tool()
def artifact_execute_in_ram(name: str, args: Optional[List[str]] = None) -> str:
    """
    [CAMINO A / MEMFD EXECUTION] Carga un binario Go del catálogo o de bin/
    y lo inyecta directamente en memoria RAM vía memfd_create sin tocar almacenamiento secundario.
    """
    bin_file = TEMP_BIN_DIR / name
    if not bin_file.exists():
        return json.dumps({"status": "ERROR", "error": f"Binario no encontrado: {name}"})

    elf_bytes = bin_file.read_bytes()
    cmd_args = args or []

    start_time = time.time()
    try:
        fd = os.memfd_create(f"anon_{name}", 0)
        os.write(fd, elf_bytes)
        os.lseek(fd, 0, os.SEEK_SET)

        res = subprocess.run(
            [f"/proc/self/fd/{fd}"] + cmd_args,
            capture_output=True,
            text=True,
            close_fds=False,
        )
        os.close(fd)
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

        return json.dumps(
            {
                "status": "SUCCESS" if res.returncode == 0 else "EXEC_FAILED",
                "exit_code": res.returncode,
                "latency_ms": latency_ms,
                "output": stdout_parsed,
                "stderr": res.stderr.strip() if res.stderr else None,
                "metric_recorded": recorded,  # True si alimentó la ponderación del catálogo
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def async_job_dispatch(
    command: str,
    label: Optional[str] = None,
    group: str = "default",
    working_dir: Optional[str] = None,
) -> str:
    """
    [CAMINO B / PUEUE] Encola un comando de larga duración en Pueue de forma asíncrona.
    Devuelve inmediatamente el task_id para evitar bloqueos del subproceso del agente.
    """
    cmd = ["pueue", "add", "--print-task-id", "--group", group]
    if label:
        cmd.extend(["--label", label])
    if working_dir:
        cmd.extend(["--working-directory", working_dir])
    cmd.extend(["--", command])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        task_id = int(res.stdout.strip())
        return json.dumps(
            {"status": "queued", "task_id": task_id, "group": group, "command": command},
            indent=2,
        )
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def async_job_inspect(task_id: Optional[int] = None, lines: int = 50) -> str:
    """
    [CAMINO B / PUEUE] Consulta el estado en JSON de la cola asíncrona o extrae el log
    aislado de un task_id específico sin bloquear.
    """
    try:
        if task_id is not None:
            res = subprocess.run(
                ["pueue", "log", str(task_id), "--lines", str(lines), "--json"],
                capture_output=True,
                text=True,
            )
            return res.stdout
        res = subprocess.run(["pueue", "status", "--json"], capture_output=True, text=True)
        return res.stdout
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def diagnose_system_crashes(limit: int = 5) -> str:
    """
    [OMARCHY PATTERN] Inspecciona volcados de memoria recientes (systemd-coredump)
    y errores críticos de journald en formato JSON para auto-diagnóstico estructurado.
    """
    # FAIL-SOFT: en hosts sin systemd-coredump/journald (contenedores, no-systemd) los
    # binarios pueden faltar. Devolvemos JSON tipado degradado, nunca una excepción.
    # Nivel FULL: prefijo sudo -n para ver coredumps/errores de TODO el sistema; DIMINISHED
    # (sin escalada) ve solo lo propio. Ambos fail-soft.
    prefix = privilege_prefix() or []

    def _safe_run(cmd):
        try:
            return subprocess.run(prefix + cmd, capture_output=True, text=True)
        except FileNotFoundError:
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


@mcp.tool()
def check_crash_alerts(resolve_after_report: bool = False) -> str:
    """
    [SPEC-OM-2 / PROACTIVE CRASH ROUTING] Enrutador proactivo de fallos: diffea los
    coredumps recientes contra el catálogo y entrega los nuevos tickets estructurados
    antes de que el agente actúe. Complementa (no reemplaza) diagnose_system_crashes.
    """
    try:
        return json.dumps(crash_router.check(resolve_after_report), indent=2)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


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
def kanban_board() -> str:
    """
    [PICO-KANBAN] Tablero de estados abstracto (idioma agéntico, transparente al usuario).
    Devuelve las lanes BACKLOG/SYNTHESIZED/LINTED/CANARY/PROMOTED/REJECTED con la ponderación
    (promotion_score) de cada tarea/artefacto. Memoria de trabajo del agente para una actividad.
    """
    try:
        return json.dumps(kanban.board(), indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def kanban_task_create(title: str, intent: str = "", category: str = "",
                       artifact_name: Optional[str] = None) -> str:
    """[PICO-KANBAN] Crea una tarea atómica en BACKLOG (opcionalmente ligada a un artefacto)."""
    try:
        return json.dumps(kanban.create_task(title, intent, category, artifact_name), indent=2)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def kanban_advance(task_id: int, to_state: str, lint_passed: Optional[bool] = None,
                   canary_passed: Optional[bool] = None, note: Optional[str] = None) -> str:
    """
    [PICO-KANBAN] Mueve una tarea de estado y recalcula su ponderación. Marca lint_passed /
    canary_passed (p.ej. canary_passed=True tras un dry-run exitoso en RAM con artifact_execute_in_ram).
    """
    try:
        return json.dumps(kanban.advance(task_id, to_state, lint_passed, canary_passed, note), indent=2)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def kanban_reevaluate() -> str:
    """
    [PICO-KANBAN] Auto-corrección del conjunto confiable: re-pondera cada artefacto reusable
    contra sus métricas ACTUALES (telemetría acumulada) y DEGRADA (reusable=0) los que ya no
    alcanzan TRUST. Cierra el lazo promoción<->degradación — la confianza se gana y se pierde.
    """
    try:
        return json.dumps(kanban.reevaluate(), indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def kanban_demote(artifact_name: str, reason: Optional[str] = None) -> str:
    """[PICO-KANBAN] Degrada explícitamente un artefacto (reusable=0). Inverso de kanban_promote."""
    try:
        return json.dumps(kanban.demote(artifact_name, reason), indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def kanban_promote(task_id: int) -> str:
    """
    [PICO-KANBAN] Promueve el artefacto ligado como REUTILIZABLE si su ponderación lo amerita
    (lint + canary + éxito histórico, score >= 0.70). Si no, devuelve REJECTED con lo que falta.
    """
    try:
        return json.dumps(kanban.promote(task_id), indent=2)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


# Whitelist de tools encadenables en un playbook (solo lectura/ejecución acotada; sin
# meta-tools ni recursión). Define el blast radius de la automatización (P1).
def _playbook_dispatch() -> Dict[str, Any]:
    return {
        "artifact_query": artifact_query,
        "artifact_catalog": artifact_catalog,
        "artifact_execute_in_ram": artifact_execute_in_ram,
        "sandbox_run": sandbox_run,
        "aep_ctl": aep_ctl,
        "check_crash_alerts": check_crash_alerts,
        "diagnose_system_crashes": diagnose_system_crashes,
        "query_system_docs": query_system_docs,
        "visual_inspect": visual_inspect,
        "kernel_trace": kernel_trace,
        "topos_audit_dag": topos_audit_dag,
    }

_PLAYBOOK_FAIL = {"ERROR", "EXEC_FAILED", "BUILD_ERROR", "LINT_ERROR",
                  "DISPLAY_UNAVAILABLE", "BLOCKED", "SELECTOR_NOT_FOUND"}


@mcp.tool()
def playbook_create(name: str, description: str, steps: List[Dict[str, Any]],
                    params_contract: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    [PICO-PLAYBOOK] Define una automatización PARAMETRIZABLE: una secuencia/DAG de pasos, cada
    uno {id?, tool, params?, depends_on?}. Los `params` pueden llevar marcadores `${var}` que se
    hidratan al ejecutar. `params_contract` declara las variables [{name, type?, required?,
    default?}] (RE-as-SDD de Jinja: defaults + requeridos estrictos + tipos). El DAG se valida
    con topos_guard (cero co-dependencias) antes de guardarse. Ej: E2E con ${url}.
    tools encadenables: artifact_query/_catalog/_execute_in_ram, sandbox_run, aep_ctl,
    check_crash_alerts, diagnose_system_crashes, query_system_docs, visual_inspect,
    kernel_trace, topos_audit_dag.
    """
    try:
        # LINT del playbook: cada paso debe referenciar un tool de la whitelist encadenable
        # (además de la validación DAG/topos que hace el store). Falla en creación, no en run.
        allowed = set(_playbook_dispatch())
        bad = sorted({s.get("tool") for s in steps
                      if isinstance(s, dict) and s.get("tool") not in allowed})
        if bad:
            return json.dumps(
                {"status": "LINT_ERROR", "invalid_tools": bad,
                 "allowed_tools": sorted(allowed)}, indent=2, ensure_ascii=False)
        return json.dumps(
            playbook_store.create(name, description, steps, params_contract),
            indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def playbook_list() -> str:
    """[PICO-PLAYBOOK] Lista los playbooks guardados con su tasa de éxito y nº de pasos."""
    try:
        return json.dumps({"status": "OK", "playbooks": playbook_store.list()}, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "ERROR", "error": str(e)}, indent=2)


@mcp.tool()
def playbook_run(name: str, vars: Optional[Dict[str, Any]] = None,
                 stop_on_error: bool = True) -> str:
    """
    [PICO-PLAYBOOK] Instancia y ejecuta un playbook. `vars` hidrata los marcadores `${var}` de
    los pasos contra el contrato del playbook (defaults + requeridos estrictos + tipos). Luego
    ejecuta en orden topológico, despachando cada paso al tool real y recogiendo resultados
    tipados. Registra la corrida (run_count/success) para ponderar la automatización.
    stop_on_error corta en el primer paso fallido.
    """
    pb = playbook_store.get(name)
    if not pb:
        return json.dumps({"status": "ERROR", "error": f"playbook '{name}' no existe"}, indent=2)

    # Hidratación RE-as-SDD: resuelve vars contra el contrato (StrictUndefined/defaults/tipos)
    # y sustituye estructuralmente `${var}` en los params de los pasos (sin eval).
    try:
        resolved = resolve_params(pb.get("params_contract") or [], vars or {})
        steps = hydrate_struct(pb["steps"], resolved, strict=True)
    except ValueError as e:
        return json.dumps({"status": "PARAM_ERROR", "error": str(e),
                           "contract": pb.get("params_contract") or []}, indent=2, ensure_ascii=False)

    v = PlaybookStore.validate_and_order(steps)
    if not v.get("ok"):
        return json.dumps({"status": "BLOCKED", "verdict": v.get("verdict"), "logs": v.get("logs")}, indent=2)

    dispatch = _playbook_dispatch()
    results: List[Dict[str, Any]] = []
    all_ok = True
    for step in v["ordered_steps"]:
        tool, params = step["tool"], step.get("params", {})
        fn = dispatch.get(tool)
        if fn is None:
            results.append({"id": step["id"], "tool": tool, "status": "NOT_ALLOWED", "ok": False})
            all_ok = False
            if stop_on_error:
                break
            continue
        try:
            raw = fn(**params)
            out = json.loads(raw) if isinstance(raw, str) else raw
            st = out.get("status", "OK") if isinstance(out, dict) else "OK"
        except Exception as e:
            st, out = "ERROR", {"error": str(e)}
        ok = st not in _PLAYBOOK_FAIL
        results.append({"id": step["id"], "tool": tool, "status": st, "ok": ok})
        if not ok:
            all_ok = False
            if stop_on_error:
                break

    playbook_store.record_run(name, all_ok)
    return json.dumps({"status": "OK" if all_ok else "PARTIAL", "playbook": name,
                       "all_ok": all_ok, "steps_run": len(results), "results": results},
                      indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
