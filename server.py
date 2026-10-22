#!/usr/bin/env python3
"""
Agent Execution Plane (AEP) - Unified FastMCP Server
Exposes deterministic system execution, in-memory Go artifact lifecycle,
asynchronous job queues (Pueue), crash forensics, and Topos DAG auditing to AI agents.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

from engine.catalog import ArtifactCatalog
from engine.hydrator import TemplateHydrator
from engine.topos_guard import ToposGuard, ToposVerdict

mcp = FastMCP("Agent-Execution-Plane")
catalog = ArtifactCatalog()
hydrator = TemplateHydrator()

# Rutas base
PROJECT_DIR = Path(__file__).resolve().parent
TEMP_BIN_DIR = Path.home() / ".local" / "share" / "agent-os" / "bin"
TEMP_BIN_DIR.mkdir(parents=True, exist_ok=True)


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
    hit = catalog.find_by_intent(intent, category)
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
            },
            indent=2,
        )
    return json.dumps(
        {
            "status": "CACHE_MISS",
            "message": "No se encontró artefacto en caché. Proceder a hidratar o sintetizar.",
            "available_templates": hydrator.list_available_templates(),
        },
        indent=2,
    )


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

        return json.dumps(
            {
                "status": "SUCCESS",
                "artifact_id": artifact_id,
                "name": name,
                "binary_path": str(bin_file),
                "binary_size_bytes": len(binary_bytes),
                "compile_time_ms": compile_latency_ms,
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

        return json.dumps(
            {
                "status": "SUCCESS" if res.returncode == 0 else "EXEC_FAILED",
                "exit_code": res.returncode,
                "latency_ms": latency_ms,
                "output": stdout_parsed,
                "stderr": res.stderr.strip() if res.stderr else None,
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
    coredumps_raw = subprocess.run(
        ["coredumpctl", "list", "--json=short", "-n", str(limit)],
        capture_output=True,
        text=True,
    )
    journal_errs = subprocess.run(
        ["journalctl", "-p", "err", "-n", str(limit), "-o", "json"],
        capture_output=True,
        text=True,
    )

    recent_coredumps = []
    if coredumps_raw.returncode == 0 and coredumps_raw.stdout.strip():
        try:
            recent_coredumps = json.loads(coredumps_raw.stdout)
        except Exception:
            pass

    recent_errors = []
    for line in journal_errs.stdout.splitlines():
        if line.strip():
            try:
                recent_errors.append(json.loads(line))
            except Exception:
                pass

    return json.dumps(
        {
            "recent_coredumps": recent_coredumps,
            "recent_systemd_errors": recent_errors,
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


if __name__ == "__main__":
    mcp.run()
