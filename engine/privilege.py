"""
Engine: privilege.py — Modelo de niveles de capacidad (least-privilege por defecto).

Fuente de verdad única sobre el privilegio disponible. Las tools privilegiadas del stack
lo consultan para operar en dos niveles:

  - FULL       : el proceso es root, o puede escalar sin password (sudo -n). Alcance
                 de sistema (observabilidad kernel-wide, control de servicios, coredumps
                 de otros usuarios).
  - DIMINISHED : usuario sin vía de escalada. Alcance acotado al propio usuario/proceso;
                 la capacidad existe pero con apertura reducida (fail-soft, nunca excepción).

Diseño de seguridad: la escalada es por-tool y acotada; nunca se asume root. Un nivel más
alto AMPLÍA la apertura (self-scope -> system-scope), no es un requisito para operar.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("aep.privilege")


class _PrivilegeCache:
    sudo_n: bool | None = None


def sudo_n_available() -> bool:
    """¿Hay sudo sin contraseña (escalada no-interactiva)? Resultado cacheado por proceso."""
    if _PrivilegeCache.sudo_n is None:
        try:
            _PrivilegeCache.sudo_n = (
                bool(shutil.which("sudo"))
                and subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5, check=False).returncode == 0
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("sudo -n check failed: %s", e)
            _PrivilegeCache.sudo_n = False
    return _PrivilegeCache.sudo_n


def privilege_prefix() -> list[str] | None:
    """[] si ya es root; ['sudo','-n'] si se puede escalar; None si no hay vía (DIMINISHED)."""
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"] if sudo_n_available() else None


def privilege_mode() -> str:
    """Etiqueta del modo efectivo: direct-root | sudo-n | unprivileged."""
    if os.geteuid() == 0:
        return "direct-root"
    return "sudo-n" if sudo_n_available() else "unprivileged"



# Constantes de capacidades
CAP_RAM_EXEC = "ram_execution"
CAP_EPHEMERAL_SANDBOX = "ephemeral_sandbox"
CAP_ARTIFACT_SYNTHESIS = "artifact_synthesis"
CAP_ORIENTATION = "orientation"
CAP_SEMANTIC_MEMORY = "semantic_memory"
CAP_ASYNC_DISPATCH = "async_dispatch"
CAP_PROCESS_INTROSPECTION = "process_introspection"
CAP_SYSTEM_INSPECT = "system_inspect"
CAP_SERVICE_CONTROL = "service_control"
CAP_CRASH_FORENSICS = "crash_forensics"
CAP_KERNEL_OBSERVABILITY = "kernel_observability"
CAP_VISUAL_ACTUATION = "visual_actuation"
CAP_TOPOS_AUDIT = "topos_audit"
CAP_TASK_MANAGEMENT = "task_management"
CAP_AUTOMATION = "automation"
CAP_SYSTEM_DOCS = "system_docs"
CAP_BACKUP_ADMIN = "backup_admin"
CAP_AUDIT_READ = "audit_read"

def capability_tier() -> str:
    """FULL si hay root o escalada disponible; DIMINISHED en caso contrario."""
    return "FULL" if privilege_prefix() is not None else "DIMINISHED"


# ---------------------------------------------------------------------------
# Manifiesto de autonomía auto-descriptivo (códigos estilo chmod/777).
#
# Reutilizamos la tríada rwx de Unix, resignificada para la autonomía del agente:
#   r (4) = SENSAR     — leer estado/telemetría del sistema
#   w (2) = ACTUAR     — mutar estado del sistema
#   x (1) = EJECUTAR   — correr por caminos no-tradicionales (RAM / kernel / escalada)
# Cada capacidad lleva un octal por nivel (DIMINISHED vs FULL). El nivel más alto AMPLÍA
# la apertura; la mayoría de bits ya están disponibles en DIMINISHED (la autonomía no
# depende del privilegio: lo usa para ensanchar el alcance de self-scope a system/kernel).
# ---------------------------------------------------------------------------

# cap -> (bits_DIMINISHED, bits_FULL, scope_FULL, tools, descripción)
_CAPABILITIES = {
    "ram_execution": (5, 5, "self", ["artifact_execute_in_ram"], "Inyectar y correr ELF en RAM (memfd_create)"),
    "ephemeral_sandbox": (5, 5, "self", ["sandbox_run"], "Ejecutar aislado en sandbox bwrap"),
    "artifact_synthesis": (
        7,
        7,
        "self",
        ["artifact_lint_and_build"],
        "Sintetizar artefactos Go: inspección de plantillas, selección fuzzy, hidratación CUE y compilación/linting en RAM (artifact_lint_and_build: action='build'|'catalog'|'select'|'hydrate')",
    ),
    "orientation": (
        4,
        4,
        "self",
        ["discover"],
        "Traducir un caso de uso -> qué reutilizar/sintetizar/automatizar y manifiesto de autonomía (discover: action='discover'|'capabilities')",
    ),
    "semantic_memory": (
        6,
        6,
        "self",
        ["artifact_catalog"],
        "Leer/escribir, DESCUBRIR, AUTO-INDEXAR y PODAR (GC seguro) la memoria semántica (sqlite-vec)",
    ),
    "async_dispatch": (
        7,
        7,
        "self",
        ["async_job_dispatch"],
        "Despachar/inspeccionar tareas asíncronas en Pueue (async_job_dispatch: action='dispatch'|'inspect')",
    ),
    "process_introspection": (
        4,
        4,
        "system",
        ["process_inspect"],
        "Introspección de descriptores de procesos (/proc/PID/fd y estado)",
    ),
    "system_inspect": (4, 4, "system", ["aep_ctl"], "Leer red, almacenamiento y paquetes (aep-ctl)"),
    "service_control": (
        4,
        6,
        "system",
        ["aep_ctl"],
        "Controlar servicios: DIMINISHED solo scope-usuario; FULL muta sistema",
    ),
    "crash_forensics": (
        4,
        4,
        "system",
        ["diagnose_system_crashes"],
        "Forense de crashes y alertas proactivas: coredumps, journald y tickets (diagnose_system_crashes: action='diagnose'|'alerts')",
    ),
    "kernel_observability": (0, 4, "kernel", ["kernel_trace"], "Telemetría de kernel eBPF: requiere FULL (CAP_BPF)"),
    "visual_actuation": (5, 5, "self", ["visual_inspect"], "Renderizar y capturar UIs headless (/dev/shm)"),
    "topos_audit": (4, 4, "self", ["topos_audit_dag"], "Auditar DAGs y bloquear co-dependencias"),
    "task_management": (
        6,
        6,
        "self",
        ["kanban_board"],
        "Pico-Kanban: tareas atómicas + ponderación con promoción/degradación y archivado reversible",
    ),
    "automation": (
        7,
        7,
        "self",
        ["playbook_run"],
        "Pico-Playbooks: orquestación de flujos DAG, ejecución, listado, creación y poda segura (playbook_run: action='run'|'create'|'list'|'prune')",
    ),
    "backup_admin": (4, 6, "system", ["aep_ctl"], "Gestión de copias de seguridad y rotación de backups (aep-ctl backup)"),
    "audit_read": (4, 4, "self", ["aep_ctl"], "Inspección y verificación de la cadena de auditoría criptográfica"),
    "system_docs": (
        4,
        4,
        "self",
        ["query_system_docs"],
        "Memoria semántica local de man-pages (sqlite-vec): sintaxis exacta sin alucinar flags",
    ),
}

_PERM_TABLE = {7: "rwx", 6: "rw-", 5: "r-x", 4: "r--", 3: "-wx", 2: "-w-", 1: "--x", 0: "---"}

# Keywords BILINGÜES (EN/ES) por capacidad: anclas léxicas language-aligned para el enrutador
# `discover`. Las descriptions están en español y los names/tools en inglés, así que una query EN
# ("run binary", "memory", "trace kernel") tenía poco con qué casar. Esto cierra la colisión ES/EN:
# el matcher las pondera como tags (x2) sumadas a los nombres de tools. Ampliar aquí es barato.
_CAP_KEYWORDS = {
    "ram_execution": "run binary memfd fileless in-memory ejecutar binario memoria elf payload probe",
    "ephemeral_sandbox": "sandbox isolate bwrap jail contained run test pytest repo workspace mount ro_paths rw_paths working_dir aislar aislado seguro pruebas",
    "artifact_synthesis": "synthesize template catalog select hydrate lint build compile go binary cue contract schema validate code static analysis vet generar crear sintetizar plantilla catalogo seleccionar hidratar compilar construir binario",
    "orientation": "discover orient what to do route start where begin capabilities manifest status chmod permisos autonomy autonomia playbook tactical guide help how to use orientar descubrir enrutar empezar",
    "semantic_memory": "memory search recall catalog query reindex prune index vector embeddings reuse find store sqlite vec memoria buscar recordar catalogo consultar indice podar sanar reutilizar guardar",
    "async_dispatch": "async background queue long job pueue dispatch inspect status log test suite ruff pytest ci lint verify cola asincrono tarea larga despachar inspeccionar estado segundo plano",
    "process_introspection": "process inspect fd descriptor proc pid introspection open files socket pipes leak rss memory telemetry resource footprint proceso descriptor introspeccion archivos abiertos fugas",
    "system_inspect": "network storage packages inspect read system status listeners mounts disks schema aep_ctl control plane contract red almacenamiento paquetes inspeccionar sistema estado esquema",
    "service_control": "service control start stop restart systemd daemon unit servicio controlar arrancar detener reiniciar",
    "crash_forensics": "crash core dump forensic coredump diagnose fault alerts router ticket new proactive journalctl systemd errors crasheo volcado forense diagnosticar fallo alertas enrutador ticket nuevo proactivo",
    "kernel_observability": "kernel trace ebpf bpf syscall observe probe openat execve landlock denials trazar sondear llamadas sistema",
    "visual_actuation": "visual screenshot render headless ui browser page html dom layout playwright chromium visual captura renderizar pantalla navegador",
    "topos_audit": "audit dag graph dependency cycle codependency architecture code review structural verification validation plan auditar grafo dependencia ciclo arquitectura",
    "task_management": "task kanban board create advance promote demote reevaluate archive unarchive manage weigh track milestone state tarea tablero crear avanzar promover degradar reevaluar archivar desarchivar gestionar ponderar seguir",
    "automation": "automate playbook run create list prune workflow chain pipeline steps gc clean orchestrate automatizar ejecutar crear listar podar orquestar flujo secuencia pasos limpiar",
    "backup_admin": "backup restore recover rotation hot snapshot sqlite wal quarantine golden micro_snapshot copia seguridad restaurar",
    "audit_read": "audit log security chain cryptographic hash ledger tamper verify verificar auditoria cadena criptografica",
    "system_docs": "man manpage documentation syntax flags command help manual documentacion sintaxis comando",
}

# Single Source of Truth for the Control Plane Schema (shared by scripts/aep-ctl and server.py)
CONTROL_PLANE_SCHEMA: dict[str, dict[str, Any]] = {
    "service": {
        "actions": ["list", "status", "start", "stop", "restart"],
        "arg": "[name]",
        "scope": "systemd --user (DIMINISHED) | system (FULL)",
        "description": "List active systemd services or inspect/mutate a specific service unit without interactive pagers.",
    },
    "network": {
        "actions": ["inspect", "routes", "listeners"],
        "arg": None,
        "description": "Inspect network interfaces, routing tables, and active TCP/UDP listening sockets.",
    },
    "storage": {
        "actions": ["usage", "mounts", "disks"],
        "arg": None,
        "description": "Inspect filesystem byte usage, mount trees, and block devices.",
    },
    "package": {
        "actions": ["installed", "list", "check", "info"],
        "arg": "[name]",
        "description": "Query Debian/Ubuntu dpkg state for installed packages and versions.",
    },
    "backup": {
        "actions": [
            "backup",
            "restore",
            "status",
            "backup_status",
            "auto_recover",
            "verify_and_auto_recover",
            "verify_integrity",
            "micro_snapshot",
            "restore_micro_snapshot",
            "list_micro_snapshots",
            "clear_micro_snapshots",
            "golden",
            "restore_golden",
            "quarantine_status",
            "workspace_snapshot",
            "workspace_restore",
        ],
        "arg": "[slot_number|name]",
        "description": "Manage 5-slot hot SQLite backups, RAM micro-snapshots (catalog only), workspace snapshots/restores, canary integrity, and quarantine.",
    },
    "security": {
        "actions": ["landlock_status", "status", "audit", "verify"],
        "arg": None,
        "description": "Check Linux Landlock LSM kernel ABI support, self-confinement readiness, and verify audit chain.",
    },
    "audit": {
        "actions": ["verify", "usage"],
        "arg": "[session_id]",
        "description": "Verify the SHA-256 tamper-evident cryptographic audit ledger or inspect per-agent tool usage summary.",
    },
    "ipc": {
        "actions": ["status", "ping", "lease", "release", "reap", "pool", "flush", "metrics", "stats", "cache"],
        "arg": "[session_id]",
        "description": "Shared-memory UNIX domain socket pool (/dev/shm/aep.sock) and ephemeral session slot management.",
    },
}

_CAP_BINARIES: dict[str, list[str]] = {
    "ram_execution": [],
    "ephemeral_sandbox": ["bwrap"],
    "artifact_synthesis": ["go"],
    "orientation": [],
    "semantic_memory": [],
    "async_dispatch": ["pueue", "pueued"],
    "process_introspection": [],
    "system_inspect": ["ss", "ip", "findmnt", "lsblk", "dpkg-query"],
    "service_control": ["systemctl"],
    "crash_forensics": ["coredumpctl", "journalctl"],
    "kernel_observability": ["bpftrace"],
    "visual_actuation": ["chromium_or_playwright"],
    "topos_audit": [],
    "task_management": [],
    "automation": [],
    "backup_admin": [],
    "audit_read": [],
    "system_docs": ["man"],
}

_CAP_TACTICAL: dict[str, dict[str, Any]] = {
    "orientation": {
        "when_to_use": "First call in any session to inspect permissions, binary readiness, tactical playbooks, or route a natural-language task.",
        "canonical_calls": [
            'discover(action="capabilities")',
            'discover(action="playbook")',
            'discover(use_case="run repository test suite in isolated sandbox")',
        ],
    },
    "topos_audit": {
        "when_to_use": "Before executing multi-step plans or code changes to verify zero circular co-dependencies (A <-> B).",
        "canonical_calls": [
            'topos_audit_dag(tasks=["plan", "code", "verify"], dependencies={"plan": [], "code": ["plan"], "verify": ["code"]})',
        ],
    },
    "ephemeral_sandbox": {
        "when_to_use": "Execute untrusted commands, linters, or repository test suites inside an isolated Bubblewrap namespace jail.",
        "canonical_calls": [
            'sandbox_run(command="pytest -q", working_dir="/path/to/repo", ro_paths=["/path/to/repo"], share_net=False)',
            'sandbox_run(command="python3 -c \'print(42)\'")',
        ],
    },
    "async_dispatch": {
        "when_to_use": "Run long-running test suites, builds, or linters asynchronously via Pueue without blocking the agent loop.",
        "canonical_calls": [
            'async_job_dispatch(action="dispatch", command="pytest -q", working_dir="/path/to/repo")',
            'async_job_dispatch(action="status", verbosity="summary")',
            'async_job_dispatch(action="log", task_id=1, lines=40)',
        ],
    },
    "system_inspect": {
        "when_to_use": "Query control-plane schema, network listeners, routes, storage mounts, or installed packages as compact typed JSON.",
        "canonical_calls": [
            'aep_ctl(action="schema")',
            'aep_ctl(domain="network", action="listeners", verbosity="summary", limit=20)',
            'aep_ctl(domain="storage", action="mounts", verbosity="summary")',
            'aep_ctl(domain="package", action="check", name="semgrep")',
        ],
    },
    "process_introspection": {
        "when_to_use": "Inspect open file descriptors (/proc/PID/fd), sockets, pipes, threads, and RSS memory delta of AEP or target PIDs.",
        "canonical_calls": [
            'process_inspect(pid=0, limit=25, verbosity="summary")',
            'process_inspect(pid=1234, limit=50)',
        ],
    },
    "ram_execution": {
        "when_to_use": "Execute pre-compiled static Go binaries from the catalog directly in anonymous RAM (memfd_create) with zero disk footprint.",
        "canonical_calls": [
            'artifact_execute_in_ram(name="socket_monitor", args=["--port=8080"])',
        ],
    },
    "artifact_synthesis": {
        "when_to_use": "Select, hydrate, vet, and compile static Go probes (CGO_ENABLED=0) from parameterized templates.",
        "canonical_calls": [
            'artifact_lint_and_build(action="catalog")',
            'artifact_lint_and_build(action="build", name="tcp_probe", intent="monitor tcp port", category="network", template_name="socket_monitor")',
        ],
    },
    "semantic_memory": {
        "when_to_use": "Search, query, reindex, or garbage-collect the hybrid SHA-256 + sqlite-vec artifact catalog.",
        "canonical_calls": [
            'artifact_catalog(action="browse", query="socket monitor", limit=5)',
            'artifact_catalog(action="query", intent="inspect open sockets", category="network")',
        ],
    },
    "crash_forensics": {
        "when_to_use": "Check proactive crash tickets or diagnose recent systemd/coredump failures with compact journal filtering.",
        "canonical_calls": [
            'diagnose_system_crashes(action="alerts")',
            'diagnose_system_crashes(action="diagnose", limit=5, verbosity="summary")',
        ],
    },
    "kernel_observability": {
        "when_to_use": "Run curated read-only eBPF probes (syscall counts, openat denials, execve monitor, Landlock audit) when in FULL tier.",
        "canonical_calls": [
            'kernel_trace(mode="syscall_count", duration_sec=2)',
            'kernel_trace(mode="security_open_denials", duration_sec=2)',
        ],
    },
    "visual_actuation": {
        "when_to_use": "Render a web UI in headless Chromium and capture a RAM screenshot (/dev/shm) with fail-soft fallback.",
        "canonical_calls": [
            'visual_inspect(url="http://localhost:8000", viewport_width=1280, viewport_height=800)',
        ],
    },
    "service_control": {
        "when_to_use": "Check or manage systemd services (user-scope in DIMINISHED, system-scope in FULL).",
        "canonical_calls": [
            'aep_ctl(domain="service", action="status", name="ssh")',
        ],
    },
    "backup_admin": {
        "when_to_use": "Create/restore 5-slot FIFO SQLite backups, ultra-fast RAM micro-snapshots, or inspect anti-poisoning quarantine.",
        "canonical_calls": [
            'aep_ctl(domain="backup", action="micro_snapshot", name="pre_change")',
            'aep_ctl(domain="backup", action="status")',
            'aep_ctl(domain="backup", action="verify_integrity")',
        ],
    },
    "audit_read": {
        "when_to_use": "Verify cryptographic integrity of the SHA-256 chained security audit log.",
        "canonical_calls": [
            'aep_ctl(domain="audit", action="verify")',
        ],
    },
    "task_management": {
        "when_to_use": "Track multi-step engineering state in SQLite (BACKLOG -> SYNTHESIZED -> LINTED -> CANARY -> PROMOTED) outside volatile LLM context.",
        "canonical_calls": [
            'kanban_board(action="board")',
            'kanban_board(action="create", title="feat: x", intent="implement x", category="engine")',
        ],
    },
    "automation": {
        "when_to_use": "Create or run parameterized multi-tool DAG playbooks, or execute single-turn ephemeral batches with in-RAM variable piping ($prev.*, $steps.<id>.*, $cache.<key>.*) and server-side field projection.",
        "canonical_calls": [
            'playbook_run(action="list")',
            'playbook_run(action="run", name="aep-self-diagnostic", return_only="last", select_fields=["status", "valid", "block_count"])',
            'playbook_run(action="batch", steps=[{"id": "s1", "tool": "process_inspect", "params": {"pid": 0}, "store_as": "proc"}], return_only="last", select_fields=["status", "pid", "fd_count"])',
        ],
    },
    "system_docs": {
        "when_to_use": "Retrieve exact CLI flag syntax from local vectorized man-pages without hallucinating options.",
        "canonical_calls": [
            'query_system_docs(query="bubblewrap bind mount read only", ingest_command="bwrap", limit=3)',
        ],
    },
}


def check_binary_prerequisites() -> dict[str, dict[str, Any]]:
    """Inspect real host installation status for all binary prerequisites used across AEP."""
    binaries = [
        "bwrap",
        "pueue",
        "pueued",
        "go",
        "golangci-lint",
        "coredumpctl",
        "journalctl",
        "bpftrace",
        "ss",
        "ip",
        "findmnt",
        "lsblk",
        "dpkg-query",
        "systemctl",
        "man",
    ]
    status: dict[str, dict[str, Any]] = {}
    local_bin = Path.home() / ".local" / "bin"
    for b in binaries:
        found = shutil.which(b)
        if not found and (local_bin / b).exists():
            found = str(local_bin / b)
        status[b] = {"installed": bool(found), "path": found}

    # Check Chromium / Playwright availability for visual_inspect
    pw_browsers = list((Path.home() / ".cache" / "ms-playwright").glob("chromium*")) if (Path.home() / ".cache" / "ms-playwright").exists() else []
    sys_browser = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    browser_path = sys_browser or (str(pw_browsers[0]) if pw_browsers else None)
    status["chromium_or_playwright"] = {
        "installed": bool(browser_path),
        "path": browser_path,
    }
    return status


def tactical_playbook() -> dict[str, Any]:
    """Kali-MCP inspired semantic playbook: taxonomic catalog, canonical 1-liners, workflows, and RoE."""
    prereqs = check_binary_prerequisites()
    return {
        "status": "OK",
        "playbook_version": "EAES-v2-Kali-Semantic",
        "overview": (
            "Agent Execution Plane (AEP) Tactical Guide. Designed for zero-hallucination, "
            "low-token consumption, and deterministic Linux control. Every tool returns typed JSON "
            "with request telemetry and an agent-brief envelope."
        ),
        "rules_of_engagement": [
            "1. TOKEN EFFICIENCY FIRST: Pass verbosity='summary' (or 'brief') on diagnostic calls (aep_ctl, diagnose_system_crashes, process_inspect) to cut payload size by 70-85%.",
            "2. SCHEMA WITHOUT GUESSING: Call aep_ctl(action='schema') to inspect all control-plane domains and valid actions before invoking aep_ctl.",
            "3. SANDBOX ISOLATION: sandbox_run defaults to share_net=False and hides the host workspace. Pass working_dir='/path/to/repo' or ro_paths=['/path'] to mount authorized directories safely.",
            "4. STATE EXTERNALIZATION: Record multi-step work in kanban_board and validate task dependencies with topos_audit_dag before mutating files.",
            "5. SNAPSHOT BEFORE MUTATION: Call aep_ctl(domain='backup', action='micro_snapshot', name='pre_edit') before risky database or catalog changes.",
            "6. EPHEMERAL PIPELINE BATCHING: Use playbook_run(action='batch', steps=[...], return_only='last', select_fields=[...]) or /dev/shm/aep.sock UNIX socket pool to execute multi-tool chains in a single turn and discard unneeded fields server-side (saving 80-98% tokens).",
            "7. ZERO-TOKEN MULTI-AGENT RAM HANDOFF & CONCURRENCY: Share state across agents in /dev/shm/aep_pool using params={'session_id': 'shared'} + store_as='key' and reference $cache.<key>.<field> (or $slot.<key>.<field>). All 15 tools (Pico-Kanban, Pico-Jenkins Go builds, Pico-Ansible playbooks, SHA-256 audit log, and RAM snapshots) are collision-free under concurrent multi-agent execution.",
            "8. MULTI-AGENT RAM CAPABILITY CACHING (GAP-DOC-02): Subagents must call discover(action='capabilities', session_id='<shared-id>', verbosity='terse') to read cached capabilities directly from RAM slot, eliminating redundant 1.2k-1.9k token re-discovery taxes (>95% savings).",
        ],
        "workflow_recipes": [
            {
                "id": "WF-1",
                "name": "Code, Contract & Architecture Audit",
                "steps": [
                    '1. discover(action="capabilities") -> Verify tier, binary readiness, and permissions.',
                    '2. aep_ctl(action="schema") -> Inspect unified control-plane contract.',
                    '3. topos_audit_dag(tasks=[...], dependencies={...}) -> Verify zero circular co-dependencies.',
                    '4. aep_ctl(domain="audit", action="verify") -> Verify SHA-256 security ledger integrity.',
                ],
            },
            {
                "id": "WF-2",
                "name": "Safe Sandboxed Repository Verification",
                "steps": [
                    '1. sandbox_run(command="pytest -q", working_dir="/path/to/repo", share_net=False) -> Run tests inside isolated Bubblewrap jail with read-only workspace bind.',
                    '2. async_job_dispatch(action="dispatch", command="ruff check . && pytest -q", working_dir="/path/to/repo") -> Offload long test suites to Pueue background queue.',
                ],
            },
            {
                "id": "WF-3",
                "name": "Low-Token System & Process Triage",
                "steps": [
                    '1. process_inspect(pid=0, limit=15, verbosity="summary") -> Check AEP RSS memory and FD deltas.',
                    '2. aep_ctl(domain="network", action="listeners", verbosity="summary", limit=15) -> List active ports compactly.',
                    '3. diagnose_system_crashes(action="diagnose", limit=5, verbosity="summary") -> Inspect compact systemd errors and coredumps.',
                ],
            },
            {
                "id": "WF-4",
                "name": "Zero-Disk Go Probe Synthesis & RAM Execution",
                "steps": [
                    '1. artifact_lint_and_build(action="select", intent="monitor tcp sockets") -> Rank proven templates.',
                    '2. artifact_lint_and_build(action="build", name="probe_1", intent="monitor tcp", category="network", template_name="socket_monitor") -> Hydrate, vet, and compile static ELF.',
                    '3. artifact_execute_in_ram(name="probe_1") -> Execute via memfd_create in RAM and auto-record canary metrics.',
                ],
            },
            {
                "id": "WF-5",
                "name": "Cloudflare-Style Ephemeral Batch & UNIX Socket Pool",
                "steps": [
                    '1. aep_ctl(domain="ipc", action="status", verbosity="summary") -> Check /dev/shm/aep.sock listener and active pool slots.',
                    '2. playbook_run(action="batch", steps=[{"id":"s1","tool":"process_inspect","params":{"pid":0}}, {"id":"s2","tool":"topos_audit_dag","params":{"tasks":["t1"],"dependencies":{}}}], return_only="last", select_fields=["status","verdict"]) -> Execute multi-step DAG in 1 turn with server-side field projection.',
                ],
            },
            {
                "id": "WF-6",
                "name": "Zero-Token Multi-Agent RAM Handoff & Collision-Free Pico-Triad",
                "steps": [
                    '1. Agent A (pragma): playbook_run(action="batch", params={"session_id":"team-1"}, agent_id="pragma", steps=[{"id":"b1","tool":"artifact_lint_and_build","params":{"action":"build","template_name":"mem-stat"},"store_as":"build_out"}]) -> Builds Go ELF in isolated /dev/shm slot and caches output.',
                    '2. Agent B (dokimos): playbook_run(action="batch", params={"session_id":"team-1"}, agent_id="dokimos", steps=[{"id":"c1","tool":"artifact_execute_in_ram","params":{"name":"$cache.build_out.name"}}, {"id":"c2","tool":"kanban_board","params":{"action":"promote","task_id":"$cache.build_out.kanban_task_id"}}], return_only="last", select_fields=["status","verdict"]) -> Reads Agent A state from /dev/shm RAM and promotes artifact in 1 turn.',
                ],
            },
        ],
        "quick_reference": {
            "orient_and_readiness": 'discover(action="capabilities", verbosity="summary")',
            "tactical_guide": 'discover(action="playbook", verbosity="summary")',
            "control_plane_schema": 'aep_ctl(action="schema")',
            "compact_listeners": 'aep_ctl(domain="network", action="listeners", verbosity="summary")',
            "compact_mounts": 'aep_ctl(domain="storage", action="mounts", verbosity="summary")',
            "sandbox_repo_test": 'sandbox_run(command="pytest -q", working_dir="/path/to/repo", verbosity="summary")',
            "ram_micro_snapshot": 'aep_ctl(domain="backup", action="micro_snapshot", name="snap1")',
            "audit_ledger_verify": 'aep_ctl(domain="audit", action="verify", verbosity="summary")',
            "ipc_socket_status": 'aep_ctl(domain="ipc", action="status", verbosity="summary")',
            "ipc_shared_cache": 'aep_ctl(domain="ipc", action="cache", name="team-1")',
            "ephemeral_batch": 'playbook_run(action="batch", steps=[...], return_only="last", select_fields=["status"])',
            "terse_cached_capabilities": 'discover(action="capabilities", session_id="team-1", verbosity="terse")',
        },
        "prerequisites_summary": {
            k: v["installed"] for k, v in prereqs.items()
        },
    }


def capability_manifest() -> dict:
    """Manifiesto de autonomía en primera vista para la IA que consume el MCP."""
    tier = capability_tier()
    idx = 1 if tier == "FULL" else 0
    prereqs = check_binary_prerequisites()
    caps = {}
    for name, (dim, full, scope, tools, desc) in _CAPABILITIES.items():
        bits = (dim, full)[idx]
        req_bins = _CAP_BINARIES.get(name, [])
        missing_bins = [b for b in req_bins if not prereqs.get(b, {}).get("installed", False)]
        tactical = _CAP_TACTICAL.get(name, {})
        caps[name] = {
            "perm": f"{bits}{_PERM_TABLE[bits]}",  # p.ej. "4r--", "7rwx"
            "octal_now": bits,
            "octal_diminished": dim,
            "octal_full": full,
            "unlocks_with_full": full > dim,
            "ready": (bits > 0) and (len(missing_bins) == 0),
            "required_binaries": req_bins,
            "missing_binaries": missing_bins,
            "scope": scope if bits else "none",
            "tools": tools,
            "description": desc,
            "when_to_use": tactical.get("when_to_use", desc),
            "canonical_calls": tactical.get("canonical_calls", []),
            "keywords": _CAP_KEYWORDS.get(name, ""),
        }
    return {
        "what_is_this": "AEP MCP: plano de ejecución para GESTIONAR LA AUTONOMÍA de agentes de IA. "
        "Transmuta primitivas de herramientas ofensivas (RAM exec, sandbox, eBPF, "
        "introspección) en capacidades agénticas gobernadas por privilegio.",
        "capability_tier": tier,
        "privilege_mode": privilege_mode(),
        "prerequisites": prereqs,
        "control_plane_domains": list(CONTROL_PLANE_SCHEMA.keys()),
        "tactical_hint": "Call discover(action='playbook') for Kali-style workflow recipes, canonical 1-liners, and token-saving Rules of Engagement.",
        "legend": {
            "r (4)": "SENSAR — leer estado/telemetría",
            "w (2)": "ACTUAR — mutar estado del sistema",
            "x (1)": "EJECUTAR — caminos no-tradicionales (RAM/kernel/escalada)",
            "octal_reference": _PERM_TABLE,
            "note": "Como chmod: cada capacidad es una tríada rwx. El nivel FULL ensancha "
            "la apertura (self -> system -> kernel); la autonomía base ya opera en DIMINISHED.",
        },
        "capabilities": caps,
    }


class PermissionDenied(Exception):
    """Excepción lanzada cuando una acción es bloqueada por CapabilityGuard."""

    def __init__(
        self,
        message: str,
        capability: str | None = None,
        agent_id: str | None = None,
        action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.capability = capability
        self.agent_id = agent_id
        self.action = action


class CapabilityGuard:
    """Motor de control de acceso basado en capacidades (CBAC)."""

    SYSTEM_MUTATION_ACTIONS: set[str] = {"system_service_mutate", "kernel_trace_start", "audit_purge"}

    PATH_BLACKLIST: tuple[str, ...] = (
        "/etc/shadow",
        "/etc/gshadow",
        "/etc/sudoers",
        "/etc/security",
        "/root",
        "/proc/kcore",
        "/dev/mem",
        "/dev/kmem",
    )

    @classmethod
    def is_path_blacklisted(cls, path_str: str) -> bool:
        """Comprueba si una ruta coincide con o está dentro de rutas restringidas."""
        try:
            p = Path(path_str).expanduser().resolve()
            resolved_str = str(p)
            ssh_dir = str(Path.home() / ".ssh")
            gnupg_dir = str(Path.home() / ".gnupg")
            if resolved_str == ssh_dir or resolved_str.startswith(ssh_dir + "/"):
                return True
            if resolved_str == gnupg_dir or resolved_str.startswith(gnupg_dir + "/"):
                return True
            for b in cls.PATH_BLACKLIST:
                if resolved_str == b or resolved_str.startswith(b + "/"):
                    return True
        except (OSError, ValueError):
            return False
        return False

    @classmethod
    def verify_action(
        cls,
        agent_id: str,
        capability: str,
        action: str,
        target: str | None = None,
    ) -> None:
        """
        Lanza PermissionDenied si la acción solicitada viola las políticas de capacidad.
        """
        tier = capability_tier()
        norm_cap = capability.lower().removeprefix("cap_")

        # 1. Validación de blacklist de rutas
        if target and cls.is_path_blacklisted(target):
            raise PermissionDenied(
                f"Acceso denegado a ruta restringida '{target}' bajo capacidad '{capability}'.",
                capability=capability,
                agent_id=agent_id,
                action=action,
            )

        # 2. DIMINISHED vs FULL: acciones restringidas a nivel de sistema
        if tier == "DIMINISHED":
            if action in cls.SYSTEM_MUTATION_ACTIONS or norm_cap == "kernel_observability":
                raise PermissionDenied(
                    f"Agente '{agent_id}' en tier DIMINISHED no tiene autorización para '{action}' en '{capability}'. Requiere nivel FULL.",
                    capability=capability,
                    agent_id=agent_id,
                    action=action,
                )

    @classmethod
    def check_action(
        cls,
        agent_id: str,
        capability: str,
        action: str,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Evaluación fail-soft de autorización que devuelve diccionario estructurado."""
        try:
            cls.verify_action(agent_id, capability, action, target)
            return {"status": "ALLOWED", "allowed": True, "agent_id": agent_id, "capability": capability}
        except PermissionDenied as e:
            return {
                "status": "PERMISSION_DENIED",
                "allowed": False,
                "error": e.message,
                "agent_id": agent_id,
                "capability": capability,
                "action": action,
            }
