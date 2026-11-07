#!/usr/bin/env python3
"""
Agent Execution Plane (AEP) - Unified FastMCP Server
Exposes deterministic system execution, in-memory Go artifact lifecycle,
asynchronous job queues (Pueue), crash forensics, and Topos DAG auditing to AI agents.
"""

import concurrent.futures
import contextlib
import contextvars
import inspect
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import NotificationOptions

from engine import headless_display, matcher
from engine import lkg_ctl as _lkg_ctl
from engine.backup import (
    clear_micro_snapshots,
    create_backup,
    create_golden_snapshot,
    create_micro_snapshot,
    create_workspace_snapshot,
    get_backup_status,
    get_quarantine_status,
    list_micro_snapshots,
    restore_backup,
    restore_golden_snapshot,
    restore_micro_snapshot,
    restore_workspace_snapshot,
    verify_and_auto_recover,
    verify_database_integrity,
)
from engine.catalog import ArtifactCatalog
from engine.crash_router import CrashRouter
from engine.harness_reconnect import RECONNECT_POINTER
from engine.hydrator import TemplateHydrator, hydrate_struct, resolve_params
from engine.ipc_pool import (
    GLOBAL_SESSION_POOL,
    GLOBAL_SOCKET_MUX,
    ensure_ipc_server_started,
    ipc_client_request,
    project_fields,
    resolve_step_refs,
)
from engine.kanban import KanbanBoard
from engine.landlock import get_landlock_status
from engine.playbook import PlaybookStore
from engine.privilege import (
    CHMOD_DEGRADATION_MATRIX,
    CONTROL_PLANE_SCHEMA,
    CapabilityGuard,
    PermissionDenied,
    capability_manifest,
    capability_tier,
    get_effective_chmod_tier,
    privilege_mode,
    privilege_prefix,
    tactical_playbook,
)
from engine.security import get_agent_usage_summary, mask_pueue_output, record_audit_event, verify_audit_chain
from engine.telemetry import RequestTelemetry, attach_envelope
from engine.template_registry import TemplateRegistry
from engine.topos_guard import ToposGuard, ToposVerdict

SERVER_START_TIME = time.time()
logger = logging.getLogger("aep.server")

_INSTRUCTIONS = """# Agent Execution Plane (AEP) — Tactical Suite & Instructions (EAES-v2)

AEP is a deterministic Linux Control Plane and High-Resilience Agent Runtime on Ubuntu/Linux. It exposes 17 typed JSON-RPC tools (19 capabilities) backed by low-level Linux kernel primitives (`memfd_create` volatile RAM execution, `/dev/shm/aep.sock` AF_UNIX multiplexed IPC & `/dev/shm/aep_pool` warm session pool, Bubblewrap namespace sandboxing, Landlock LSM confinement, `bpftrace` eBPF observability, Pueue async queues, and `sqlite-vec` hybrid semantic memory) under 4-tier Unix chmod octal privilege governance:
- **7rwx** (Root / Passwordless Sudo): Unrestricted system-wide & kernel scope, raw packet capture, eBPF tracing, system unit mutation, netfilter hardening.
- **6rw-** (Standard User RW): Bounded user scope, user-space systemd units (`systemctl --user`), in-RAM anonymous exec (`memfd_create`), SQLite RW, user Pueue dispatch.
- **5r-x** (Restricted / Container RO-Exec): Read-only workspace bind, in-RAM anonymous execution permitted, template inspection & syntax linting, query tools active.
- **4r--** (Auditor / RO-Observer): Strict read-only audit posture, zero disk mutation, DAG verification (`topos_audit_dag`), SHA-256 ledger audit, query docs.
- Backward compatibility: `FULL` maps to `7rwx`; `DIMINISHED` maps to `6rw-`, `5r-x`, and `4r--`.

## 1. Recommended First Calls (Zero-Guessing Orientation)
1. `discover(action="capabilities", verbosity="summary")` -> Returns the `chmod/777`-style autonomy manifest (`r`=sense, `w`=act, `x`=execute), active tier (`FULL`/`DIMINISHED`), and real host binary readiness.
2. `discover(action="playbook", verbosity="summary")` -> Returns workflow recipes (`WF-1..WF-11`) and canonical calls.
3. `aep_ctl(action="schema")` -> Returns the complete 9-domain control-plane contract (`service`, `network`, `storage`, `package`, `backup`, `security`, `audit`, `ipc`, `schema`) without requiring a dummy domain.

## 2. Complete 17-Tool Suite Map (6 Operational Domains)
- **Domain 1 — Orientation, Synthesis & In-RAM Execution**:
  1. `discover(use_case="", action="discover"|"capabilities"|"playbook", limit=3, verbosity="summary")`
  2. `artifact_lint_and_build(action="build"|"catalog"|"select"|"hydrate", name=..., template_name=..., agent_id=..., verbosity="summary")` *(1-step isolated Go build in `/dev/shm/aep_pool` + atomic `os.replace` & `kanban.upsert_build_task`: `template_name="socket-monitor"|"fd-rescuer"|"disk-usage"|"mem-stat"|"landlock-guard"`)*
  3. `artifact_execute_in_ram(name="socket_monitor", args=[], verbosity="summary", limit=25)` *(executes ELF via `memfd_create` with `fd_delta=0`)*
  4. `artifact_catalog(action="browse"|"query"|"reindex"|"prune", query=..., limit=10, verbosity="summary")`
  5. `default_primitives(action="list"|"info"|"run", name="socket-monitor"|"fd-rescuer"|"disk-usage"|"mem-stat"|"landlock-guard", params={}, verbosity="summary")` *(instant in-RAM system diagnostics without template compilation lifecycle)*
- **Domain 2 — State Governance & Process Introspection**:
  17. `autoevol(action="graph"|"gaps"|"thread"|"log"|"diff"|"spec"|"verify"|"fix_test"|"heal", node=..., a=..., b=..., gap=..., base=..., cycle=..., job=..., apply=False, restart=False, probe=False, limit=10, select_fields=[...], verbosity="summary")` *(read-only thread graph: Merkle root R, omission gaps, drift, ranking; persists generations only at tier >= 6rw-)*
  6. `topos_audit_dag(tasks=["plan","code","test"], dependencies={"code":["plan"],"test":["code"]}, verbosity="summary")` *(blocks circular co-dependencies `A <-> B`)*
  7. `kanban_board(action="board"|"create"|"advance"|"promote"|"demote"|"reevaluate"|"archive"|"unarchive", verbosity="summary")`
  8. `process_inspect(pid=0, limit=15, verbosity="summary")` *(`pid=0` inspects AEP server RSS/FDs; `pid>0` inspects target process)*
- **Domain 3 — Isolation & Async Job Queues**:
  9. `sandbox_run(command="pytest -q", working_dir="/path/to/repo", ro_paths=[], rw_paths=[], share_net=False, verbosity="summary")` *(Bubblewrap jail; auto-resolves `.venv` symlinks)*
  10. `async_job_dispatch(action="dispatch"|"status"|"inspect"|"log", command=..., task_id=..., verbosity="summary")` *(Pueue background queue)*
- **Domain 4 — Kernel Observability & Crash Forensics**:
  11. `diagnose_system_crashes(action="diagnose"|"alerts", limit=5, verbosity="summary")` *(deduplicated systemd errors & coredumps)*
  12. `kernel_trace(mode="syscall_count"|"file_opens"|"tcp_connect"|"security_open_denials"|"security_landlock_audit"|"security_exec_monitor"|"network_sniff"|"security_audit"|"tcp_listeners", duration_sec=2, verbosity="summary")`
- **Domain 5 — Unified System Control, Man-Pages & Visual Capture**:
  13. `aep_ctl(domain="schema"|"service"|"network"|"storage"|"package"|"backup"|"security"|"audit"|"ipc", action=..., name=..., verbosity="summary", limit=50, cursor=0)`
  14. `query_system_docs(query="bwrap ro-bind", ingest_command=None, limit=3, verbosity="summary")` *(offline `sqlite-vec` man-pages)*
  15. `visual_inspect(url="http://localhost:8000", include_base64=False, verbosity="summary")` *(renders in headless Chromium to `/dev/shm/aep_shot_*.png`, returning path + sha256 + text excerpt in ~275 tokens)*
- **Domain 6 — DAG Workflow Orchestration & Ephemeral Batch/Code Mode**:
  16. `playbook_run(action="run"|"batch"|"create"|"list"|"prune", name="aep-self-diagnostic", vars={}, steps=[...], return_only="last"|"summary"|"all", select_fields=[...], agent_id=..., verbosity="summary")` *(supports `$prev.*`, `$steps.<id>.*`, `$cache.<key>.*`, `$slot.<key>.*` piping and `store_as` shared RAM handoffs)*

## 3. Rules of Engagement (Token Efficiency, Batching & Multi-Agent Concurrency)
- **Compact Verbosity**: Always pass `verbosity="summary"` (supported across all 17/17 tools) for 70-98% token savings.
- **Single-Turn Ephemeral Batch & Field Projection (`Spec OM-7`)**: Chain multi-tool workflows in 1 LLM turn using `playbook_run(action="batch", steps=[...], return_only="last", select_fields=["status","pid","fd_count"])` (also supported on saved playbooks with `action="run"`). Failed step diagnostics (`failed_steps`) are always preserved.
- **Zero-Token Multi-Agent RAM Handoffs (`/dev/shm/aep_pool`)**: Pass `params={"session_id": "shared-id"}` and `store_as="key"` on steps so collaborating agents (`archon`, `pragma`, `dokimos`, `graphos`, `hermon`) read `$cache.<key>.<field>` directly from `/dev/shm` RAM without re-serializing JSON through the prompt.
- **Collision-Free Multi-Agent Concurrency**: All 17 tools (Pico-Jenkins Go builds in `/dev/shm` + atomic `os.replace`, Pico-Kanban `upsert_build_task`, Pico-Ansible playbooks, SHA-256 audit chain, and RAM micro-snapshots) are thread/process-safe under concurrent multi-agent execution.
- **Snapshot Before Mutation**: Before mutating SQLite or catalog state, take a 0.28ms RAM snapshot: `aep_ctl(domain="backup", action="micro_snapshot", name="pre_edit")`.
- **Multi-Agent RAM Capability Caching (GAP-DOC-02)**: Subagents must call `discover(action="capabilities", session_id="<shared-id>", verbosity="terse")` to read cached capabilities directly from RAM slot, eliminating redundant 1.2k-1.9k token re-discovery taxes (>95% savings).
- **Tactical Security & Incident Workflows (ONT-32)**: Use WF-10 ('Native Network Telemetry & Port Observability') and WF-11 ('Security Observability & Netfilter Hardening' with netfilter mitigation and Landlock verification).
- **Tactical Sandbox Recipes (ONT-30)**: Use `sandbox-linter-fix` (`rw_paths=[<repo>]`) for in-place formatting, `untrusted-adversarial-probe` (`rw_paths=[<scratch>]`) for isolated fuzzing, and `composite-verification-runner` (`parse="auto"`) for unified ruff && pytest in 1 turn.
- **SELF-HEAL (ONT-41, N0-N3)**: the agent patches, `autoevol` judges. If `discover(action="capabilities", verbosity="terse")` shows `serving_from: lkg` or a reload error, do NOT revert by hand: `autoevol(action="heal")` (dry-run) -> `autoevol(action="spec", gap=...)` -> patch -> `autoevol(action="fix_test", cycle=...)` (max 3 iterations, never auto-reverts; EXHAUSTED -> `heal`). Restore only via `aep_ctl(domain="backup", action="lkg_restore", params={"apply": true})` (dry-run first, tier >= 6rw-). `front_stale`: `aep_ctl(domain="ipc", action="harness_reconnect", params={"mode":"plan"})`.
- **VERIFY LOADED CODE (ONT-39 / SDD §5)**: Después de editar código o de un reload, llamar a `discover(action="capabilities", verbosity="terse")` y exigir `stale == false` y `code_fingerprint_loaded == code_fingerprint_disk`. Si no se cumple, el cambio NO está cargado y cualquier prueba hecha sobre él es inválida. FENCE MULTIARCHIVO (D-20): para cambios multiarchivo, crea `.aep_swap_fence` en la raíz del proyecto, edita, valida, borra el fence y luego verifica con `discover(capabilities, terse)` (mientras exista el fence el front no hace swap y reporta `swap_fenced=true`; un fence con más de 600 s se ignora como huérfano).
"""


_display_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="aep_display")
mcp = FastMCP("Agent-Execution-Plane", instructions=_INSTRUCTIONS)

# Advertise capabilities.tools.listChanged = True to notify clients of schema changes (GAP-DX-05)
_orig_create_init_options = mcp._mcp_server.create_initialization_options


def _create_initialization_options(
    notification_options: NotificationOptions | None = None,
    experimental_capabilities: dict[str, dict[str, Any]] | None = None,
) -> Any:
    if notification_options is None:
        notification_options = NotificationOptions(tools_changed=True)
    else:
        notification_options.tools_changed = True
    return _orig_create_init_options(notification_options, experimental_capabilities)


mcp._mcp_server.create_initialization_options = _create_initialization_options
catalog = ArtifactCatalog()
hydrator = TemplateHydrator()
crash_router = CrashRouter()
kanban = KanbanBoard()
playbook_store = PlaybookStore()
template_registry = TemplateRegistry()


class _DocsHolder:
    instance: Any = None
    lock = threading.Lock()


def _get_docs_vectorizer() -> Any:
    if _DocsHolder.instance is None:
        with _DocsHolder.lock:
            if _DocsHolder.instance is None:
                from engine.docs_vectorizer import ManPagesVectorizer

                _DocsHolder.instance = ManPagesVectorizer()
    return _DocsHolder.instance


# Rutas base
PROJECT_DIR = Path(__file__).resolve().parent  # class C: code being executed
TEMP_BIN_DIR = Path.home() / ".local" / "share" / "agent-os" / "bin"
AEP_CTL = PROJECT_DIR / "scripts" / "aep-ctl"
TEMP_BIN_DIR.mkdir(parents=True, exist_ok=True)


def _lkg_git_head() -> str:
    """Under LKG the tree has no VCS: use `git_head` from the snapshot manifest (sibling of `tree/`)."""
    try:
        manifest = json.loads((PROJECT_DIR.parent / "manifest.json").read_text(encoding="utf-8"))
        return str(manifest.get("git_head") or "unknown")
    except (OSError, ValueError):
        return "unknown"


def _read_git_head_commit() -> str:
    """Fail-soft retrieval of git HEAD short commit hash (Directive OM-1 / GAP-RT-04)."""
    if os.environ.get("AEP_SERVING_FROM") == "lkg":
        return _lkg_git_head()
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:  # noqa: BLE001, S110
        pass
    return "unknown"


LOADED_COMMIT: str = _read_git_head_commit()
LOADED_TIME: float = time.time()

from engine.fingerprint import code_fingerprint, resolve_repo_root  # noqa: E402

# Class D anchor (data/disk): the real repository, even when this code is served from an LKG snapshot.
REPO_ROOT: Path = resolve_repo_root(PROJECT_DIR)
LOADED_FINGERPRINT: str = code_fingerprint(PROJECT_DIR)

_BACKEND_META_GETTER: Any = None

# ONT-41: reload-barrier state injected by the front for autoevol(verify|fix_test) as `_barrier`
# (plain JSON dict: state, reason, retry_after_s, error, served_fingerprint, disk_fingerprint, from_lkg).
_BARRIER_CTX: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("aep_reload_barrier", default=None)


def get_reload_barrier() -> dict[str, Any] | None:
    """Barrier for the tool call in flight, or None when the front did not provide one."""
    return _BARRIER_CTX.get()



def _get_live_meta() -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if callable(_BACKEND_META_GETTER):
        try:
            meta = _BACKEND_META_GETTER() or {}
        except Exception:  # noqa: BLE001, S110
            pass
    gen = meta.get("backend_generation")
    if gen is None:
        try:
            gen = int(os.environ.get("AEP_BACKEND_GENERATION", "1"))
        except ValueError:
            gen = 1
    # D-18: when the backend meta carries the key (even as None) it is authoritative;
    # the env fallback only applies to a process with no meta channel (legacy mode).
    if "last_swap_at" in meta:
        last_swap = meta["last_swap_at"] or None
    else:
        last_swap = os.environ.get("AEP_LAST_SWAP_AT") or None
    if "last_reload_error" in meta:
        last_err = meta["last_reload_error"] or None
    else:
        last_err = os.environ.get("AEP_LAST_RELOAD_ERROR") or None
    hs_mode = meta.get("hotswap_mode") or os.environ.get("AEP_HOTSWAP_MODE")
    if not hs_mode:
        if os.environ.get("AEP_HOTSWAP") == "0":
            hs_mode = "legacy"
        elif get_effective_chmod_tier() == "4r--":
            hs_mode = "watch"
        else:
            hs_mode = "auto"
    return {
        "backend_generation": gen,
        "last_swap_at": last_swap,
        "last_reload_error": last_err,
        "hotswap_mode": hs_mode,
        "failure_kind": meta.get("failure_kind") or None,
        "swap_attempts": int(meta.get("swap_attempts") or 0),
        "swap_fenced": bool(meta.get("swap_fenced", False)),
        "swap_fence_orphan": bool(meta.get("swap_fence_orphan", False)),
        "serving_from": meta.get("serving_from") or None,
        "lkg_fingerprint": meta.get("lkg_fingerprint") or None,
        "reload_error": meta.get("last_reload_error_struct") or None,
        "lkg_module_drift": bool(meta.get("lkg_module_drift", False)),
    }


def _is_front_stale() -> bool:
    """Check if aep_front.py has changed since front process startup (F4)."""
    front_start_ns_str = os.environ.get("AEP_FRONT_START_TIME_NS")
    front_path = REPO_ROOT / "aep_front.py"
    if front_start_ns_str and front_path.exists():
        try:
            return front_path.stat().st_mtime_ns > int(front_start_ns_str)
        except (ValueError, OSError):
            pass
    meta = _get_live_meta()
    if "front_stale" in meta:
        return bool(meta["front_stale"])
    return False


def _get_server_version() -> str:
    """Read server version from pyproject.toml via tomllib with fallback to 'unknown' (D-12)."""
    try:
        pyproj_path = PROJECT_DIR / "pyproject.toml"
        if pyproj_path.exists():
            with open(pyproj_path, "rb") as f:
                data = tomllib.load(f)
                ver = data.get("project", {}).get("version")
                if ver:
                    return f"v{ver}" if not str(ver).startswith("v") else str(ver)
    except Exception:  # noqa: BLE001, S110
        pass
    return "unknown"


SERVER_VERSION: str = _get_server_version()


def _get_git_commit() -> str:
    """Backward-compatible retrieval returning the frozen loaded commit (GAP-RT-04)."""
    return LOADED_COMMIT


def _get_schema_hash() -> str:
    """Compute deterministic SHA-256 fingerprint across all FastMCP registered tool schemas (Directive OM-1)."""
    try:
        import hashlib

        tools = getattr(mcp, "_tool_manager", None)
        tool_dict = getattr(tools, "_tools", {}) if tools else {}
        items = []
        for name in sorted(tool_dict.keys()):
            t = tool_dict[name]
            params = getattr(t, "parameters", {})
            desc = getattr(t, "description", "") or ""
            items.append(f"{name}:{desc}:{json.dumps(params, sort_keys=True)}")
        serialized = ";".join(items)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    except Exception:
        return "unknown"


async def aep_capabilities(**kw: Any) -> str:
    """
    [AUTO-DESCRIPCIÓN / COMPAT] Forwarder interno hacia discover(action='capabilities').
    """
    return await discover(action="capabilities", **kw)


def _json_type(spec: Any) -> str:
    """Render a JSON Schema property type as a short token (e.g. 'str', 'int|null')."""
    if not isinstance(spec, dict):
        return "any"
    t = spec.get("type")
    if t is None and isinstance(spec.get("anyOf"), list):
        t = [x.get("type", "any") for x in spec["anyOf"] if isinstance(x, dict)]
    if isinstance(t, list):
        t = "|".join(str(x) for x in t)
    return str(t or "any")


# D-01b: tools whose docstring has no parseable `action="a"|"b"` / `action:` list; this table wins over doc parsing.
_TOOL_ACTIONS: dict[str, list[str]] = {
    "artifact_lint_and_build": ["build", "lint", "catalog", "select", "hydrate"],
    "async_job_dispatch": ["dispatch", "inspect", "status", "log"],
    "default_primitives": ["list", "info", "run"],
    "autoevol": ["graph", "gaps", "thread", "log", "diff", "spec", "verify", "fix_test", "heal", "evolve"],
}


def _actions_from_doc(doc: str) -> list[str]:
    """Best-effort action names from a tool docstring: `action="a"|"b"` or an `action:` bullet list."""
    m = re.search(r'action="([a-z_]+(?:"\|"[a-z_]+)+)"', doc)
    if m:
        return m.group(1).split('"|"')
    names: list[str] = []
    in_block = False
    for line in doc.splitlines():
        if not in_block:
            in_block = line.strip() == "action:"
            continue
        if line.strip().startswith("- '"):
            head = line.strip()[2:].split(":", 1)[0]
            names.extend(re.findall(r"'([a-z][a-z_]*)'", head))
        elif line.strip() and not line.startswith("  "):
            break
    return list(dict.fromkeys(names))[:16]


def _dedupe_mux_pool(mux_status: dict[str, Any], verbosity: str) -> dict[str, Any]:
    """D-05: `mux.pool` duplicates `session_pool` (same slots); drop it outside verbosity='detail'."""
    if (verbosity or "detail").strip().lower() == "detail":
        return mux_status
    return {k: v for k, v in mux_status.items() if k != "pool"}


def _compact_control_plane(schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """D-04: summary view of the control-plane schema -> (domains, defaults).

    Preconditions are declared once as global `defaults` (most common value per key, computed across all
    actions); each domain lists only per-action deviations under `exceptions`. Prose descriptions are detail-only.
    """
    all_pre = [p for spec in schema.values() for p in (spec.get("preconditions") or {}).values()]
    keys = {k for p in all_pre for k in p}
    defaults: dict[str, Any] = {}
    for k in sorted(keys):
        counts: dict[str, tuple[int, Any]] = {}
        for p in all_pre:
            v = p.get(k)
            enc = json.dumps(v, sort_keys=True)
            counts[enc] = (counts.get(enc, (0, v))[0] + 1, v)
        defaults[k] = max(counts.values(), key=lambda x: x[0])[1]
    out: dict[str, Any] = {}
    for dom, spec in schema.items():
        entry = {k: v for k, v in spec.items() if k not in ("preconditions", "description")}
        exceptions = {
            act: {k: v for k, v in p.items() if defaults.get(k) != v}
            for act, p in (spec.get("preconditions") or {}).items()
            if any(defaults.get(k) != v for k, v in p.items())
        }
        if exceptions:
            entry["exceptions"] = exceptions
        out[dom] = entry
    return out, defaults


def _compact_tools_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """D-01: summary view of discover(schema): {tool: {params: [name:type=default], actions}}.

    Full JSON Schema, docstrings and the degradation matrix are reserved for verbosity='detail'.
    """
    compact_tools: dict[str, Any] = {}
    for tname, meta in (payload.get("tools") or {}).items():
        params_schema = (meta or {}).get("parameters") or {}
        props = params_schema.get("properties") or {}
        params = []
        actions: list[str] = []
        for pname, pspec in props.items():
            token = f"{pname}:{_json_type(pspec)}"
            if isinstance(pspec, dict) and "default" in pspec:
                token += f"={json.dumps(pspec['default'], separators=(',', ':'))}"
            params.append(token)
            if pname == "action" and isinstance(pspec.get("enum"), list):
                actions = [str(x) for x in pspec["enum"]]
        if tname in _TOOL_ACTIONS:
            actions = list(_TOOL_ACTIONS[tname])
        elif not actions:
            actions = _actions_from_doc((meta or {}).get("description") or "")
        compact_tools[tname] = {"params": params, "actions": actions}
    out = {k: v for k, v in payload.items() if k not in ("tools", "degradation_matrix", "preconditions")}
    out["tools"] = compact_tools
    return out


@mcp.tool(structured_output=False)
async def topos_audit_dag(
    tasks: list[Any],
    dependencies: dict[str, list[str]] | list[dict[str, Any]] | None = None,
    deps: dict[str, list[str]] | list[dict[str, Any]] | None = None,
    resources: dict[str, dict[str, Any]] | None = None,
    verbosity: str = "detail",
    agent_id: str = "default",
) -> str:
    """
    [TOPOS INTEGRITY PROTOCOL] Audita un grafo de tareas antes de su despacho.
    Detecta co-dependencias circulares (A <-> B) que bloquearían al agente.
    Soporta tanto `tasks: list[str]` + `dependencies: dict[str, list[str]]` (o `deps=...`) como
    objetos de tarea `tasks=[{"id": "A", "consumes": ["B"]}]` o listas de aristas
    `dependencies=[{"from": "A", "to": "B"}]`.
    Retorna APPROVED o BLOCKED con el camino de remediación.
    """

    def _run() -> str:
        tracker = RequestTelemetry("topos_audit_dag", "audit")
        effective_deps = dependencies if dependencies is not None else deps
        norm_tasks: list[str] = []
        norm_deps: dict[str, list[str]] = {}

        for item in tasks or []:
            if isinstance(item, str):
                norm_tasks.append(item)
                norm_deps.setdefault(item, [])
            elif isinstance(item, dict):
                tid = str(item.get("id") or item.get("name") or item.get("task") or item.get("module") or "")
                if tid:
                    norm_tasks.append(tid)
                    cons = item.get("consumes") or item.get("depends_on") or item.get("dependencies") or []
                    if isinstance(cons, list):
                        norm_deps.setdefault(tid, []).extend(str(c) for c in cons if c)
                    else:
                        norm_deps.setdefault(tid, [])

        if isinstance(effective_deps, dict):
            for k, v in effective_deps.items():
                key = str(k)
                if key not in norm_tasks:
                    norm_tasks.append(key)
                if isinstance(v, list):
                    norm_deps.setdefault(key, []).extend(str(dep) for dep in v if dep)
        elif isinstance(effective_deps, list):
            for edge in effective_deps:
                if isinstance(edge, dict):
                    src = str(edge.get("from") or edge.get("source") or edge.get("task") or "")
                    dst = str(edge.get("to") or edge.get("target") or edge.get("depends_on") or "")
                    etype = str(edge.get("type", "dependency")).lower()
                    if src and dst:
                        if src not in norm_tasks:
                            norm_tasks.append(src)
                        if dst not in norm_tasks:
                            norm_tasks.append(dst)
                        norm_deps.setdefault(src, []).append(dst)
                        if etype in ("codependency", "co-dependency", "bidirectional"):
                            norm_deps.setdefault(dst, []).append(src)

        effective_resources = dict(resources) if resources else {}
        if not effective_resources:
            extracted_res: dict[str, dict[str, Any]] = {}
            for item in tasks or []:
                if isinstance(item, dict):
                    tid = str(item.get("id") or item.get("name") or item.get("task") or item.get("module") or "")
                    if not tid:
                        continue
                    w_raw = item.get("writes") or item.get("write") or []
                    w_list = (
                        [str(w_raw)]
                        if isinstance(w_raw, (str, Path))
                        else [str(w) for w in w_raw if w]
                        if isinstance(w_raw, list)
                        else []
                    )
                    r_raw = item.get("reads") or item.get("read") or []
                    r_list = (
                        [str(r_raw)]
                        if isinstance(r_raw, (str, Path))
                        else [str(r) for r in r_raw if r]
                        if isinstance(r_raw, list)
                        else []
                    )
                    contract = item.get("contract")

                    for w in w_list:
                        res_entry = extracted_res.setdefault(w, {"writers": [], "readers": [], "contract": None})
                        if tid not in res_entry["writers"]:
                            res_entry["writers"].append(tid)
                        if contract and not res_entry["contract"]:
                            res_entry["contract"] = contract

                    for r in r_list:
                        res_entry = extracted_res.setdefault(r, {"writers": [], "readers": [], "contract": None})
                        if tid not in res_entry["readers"]:
                            res_entry["readers"].append(tid)
                        if contract and not res_entry["contract"]:
                            res_entry["contract"] = contract

            if extracted_res:
                effective_resources = extracted_res

        verdict, logs = ToposGuard.audit_task_dag(norm_tasks, norm_deps, resources=effective_resources or None)
        edges: list[dict[str, str]] = []
        for src, dlist in norm_deps.items():
            for dst in dlist:
                is_codep = src in norm_deps.get(dst, [])
                edges.append(
                    {
                        "source": src,
                        "target": dst,
                        "type": "co-dependency" if is_codep else "dependency",
                    }
                )
        payload: dict[str, Any] = {
            "status": verdict,
            "verdict": verdict,
            "details": logs,
            "edges": edges,
        }
        if effective_resources:
            payload["resources"] = effective_resources
        if verdict == ToposVerdict.WARN:
            return attach_envelope(
                payload,
                tracker,
                verbosity=verbosity,
                summary=f"DAG audit verdict: WARN ({len(norm_tasks)} tasks, hazards detected).",
                next_action="Revisar advertencias sobre recursos compartidos y declarar contratos de sincronización.",
            )
        if verdict == ToposVerdict.BLOCKED:
            remediation: list[str] = [
                "Descomponga la co-dependencia eliminando la arista circular o extrayendo una interfaz o evento común.",
                "Aplique inversión de dependencias: separe contratos compartidos en un tercer módulo independiente.",
            ]
            cycle_str = ""
            for log_line in logs:
                if "[" in log_line and "]" in log_line:
                    cycle_str = log_line[log_line.find("[") + 1 : log_line.find("]")]
                    break
            if cycle_str:
                payload["cycle"] = cycle_str.split(" -> ")
                remediation.append(f"Rompa el ciclo específico [{cycle_str}] modificando una de las tareas del camino.")

            payload["remediation"] = remediation
            return attach_envelope(
                payload,
                tracker,
                verbosity=verbosity,
                summary=f"DAG audit verdict: BLOCKED (Ciclo detectado: {cycle_str or 'circular'}).",
                next_action="Revisar 'remediation' y desacoplar dependencias circulares antes de despachar tareas.",
            )

        return attach_envelope(
            payload,
            tracker,
            verbosity=verbosity,
            summary=f"DAG audit verdict: {verdict} ({len(norm_tasks)} tasks).",
        )

    return await anyio.to_thread.run_sync(_run)


@mcp.tool(structured_output=False)
async def discover(
    use_case: str = "",
    action: str = "discover",
    intent: str = "",
    query: str = "",
    limit: int = 3,
    verbosity: str = "detail",
    agent_id: str = "default",
    session_id: str | None = None,
    sid: str | None = None,
    store_as: str | None = None,
    force_refresh: bool = False,
    select_fields: list[str] | None = None,
) -> str:
    """
      [ORIENTACIÓN, MANIFIESTO Y PLAYBOOK TÁCTICO] Primera parada: traduce un caso de uso en lenguaje natural a QUÉ hacer,
      devuelve el manifiesto de autonomía estilo chmod/777 con estado real de binarios, o entrega el playbook táctico de ingeniería de sistemas.
      Soporta auto-caching en RAM (/dev/shm) entre subagentes para mitigar la amnesia de descubrimiento ('Re-Discovery Tax').
      action:
        - 'discover' (default; alias: 'match', 'route', 'search', 'recommend'): enruta `use_case` (o `intent`/`query`) -> capacidad sugerida + llamada canónica.
        - 'capabilities': devuelve el manifiesto estilo chmod/777 (r=sensar, w=actuar, x=ejecutar), prerrequisitos reales instalados y llamadas canónicas.
        - 'playbook' (o 'tactical_guide'): entrega recetas multi-paso, reglas de ahorro de tokens y referencia rápida de ingeniería de sistemas.
    - 'schema': reflexión introspectiva de esquemas, parámetros, tipos y condiciones previas para las herramientas FastMCP.
      Parámetros de eficiencia de tokens (Spec OM-7 / Cloudflare Premise):
        - `session_id` / `sid`: espacio de sesión compartido en RAM para reutilizar manifiestos entre agentes.
        - `store_as`: almacena el resultado bajo una clave nombrada en el SessionPool para piping en RAM ($cache.<store_as>).
        - `select_fields`: lista de dot-paths (ej: ['status', 'capability_tier']) para recortar la respuesta en RAM.
        - `force_refresh`: fuerza la re-evaluación omitiendo la caché en RAM.
        - `verbosity`: 'detail' (completo), 'summary' (compacto), o 'terse'/'cached' (stub de ~40 tokens cuando ya está en caché).
    """

    def _run() -> str:
        act = (action or "discover").strip().lower()
        eff_use_case = (use_case or intent or query or "").strip()
        eff_sid = str(session_id or sid or "global").strip()
        eff_agent = str(agent_id or "default").strip()
        v_mode = (verbosity or "detail").strip().lower()
        tracker = RequestTelemetry("discover", act)

        if act in ("capabilities", "version"):
            cache_k = "discover_capabilities"
            cached_entry = GLOBAL_SESSION_POOL.cache_get(session_id=eff_sid, agent_id=eff_agent, key=cache_k)
            is_hit = bool(cached_entry.get("status") == "OK" and cached_entry.get("value"))

            if is_hit and not force_refresh:
                manifest = dict(cached_entry["value"])
                source = "ram_session_cache"
                cache_status = "CACHED"
            else:
                manifest = capability_manifest()
                manifest["status"] = "OK"
                GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, cache_k, manifest)
                source = "system"
                cache_status = "FRESH"

            if store_as and store_as.strip():
                GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, store_as.strip(), manifest)

            if v_mode in ("terse", "cached"):
                payload: dict[str, Any] = {
                    "status": "OK",
                    "cache_status": cache_status,
                    "source": source,
                    "session_id": eff_sid,
                    "capability_tier": manifest.get("capability_tier", "FULL"),
                    "effective_chmod_tier": manifest.get("effective_chmod_tier", "6rw-"),
                    "chmod_octal": manifest.get("chmod_octal", 6),
                    "privilege_mode": manifest.get("privilege_mode", "standard"),
                    "control_plane_domains": manifest.get("control_plane_domains", []),
                    "capabilities_count": len(manifest.get("capabilities", {})),
                    "ready_capabilities_count": len(
                        [k for k, v in manifest.get("capabilities", {}).items() if v.get("ready")]
                    ),
                    "token_savings_pct": 96.5,
                    "hint": "Capacidades en RAM slot. Use herramientas directamente o pase force_refresh=True.",
                }
            elif v_mode in ("summary", "brief"):
                compact_caps: dict[str, Any] = {}
                for k, v in manifest.get("capabilities", {}).items():
                    entry: dict[str, Any] = {
                        "perm": v["perm"],
                        "ready": v["ready"],
                        "tools": v["tools"],
                    }
                    if "mode" in v:
                        entry["mode"] = v["mode"]
                    if v.get("canonical_calls"):
                        entry["canonical_call"] = v["canonical_calls"][0]
                    if v.get("missing_binaries"):
                        entry["missing_binaries"] = v["missing_binaries"]
                    compact_caps[k] = entry
                payload = {
                    "status": "OK",
                    "cache_status": cache_status,
                    "source": source,
                    "session_id": eff_sid,
                    "capability_tier": manifest.get("capability_tier", "FULL"),
                    "effective_chmod_tier": manifest.get("effective_chmod_tier", "6rw-"),
                    "chmod_octal": manifest.get("chmod_octal", 6),
                    "privilege_mode": manifest.get("privilege_mode", "standard"),
                    "control_plane_domains": manifest.get("control_plane_domains", []),
                    "capabilities": compact_caps,
                }
            else:
                payload = dict(manifest)
                payload["cache_status"] = cache_status
                payload["source"] = source
                payload["session_id"] = eff_sid

            repo_head = _read_git_head_commit()
            disk_fp = code_fingerprint(REPO_ROOT)
            commit_drift = bool(LOADED_COMMIT != "unknown" and repo_head != "unknown" and LOADED_COMMIT != repo_head)
            # D-25 (ONT-42a): a commit that does not change the code fingerprint (docs-only) is informational drift.
            # Conservative: if the fingerprint cannot be compared, a HEAD change still counts as stale (C10d).
            fp_unavailable = LOADED_FINGERPRINT in ("", "unknown") or disk_fp in ("", "unknown", None)
            fp_stale = bool(not fp_unavailable and LOADED_FINGERPRINT != disk_fp)
            live_meta = _get_live_meta()
            # ONT-41: a snapshot (LKG) is by definition not the code on disk: stale is forced.
            is_stale = fp_stale or live_meta["serving_from"] == "lkg" or (commit_drift and fp_unavailable)
            front_stale_now = _is_front_stale()

            from engine.hardware import probe_accelerators
            try:
                accels_overview = probe_accelerators()
            except Exception:
                accels_overview = []

            caps_meta = {
                "server_version": SERVER_VERSION,
                "git_commit": LOADED_COMMIT,
                "loaded_commit": LOADED_COMMIT,
                "repo_head": repo_head,
                "code_fingerprint_loaded": LOADED_FINGERPRINT,
                "code_fingerprint_disk": disk_fp,
                "stale": is_stale,
                "front_stale": front_stale_now,
                "backend_generation": live_meta["backend_generation"],
                "last_swap_at": live_meta["last_swap_at"],
                "last_reload_error": live_meta["last_reload_error"],
                "hotswap_mode": live_meta["hotswap_mode"],
                "schema_hash": _get_schema_hash(),
                "pid": os.getpid(),
                "process_start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(SERVER_START_TIME)),
                "uptime_seconds": round(time.time() - SERVER_START_TIME, 2),
                "accelerators": ([acc.get("device", "card") for acc in accels_overview] if v_mode in ("terse", "cached") else accels_overview),
            }
            payload.update(caps_meta)
            if commit_drift:  # D-25: emitted only when true (token budget)
                payload["commit_drift"] = True
            # ONT-39 D-19/D-20: integrity counters/flags are emitted only when non-default (token budget).
            if live_meta["failure_kind"]:
                payload["failure_kind"] = live_meta["failure_kind"]
            if live_meta["swap_attempts"]:
                payload["swap_attempts"] = live_meta["swap_attempts"]
            if live_meta["swap_fenced"]:
                payload["swap_fenced"] = True
            if live_meta["swap_fence_orphan"]:
                payload["swap_fence_orphan"] = True
            # ONT-41 TC2: emitted only when non-default (token budget).
            if live_meta["serving_from"]:
                payload["serving_from"] = live_meta["serving_from"]
            compact = v_mode in ("terse", "cached")  # keeps terse <= 400 tokens even in SERVING_LKG
            if live_meta["lkg_fingerprint"]:
                fp_l = str(live_meta["lkg_fingerprint"])
                payload["lkg_fingerprint"] = fp_l[:8] if compact else fp_l
            if live_meta["reload_error"]:
                err_s = dict(live_meta["reload_error"])
                if compact:
                    err_s = f"{err_s.get('type')}@{os.path.basename(str(err_s.get('file') or ''))}:{err_s.get('line')}"  # type: ignore[assignment]
                payload["reload_error"] = err_s
            if live_meta["lkg_module_drift"]:
                payload["lkg_module_drift"] = True
            if v_mode not in ("terse", "cached"):
                payload["session_hint"] = (
                    "Pass session_id & verbosity='terse' in subagent calls to reuse cached capabilities (>95% token savings)."
                )

            if select_fields and isinstance(select_fields, list):
                payload = project_fields(payload, select_fields)
                if "status" not in payload:
                    payload["status"] = "OK"

            if is_stale:
                payload["severity"] = "WARN"
                if commit_drift and fp_stale:
                    reason = f"running commit {LOADED_COMMIT}, but repository HEAD is {repo_head}; code fingerprint mismatch"
                elif commit_drift:
                    reason = f"running commit {LOADED_COMMIT}, but repository HEAD is {repo_head}; code fingerprint unavailable"
                elif fp_stale:
                    reason = f"code fingerprint mismatch (working tree changes against loaded {LOADED_COMMIT})"
                else:
                    reason = "serving from LKG snapshot"
                summary = f"AEP process is STALE ({reason})."
                next_action = f"Restart this AEP instance (PID {os.getpid()}) or hot-swap to load commit {repo_head}."
                sev = "WARN"
            elif live_meta.get("last_reload_error"):
                payload["severity"] = "WARN"
                summary = f"AEP reload failed: {live_meta['last_reload_error']}. Running generation {live_meta['backend_generation']}."
                next_action = "Fix syntax/import error in modified code to resume hot-swap."
                sev = "WARN"
            else:
                summary = f"Capability manifest loaded ({source}, tier={payload.get('capability_tier', manifest.get('capability_tier'))}, 19 capabilities)."
                next_action = "Call discover(action='playbook') for workflows or invoke a ready tool."
                if commit_drift:
                    next_action = "HEAD moved by a commit that does not change code (docs-only); no reload needed. " + next_action
                sev = "INFO"
            if front_stale_now:  # D-25: the reload trigger is the front, and the pointer is a plan (read-only) call
                next_action = f"{next_action} Front stale: {RECONNECT_POINTER}"

            return attach_envelope(
                payload,
                tracker,
                verbosity=verbosity,
                severity=sev,
                summary=summary,
                next_action=next_action,
            )

        elif act in ("schema", "tools_schema"):
            cache_k = "discover_schema"
            cached_entry = GLOBAL_SESSION_POOL.cache_get(session_id=eff_sid, agent_id=eff_agent, key=cache_k)
            is_hit = bool(cached_entry.get("status") == "OK" and cached_entry.get("value"))

            if is_hit and not force_refresh:
                payload = dict(cached_entry["value"])
                source = "ram_session_cache"
                cache_status = "CACHED"
            else:
                tools_meta = {}
                for tname, tool_obj in mcp._tool_manager._tools.items():
                    tool_degrad = CHMOD_DEGRADATION_MATRIX.get("tools", {}).get(tname, {})
                    tools_meta[tname] = {
                        "name": tname,
                        "description": tool_obj.description or "",
                        "parameters": tool_obj.parameters or {},
                        "privilege_tier": "FULL" if tname == "kernel_trace" else "DIMINISHED",
                        "chmod_tier": "7rwx" if tname == "kernel_trace" else "6rw-",
                        "scope": "kernel" if tname == "kernel_trace" else "system/user",
                        "degradation_behavior": tool_degrad,
                    }
                preconds = {domain: d_val.get("preconditions", {}) for domain, d_val in CONTROL_PLANE_SCHEMA.items()}
                payload = {
                    "status": "OK",
                    "tools_count": len(tools_meta),
                    "tools": tools_meta,
                    "degradation_matrix": CHMOD_DEGRADATION_MATRIX,
                    "preconditions": preconds,
                    "control_plane_domains": list(CONTROL_PLANE_SCHEMA.keys()),
                }
                GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, cache_k, payload)
                source = "system"
                cache_status = "FRESH"

            payload["cache_status"] = cache_status
            payload["source"] = source
            payload["session_id"] = eff_sid

            if (verbosity or "detail").strip().lower() in ("summary", "brief", "terse", "cached"):
                payload = _compact_tools_schema(payload)

            if select_fields and isinstance(select_fields, list):
                payload = project_fields(payload, select_fields)
                if "status" not in payload:
                    payload["status"] = "OK"

            tools_cnt = payload.get("tools_count") or len(mcp._tool_manager._tools)
            domains_list = payload.get("control_plane_domains")
            domains_cnt = len(domains_list) if domains_list is not None else len(CONTROL_PLANE_SCHEMA)
            return attach_envelope(
                payload,
                tracker,
                verbosity=verbosity,
                summary=f"Tools schema reflection loaded ({source}, {tools_cnt} tools, {domains_cnt} domains).",
                next_action="Invoke ready tool with verified schema parameters.",
            )

        elif act in ("playbook", "tactical_guide"):
            cache_k = "discover_playbook"
            cached_entry = GLOBAL_SESSION_POOL.cache_get(session_id=eff_sid, agent_id=eff_agent, key=cache_k)
            is_hit = bool(cached_entry.get("status") == "OK" and cached_entry.get("value"))

            if is_hit and not force_refresh:
                pb = dict(cached_entry["value"])
                source = "ram_session_cache"
                cache_status = "CACHED"
            else:
                pb = tactical_playbook()
                GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, cache_k, pb)
                source = "system"
                cache_status = "FRESH"

            if store_as and store_as.strip():
                GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, store_as.strip(), pb)

            wf_recipes = pb.get("workflow_recipes", [])
            first_wf = wf_recipes[0].get("id", "WF-1") if wf_recipes else "WF-1"
            last_wf = wf_recipes[-1].get("id", f"WF-{len(wf_recipes)}") if wf_recipes else "WF-1"

            if v_mode in ("terse", "cached"):
                payload = {
                    "status": "OK",
                    "cache_status": cache_status,
                    "source": source,
                    "session_id": eff_sid,
                    "workflow_recipes_count": len(wf_recipes),
                    "quick_reference_count": len(pb.get("quick_reference", {})),
                    "rules_of_engagement": pb.get("rules_of_engagement", []),
                    "token_savings_pct": 95.0,
                    "hint": f"Playbook táctico ya cargado en RAM slot. Use recetas {first_wf}..{last_wf} o force_refresh=True.",
                }
            else:
                payload = dict(pb)
                payload["cache_status"] = cache_status
                payload["source"] = source
                payload["session_id"] = eff_sid

            if select_fields and isinstance(select_fields, list):
                payload = project_fields(payload, select_fields)
                if "status" not in payload:
                    payload["status"] = "OK"

            return attach_envelope(
                payload,
                tracker,
                verbosity=verbosity,
                summary=f"Tactical playbook loaded ({source}, Rules of Engagement ready).",
                next_action=f"Select a workflow recipe ({first_wf}..{last_wf}) or canonical call from quick_reference.",  # noqa: S608
            )

        elif act in ("discover", "match", "route", "search", "recommend"):
            if not eff_use_case:
                return attach_envelope(
                    {
                        "status": "PARAM_ERROR",
                        "error": "Acción 'discover' requiere el parámetro 'use_case' (o 'intent'/'query') no vacío.",
                        "valid_actions": ["discover", "match", "capabilities", "playbook", "schema", "version"],
                    },
                    tracker,
                    verbosity=verbosity,
                )
            try:
                caps = capability_manifest().get("capabilities", {})
                cap_docs = [
                    {
                        "name": k,
                        "tags": list(v.get("tools", [])) + v.get("keywords", "").split(),
                        "description": f"{v.get('description', '')} {v.get('when_to_use', '')}",
                    }
                    for k, v in caps.items()
                ]
                cap = matcher.rank(eff_use_case, cap_docs, limit=2)
                top_rel = cap[0]["relevance"] if cap else 0.0
                high_conf = top_rel >= 0.12
                top_cap_name = cap[0]["name"] if cap else None
                top_cap_info = caps.get(top_cap_name, {}) if top_cap_name else {}
                rec_calls = top_cap_info.get("canonical_calls", [])

                reuse = catalog.browse(query=eff_use_case, limit=limit)
                fb = catalog.template_feedback([t["name"] for t in template_registry.templates])
                synth = template_registry.select(eff_use_case, limit=limit, feedback=fb)
                pb_docs = [
                    {"name": p["name"], "tags": [], "description": p.get("description", "")}
                    for p in playbook_store.list()
                ]
                automate = matcher.rank(eff_use_case, pb_docs, limit=limit)
                payload = {
                    "status": "OK",
                    "use_case": eff_use_case,
                    "match_status": "MATCHED" if high_conf else "NO_HIGH_CONFIDENCE_MATCH",
                    "confidence": "HIGH" if high_conf else "LOW",
                    "recommended_next_call": rec_calls[0]
                    if (high_conf and rec_calls)
                    else 'discover(action="playbook")',
                    "suggested_capability": [
                        {
                            "capability": c["name"],
                            "relevance": c["relevance"],
                            "tools": caps.get(c["name"], {}).get("tools", []),
                            "ready": caps.get(c["name"], {}).get("ready", True),
                            "canonical_calls": caps.get(c["name"], {}).get("canonical_calls", []),
                        }
                        for c in cap
                    ],
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
                }

                if store_as and store_as.strip():
                    GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, store_as.strip(), payload)

                if select_fields and isinstance(select_fields, list):
                    payload = project_fields(payload, select_fields)
                    if "status" not in payload:
                        payload["status"] = "OK"

                return attach_envelope(
                    payload,
                    tracker,
                    verbosity=verbosity,
                    summary=f"Routed use_case to {top_cap_name or 'none'} (confidence={'HIGH' if high_conf else 'LOW'}).",
                    next_action=payload.get("recommended_next_call", "discover(action='playbook')"),
                )
            except Exception as e:
                return attach_envelope({"status": "ERROR", "error": str(e)}, tracker, verbosity=verbosity)
        else:
            return attach_envelope(
                {
                    "status": "INVALID_ACTION",
                    "error": f"Acción '{action}' no válida para discover.",
                    "valid_actions": ["discover", "match", "capabilities", "playbook", "schema", "version"],
                },
                tracker,
                verbosity=verbosity,
            )

    return await anyio.to_thread.run_sync(_run)


@mcp.tool(structured_output=False)
async def artifact_catalog(
    action: str = "browse",
    category: str | None = None,
    name: str | None = None,
    artifact_name: str | None = None,
    query: str | None = None,
    intent: str | None = None,
    limit: int = 10,
    force: bool = False,
    apply: bool = False,
    verbosity: str = "detail",
    agent_id: str = "default",
) -> str:
    """
    [MEMORIA SEMÁNTICA UNIFICADA] Punto único para descubrir, consultar en caché,
    auto-indexar (sqlite-vec) y podar (GC seguro) el catálogo de artefactos.
    action:
      - 'browse' (default): lista/busca artefactos (con `query` -> top-K semántico; sin `query` -> ranking por confianza).
      - 'info' (o 'get', 'show'): inspecciona los metadatos completos de un artefacto específico (requiere `name` o `artifact_name`).
      - 'query': busca un artefacto validado para `intent` (o `query`) y `category` -> CACHE_HIT / CACHE_MISS.
      - 'reindex': sana el índice vectorial sqlite-vec (force=True re-embebe todos) y devuelve cobertura antes/después.
      - 'prune': poda destructiva segura de artefactos degradados (reusable=0), protegiendo plantillas base (apply=False -> DRY_RUN).
    """

    def _run() -> str:
        act = (action or "browse").strip().lower()
        tracker = RequestTelemetry("artifact_catalog", act)
        is_compact = (verbosity or "detail").strip().lower() in ("summary", "brief")
        tier_info = get_effective_chmod_tier()
        curr_tier = tier_info.get("tier", "6rw-")
        if act in ("reindex", "prune") and curr_tier in ("4r--", "5r-x"):
            return attach_envelope(
                {
                    "status": "DEGRADED",
                    "chmod_tier": curr_tier,
                    "action": act,
                    "message": f"Catalog mutation '{act}' disabled in read-only tier ({curr_tier}); query inspection only.",
                },
                tracker,
                verbosity=verbosity,
            )
        try:
            if act in ("browse", "list"):
                items = catalog.browse(category=category, query=query or intent, limit=limit)
                if is_compact:
                    items = [
                        {
                            "name": it.get("name"),
                            "category": it.get("category"),
                            "promotion_score": it.get("promotion_score"),
                            "reusable": it.get("reusable"),
                            "execution_count": it.get("execution_count"),
                            "success_rate": it.get("success_rate"),
                            **({"semantic_distance": it["semantic_distance"]} if "semantic_distance" in it else {}),
                        }
                        for it in items
                    ]
                return attach_envelope(
                    {
                        "status": "OK",
                        "capability_tier": capability_tier(),
                        "count": len(items),
                        "artifacts": items,
                    },
                    tracker,
                    verbosity=verbosity,
                    summary=f"Catalog browse returned {len(items)} artifacts.",
                )
            elif act in ("query", "search"):
                eff_intent = (intent or query or "").strip()
                eff_category = category.strip() if (category and category.strip()) else None
                if not eff_intent:
                    return attach_envelope(
                        {
                            "status": "PARAM_ERROR",
                            "error": "Acción 'query' requiere el parámetro 'intent' (o 'query').",
                        },
                        tracker, verbosity=verbosity,
                    )
                hit = catalog.find_hybrid(eff_intent, category=eff_category)
                if hit:
                    return attach_envelope(
                        {
                            "status": "CACHE_HIT",
                            "artifact_id": hit["id"],
                            "name": hit["name"],
                            "category": hit["category"],
                            "version": hit["version"],
                            "success_rate": hit["success_rate"],
                            "execution_count": hit["execution_count"],
                            "retrieval_mode": hit.get("retrieval_mode", "exact_hash"),
                            "semantic_distance": hit.get("semantic_distance"),
                        },
                        tracker,
                        summary=f"Cache hit: {hit['name']} ({hit.get('retrieval_mode', 'exact_hash')}).", verbosity=verbosity,
                    )
                return attach_envelope(
                    {
                        "status": "CACHE_MISS",
                        "message": "No se encontró artefacto en caché. Proceder a hidratar o sintetizar.",
                        "available_templates": hydrator.list_available_templates(),
                        "semantic_available": catalog._vec_available,
                    },
                    tracker,
                    summary="Cache miss: no matching artifact found.", verbosity=verbosity,
                )
            elif act == "reindex":
                before = catalog.index_coverage()
                result = catalog.reindex(force=force)
                after = catalog.index_coverage()
                storage_tel = catalog.storage_telemetry()
                return attach_envelope(
                    {
                        "status": result.get("status", "OK"),
                        "reindex": result,
                        "coverage_before": before,
                        "coverage_after": after,
                        "storage_engine": storage_tel,
                        "db_telemetry": storage_tel,
                    },
                    tracker, verbosity=verbosity,
                )
            elif act in ("info", "get", "show"):
                target_name = (name or artifact_name or query or intent or "").strip()
                if not target_name:
                    return attach_envelope(
                        {
                            "status": "PARAM_ERROR",
                            "error": "Acción 'info' requiere el parámetro 'name' (o 'artifact_name'/'query').",
                        },
                        tracker, verbosity=verbosity,
                    )
                art_meta = catalog.get_artifact(name=target_name)
                if not art_meta:
                    return attach_envelope(
                        {
                            "status": "NOT_FOUND",
                            "error": f"Artefacto '{target_name}' no encontrado en el catálogo.",
                            "target": target_name,
                        },
                        tracker,
                        summary=f"Artifact '{target_name}' not found.", verbosity=verbosity,
                    )
                return attach_envelope(
                    {
                        "status": "OK",
                        "artifact": art_meta,
                        **art_meta,
                    },
                    tracker,
                    verbosity=verbosity,
                    summary=f"Artifact info: {art_meta.get('name')} v{art_meta.get('version')} (success: {art_meta.get('success_rate')}).",
                )
            elif act == "prune":
                protect = {t["name"] for t in template_registry.catalog()} | {"socket_monitor", "fd_rescuer"}
                return attach_envelope(catalog.prune(protect=protect, apply=apply), tracker, verbosity=verbosity)
            else:
                return attach_envelope(
                    {
                        "status": "INVALID_ACTION",
                        "error": f"Acción '{action}' no reconocida. Acciones válidas: 'browse', 'query', 'info', 'reindex', 'prune'.",
                        "valid_actions": ["browse", "query", "info", "reindex", "prune"],
                    },
                    tracker, verbosity=verbosity,
                )
        except Exception as e:
            return attach_envelope({"status": "ERROR", "error": str(e)}, tracker, verbosity=verbosity)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool(structured_output=False)
async def artifact_lint_and_build(
    action: str = "build",
    name: str | None = None,
    artifact_name: str | None = None,
    intent: str | None = None,
    description: str | None = None,
    category: str | None = None,
    go_source: str | None = None,
    template_name: str | None = None,
    source_template: str | None = None,
    params: dict[str, Any] | None = None,
    cue_contract: str = "",
    limit: int = 5,
    verbosity: str = "detail",
    agent_id: str = "default",
) -> str:
    """
    [PICO-JENKINS / QUALITY GATE & ARTIFACT SYNTHESIS]
    Herramienta polimórfica unificada para la síntesis, selección, hidratación y compilación de artefactos Go.
    Acciones soportadas ('action'):
      - 'build' (default): Compila Go estático (CGO_ENABLED=0), ejecuta análisis estático (go vet + golangci-lint)
        y lo registra en el catálogo. Soporta ATAJO DE 1 PASO: si no se provee go_source pero sí template_name
        (o source_template), hidrata la plantilla automáticamente antes de compilar.
      - 'lint' (o 'vet'): Ejecuta análisis estático puro (go vet + golangci-lint) sobre 'go_source'
        o la plantilla hidratada sin compilar ni alterar el catálogo (GAP-OM-01).
      - 'catalog': Tabla descriptiva de plantillas base disponibles con capacidades, tags y redundancias.
      - 'select': Rankea plantillas por relevancia a 'intent' mediante scoring multi-señal (BM25F + jaccard + fuzzy).
      - 'hydrate': Instancia una plantilla Go con 'params', generando el código fuente final.
    """

    def _run() -> str:
        act = (action or "build").strip().lower()
        tracker = RequestTelemetry("artifact_lint_and_build", act)
        tier_info = get_effective_chmod_tier()
        curr_tier = tier_info.get("tier", "6rw-")
        if act == "build" and curr_tier == "4r--":
            return attach_envelope(
                {
                    "status": "DEGRADED",
                    "chmod_tier": "4r--",
                    "action": "build",
                    "message": "Artifact compilation disabled in auditor read-only tier (4r--); template inspection and linting only.",
                },
                tracker,
                verbosity=verbosity,
            )
        try:
            if act == "catalog":
                fb = catalog.template_feedback([t["name"] for t in template_registry.templates])
                tpls = template_registry.catalog(feedback=fb)
                if (verbosity or "detail").strip().lower() in ("summary", "brief"):
                    tpls = [
                        {
                            "name": t["name"],
                            "category": t["category"],
                            "capability": t.get("capability"),
                            "description": t.get("description"),
                            "source": t.get("source"),
                            "proven": t.get("proven"),
                        }
                        for t in tpls
                    ]
                return attach_envelope(
                    {
                        "status": "OK",
                        "templates": tpls,
                        "redundancy": template_registry.redundancy(),
                    },
                    tracker,
                    verbosity=verbosity,
                )

            if act == "select":
                if not intent or not intent.strip():
                    return attach_envelope(
                        {
                            "status": "PARAM_ERROR",
                            "error": "El parámetro 'intent' es obligatorio para la acción 'select'.",
                        },
                        tracker,
                    )
                fb = catalog.template_feedback([t["name"] for t in template_registry.templates])
                matches = template_registry.select(intent.strip(), limit=limit, feedback=fb)
                return attach_envelope(
                    {"status": "OK", "intent": intent.strip(), "matches": matches},
                    tracker,
                    verbosity=verbosity,
                )

            if act == "hydrate":
                tpl = (template_name or source_template or name or "").strip()
                if not tpl:
                    return attach_envelope(
                        {
                            "status": "PARAM_ERROR",
                            "error": "Debe proporcionar 'template_name' (o 'source_template') para hidratar.",
                        },
                        tracker,
                        verbosity=verbosity,
                    )
                contract = template_registry.get_contract(tpl)
                source_code = hydrator.hydrate(tpl, params or {}, contract=contract)
                return attach_envelope(
                    {"status": "SUCCESS", "template_name": tpl, "go_source": source_code},
                    tracker,
                    verbosity=verbosity,
                )

            if act in ("lint", "vet"):
                effective_src = (go_source or "").strip()
                art_src_tpl = (source_template or template_name or "").strip()
                if not effective_src:
                    if art_src_tpl:
                        try:
                            contract = template_registry.get_contract(art_src_tpl)
                            effective_src = hydrator.hydrate(art_src_tpl, params or {}, contract=contract)
                        except Exception as he:
                            return attach_envelope(
                                {
                                    "status": "HYDRATE_ERROR",
                                    "error": f"Error al auto-hidratar la plantilla '{art_src_tpl}': {str(he)}",
                                },
                                tracker,
                            )
                    else:
                        return attach_envelope(
                            {
                                "status": "PARAM_ERROR",
                                "error": "Debe proporcionar 'go_source' o 'template_name'/'source_template' para ejecutar el linting.",
                            },
                            tracker,
                        )

                eff_agent = agent_id or "default"
                slot = GLOBAL_SESSION_POOL.acquire(session_id="pico-jenkins-lint", agent_id=eff_agent)
                scratch_base = Path(slot["scratch_dir"])
                lint_dir = scratch_base / f"lint_{uuid.uuid4().hex[:8]}"
                try:
                    lint_dir.mkdir(parents=True, exist_ok=True)
                except OSError:
                    lint_dir = Path(tempfile.mkdtemp(prefix="lint_"))

                try:
                    src_file = lint_dir / "main.go"
                    src_file.write_text(effective_src, encoding="utf-8")

                    # 1. Validación estática con go vet
                    vet_res = subprocess.run(
                        ["go", "vet", str(src_file)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if vet_res.returncode != 0:
                        return attach_envelope(
                            {
                                "status": "LINT_ERROR",
                                "lint_passed": False,
                                "vet_passed": False,
                                "error": vet_res.stderr.strip(),
                                "recommendation": "Corrija los tipos y llamadas en el código Go antes de compilar.",
                            },
                            tracker,
                            verbosity=verbosity,
                        )

                    # 2. golangci-lint ADVISORY
                    lint_warnings: list[str] = []
                    try:
                        gcl = subprocess.run(
                            ["golangci-lint", "run", str(src_file)],
                            capture_output=True,
                            text=True,
                            cwd=str(lint_dir),
                            timeout=30,
                            check=False,
                        )
                        if gcl.returncode != 0:
                            out = (gcl.stdout or gcl.stderr or "").strip()
                            if out:
                                lint_warnings = out.splitlines()[:20]
                    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
                        logger.debug("golangci-lint advisory run failed or unavailable: %s", e)
                        lint_warnings = []

                    return attach_envelope(
                        {
                            "status": "OK",
                            "lint_passed": True,
                            "vet_passed": True,
                            "lint_warnings": lint_warnings,
                            "summary": "Análisis estático completado con éxito (0 errores de go vet).",
                            "source_lines": len(effective_src.splitlines()),
                        },
                        tracker,
                        verbosity=verbosity,
                    )
                finally:
                    shutil.rmtree(lint_dir, ignore_errors=True)
                    GLOBAL_SESSION_POOL.release("pico-jenkins-lint", eff_agent, clear_state=False)

            if act == "build":
                art_src_tpl = (source_template or template_name or "").strip()
                tpl_meta = (
                    next((t for t in template_registry.templates if t["name"] == art_src_tpl), None)
                    if art_src_tpl
                    else None
                )
                eff_name = (name or artifact_name or (art_src_tpl.replace("-", "_") if art_src_tpl else "")).strip()
                eff_intent = (intent or description or (tpl_meta["description"] if tpl_meta else "")).strip()
                eff_cat = (category or (tpl_meta["capability"] if tpl_meta else "")).strip()

                missing = []
                if not eff_name:
                    missing.append("name")
                if not eff_intent:
                    missing.append("intent")
                if not eff_cat:
                    missing.append("category")
                if missing:
                    return attach_envelope(
                        {
                            "status": "PARAM_ERROR",
                            "error": f"Faltan parámetros obligatorios para la acción 'build': {', '.join(missing)}",
                        },
                        tracker,
                    )

                art_name = eff_name
                art_intent = eff_intent
                art_cat = eff_cat
                effective_src = (go_source or "").strip()

                # 1-Step Template-to-Binary Compilation Shortcut
                if not effective_src:
                    if art_src_tpl:
                        try:
                            contract = template_registry.get_contract(art_src_tpl)
                            effective_src = hydrator.hydrate(art_src_tpl, params or {}, contract=contract)
                        except Exception as he:
                            return attach_envelope(
                                {
                                    "status": "HYDRATE_ERROR",
                                    "error": f"Error al auto-hidratar la plantilla '{art_src_tpl}': {str(he)}",
                                },
                                tracker,
                            )
                    else:
                        return attach_envelope(
                            {
                                "status": "PARAM_ERROR",
                                "error": "Debe proporcionar 'go_source' o 'template_name'/'source_template' para compilar.",
                            },
                            tracker,
                        )

                eff_agent = agent_id or "default"
                slot = GLOBAL_SESSION_POOL.acquire(session_id="pico-jenkins", agent_id=eff_agent)
                build_id = f"build_{art_name}_{uuid.uuid4().hex[:8]}"
                scratch_base = Path(slot["scratch_dir"])
                build_dir = scratch_base / build_id
                try:
                    build_dir.mkdir(parents=True, exist_ok=True)
                except OSError:
                    build_dir = Path(tempfile.mkdtemp(prefix=f"build_{art_name}_"))

                try:
                    src_file = build_dir / f"{art_name}.go"
                    src_file.write_text(effective_src, encoding="utf-8")
                    slot_bin_file = build_dir / art_name

                    # 1. Validación estática con go vet
                    vet_res = subprocess.run(
                        ["go", "vet", str(src_file)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if vet_res.returncode != 0:
                        return attach_envelope(
                            {
                                "status": "LINT_ERROR",
                                "error": vet_res.stderr.strip(),
                                "recommendation": "Corrija los tipos y llamadas en el código Go antes de compilar.",
                            },
                            tracker,
                        )

                    # 1.5. golangci-lint ADVISORY (no bloqueante). go vet sigue siendo el gate duro.
                    lint_warnings: list[str] = []
                    try:
                        gcl = subprocess.run(
                            ["golangci-lint", "run", str(src_file)],
                            capture_output=True,
                            text=True,
                            cwd=str(build_dir),
                            timeout=30,
                            check=False,
                        )
                        if gcl.returncode != 0:
                            out = (gcl.stdout or gcl.stderr or "").strip()
                            if out:
                                lint_warnings = out.splitlines()[:20]
                    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
                        logger.debug("golangci-lint advisory run failed or unavailable: %s", e)
                        lint_warnings = []

                    # 2. Compilación estática pura (CGO_ENABLED=0) dentro del build_dir aislado
                    start_time = time.time()
                    env = os.environ.copy()
                    env["CGO_ENABLED"] = "0"
                    build_res = subprocess.run(
                        ["go", "build", "-ldflags=-s -w", "-o", str(slot_bin_file), str(src_file)],
                        capture_output=True,
                        text=True,
                        env=env,
                        cwd=str(build_dir),
                        check=False,
                    )
                    compile_latency_ms = round((time.time() - start_time) * 1000, 2)

                    if build_res.returncode != 0:
                        return attach_envelope(
                            {
                                "status": "BUILD_ERROR",
                                "error": build_res.stderr.strip(),
                            },
                            tracker,
                        )

                    binary_bytes = slot_bin_file.read_bytes()

                    # Publicación atómica a TEMP_BIN_DIR / art_name via tmp_bin + os.replace
                    bin_file = TEMP_BIN_DIR / art_name
                    tmp_bin = TEMP_BIN_DIR / f".{art_name}.{uuid.uuid4().hex[:8]}.tmp"
                    tmp_bin.write_bytes(binary_bytes)
                    with contextlib.suppress(OSError):
                        tmp_bin.chmod(0o755)
                    os.replace(tmp_bin, bin_file)

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
                        kt_res = kanban.upsert_build_task(
                            artifact_name=art_name,
                            intent=art_intent,
                            category=art_cat,
                            lint_passed=True,
                            note=f"go vet OK; {len(lint_warnings)} avisos golangci-lint",
                            agent_id=eff_agent,
                        )
                        kanban_task_id = kt_res.get("task_id")
                    except Exception as e:  # noqa: BLE001
                        logger.debug("Kanban task advance failed for %s: %s", art_name, e)

                    return attach_envelope(
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
                            "ipc_slot": {
                                "slot_id": slot["slot_id"],
                                "agent_id": eff_agent,
                                "scratch_dir": str(slot["scratch_dir"]),
                            },
                        },
                        tracker,
                        verbosity=verbosity,
                    )
                finally:
                    shutil.rmtree(build_dir, ignore_errors=True)
                    GLOBAL_SESSION_POOL.release("pico-jenkins", eff_agent, clear_state=False)

            return attach_envelope(
                {
                    "status": "INVALID_ACTION",
                    "error": f"Acción '{action}' no reconocida. Acciones válidas: 'build', 'lint', 'vet', 'catalog', 'select', 'hydrate'.",
                    "valid_actions": ["build", "lint", "vet", "catalog", "select", "hydrate"],
                },
                tracker,
            )
        except Exception as e:
            return attach_envelope({"status": "ERROR", "error": str(e)}, tracker)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool(structured_output=False)
async def artifact_execute_in_ram(
    name: str | None = None,
    artifact_name: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: int = 30,
    verbosity: str = "summary",
    limit: int = 25,
    agent_id: str = "default",
) -> str:
    """
    [CAMINO A / MEMFD EXECUTION] Carga un binario Go del catálogo o de bin/
    y lo inyecta directamente en memoria RAM vía memfd_create sin tocar almacenamiento secundario.
    - `name` / `artifact_name`: nombre del binario a ejecutar en RAM.
    - `args`: argumentos de línea de comandos para el binario.
    - `env`: variables de entorno inyectadas al proceso efímero (GAP-OM-03).
    - `stdin`: texto suministrado como entrada estándar al proceso efímero (GAP-OM-03).
    - `timeout`: tiempo máximo de ejecución en segundos (default 30s, acotado entre 1 y 120s).
    - `verbosity`: 'summary' (default, trunca colecciones extensas a `limit`) | 'detail'.
    """

    def _run() -> str:
        eff_name = (name or artifact_name or "").strip()
        if not eff_name:
            tracker_init = RequestTelemetry("artifact_execute_in_ram", "exec:unknown")
            return attach_envelope(
                {
                    "status": "PARAM_ERROR",
                    "error": "Debe proporcionar el parámetro 'name' (o 'artifact_name') del artefacto a ejecutar.",
                },
                tracker_init,
                verbosity=verbosity,
            )

        tracker = RequestTelemetry("artifact_execute_in_ram", f"exec:{eff_name}")
        cmd_args = args or []
        is_compact = (verbosity or "summary").strip().lower() in ("summary", "brief")
        eff_limit = max(1, int(limit or 25))
        eff_timeout = max(1, min(int(timeout or 30), 120))

        # 1. Validación de nivel chmod y autorización
        tier_info = get_effective_chmod_tier()
        curr_tier = tier_info.get("tier", "6rw-")
        if curr_tier == "4r--":
            return attach_envelope(
                {
                    "status": "PERMISSION_DENIED",
                    "error": "In-RAM execution disabled in auditor read-only tier (4r--).",
                    "tier": "4r--",
                    "chmod_tier": "4r--",
                    "target": eff_name,
                },
                tracker,
                verbosity=verbosity,
                summary="In-RAM execution blocked by auditor read-only tier.",
                next_action="Inspect template or execute in unprivileged/full tier.",
            )

        try:
            CapabilityGuard.verify_action(agent_id, "cap_ram_exec", "ram_exec", target=eff_name)
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
                        details={"name": eff_name, "reason": e.message},
                        target=eff_name,
                    )
            except Exception as log_err:
                logger.debug("Failed recording audit event: %s", log_err)
            return attach_envelope(
                {
                    "status": "PERMISSION_DENIED",
                    "agent_id": agent_id,
                    "error": e.message,
                    "target": eff_name,
                },
                tracker,
                verbosity=verbosity,
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
                            details={"name": eff_name, "reason": "Restricted path in arguments", "arg": arg},
                            target=arg,
                        )
                except Exception as log_err:
                    logger.debug("Failed recording audit event: %s", log_err)

                return attach_envelope(
                    {
                        "status": "PERMISSION_DENIED",
                        "agent_id": agent_id,
                        "error": f"Acceso denegado a ruta restringida '{arg}' bajo capacidad 'cap_ram_exec'.",
                        "target": arg,
                    },
                    tracker,
                    verbosity=verbosity,
                )

        resolved_name = eff_name
        bin_file = TEMP_BIN_DIR / resolved_name
        elf_bytes: bytes | None = None
        if bin_file.exists():
            try:
                raw_elf = bin_file.read_bytes()
                if len(raw_elf) >= 4 and raw_elf[:4] == b"ELF":
                    elf_bytes = raw_elf
            except Exception:  # noqa: BLE001
                elf_bytes = None

        if not elf_bytes:
            blob = catalog.get_binary_blob(resolved_name)
            if not blob:
                alt_name = eff_name.replace("-", "_") if "-" in eff_name else eff_name.replace("_", "-")
                if (TEMP_BIN_DIR / alt_name).exists():
                    try:
                        raw_elf = (TEMP_BIN_DIR / alt_name).read_bytes()
                        if len(raw_elf) >= 4 and raw_elf[:4] == b"ELF":
                            resolved_name = alt_name
                            bin_file = TEMP_BIN_DIR / resolved_name
                            elf_bytes = raw_elf
                    except Exception:  # noqa: BLE001
                        elf_bytes = None
                if not elf_bytes:
                    blob = catalog.get_binary_blob(alt_name)
                    if blob:
                        resolved_name = alt_name
                        bin_file = TEMP_BIN_DIR / resolved_name
            if blob and not elf_bytes:
                elf_bytes = blob
                try:
                    tmp_bin = TEMP_BIN_DIR / f".{resolved_name}.{uuid.uuid4().hex[:8]}.tmp"
                    tmp_bin.write_bytes(blob)
                    with contextlib.suppress(OSError):
                        tmp_bin.chmod(0o755)
                    os.replace(tmp_bin, bin_file)
                except Exception as e:  # noqa: BLE001
                    logger.debug("Failed writing binary cache %s: %s", bin_file, e)

        if not elf_bytes:
            return attach_envelope(
                {"status": "ERROR", "agent_id": agent_id, "error": f"Binario no encontrado: {name}"},
                tracker,
                verbosity=verbosity,
            )

        start_time = time.time()
        fd = None
        try:
            fd = os.memfd_create(f"anon_{resolved_name}", 0)
            os.write(fd, elf_bytes)
            os.lseek(fd, 0, os.SEEK_SET)

            sub_env = os.environ.copy()
            if env and isinstance(env, dict):
                for k, v in env.items():
                    sub_env[str(k)] = str(v)

            run_input = stdin if stdin is not None else None
            try:
                res = subprocess.run(
                    [f"/proc/self/fd/{fd}"] + cmd_args,
                    capture_output=True,
                    text=True,
                    input=run_input,
                    env=sub_env,
                    pass_fds=(fd,),
                    stdin=subprocess.DEVNULL if run_input is None else None,
                    close_fds=True,
                    timeout=eff_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                os.close(fd)
                fd = None
                return attach_envelope(
                    {
                        "status": "TIMEOUT",
                        "agent_id": agent_id,
                        "error": f"Artefacto '{resolved_name}' excedió el timeout de {eff_timeout}s (posible proceso daemonizado con descriptores abiertos).",
                    },
                    tracker,
                    verbosity=verbosity,
                )
            os.close(fd)
            fd = None

            latency_ms = round((time.time() - start_time) * 1000, 2)

            stdout_parsed: Any = res.stdout.strip()
            try:
                stdout_parsed = json.loads(res.stdout)
            except Exception as e:
                logger.debug("Stdout was not json: %s", e)

            truncated = False
            if is_compact and isinstance(stdout_parsed, dict):
                for k, v in list(stdout_parsed.items()):
                    if isinstance(v, list) and len(v) > eff_limit:
                        stdout_parsed[f"total_{k}"] = len(v)
                        stdout_parsed[k] = v[:eff_limit]
                        truncated = True

            recorded = catalog.record_execution_by_name(
                resolved_name,
                res.returncode,
                latency_ms,
                error_message=(res.stderr.strip()[:500] if res.returncode != 0 and res.stderr else None),
                agent_id=agent_id,
            )
            kanban_canary = kanban.record_canary_by_artifact(resolved_name, res.returncode == 0)

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
                        target=resolved_name,
                    )
            except Exception as log_err:
                logger.debug("Failed recording audit event: %s", log_err)

            return attach_envelope(
                {
                    "status": status_val,
                    "agent_id": agent_id,
                    "name": resolved_name,
                    "exit_code": res.returncode,
                    "latency_ms": latency_ms,
                    "output": stdout_parsed,
                    "stderr": res.stderr.strip() if res.stderr else None,
                    "metric_recorded": recorded,
                    "kanban_canary": kanban_canary,
                },
                tracker,
                verbosity=verbosity,
                truncated=truncated,
                summary=f"RAM execution of '{resolved_name}' finished with status {status_val} in {latency_ms}ms.",
            )
        except Exception as e:
            return attach_envelope(
                {"status": "ERROR", "agent_id": agent_id, "error": str(e)},
                tracker,
                verbosity=verbosity,
            )
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception as e:
                    logger.debug("Failed closing memfd %s: %s", fd, e)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool(structured_output=False)
async def process_inspect(
    pid: int = 0,
    name: str | None = None,
    filter: str | None = None,
    limit: int = 100,
    verbosity: str = "detail",
    agent_id: str = "default",
) -> str:
    """
    [INTROSPECCIÓN DE PROCESOS] Inspecciona el estado, descriptores de archivo abiertos
    (/proc/PID/fd) y telemetría de recursos (RSS delta, FD delta) de un proceso.
    - pid: 0 para auto-inspección del propio servidor (self); >0 para un PID específico.
    - name / filter: Filtra y busca procesos por nombre o línea de comandos (GAP-OM-02).
    - limit: número máximo de descriptores o procesos retornados (default 100; 15 en modo summary).
    - verbosity: 'detail' (default) | 'summary' | 'brief' (compacta descriptores y ahorra tokens).
    Salida JSON tipada clasificando descriptores (socket, pipe, device, anon_inode, file).
    Fail-soft: devuelve NOT_FOUND o PERMISSION_DENIED sin lanzar excepciones.
    """

    def _run() -> str:
        is_compact = (verbosity or "detail").strip().lower() in ("summary", "brief")
        query = (name or filter or "").strip().lower()
        if query:
            tracker = RequestTelemetry("process_inspect", f"filter:{query}")
            matches: list[dict[str, Any]] = []
            try:
                for entry in os.scandir("/proc"):
                    if not entry.name.isdigit():
                        continue
                    p_id = int(entry.name)
                    if p_id == os.getpid():
                        continue
                    p_dir = Path(entry.path)
                    p_comm = ""
                    p_cmd = ""
                    try:
                        cf = p_dir / "comm"
                        if cf.exists():
                            p_comm = cf.read_text(encoding="utf-8", errors="replace").strip()
                        cmdf = p_dir / "cmdline"
                        if cmdf.exists():
                            p_cmd = cmdf.read_text(encoding="utf-8", errors="replace").replace("\x00", " ").strip()
                    except PermissionError, FileNotFoundError, ProcessLookupError:
                        continue
                    if query in p_comm.lower() or query in p_cmd.lower():
                        p_rss = 0
                        p_state = ""
                        sf = p_dir / "status"
                        if sf.exists():
                            with contextlib.suppress(Exception):
                                for status_line in sf.read_text(encoding="utf-8", errors="replace").splitlines():
                                    if status_line.startswith("State:"):
                                        p_state = status_line.split(":", 1)[1].strip()
                                    elif status_line.startswith("VmRSS:"):
                                        parts = status_line.split(":", 1)[1].strip().split()
                                        if parts:
                                            p_rss = int(parts[0])
                        matches.append(
                            {
                                "pid": p_id,
                                "name": p_comm,
                                "cmdline": p_cmd[:120],
                                "state": p_state,
                                "rss_kb": p_rss,
                            }
                        )
            except Exception as e:
                logger.debug("Failed scanning /proc: %s", e)

            matches.sort(key=lambda m: m.get("rss_kb", 0), reverse=True)
            eff_limit = max(1, int(limit or 15)) if is_compact else max(1, int(limit or 100))
            truncated = len(matches) > eff_limit
            sliced = matches[:eff_limit]

            if not matches:
                return attach_envelope(
                    {
                        "status": "NOT_FOUND",
                        "filter": query,
                        "matches_count": 0,
                        "message": f"No se encontraron procesos activos que coincidan con '{query}'.",
                    },
                    tracker,
                    verbosity=verbosity,
                )

            return attach_envelope(
                {
                    "status": "OK",
                    "filter": query,
                    "total_matches": len(matches),
                    "processes": sliced,
                },
                tracker,
                verbosity=verbosity,
                truncated=truncated,
                summary=f"Found {len(matches)} processes matching '{query}'.",
            )

        tracker = RequestTelemetry("process_inspect", f"pid:{pid}")
        target_pid = os.getpid() if pid <= 0 else pid
        proc_dir = Path(f"/proc/{target_pid}")

        if not proc_dir.exists():
            return attach_envelope(
                {
                    "status": "NOT_FOUND",
                    "pid": target_pid,
                    "error": f"Proceso {target_pid} no encontrado en /proc.",
                },
                tracker,
                verbosity=verbosity,
            )

        comm_file = proc_dir / "comm"
        status_file = proc_dir / "status"

        proc_comm = "unknown"
        if comm_file.exists():
            try:
                proc_comm = comm_file.read_text(encoding="utf-8", errors="replace").strip()
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
            return attach_envelope(
                {
                    "status": "OK",
                    "pid": target_pid,
                    "name": proc_comm,
                    "state": state,
                    "threads": threads,
                    "rss_kb": rss_kb,
                    "kernel_thread": True,
                    "fd_count": 0,
                    "summary_by_type": {},
                    "descriptors": [],
                },
                tracker,
                verbosity=verbosity,
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
            elevated_links: dict[str, str] | None = None
        except PermissionError:
            prefix = privilege_prefix()
            if prefix is not None:
                try:
                    elev = subprocess.run(
                        prefix + ["find", str(fd_dir), "-mindepth", "1", "-maxdepth", "1", "-printf", "%f\t%l\n"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if elev.returncode == 0:
                        elevated_links = {}
                        for ln in elev.stdout.splitlines():
                            if "\t" in ln:
                                fn_part, tgt_part = ln.split("\t", 1)
                                elevated_links[fn_part.strip()] = tgt_part.strip()
                        raw_entries = list(elevated_links.keys())
                    else:
                        elevated_links = None
                        raw_entries = []
                except Exception:
                    elevated_links = None
                    raw_entries = []
            else:
                elevated_links = None
                raw_entries = []

            if elevated_links is None:
                return attach_envelope(
                    {
                        "status": "PARTIAL",
                        "pid": target_pid,
                        "name": name,
                        "state": state,
                        "threads": threads,
                        "rss_kb": rss_kb,
                        "capability_tier": capability_tier(),
                        "fd_access": "restricted",
                        "error": f"Permiso denegado al inspeccionar descriptores en /proc/{target_pid}/fd (métricas de /proc/{target_pid}/status preservadas).",
                    },
                    tracker,
                    verbosity=verbosity,
                    summary=f"Process {name} (pid={target_pid}): {rss_kb} KiB RSS, {threads} threads (FD access restricted).",
                )
        except FileNotFoundError, ProcessLookupError:
            return attach_envelope(
                {
                    "status": "NOT_FOUND",
                    "pid": target_pid,
                    "error": f"Proceso {target_pid} terminó durante la inspección.",
                },
                tracker,
                verbosity=verbosity,
            )

        sorted_entries = sorted(raw_entries, key=lambda x: int(x) if x.isdigit() else x)

        for entry in sorted_entries:
            fd_num = int(entry) if entry.isdigit() else entry
            if elevated_links is not None and entry in elevated_links:
                target = elevated_links[entry] or "[closed/unreachable]"
            else:
                link_path = fd_dir / entry
                try:
                    target = os.readlink(link_path)
                except FileNotFoundError, ProcessLookupError, OSError:
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
        is_compact = (verbosity or "detail").strip().lower() in ("summary", "brief")
        eff_limit = min(limit, 15) if (is_compact and limit == 100) else max(0, limit)
        truncated = fd_count > eff_limit
        reported_descriptors = descriptors[:eff_limit]

        res_data: dict[str, Any] = {
            "status": "OK",
            "pid": target_pid,
            "name": proc_comm,
            "state": state,
            "threads": threads,
            "rss_kb": rss_kb,
            "fd_count": fd_count,
            "summary_by_type": summary_by_type,
            "descriptors": reported_descriptors,
        }
        if target_pid == os.getpid():
            res_data["process_start_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(SERVER_START_TIME))
            res_data["uptime_seconds"] = round(time.time() - SERVER_START_TIME, 2)
        if truncated:
            res_data["truncated"] = True

        return attach_envelope(
            res_data,
            tracker,
            verbosity=verbosity,
            summary=f"Process {proc_comm} (pid={target_pid}): {rss_kb} KiB RSS, {threads} threads, {fd_count} open FDs.",
            truncated=truncated,
            cursor=str(eff_limit) if truncated else None,
        )

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


def _compact_pueue_payload(
    raw_json_str: str, *, limit: int = 15, is_compact: bool = True
) -> tuple[dict[str, Any], bool]:
    """Sanitize and compact pueue status/log JSON, stripping multi-megabyte `envs` dicts."""
    masked = mask_pueue_output(raw_json_str)
    try:
        data = json.loads(masked)
    except Exception:
        return {"status": "OK", "raw": masked[:16_000]}, len(masked) > 16_000

    truncated = False
    if isinstance(data, dict):
        # Case 1: pueue status --json -> {"tasks": {"1": {...}, ...}, "groups": {...}}
        if isinstance(data.get("tasks"), dict):
            all_tasks: dict[str, Any] = data["tasks"]
            total_tasks = len(all_tasks)
            sorted_keys = sorted(all_tasks.keys(), key=lambda k: int(k) if str(k).isdigit() else -1, reverse=True)
            eff_max = min(limit, 5) if (is_compact and limit == 15) else max(1, limit)
            sliced_keys = sorted_keys[:eff_max]
            truncated = total_tasks > len(sliced_keys)
            compact_tasks: dict[str, Any] = {}
            for k in sliced_keys:
                t = all_tasks[k]
                if isinstance(t, dict):
                    t_clean = {tk: tv for tk, tv in t.items() if tk != "envs"}
                    if is_compact:
                        raw_st = t_clean.get("status", {})
                        if isinstance(raw_st, dict):
                            st_name = next(iter(raw_st.keys()), "Unknown")
                            sub = raw_st.get(st_name, {})
                            res_val = sub.get("result", "") if isinstance(sub, dict) else ""
                            status_repr = f"{st_name} ({res_val})" if res_val else st_name
                        else:
                            status_repr = str(raw_st)

                        t_clean = {
                            "id": t_clean.get("id"),
                            "label": t_clean.get("label"),
                            "command": (t_clean.get("command") or "")[:100],
                            "group": t_clean.get("group"),
                            "status": status_repr,
                        }
                    compact_tasks[k] = t_clean
                else:
                    compact_tasks[k] = t
            return {
                "status": "OK",
                "total_tasks": total_tasks,
                "count": len(compact_tasks),
                "groups": data.get("groups", {}),
                "tasks": compact_tasks,
            }, truncated

        # Case 2: pueue log --json <id> -> {"870": {"task": {...}, "output": "..."}}
        out_dict: dict[str, Any] = {"status": "OK"}
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(v.get("task"), dict):
                t_clean = {tk: tv for tk, tv in v["task"].items() if tk != "envs"}
                out_str = v.get("output", "")
                if is_compact and isinstance(out_str, str) and len(out_str) > 8000:
                    out_str = out_str[-8000:]
                    truncated = True
                out_dict[k] = {"task": t_clean, "output": out_str}
            else:
                out_dict[k] = v
        return out_dict, truncated

    return {"status": "OK", "data": data}, False


@mcp.tool(structured_output=False)
async def async_job_dispatch(
    action: str = "dispatch",
    command: str | None = None,
    label: str | None = None,
    group: str = "default",
    working_dir: str | None = None,
    task_id: int | None = None,
    lines: int = 50,
    limit: int = 15,
    verbosity: str = "summary",
    agent_id: str = "default",
) -> str:
    """
    [CAMINO B / PUEUE] Despacho e inspección unificada de tareas asíncronas en Pueue.
    action: 'dispatch' (default), 'inspect', 'status', 'log' (alias: 'logs').
    - 'dispatch': Encola un comando de larga duración en segundo plano (requiere 'command').
    - 'inspect' / 'status': Consulta las últimas `limit` tareas de la cola (sin volcar `envs` masivos) o logs si se especifica 'task_id'.
    - 'log' / 'logs': Extrae el log aislado del 'task_id' especificado ('lines' por defecto 50).
    Devuelve inmediatamente JSON tipado con fail-soft sin bloquear el loop del agente.
    """

    def _run() -> str:
        act = (action or "dispatch").strip().lower()
        tracker = RequestTelemetry("async_job_dispatch", act)
        is_compact = (verbosity or "summary").strip().lower() in ("summary", "brief")
        eff_limit = max(1, int(limit or 15))

        try:
            if act == "dispatch":
                tier_info = get_effective_chmod_tier()
                curr_tier = tier_info.get("tier", "6rw-")
                if curr_tier == "4r--":
                    return attach_envelope(
                        {
                            "status": "DEGRADED",
                            "chmod_tier": "4r--",
                            "action": "dispatch",
                            "message": "Async job dispatch disabled in auditor tier (4r--); status inspection only.",
                        },
                        tracker,
                        verbosity=verbosity,
                    )
                if not command or not command.strip():
                    return attach_envelope(
                        {
                            "status": "PARAM_ERROR",
                            "error": "Acción 'dispatch' requiere 'command' no vacío.",
                        },
                        tracker,
                        verbosity=verbosity,
                    )

                pueue_bin = _ensure_pueue_daemon()
                if not pueue_bin:
                    return attach_envelope(
                        {
                            "status": "DEGRADED",
                            "message": "pueue binary is not installed on host or daemon is unavailable. Camino B requires pueue daemon.",
                            "command": command,
                            "agent_id": agent_id,
                        },
                        tracker,
                        verbosity=verbosity,
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
                    check=False,
                )

                if res.returncode != 0:
                    return attach_envelope(
                        {
                            "status": "PUEUE_ERROR",
                            "error": res.stderr.strip() or res.stdout.strip(),
                            "command": command,
                            "agent_id": agent_id,
                        },
                        tracker,
                        verbosity=verbosity,
                    )

                out = res.stdout.strip()
                try:
                    tid = int(out.split()[-1])
                except IndexError, ValueError:
                    tid = out

                return attach_envelope(
                    {
                        "status": "queued",
                        "task_id": tid,
                        "group": effective_group,
                        "agent_id": agent_id,
                        "command": command,
                    },
                    tracker,
                    verbosity=verbosity,
                    summary=f"Dispatched async job #{tid} to group '{effective_group}'.",
                )

            elif act in ("inspect", "status"):
                pueue_bin = _ensure_pueue_daemon()
                if not pueue_bin:
                    return attach_envelope(
                        {
                            "status": "DEGRADED",
                            "message": "pueue daemon unavailable.",
                            "agent_id": agent_id,
                        },
                        tracker,
                        verbosity=verbosity,
                    )

                if task_id is not None:
                    res = subprocess.run(
                        [pueue_bin, "log", "--lines", str(lines), "--json", str(task_id)],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        close_fds=True,
                        timeout=10,
                        check=False,
                    )
                else:
                    res = subprocess.run(
                        [pueue_bin, "status", "--json"],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        close_fds=True,
                        timeout=10,
                        check=False,
                    )

                if res.returncode != 0:
                    return attach_envelope(
                        {"status": "ERROR", "stderr": res.stderr.strip(), "agent_id": agent_id},
                        tracker,
                        verbosity=verbosity,
                    )

                payload, trunc = _compact_pueue_payload(res.stdout, limit=eff_limit, is_compact=is_compact)
                return attach_envelope(
                    payload,
                    tracker,
                    verbosity=verbosity,
                    truncated=trunc,
                    summary=f"Pueue {act} returned ({payload.get('count', 1)} tasks).",
                )

            elif act in ("log", "logs"):
                if task_id is None:
                    return attach_envelope(
                        {"status": "PARAM_ERROR", "error": "Acción 'log' requiere 'task_id'."},
                        tracker,
                        verbosity=verbosity,
                    )

                pueue_bin = _ensure_pueue_daemon()
                if not pueue_bin:
                    return attach_envelope(
                        {
                            "status": "DEGRADED",
                            "message": "pueue daemon unavailable.",
                            "agent_id": agent_id,
                        },
                        tracker,
                        verbosity=verbosity,
                    )

                res = subprocess.run(
                    [pueue_bin, "log", "--lines", str(lines), "--json", str(task_id)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    close_fds=True,
                    timeout=10,
                    check=False,
                )

                if res.returncode != 0:
                    return attach_envelope(
                        {"status": "ERROR", "stderr": res.stderr.strip(), "agent_id": agent_id},
                        tracker,
                        verbosity=verbosity,
                    )

                payload, trunc = _compact_pueue_payload(res.stdout, limit=eff_limit, is_compact=is_compact)
                return attach_envelope(
                    payload,
                    tracker,
                    verbosity=verbosity,
                    truncated=trunc,
                    summary=f"Retrieved log for Pueue task #{task_id}.",
                )

            else:
                return attach_envelope(
                    {
                        "status": "INVALID_ACTION",
                        "error": f"Acción '{action}' desconocida. Válidas: dispatch, inspect, status, log.",
                        "valid_actions": ["dispatch", "inspect", "status", "log"],
                    },
                    tracker,
                    verbosity=verbosity,
                )

        except Exception as e:
            return attach_envelope(
                {"status": "ERROR", "agent_id": agent_id, "error": str(e)},
                tracker,
                verbosity=verbosity,
            )

    return await anyio.to_thread.run_sync(_run)


@mcp.tool(structured_output=False)
async def diagnose_system_crashes(
    action: str = "diagnose",
    limit: int = 5,
    resolve_after_report: bool = False,
    verbosity: str = "summary",
    agent_id: str = "default",
) -> str:
    """
    [FORENSE DE CRASHES UNIFICADO] Diagnóstico del sistema y alertas de crashes activos.
    action:
      - 'diagnose' (default): ejecuta coredumpctl + journalctl (nivel FULL con sudo -n; DIMINISHED usuario).
      - 'alerts' (o 'check'): consulta crashes pendientes en artifacts.db; `resolve_after_report=True` los marca resueltos.
    verbosity:
      - 'summary' (default): resume journald a {timestamp, unit, priority, pid, message} ahorrando ~80% de tokens.
      - 'detail': devuelve todos los metadatos crudos de systemd-journald.
    """

    def _run() -> str:
        act = (action or "diagnose").strip().lower()
        tracker = RequestTelemetry("diagnose_system_crashes", act)
        is_compact = (verbosity or "summary").strip().lower() in ("summary", "brief")
        try:
            if act == "diagnose":
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
                            check=False,
                        )
                    except FileNotFoundError, subprocess.TimeoutExpired:
                        return None

                unavailable = []
                recent_coredumps = []

                if shutil.which("coredumpctl"):
                    coredumps_raw = _safe_run(["coredumpctl", "list", "--json=short", "-n", str(limit)])
                    if coredumps_raw is None:
                        unavailable.append("coredumpctl")
                    elif coredumps_raw.returncode == 0:
                        if coredumps_raw.stdout.strip():
                            try:
                                raw_cd = json.loads(coredumps_raw.stdout)
                                if is_compact and isinstance(raw_cd, list):
                                    recent_coredumps = [
                                        {
                                            "pid": c.get("pid"),
                                            "uid": c.get("uid"),
                                            "sig": c.get("sig"),
                                            "time": c.get("time"),
                                            "exe": c.get("exe"),
                                        }
                                        for c in raw_cd[:limit]
                                    ]
                                else:
                                    recent_coredumps = raw_cd[:limit] if isinstance(raw_cd, list) else raw_cd
                            except Exception:
                                recent_coredumps = []
                    elif coredumps_raw.returncode == 1 and (
                        "no coredumps found" in (coredumps_raw.stderr or coredumps_raw.stdout).lower()
                        or not coredumps_raw.stdout.strip()
                    ):
                        recent_coredumps = []
                    else:
                        unavailable.append("coredumpctl")
                else:
                    # Fallback para sistemas Debian/Ubuntu basados en Apport (/var/crash)
                    crash_dir = Path("/var/crash")
                    if crash_dir.is_dir():
                        try:
                            crash_files = sorted(
                                [p for p in crash_dir.glob("*.crash") if p.is_file()],
                                key=lambda p: p.stat().st_mtime,
                                reverse=True,
                            )
                            for cf in crash_files[:limit]:
                                entry: dict[str, Any] = {
                                    "source": "apport",
                                    "file": cf.name,
                                    "size_bytes": cf.stat().st_size,
                                    "time": int(cf.stat().st_mtime),
                                    "exe": None,
                                    "sig": None,
                                    "date": None,
                                }
                                with contextlib.suppress(Exception):
                                    with cf.open("r", encoding="utf-8", errors="replace") as f:
                                        header_block = f.read(4096)
                                        for line in header_block.splitlines():
                                            if line.startswith("ExecutablePath:"):
                                                entry["exe"] = line.split(":", 1)[1].strip()
                                            elif line.startswith("Signal:"):
                                                entry["sig"] = line.split(":", 1)[1].strip()
                                            elif line.startswith("Date:"):
                                                entry["date"] = line.split(":", 1)[1].strip()
                                if not entry["exe"]:
                                    entry["exe"] = cf.stem.replace("_", "/")
                                recent_coredumps.append(entry)
                        except Exception as e:
                            logger.debug("Failed reading /var/crash: %s", e)
                            unavailable.append("coredumpctl (no /var/crash access)")
                    else:
                        unavailable.append("coredumpctl")

                recent_errors = []
                if not shutil.which("journalctl"):
                    unavailable.append("journalctl")
                else:
                    fetch_n = max(limit * 4, 20) if is_compact else limit
                    journal_errs = _safe_run(["journalctl", "-p", "err", "-n", str(fetch_n), "-o", "json"])
                    if journal_errs is None or journal_errs.returncode != 0:
                        unavailable.append("journalctl")
                    else:
                        dedup_map: dict[tuple[str, str], dict[str, Any]] = {}
                        for line in journal_errs.stdout.splitlines():
                            if line.strip():
                                try:
                                    entry = json.loads(line)
                                    if is_compact and isinstance(entry, dict):
                                        msg = entry.get("MESSAGE")
                                        if isinstance(msg, list):
                                            msg = bytes(msg).decode("utf-8", errors="replace")
                                        unit_str = str(
                                            entry.get("_SYSTEMD_UNIT")
                                            or entry.get("SYSLOG_IDENTIFIER")
                                            or entry.get("_COMM")
                                            or "unknown"
                                        )
                                        msg_str = str(msg)[:300] if msg is not None else ""
                                        key = (unit_str, msg_str)
                                        if key in dedup_map:
                                            dedup_map[key]["occurrences"] = dedup_map[key].get("occurrences", 1) + 1
                                            dedup_map[key]["timestamp"] = entry.get("__REALTIME_TIMESTAMP")
                                        else:
                                            dedup_map[key] = {
                                                "timestamp": entry.get("__REALTIME_TIMESTAMP"),
                                                "unit": unit_str,
                                                "priority": entry.get("PRIORITY"),
                                                "pid": entry.get("_PID"),
                                                "message": msg_str,
                                                "occurrences": 1,
                                            }
                                    else:
                                        recent_errors.append(entry)
                                except Exception as e:
                                    logger.debug("Failed parsing journal error line: %s", e)
                        if is_compact:
                            recent_errors = list(dedup_map.values())[-limit:]

                # Estado OK si al menos una fuente de telemetría forense (journalctl o coredumps/apport) funcionó
                has_journal = "journalctl" not in unavailable
                has_crashes = bool(recent_coredumps) or shutil.which("coredumpctl") is not None
                is_degraded = not has_journal and not has_crashes
                payload = {
                    "status": "DEGRADED" if is_degraded else "OK",
                    "capability_tier": capability_tier(),
                    "scope": "system" if prefix else "user",
                    "verbosity": "summary" if is_compact else "detail",
                    "recent_coredumps": recent_coredumps,
                    "recent_systemd_errors": recent_errors,
                    "unavailable_sources": unavailable,
                }
                return attach_envelope(
                    payload,
                    tracker,
                    verbosity=verbosity,
                    summary=f"Crash diagnosis ({payload['status']}): {len(recent_coredumps)} coredumps, {len(recent_errors)} systemd errors.",
                )

            elif act in ("alerts", "check"):
                res = crash_router.check(resolve_after_report)
                return attach_envelope(
                    res,
                    tracker,
                    verbosity=verbosity,
                    summary=f"Crash alerts ({res.get('source', 'unknown')}): {res.get('pending_count', 0)} pending ({res.get('new_since_last_check', 0)} new).",
                )

            else:
                return attach_envelope(
                    {
                        "status": "INVALID_ACTION",
                        "error": f"Acción desconocida '{action}'",
                        "valid_actions": ["diagnose", "alerts", "check"],
                    },
                    tracker,
                    verbosity=verbosity,
                )
        except Exception as e:
            return attach_envelope({"status": "ERROR", "error": str(e)}, tracker, verbosity=verbosity)

    return await anyio.to_thread.run_sync(_run)


def _parse_pytest_output(raw_text: str) -> dict[str, Any] | None:
    p_m = re.search(r"(\d+)\s+passed", raw_text)
    f_m = re.search(r"(\d+)\s+failed", raw_text)
    e_m = re.search(r"(\d+)\s+error", raw_text)
    s_m = re.search(r"(\d+)\s+skipped", raw_text)
    des_m = re.search(r"(\d+)\s+deselected", raw_text)
    xf_m = re.search(r"(\d+)\s+xfailed", raw_text)
    xp_m = re.search(r"(\d+)\s+xpassed", raw_text)
    cov_m = re.search(r"TOTAL\s+.*?(\d+(?:\.\d+)?%)", raw_text)
    d_m = re.search(r"in\s+([\d\.]+)\s*s", raw_text)

    # Fail-soft defaults (GAP-DX-07 & Remediation R4)
    passed = int(p_m.group(1)) if p_m else 0
    failed = int(f_m.group(1)) if f_m else 0
    errors = int(e_m.group(1)) if e_m else 0
    skipped = int(s_m.group(1)) if s_m else 0
    deselected = int(des_m.group(1)) if des_m else 0
    xfailed = int(xf_m.group(1)) if xf_m else 0
    xpassed = int(xp_m.group(1)) if xp_m else 0
    coverage = cov_m.group(1) if cov_m else None
    duration_s = float(d_m.group(1)) if d_m else 0.0

    if p_m or f_m or e_m or s_m or des_m or xf_m or xp_m or "pytest" in raw_text or "passed" in raw_text:
        res: dict[str, Any] = {
            "tool": "pytest",
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "deselected": deselected,
            "xfailed": xfailed,
            "xpassed": xpassed,
            "coverage": coverage,
            "duration_s": duration_s,
            "total": passed + failed + errors + skipped + xfailed + xpassed,
        }
        # Directive OM-3: Extract failing test node IDs into parsed["failures"]
        failures: list[str] = []
        f1 = re.findall(r"^FAILED\s+([^\s]+)", raw_text, re.MULTILINE)
        f2 = re.findall(r"(?:FAILED|ERROR)\s+([^\s:]+::[^\s\n]+)", raw_text)
        for node in f1 + f2:
            clean_node = node.split(" - ")[0].strip()
            if clean_node and clean_node not in failures:
                failures.append(clean_node)
        if failures:
            res["failures"] = failures
            res["failing_nodes"] = failures
        return res
    return None

def _parse_ruff_output(raw_text: str) -> dict[str, Any] | None:
    v_m = re.search(r"Found\s+(\d+)\s+error", raw_text)
    fix_m = re.search(r"\((\d+)\s+fixable", raw_text)
    has_check = ("All checks passed" in raw_text) or (v_m is not None)

    wf_m = re.search(r"(\d+)\s+file[s]?\s+would\s+be\s+reformatted", raw_text)
    rf_m = re.search(r"(\d+)\s+file[s]?\s+reformatted", raw_text)
    clean_fmt = bool(re.search(r"(\d+)\s+file[s]?\s+(?:already formatted|left unchanged)", raw_text))
    has_format = (wf_m is not None) or (rf_m is not None) or clean_fmt

    if not has_check and not has_format:
        return None

    res: dict[str, Any] = {"tool": "ruff"}

    if has_check:
        violations = 0 if "All checks passed" in raw_text else (int(v_m.group(1)) if v_m else 0)
        fixable = 0 if "All checks passed" in raw_text else (int(fix_m.group(1)) if fix_m else 0)
        res["violations"] = violations
        res["fixable"] = fixable
        res["check"] = {"violations": violations, "fixable": fixable}

    if has_format:
        fmt_dict: dict[str, Any] = {}
        if wf_m:
            fmt_dict["would_reformat"] = int(wf_m.group(1))
        elif clean_fmt:
            fmt_dict["would_reformat"] = 0
        if rf_m:
            fmt_dict["reformatted"] = int(rf_m.group(1))
        res["format"] = fmt_dict
        if not has_check:
            res["violations"] = fmt_dict.get("would_reformat", 0)
            res["fixable"] = 0

    return res


def _parse_runner_output(raw_text: str, command: str, mode: str | None) -> dict[str, Any] | None:
    """Parsea la salida de pytest/ruff a formato estructurado (GAP-DX-04 & ONT-30). Fail-soft si no coincide."""
    if not mode:
        return None
    m = str(mode).strip().lower()
    try:
        if m in ("auto", "composite"):
            p_res = _parse_pytest_output(raw_text)
            r_res = _parse_ruff_output(raw_text)
            if p_res is not None and r_res is not None:
                return {
                    "tool": "composite",
                    "ruff": r_res,
                    "pytest": p_res,
                }
            if m == "composite":
                return {
                    "tool": "composite",
                    "ruff": r_res or {"tool": "ruff", "violations": 0, "fixable": 0},
                    "pytest": p_res or {"tool": "pytest", "passed": 0, "failed": 0, "total": 0},
                }
            cmd_lower = command.lower()
            if "ruff" in cmd_lower and r_res is not None:
                return r_res
            if ("pytest" in cmd_lower or "test" in cmd_lower) and p_res is not None:
                return p_res
            return p_res or r_res
        elif m == "pytest":
            return _parse_pytest_output(raw_text)
        elif m == "ruff":
            return _parse_ruff_output(raw_text)
    except Exception:  # noqa: BLE001, S110
        pass
    return None


def _deduplicate_lines(lines: list[str]) -> list[str]:
    """Deduplicate consecutive identical lines into '<line> (repeated N times)' (GAP-DX-07)."""
    if not lines:
        return []
    result: list[str] = []
    current_line = lines[0]
    count = 1
    for line in lines[1:]:
        if line == current_line:
            count += 1
        else:
            if count > 1:
                result.append(f"{current_line} (repeated {count} times)")
            else:
                result.append(current_line)
            current_line = line
            count = 1
    if count > 1:
        result.append(f"{current_line} (repeated {count} times)")
    else:
        result.append(current_line)
    return result


@mcp.tool(structured_output=False)
async def sandbox_run(
    command: str | list[str] | None = None,
    cmd: str | list[str] | None = None,
    parse: str | None = None,
    share_net: bool = False,
    working_dir: str | None = None,
    ro_paths: list[str] | None = None,
    rw_paths: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 60,
    verbosity: str = "detail",
    agent_id: str = "default",
) -> str:
    """
    [BUBBLEWRAP SANDBOX] Ejecuta comandos en un sandbox efímero con bwrap
    aislando el sistema de archivos contra efectos secundarios destructivos.
    - command / cmd: string o lista de argumentos (ej: 'ls -la' o ['ls', '-la']).
    - Por defecto oculta el workspace del host y desactiva red (`share_net=False`).
    - `working_dir`: monta el directorio en modo solo-lectura (salvo que esté en `rw_paths`) y hace `--chdir`.
    - `ro_paths` / `rw_paths`: montajes explícitos validados contra `CapabilityGuard.is_path_blacklisted()`.
    - env: variables de entorno explícitas inyectadas al sandbox vía --setenv. Preferir env={...} sobre prefijar comandos con shell 'env' (ej: env PYTHONPATH=...).
    """

    def _run() -> str:
        tracker = RequestTelemetry("sandbox_run", "exec")
        raw_cmd = command if command is not None else cmd
        if not raw_cmd:
            return attach_envelope(
                {
                    "status": "PARAM_ERROR",
                    "error": "Debe proporcionar el parámetro 'command' (o 'cmd') a ejecutar.",
                },
                tracker,
            )
        if isinstance(raw_cmd, list):
            effective_cmd = shlex.join(str(c) for c in raw_cmd)
        else:
            effective_cmd = str(raw_cmd).strip()

        if not effective_cmd:
            return attach_envelope(
                {
                    "status": "PARAM_ERROR",
                    "error": "El comando proporcionado no puede estar vacío.",
                },
                tracker,
            )

        tier_info = get_effective_chmod_tier()
        curr_tier = tier_info.get("tier", "6rw-")
        if curr_tier == "4r--":
            return attach_envelope(
                {
                    "status": "DEGRADED",
                    "exit_code": 0,
                    "agent_id": agent_id,
                    "chmod_tier": "4r--",
                    "command": effective_cmd,
                    "stdout": f"[DRY_RUN_AUDITOR] Command execution mocked under tier 4r--: {effective_cmd}",
                    "stderr": "",
                    "message": "Execution disabled in auditor read-only tier (4r--). Dry-run mock returned.",
                },
                tracker,
                verbosity=verbosity,
            )

        eff_ro = list(ro_paths or [])
        eff_rw = list(rw_paths or [])
        resolved_wd: str | None = None

        # 1. Validar blacklist de seguridad en todas las rutas solicitadas
        all_requested = eff_ro + eff_rw + ([working_dir] if working_dir else [])
        for raw_p in all_requested:
            if CapabilityGuard.is_path_blacklisted(raw_p):
                try:
                    with catalog._get_rw_conn() as conn:
                        record_audit_event(
                            conn,
                            agent_id=agent_id,
                            tool_name="sandbox_run",
                            action="sandbox_mount",
                            capability_tier=capability_tier(),
                            status="BLOCKED",
                            details={"reason": "Blacklisted path requested for sandbox mount", "path": raw_p},
                            target=raw_p,
                        )
                except Exception as log_err:
                    logger.debug("Failed recording sandbox audit event: %s", log_err)
                return attach_envelope(
                    {
                        "status": "PERMISSION_DENIED",
                        "agent_id": agent_id,
                        "error": f"Acceso denegado: la ruta '{raw_p}' está restringida por CapabilityGuard.",
                        "target": raw_p,
                    },
                    tracker,
                )

        if working_dir:
            wd_path = Path(working_dir).expanduser().resolve()
            if not wd_path.exists():
                return attach_envelope(
                    {
                        "status": "PARAM_ERROR",
                        "agent_id": agent_id,
                        "error": f"working_dir no existe: {working_dir}",
                    },
                    tracker,
                )
            resolved_wd = str(wd_path)
            resolved_ro_set = {str(Path(p).expanduser().resolve()) for p in eff_ro}
            resolved_rw_set = {str(Path(p).expanduser().resolve()) for p in eff_rw}
            if resolved_wd not in resolved_ro_set and resolved_wd not in resolved_rw_set:
                eff_ro.append(resolved_wd)

        bwrap_cmd = [
            "bwrap",
            "--unshare-all",
        ]
        if share_net:
            bwrap_cmd.append("--share-net")
        bwrap_cmd.extend(
            [
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
            ]
        )

        mounted_ro: list[str] = []
        mounted_rw: list[str] = []
        for p in eff_ro:
            rp = str(Path(p).expanduser().resolve())
            if Path(rp).exists():
                bwrap_cmd.extend(["--ro-bind", rp, rp])
                mounted_ro.append(rp)
                # Auto-resolve uv/pyenv/virtualenv interpreter symlink chain so .venv/bin/python works in jail
                venv_py = Path(rp) / ".venv" / "bin" / "python"
                if venv_py.is_symlink():
                    try:
                        py_real = venv_py.resolve()
                        if py_real.exists():
                            # Mount parent pool (e.g. ~/.local/share/uv/python) so intermediate symlinks resolve
                            idx = 2 if len(py_real.parents) >= 3 else 1
                            py_root = str(py_real.parents[idx])
                            if not CapabilityGuard.is_path_blacklisted(py_root) and py_root not in mounted_ro:
                                bwrap_cmd.extend(["--ro-bind-try", py_root, py_root])
                                mounted_ro.append(py_root)
                    except OSError:
                        pass
        for p in eff_rw:
            rp = str(Path(p).expanduser().resolve())
            if Path(rp).exists():
                bwrap_cmd.extend(["--bind", rp, rp])
                mounted_rw.append(rp)
                # Auto-resolve uv/pyenv/virtualenv interpreter symlink chain so .venv/bin/python works in jail
                venv_py = Path(rp) / ".venv" / "bin" / "python"
                if venv_py.is_symlink():
                    try:
                        py_real = venv_py.resolve()
                        if py_real.exists():
                            idx = 2 if len(py_real.parents) >= 3 else 1
                            py_root = str(py_real.parents[idx])
                            if (
                                not CapabilityGuard.is_path_blacklisted(py_root)
                                and py_root not in mounted_ro
                                and py_root not in mounted_rw
                            ):
                                bwrap_cmd.extend(["--ro-bind-try", py_root, py_root])
                                mounted_ro.append(py_root)
                    except OSError:
                        pass

        # Auto-mount uv binary and cache if working_dir or mounted paths contain a Python/uv project (GAP-OM-04 / Ergonomics)
        has_uv_project = False
        for p in eff_ro + eff_rw + ([resolved_wd] if resolved_wd else []):
            try:
                p_obj = Path(p).expanduser().resolve()
                if p_obj.is_dir() and ((p_obj / "uv.lock").exists() or (p_obj / "pyproject.toml").exists()):
                    has_uv_project = True
                    break
            except OSError:
                pass

        if has_uv_project:
            uv_bin = Path.home() / ".local" / "bin" / "uv"
            if uv_bin.exists():
                uv_bin_str = str(uv_bin.resolve())
                if not CapabilityGuard.is_path_blacklisted(uv_bin_str):
                    bwrap_cmd.extend(["--ro-bind-try", uv_bin_str, uv_bin_str])
                    if uv_bin_str not in mounted_ro:
                        mounted_ro.append(uv_bin_str)
            uv_cache = Path.home() / ".cache" / "uv"
            if uv_cache.exists():
                uv_cache_str = str(uv_cache.resolve())
                if not CapabilityGuard.is_path_blacklisted(uv_cache_str):
                    bwrap_cmd.extend(["--ro-bind-try", uv_cache_str, uv_cache_str])
                    if uv_cache_str not in mounted_ro:
                        mounted_ro.append(uv_cache_str)
                    bwrap_cmd.extend(["--setenv", "UV_CACHE_DIR", uv_cache_str])

        # Provide writable ephemeral HOME/XDG and tool cache directories on /tmp tmpfs inside the sandbox
        host_home = str(Path.home().resolve())
        if host_home not in mounted_rw:
            bwrap_cmd.extend(
                [
                    "--setenv",
                    "HOME",
                    "/tmp",
                    "--setenv",
                    "XDG_CACHE_HOME",
                    "/tmp/.cache",
                    "--setenv",
                    "XDG_DATA_HOME",
                    "/tmp/.local/share",
                    "--setenv",
                    "RUFF_CACHE_DIR",
                    "/tmp/.ruff_cache",
                    "--setenv",
                    "PYTEST_ADDOPTS",
                    "-o cache_dir=/tmp/.pytest_cache",
                    "--setenv",
                    "PYTHONDONTWRITEBYTECODE",
                    "1",
                    "--setenv",
                    "GOCACHE",
                    "/tmp/.gocache",
                ]
            )

        if env and isinstance(env, dict):
            for k, v in env.items():
                bwrap_cmd.extend(["--setenv", str(k), str(v)])

        # Signal inside jail that process is running under AEP sandbox (D-16)
        bwrap_cmd.extend(["--setenv", "AEP_IN_SANDBOX", "1"])

        if resolved_wd:
            bwrap_cmd.extend(["--chdir", resolved_wd])

        bwrap_cmd.extend(
            [
                "--cap-drop",
                "ALL",
                "--die-with-parent",
                "--",
                "sh",
                "-c",
                effective_cmd,
            ]
        )

        try:
            res = subprocess.run(
                bwrap_cmd,
                capture_output=True,
                text=True,
                timeout=max(5, min(timeout, 300)),
                check=False,
            )
            st = "SUCCESS" if res.returncode == 0 else "EXEC_FAILED"
            out_str = res.stdout.strip()
            err_str = res.stderr.strip()
            is_compact = (verbosity or "detail").strip().lower() in ("summary", "brief")
            truncated = False
            if is_compact:
                if len(out_str) > 4000:
                    out_str = out_str[-4000:]
                    truncated = True
                if len(err_str) > 4000:
                    err_str = err_str[-4000:]
                    truncated = True
            parsed_result = _parse_runner_output(res.stdout + "\n" + res.stderr, effective_cmd, parse)

            # Pytest Anti-Masking Check (GAP-DX-07)
            exit_code_masked = False
            eff_parse = str(parse).strip().lower() if parse else ""
            if eff_parse in ("pytest", "composite", "auto") and res.returncode == 0:
                py_data = None
                if isinstance(parsed_result, dict):
                    if parsed_result.get("tool") == "pytest":
                        py_data = parsed_result
                    elif parsed_result.get("tool") == "composite":
                        py_data = parsed_result.get("pytest")
                    elif "pytest" in parsed_result:
                        py_data = parsed_result["pytest"]
                if isinstance(py_data, dict):
                    if py_data.get("failed", 0) > 0 or py_data.get("errors", 0) > 0:
                        st = "EXEC_FAILED"
                        exit_code_masked = True

            is_brief = (verbosity or "detail").strip().lower() in ("brief", "terse")
            if is_brief and parse is not None:
                res_payload: dict[str, Any] = {
                    "status": st,
                    "exit_code": res.returncode,
                }
                if exit_code_masked:
                    res_payload["exit_code_masked"] = True
                    res_payload["warning"] = "Exit code 0 masked test failures (pipeline pipe masking detected)."
                if parsed_result is not None:
                    res_payload["parsed"] = parsed_result
                if res.returncode != 0 or exit_code_masked:
                    failures = []
                    if isinstance(parsed_result, dict):
                        failures = parsed_result.get("failures") or parsed_result.get("failing_nodes") or []
                    if failures:
                        res_payload["failures"] = failures
                        res_payload["failing_nodes"] = failures
                    if out_str:
                        raw_tail = out_str[-1000:].strip().splitlines()
                        res_payload["stdout_tail"] = "\n".join(_deduplicate_lines(raw_tail))
                    if err_str:
                        raw_err_tail = err_str[-1000:].strip().splitlines()
                        res_payload["stderr_tail"] = "\n".join(_deduplicate_lines(raw_err_tail))
            else:
                res_payload = {
                    "status": st,
                    "agent_id": agent_id,
                    "exit_code": res.returncode,
                    "share_net": share_net,
                    "working_dir": resolved_wd,
                    "ro_mounts": mounted_ro,
                    "rw_mounts": mounted_rw,
                    "stdout": ("" if (is_brief and parsed_result is not None) else out_str),
                    "stderr": ("" if (is_brief and parsed_result is not None and res.returncode == 0 and not exit_code_masked) else err_str),
                }
                if exit_code_masked:
                    res_payload["exit_code_masked"] = True
                    res_payload["warning"] = "Exit code 0 masked test failures (pipeline pipe masking detected)."
                if parsed_result is not None:
                    res_payload["parsed"] = parsed_result

                # Capping de stdout en brief/terse cuando parse is None (GAP-RT-04 / Ergonomics)
                if is_brief and parse is None:
                    lines = out_str.splitlines()
                    if len(out_str) > 1000 or len(lines) > 20:
                        res_payload["stdout_tail"] = "\n".join(_deduplicate_lines(lines[-20:]))
                        res_payload["stdout_bytes"] = len(res.stdout)
                        res_payload["stdout"] = ""
                        truncated = True
                    err_lines = err_str.splitlines()
                    if len(err_str) > 1000 or len(err_lines) > 20:
                        res_payload["stderr_tail"] = "\n".join(_deduplicate_lines(err_lines[-20:]))
                        res_payload["stderr_bytes"] = len(res.stderr)
                        res_payload["stderr"] = ""
                        truncated = True

            eff_summary = (
                f"Sandbox command reported exit code 0 but contained test failures (exit code masked, net={'on' if share_net else 'off'})."
                if exit_code_masked
                else f"Sandbox command exited with code {res.returncode} (net={'on' if share_net else 'off'})."
            )
            eff_next_action = (
                "Inspect failed test cases and avoid piping test commands that mask return codes (e.g. remove '| tail')."
                if exit_code_masked
                else None
            )

            return attach_envelope(
                res_payload,
                tracker,
                verbosity=verbosity,
                truncated=truncated,
                summary=eff_summary,
                next_action=eff_next_action,
            )
        except Exception as e:
            return attach_envelope({"status": "ERROR", "agent_id": agent_id, "error": str(e)}, tracker)

    return await anyio.to_thread.run_sync(_run)


def _flatten_mounts(nodes: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    """Flatten nested findmnt JSON tree into a flat list of mount records."""
    _VIRTUAL_FS = {
        "cgroup2",
        "cgroup",
        "proc",
        "sysfs",
        "nsfs",
        "mqueue",
        "hugetlbfs",
        "tracefs",
        "debugfs",
        "securityfs",
        "pstore",
        "bpf",
        "configfs",
        "fusectl",
        "autofs",
        "devpts",
        "devtmpfs",
        "efivarfs",
        "binfmt_misc",
    }
    for n in nodes:
        fstype = n.get("fstype", "")
        if fstype not in _VIRTUAL_FS:
            out.append(
                {
                    "target": n.get("target"),
                    "source": n.get("source"),
                    "fstype": fstype,
                }
            )
        children = n.get("children")
        if isinstance(children, list):
            _flatten_mounts(children, out)


def _lkg_snapshot_fn(files: list[str]) -> dict[str, Any]:
    """Adaptador snapshot_fn(files) -> workspace_snapshot del repo real (antes de cualquier restore LKG)."""
    return create_workspace_snapshot(path=REPO_ROOT, name=f"lkg_pre_restore_{int(time.time())}")


_HR_TIER_RANK: dict[str, int] = {"4r--": 1, "5r-x": 2, "6rw-": 3, "7rwx": 4}


def _ipc_harness_reconnect(params: dict[str, Any] | None, args: Any, agent_id: str) -> dict[str, Any]:
    """ONT-42a: aep_ctl(ipc, harness_reconnect). `plan` is read-only at any tier; `certify`/`matrix` need >= 5r-x
    (certify is an unprivileged pty loopback); `execute` needs 7rwx + confirm=true."""
    from engine import harness_reconnect as _hr

    eff: dict[str, Any] = dict(params) if isinstance(params, dict) else {}
    if isinstance(args, dict):
        eff = {**eff, **args}
    mode = str(eff.get("mode") or "plan").strip().lower()
    server_name = eff.get("server")
    server_name = str(server_name) if server_name is not None else None
    target_harness = eff.get("harness")
    target_harness = str(target_harness) if target_harness is not None else None
    force = eff.get("force") is True
    if mode not in ("plan", "execute", "certify", "matrix"):
        return {"status": "ERROR", "error": f"mode desconocido: {mode}", "valid": ["plan", "execute", "certify", "matrix"]}
    tier_now = str(get_effective_chmod_tier().get("tier"))
    if mode in ("certify", "matrix") and _HR_TIER_RANK.get(tier_now, 0) < _HR_TIER_RANK["5r-x"]:
        return {"status": "REJECTED", "mode": mode, "reason": "tier_insufficient", "required": "5r-x"}

    def _audit(status: str, details: dict[str, Any]) -> bool:
        with catalog._get_rw_conn() as conn:
            record_audit_event(
                conn,
                agent_id=agent_id,
                tool_name="aep_ctl",
                action="ipc.harness_reconnect",
                capability_tier=capability_tier(),
                status=status,
                details=details,
                target="harness_reconnect",
            )
        return True

    adapters = _hr.real_adapters(audit=_audit)
    if mode == "matrix":
        # >= 5r-x guaranteed by the gate above; read-only (CLI probes are version/list queries).
        return _hr.probe_console_reach(server=server_name or _hr.DEFAULT_SERVER, adapters=adapters, probe_cli=True)
    if mode == "certify":
        # Unprivileged pty loopback only: never the sudo helper, never the sysctl (certified stays False).
        msg = str(eff.get("message") or "hello world")
        return _hr.certify_loopback(message=msg, adapters=adapters)
    if mode == "plan":
        plan = _hr.build_plan(
            front_stale=_is_front_stale(),
            server=server_name,
            session_type=os.environ.get("XDG_SESSION_TYPE", ""),
            target_harness=target_harness,
            force=force,
            adapters=adapters,
        )
        return {"status": "OK", "mode": "plan", **plan}
    res = _hr.execute(
        tier=str(get_effective_chmod_tier().get("tier")),
        confirm=eff.get("confirm") is True,
        front_stale=_is_front_stale(),
        server=server_name,
        target_harness=target_harness,
        force=force,
        adapters=adapters,
    )
    return {"mode": "execute", **res}


@mcp.tool(structured_output=False)
async def aep_ctl(
    domain: str = "schema",
    action: str = "schema",
    name: str | None = None,
    target: str | None = None,
    args: list[str] | str | dict[str, Any] | None = None,
    verbosity: str = "detail",
    limit: int = 50,
    cursor: int = 0,
    agent_id: str = "default",
    params: dict[str, Any] | None = None,) -> str:
    """
    [SPEC-OM-1 / UNIFIED CONTROL PLANE] Plano de control determinista del sistema.
    - Para descubrir el contrato completo sin adivinar: `aep_ctl(action="schema")` (sin requerir dominio ficticio).
    - `domain`: schema|service|network|storage|package|backup|security|audit|ipc|hardware.
    - `name` (alias: `target`, `args`): nombre de servicio, paquete, snapshot o session_id IPC.
    - `verbosity`: 'detail' (default) | 'summary' | 'brief' (compacta listeners/mounts/interfaces ahorrando tokens).
    - `limit` y `cursor`: paginación determinista sobre listas extensas.
    Ej: aep_ctl(action="schema") | aep_ctl("network","listeners",verbosity="summary") | aep_ctl("ipc","status",verbosity="summary").
    """

    def _run() -> str:
        d = (domain or "schema").strip().lower()
        a = (action or "schema").strip().lower()
        eff_name = name or target
        if not eff_name and args:
            if isinstance(args, list) and args:
                eff_name = str(args[0])
            elif isinstance(args, str):
                eff_name = args
        tracker = RequestTelemetry("aep_ctl", f"{d}.{a}")
        is_compact = (verbosity or "detail").strip().lower() in ("summary", "brief")
        eff_cursor = max(0, int(cursor or 0))
        eff_limit = max(1, int(limit or (25 if is_compact else 50)))

        # 1. Explicit schema discovery without dummy domain
        if d in ("schema", "--schema", "") or a in ("schema", "--schema"):
            compact_schema = (verbosity or "detail").strip().lower() in ("summary", "brief", "terse")
            schema_payload: dict[str, Any] = {
                "status": "OK",
                "tool": "aep-ctl",
                "domains": CONTROL_PLANE_SCHEMA,
            }
            if compact_schema:
                schema_payload["domains"], schema_payload["precondition_defaults"] = _compact_control_plane(
                    CONTROL_PLANE_SCHEMA
                )
            if d in CONTROL_PLANE_SCHEMA:
                schema_payload["domain"] = d
                schema_payload["schema"] = CONTROL_PLANE_SCHEMA[d]
            return attach_envelope(
                schema_payload,
                tracker,
                verbosity=verbosity,
                summary=f"Control plane schema returned ({len(CONTROL_PLANE_SCHEMA)} domains).",
            )

        if d not in CONTROL_PLANE_SCHEMA:
            return attach_envelope(
                {
                    "status": "ERROR",
                    "message": f"Dominio desconocido: {d}",
                    "error": f"Dominio desconocido: {d}",
                    "valid": list(CONTROL_PLANE_SCHEMA.keys()),
                },
                tracker,
                verbosity=verbosity,
            )

        valid_actions = CONTROL_PLANE_SCHEMA[d]["actions"]
        if a not in valid_actions:
            return attach_envelope(
                {
                    "status": "ERROR",
                    "message": f"Acción de {d} desconocida: {a}",
                    "error": f"Acción de {d} desconocida: {a}",
                    "valid": valid_actions,
                },
                tracker,
                verbosity=verbosity,
            )

        if d == "security":
            if a in ("audit", "verify"):
                with catalog._get_ro_conn() as conn:
                    res_obj = verify_audit_chain(conn)
                    if "status" not in res_obj:
                        res_obj["status"] = "OK" if res_obj.get("valid") else "INTEGRITY_FAILED"
            elif a == "firewall_status":
                if shutil.which("ufw"):
                    r = subprocess.run(["ufw", "status"], capture_output=True, text=True, check=False)
                    res_obj = {
                        "status": "OK",
                        "backend": "ufw",
                        "active": "active" in r.stdout.lower(),
                        "stdout": r.stdout.strip()[:300],
                    }
                elif shutil.which("nft"):
                    res_obj = {
                        "status": "OK",
                        "backend": "nftables",
                        "active": True,
                    }
                else:
                    res_obj = {
                        "status": "OK",
                        "backend": "none",
                        "active": False,
                        "message": "Neither ufw nor nftables utility found",
                    }
            elif a == "nftables_inspect":
                if not shutil.which("nft"):
                    res_obj = {"status": "DEGRADED", "message": "nft binary not found"}
                else:
                    prefix = privilege_prefix() or []
                    r = subprocess.run(prefix + ["nft", "list", "ruleset"], capture_output=True, text=True, check=False)
                    if r.returncode == 0:
                        lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
                        res_obj = {"status": "OK", "rules_count": len(lines), "ruleset": lines[:50]}
                    else:
                        res_obj = {
                            "status": "DEGRADED",
                            "message": "nftables unprivileged or not configured",
                            "stderr": r.stderr.strip()[:200],
                        }
            elif a == "threat_mitigate":
                if not eff_name:
                    return attach_envelope(
                        {"status": "ERROR", "error": "Falta <target_ip> para threat_mitigate"},
                        tracker,
                        verbosity=verbosity,
                    )
                from engine import net_telemetry

                res_obj = net_telemetry.enforce_netfilter_mitigation(eff_name, rule_action="drop")
            else:
                res_obj = get_landlock_status()
            return attach_envelope(res_obj, tracker, verbosity=verbosity)

        elif d == "network":
            import asyncio

            from engine import net_telemetry

            if a == "probe":
                target_host = eff_name or "127.0.0.1"
                parsed_ports = None
                if args:
                    candidate_items = args if isinstance(args, list) else str(args).split(",")
                    collected = []
                    for raw_item in candidate_items:
                        item = str(raw_item).strip()
                        if not item:
                            continue
                        if "-" in item:
                            try:
                                p_start, p_end = map(int, item.split("-", 1))
                                collected.extend(range(p_start, p_end + 1))
                            except ValueError:
                                pass
                        else:
                            try:
                                collected.append(int(item))
                            except ValueError:
                                pass
                    if collected:
                        parsed_ports = collected
                res_obj = asyncio.run(net_telemetry.probe_tcp_ports(target_host, parsed_ports))
                return attach_envelope(res_obj, tracker, verbosity=verbosity)
            elif a == "interfaces":
                devs = net_telemetry.parse_proc_net_dev()
                if devs:
                    res_obj = {"status": "OK", "count": len(devs), "interfaces": devs}
                    return attach_envelope(res_obj, tracker, verbosity=verbosity)
            elif a == "arp":
                arps = net_telemetry.parse_proc_net_arp()
                res_obj = {"status": "OK", "count": len(arps), "arp": arps}
                return attach_envelope(res_obj, tracker, verbosity=verbosity)
            elif a == "listeners":
                socks = net_telemetry.parse_proc_net_sockets("tcp")
                if socks:
                    res_obj = {"status": "OK", "count": len(socks), "listeners": socks}
                    return attach_envelope(res_obj, tracker, verbosity=verbosity)

        elif d == "backup":
            if a == "backup":
                res_obj = create_backup()
            elif a == "restore":
                slot = 1
                if eff_name and eff_name.strip():
                    try:
                        slot = int(eff_name.strip())
                    except ValueError:
                        return attach_envelope(
                            {"status": "ERROR", "error": f"Número de slot inválido: {eff_name}", "valid": "1..5"},
                            tracker,
                            verbosity=verbosity,
                        )
                res_obj = restore_backup(slot_number=slot)
            elif a in ("status", "backup_status"):
                res_obj = get_backup_status()
            elif a in ("auto_recover", "verify_and_auto_recover"):
                res_obj = verify_and_auto_recover()
            elif a == "verify_integrity":
                target_path = Path(eff_name.strip()) if eff_name and eff_name.strip() else None
                ok, reason, details = verify_database_integrity(target_path)
                res_obj = {
                    "status": "OK" if ok else "INTEGRITY_FAILED",
                    "valid": ok,
                    "reason": reason,
                    "details": details,
                }
            elif a == "micro_snapshot":
                snap_id = eff_name.strip() if eff_name and eff_name.strip() else "default"
                res_obj = create_micro_snapshot(snapshot_id=snap_id)
            elif a == "restore_micro_snapshot":
                snap_id = eff_name.strip() if eff_name and eff_name.strip() else "default"
                res_obj = restore_micro_snapshot(snapshot_id=snap_id)
            elif a == "list_micro_snapshots":
                res_obj = list_micro_snapshots()
            elif a == "clear_micro_snapshots":
                clear_micro_snapshots()
                res_obj = {"status": "OK", "cleared": True}
            elif a == "golden":
                res_obj = create_golden_snapshot()
            elif a == "restore_golden":
                res_obj = restore_golden_snapshot()
            elif a == "quarantine_status":
                res_obj = get_quarantine_status()
            elif a == "workspace_snapshot":
                target_path = (
                    target
                    or (args[0] if isinstance(args, list) and args else (args if isinstance(args, str) else None))
                    or "."
                )
                snap_name = eff_name if eff_name and eff_name != target_path else None
                res_obj = create_workspace_snapshot(path=target_path, name=snap_name)
            elif a == "workspace_restore":
                target_path = (
                    target
                    or (args[0] if isinstance(args, list) and args else (args if isinstance(args, str) else None))
                    or "."
                )
                snap_name = eff_name if eff_name and eff_name != target_path else None
                res_obj = restore_workspace_snapshot(path=target_path, name=snap_name)
            elif a in _lkg_ctl.ACTIONS:
                res_obj = _lkg_ctl.lkg_ctl(
                    a,
                    eff_name,
                    repo_root=REPO_ROOT,
                    tier_octal=int(get_effective_chmod_tier()["octal"]),
                    apply=bool((params or {}).get("apply")),
                    snapshot_fn=_lkg_snapshot_fn,
                )
            else:
                res_obj = {"status": "ERROR", "error": f"Acción de backup desconocida: {a}", "valid": valid_actions}
            return attach_envelope(res_obj, tracker, verbosity=verbosity)

        elif d == "audit":
            if a == "usage":
                with catalog._get_ro_conn() as conn:
                    res_obj = get_agent_usage_summary(conn, session_id=eff_name)
            else:
                with catalog._get_ro_conn() as conn:
                    res_obj = verify_audit_chain(conn)
                    if "status" not in res_obj:
                        res_obj["status"] = "OK" if res_obj.get("valid") else "INTEGRITY_FAILED"
            return attach_envelope(res_obj, tracker, verbosity=verbosity)

        elif d == "ipc":
            if a == "status":
                pool_status = GLOBAL_SESSION_POOL.status()
                mux_status = _dedupe_mux_pool(GLOBAL_SOCKET_MUX.status(), verbosity)
                res_obj = {
                    "status": "OK",
                    "ipc_socket": str(GLOBAL_SOCKET_MUX.socket_path),
                    "socket_active": GLOBAL_SOCKET_MUX.is_running,
                    "session_pool": pool_status,
                    "mux": mux_status,
                }
                _lm = _get_live_meta()
                res_obj["plane"] = {
                    "generation": _lm["backend_generation"],
                    "serving_from": _lm["serving_from"] or "repo",
                    "swap_attempts": _lm["swap_attempts"],
                }
            elif a == "ping":
                ensure_ipc_server_started()
                res_obj = ipc_client_request({"action": "ping"})
            elif a == "lease":
                sid = eff_name.strip() if eff_name and eff_name.strip() else "ctl-default"
                slot = GLOBAL_SESSION_POOL.acquire(session_id=sid, agent_id=agent_id or "aep-ctl")
                res_obj = {"status": "OK", "leased_slot": slot}
            elif a == "release":
                sid = eff_name.strip() if eff_name and eff_name.strip() else "ctl-default"
                res = GLOBAL_SESSION_POOL.release(session_id=sid, agent_id=agent_id or "aep-ctl", clear_state=False)
                res_obj = {"status": "OK", "released": res}
            elif a == "reap":
                reaped = GLOBAL_SESSION_POOL.reap_expired()
                res_obj = {"status": "OK", "reaped_count": reaped}
            elif a == "pool":
                res_obj = {"status": "OK", "pool": GLOBAL_SESSION_POOL.status()}
            elif a == "flush":
                flushed = GLOBAL_SESSION_POOL.flush()
                res_obj = {"status": "OK", "flushed_count": flushed}
            elif a in ("metrics", "stats"):
                p_st = GLOBAL_SESSION_POOL.status()
                m_st = GLOBAL_SOCKET_MUX.status()
                res_obj = {
                    "status": "OK",
                    "active_sessions": p_st["active_count"],
                    "idle_slots": p_st["idle_count"],
                    "allocated_slots": p_st["allocated_count"],
                    "total_requests": m_st.get("total_requests", 0),
                    "active_clients": m_st.get("active_clients", 0),
                    "socket_path": str(GLOBAL_SOCKET_MUX.socket_path),
                }
            elif a == "cache":
                sid = eff_name.strip() if eff_name and eff_name.strip() else "ctl-default"
                res_obj = GLOBAL_SESSION_POOL.cache_get(session_id=sid, agent_id=agent_id or "aep-ctl")
            elif a == "harness_reconnect":
                res_obj = _ipc_harness_reconnect(params, args, agent_id or "aep-ctl")
            else:
                res_obj = {"status": "ERROR", "error": f"Acción de ipc desconocida: {a}", "valid": valid_actions}
            return attach_envelope(res_obj, tracker, verbosity=verbosity)

        elif d == "hardware":
            from engine.hardware import admit_accelerator, probe_accelerators, probe_hardware_inventory

            if a == "inventory":
                res_obj = probe_hardware_inventory()
            elif a == "accelerators":
                accels = probe_accelerators()
                res_obj = {"status": "OK", "count": len(accels), "accelerators": accels}
            elif a == "admit":
                device = eff_name if eff_name and eff_name != "auto" else None
                req_vram = 0
                req_gtt = 0
                req_mib = 0
                margin = 4096

                eff_params = dict(params) if isinstance(params, dict) else {}
                if isinstance(args, dict):
                    eff_params = {**eff_params, **args}

                if eff_params:
                    if "vram_mib" in eff_params:
                        req_vram = int(eff_params["vram_mib"]) if str(eff_params["vram_mib"]).isdigit() else 0
                    elif "req_vram_mib" in eff_params:
                        req_vram = int(eff_params["req_vram_mib"]) if str(eff_params["req_vram_mib"]).isdigit() else 0

                    if "gtt_mib" in eff_params:
                        req_gtt = int(eff_params["gtt_mib"]) if str(eff_params["gtt_mib"]).isdigit() else 0
                    elif "req_gtt_mib" in eff_params:
                        req_gtt = int(eff_params["req_gtt_mib"]) if str(eff_params["req_gtt_mib"]).isdigit() else 0

                    if "req_mib" in eff_params:
                        req_mib = int(eff_params["req_mib"]) if str(eff_params["req_mib"]).isdigit() else 0

                    if "margin_mib" in eff_params:
                        margin = int(eff_params["margin_mib"]) if str(eff_params["margin_mib"]).isdigit() else 4096
                    elif "margin" in eff_params:
                        margin = int(eff_params["margin"]) if str(eff_params["margin"]).isdigit() else 4096

                    if "device" in eff_params and eff_params["device"] is not None:
                        device = str(eff_params["device"])

                nums = []
                if isinstance(args, list):
                    i = 0
                    while i < len(args):
                        item = str(args[i])
                        if item in ("--vram", "-vram", "--req_vram", "--req-vram") and i + 1 < len(args):
                            req_vram = int(args[i + 1]) if str(args[i + 1]).isdigit() else 0
                            i += 2
                        elif item in ("--gtt", "-gtt", "--req_gtt", "--req-gtt") and i + 1 < len(args):
                            req_gtt = int(args[i + 1]) if str(args[i + 1]).isdigit() else 0
                            i += 2
                        elif item in ("--margin", "-margin", "--margin_mib", "--margin-mib") and i + 1 < len(args):
                            margin = int(args[i + 1]) if str(args[i + 1]).isdigit() else 4096
                            i += 2
                        elif item in ("--req", "-req", "--req_mib", "--req-mib") and i + 1 < len(args):
                            req_mib = int(args[i + 1]) if str(args[i + 1]).isdigit() else 0
                            i += 2
                        elif item in ("--device", "-device", "--card", "-card") and i + 1 < len(args):
                            device = str(args[i + 1])
                            i += 2
                        elif item.isdigit():
                            nums.append(int(item))
                            i += 1
                        else:
                            i += 1
                elif isinstance(args, str):
                    for part in args.split():
                        try:
                            nums.append(int(part))
                        except (ValueError, TypeError):
                            pass

                if len(nums) > 0 and req_vram == 0 and req_mib == 0:
                    if len(nums) == 1:
                        req_mib = nums[0]
                    else:
                        req_vram = nums[0]
                if len(nums) > 1 and req_gtt == 0:
                    req_gtt = nums[1]
                if len(nums) > 2 and margin == 4096:
                    margin = nums[2]

                res_obj = admit_accelerator(
                    device=device,
                    req_vram_mib=req_vram,
                    req_gtt_mib=req_gtt,
                    margin_mib=margin,
                    req_mib=req_mib,
                    params=eff_params,
                )
            else:
                res_obj = {"status": "ERROR", "error": f"Acción de hardware desconocida: {a}", "valid": valid_actions}
            return attach_envelope(res_obj, tracker, verbosity=verbosity)

        if not AEP_CTL.exists():
            return attach_envelope(
                {"status": "ERROR", "error": f"aep-ctl no encontrado en {AEP_CTL}"},
                tracker,
                verbosity=verbosity,
            )
        cmd = ["python3", str(AEP_CTL), d, a]
        if eff_name:
            cmd.append(eff_name)
        cmd.append("--json")
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            raw_out = res.stdout.strip()
            if not raw_out:
                return attach_envelope(
                    {"status": "ERROR", "stderr": res.stderr.strip()},
                    tracker,
                    verbosity=verbosity,
                )
            parsed = json.loads(raw_out)

            # Apply compact summarization & pagination when requested or on large collections
            truncated = False
            next_cur: str | None = None
            if isinstance(parsed, dict) and parsed.get("status") == "OK":
                if d == "network" and a == "listeners" and isinstance(parsed.get("listeners"), list):
                    all_items = parsed["listeners"]
                    total = len(all_items)
                    cap = min(eff_limit, 25) if is_compact else eff_limit
                    sliced = all_items[eff_cursor : eff_cursor + cap]
                    if is_compact:
                        sliced = [
                            {
                                "proto": it.get("proto"),
                                "local": it.get("local"),
                                "process": it.get("process"),
                                "pid": it.get("pid"),
                            }
                            for it in sliced
                        ]
                    truncated = (eff_cursor + len(sliced)) < total
                    next_cur = str(eff_cursor + len(sliced)) if truncated else None
                    parsed["total_count"] = total
                    parsed["count"] = len(sliced)
                    parsed["listeners"] = sliced
                elif d == "network" and a == "inspect" and is_compact and isinstance(parsed.get("interfaces"), list):
                    parsed["interfaces"] = [
                        {
                            "ifname": iface.get("ifname"),
                            "operstate": iface.get("operstate"),
                            "mtu": iface.get("mtu"),
                            "addresses": [
                                ai.get("local")
                                for ai in iface.get("addr_info", [])
                                if isinstance(ai, dict) and ai.get("local")
                            ],
                        }
                        for iface in parsed["interfaces"]
                    ]
                elif d == "network" and a == "routes" and isinstance(parsed.get("routes"), list):
                    all_routes = parsed["routes"]
                    total = len(all_routes)
                    cap = min(eff_limit, 15) if is_compact else eff_limit
                    sliced = all_routes[eff_cursor : eff_cursor + cap]
                    truncated = (eff_cursor + len(sliced)) < total
                    next_cur = str(eff_cursor + len(sliced)) if truncated else None
                    parsed["total_count"] = total
                    parsed["count"] = len(sliced)
                    parsed["routes"] = sliced
                elif d == "storage" and a == "mounts" and is_compact and isinstance(parsed.get("filesystems"), list):
                    flat: list[dict[str, Any]] = []
                    _flatten_mounts(parsed["filesystems"], flat)
                    total = len(flat)
                    cap = min(eff_limit, 25)
                    sliced = flat[eff_cursor : eff_cursor + cap]
                    truncated = (eff_cursor + len(sliced)) < total
                    next_cur = str(eff_cursor + len(sliced)) if truncated else None
                    parsed = {
                        "status": "OK",
                        "verbosity": "summary",
                        "total_mounts": total,
                        "count": len(sliced),
                        "filesystems": sliced,
                    }
                elif d == "storage" and a == "disks" and is_compact and isinstance(parsed.get("blockdevices"), list):
                    raw_devs = parsed["blockdevices"]
                    loop_cnt = sum(1 for bd in raw_devs if isinstance(bd, dict) and bd.get("type") == "loop")
                    real_devs = [
                        bd
                        for bd in raw_devs
                        if isinstance(bd, dict) and bd.get("type") != "loop" and bd.get("size") != "0B"
                    ]
                    parsed["filtered_loop_devices"] = loop_cnt
                    parsed["count"] = len(real_devs)
                    parsed["blockdevices"] = real_devs
                elif d == "storage" and a == "usage" and is_compact and isinstance(parsed.get("filesystems"), list):
                    real_fs = [
                        fs
                        for fs in parsed["filesystems"]
                        if isinstance(fs, dict)
                        and fs.get("source") not in ("none", "efivarfs")
                        and not str(fs.get("mount", "")).startswith("/run/credentials/")
                    ]
                    parsed["count"] = len(real_fs)
                    parsed["filesystems"] = real_fs
                elif d == "package" and a in ("installed", "list") and isinstance(parsed.get("packages"), list):
                    all_pkgs = parsed["packages"]
                    total = parsed.get("count", len(all_pkgs))
                    cap = min(eff_limit, 30) if is_compact else eff_limit
                    sliced = all_pkgs[eff_cursor : eff_cursor + cap]
                    truncated = (eff_cursor + len(sliced)) < len(all_pkgs)
                    next_cur = str(eff_cursor + len(sliced)) if truncated else None
                    parsed["total_count"] = total
                    parsed["count"] = len(sliced)
                    parsed["packages"] = sliced
                elif d == "service" and a == "list" and isinstance(parsed.get("services"), list):
                    all_svcs = parsed["services"]
                    total = parsed.get("count", len(all_svcs))
                    cap = min(eff_limit, 25) if is_compact else eff_limit
                    sliced = all_svcs[eff_cursor : eff_cursor + cap]
                    truncated = (eff_cursor + len(sliced)) < len(all_svcs)
                    next_cur = str(eff_cursor + len(sliced)) if truncated else None
                    parsed["total_count"] = total
                    parsed["count"] = len(sliced)
                    parsed["services"] = sliced

            return attach_envelope(
                parsed,
                tracker,
                verbosity=verbosity,
                truncated=truncated,
                cursor=next_cur,
            )
        except Exception as e:
            return attach_envelope({"status": "ERROR", "error": str(e)}, tracker, verbosity=verbosity)

    return await anyio.to_thread.run_sync(_run)


async def check_crash_alerts(resolve_after_report: bool = False) -> str:
    """
    [COMPAT] Consulta crashes no resueltos en artifacts.db. Alerta proactiva
    antes de que el agente actúe. (Des-registrado de MCP en Fase 6; unificado en diagnose_system_crashes).
    """
    return await diagnose_system_crashes(action="alerts", resolve_after_report=resolve_after_report)


@mcp.tool(structured_output=False)
async def query_system_docs(
    query: str | None = None,
    q: str | None = None,
    limit: int = 3,
    ingest_command: str | None = None,
    source: str | None = None,
    verbosity: str = "detail",
    agent_id: str = "default",
) -> str:
    """
    [SPEC-OM-4 / DOCS VECTORIZER] Memoria semántica local de man-pages (sqlite-vec).
    Devuelve la sintaxis exacta de herramientas del sistema sin alucinar ni navegar la web.
    - `query` / `q`: consulta en lenguaje natural o comando del sistema.
    - `ingest_command`: ingiere la man-page de un comando extra on-demand antes de consultar.
    """

    def _run() -> str:
        eff_query = (query or q or "").strip()
        tracker = RequestTelemetry("query_system_docs", source or "man")
        if not eff_query:
            return attach_envelope(
                {
                    "status": "PARAM_ERROR",
                    "error": "Debe proporcionar el parámetro 'query' (o 'q') a consultar.",
                },
                tracker,
                verbosity=verbosity,
            )

        try:
            dv = _get_docs_vectorizer()
            if ingest_command:
                dv.ingest_command(ingest_command)
            res = dv.query(eff_query, limit)
            return attach_envelope(
                res,
                tracker,
                verbosity=verbosity,
                summary=f"Retrieved {len(res.get('results', []))} doc chunks for query '{eff_query[:40]}'.",
            )
        except Exception as e:
            return attach_envelope({"status": "ERROR", "error": str(e)}, tracker, verbosity=verbosity)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool(structured_output=False)
async def visual_inspect(
    url: str,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    selector: str | None = None,
    full_page: bool = True,
    include_base64: bool = False,
    verbosity: str = "summary",
    agent_id: str = "default",
) -> str:
    """
    [SPEC-OM-5 / HEADLESS DISPLAY] Renderiza una URL (http(s):// o file://) en Chromium
    headless y captura un screenshot en RAM (/dev/shm).
    - Por defecto (`include_base64=False`, `verbosity='summary'`), guarda el PNG en `/dev/shm/aep_shot_*.png`
      y devuelve `screenshot_path`, `screenshot_sha256`, `screenshot_bytes`, `title` y `text_excerpt`
      sin inundar el contexto con >100 KB de base64.
    - Pasa `include_base64=True` o `verbosity='full'` si requieres el string `screenshot_base64` inline.
    FAIL-SOFT si no hay navegador.
    """

    def _run() -> str:
        tracker = RequestTelemetry("visual_inspect", "render")
        want_b64 = bool(include_base64 or (verbosity or "").strip().lower() == "full")
        try:
            future = _display_executor.submit(
                headless_display.visual_inspect,
                url,
                viewport_width,
                viewport_height,
                selector,
                full_page,
                want_b64,
            )
            res = future.result(timeout=25)
            return attach_envelope(
                res,
                tracker,
                verbosity=verbosity,
                summary=f"Rendered '{res.get('title', url)}' ({res.get('screenshot_bytes', 0)} bytes in /dev/shm).",
            )
        except concurrent.futures.TimeoutError:
            return attach_envelope(
                {
                    "status": "DISPLAY_UNAVAILABLE",
                    "message": "Playwright timeout exceeded 25s",
                    "url": url,
                },
                tracker,
                verbosity=verbosity,
            )
        except Exception as e:
            return attach_envelope({"status": "ERROR", "error": str(e)}, tracker, verbosity=verbosity)

    return await anyio.to_thread.run_sync(_run)


_BPFTRACE_MODES = {
    # eBPF kernel observability & packet telemetry.
    "syscall_count": "tracepoint:raw_syscalls:sys_enter {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "file_opens": "tracepoint:syscalls:sys_enter_openat {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "tcp_connect": "kprobe:tcp_connect {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "security_open_denials": "tracepoint:syscalls:sys_exit_openat /args->ret < 0/ {{ @[comm, args->ret] = count(); }} interval:s:{d} {{ exit(); }}",
    "security_landlock_audit": "tracepoint:syscalls:sys_enter_landlock_restrict_self {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "security_exec_monitor": "tracepoint:syscalls:sys_enter_execve {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "network_sniff": "kprobe:netif_receive_skb {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "security_audit": "tracepoint:syscalls:sys_enter_capget {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
    "tcp_listeners": "kprobe:inet_csk_listen_start {{ @[comm] = count(); }} interval:s:{d} {{ exit(); }}",
}

_BPFTRACE_MODE_ALIASES = {
    "syscalls": "syscall_count",
    "syscall": "syscall_count",
    "opens": "file_opens",
    "openat": "file_opens",
    "tcp": "tcp_connect",
    "denials": "security_open_denials",
    "landlock": "security_landlock_audit",
    "exec": "security_exec_monitor",
    "execve": "security_exec_monitor",
    "sniff": "network_sniff",
    "network": "network_sniff",
    "audit": "security_audit",
    "listeners": "tcp_listeners",
}


@mcp.tool(structured_output=False)
async def kernel_trace(
    mode: str = "syscall_count",
    duration_sec: int = 3,
    probe: str | None = None,
    duration: int | None = None,
    limit: int = 25,
    verbosity: str = "summary",
    agent_id: str = "default",
) -> str:
    """
    [SPEC-OM-6 / KERNEL TRACE via eBPF] Observabilidad de kernel a bajo nivel (bpftrace).
    Requiere nivel FULL (sudo -n disponible); degrada limpiamente a DIMINISHED si no hay root.
    `mode` (alias `probe`): 'syscall_count' (alias 'syscalls'), 'file_opens' ('opens'),
    'tcp_connect' ('tcp'), 'security_open_denials' ('denials'),
    'security_landlock_audit' ('landlock'), 'security_exec_monitor' ('exec'), 'network_sniff' ('sniff'/'network'), 'security_audit' ('audit'), 'tcp_listeners' ('listeners').
    Ordena resultados de mayor a menor actividad y trunca a `limit` en modo `summary`.
    """

    def _run() -> str:
        raw_mode = (probe or mode or "syscall_count").strip().lower()
        eff_mode = _BPFTRACE_MODE_ALIASES.get(raw_mode, raw_mode)
        eff_dur = int(duration if duration is not None else duration_sec)
        is_compact = (verbosity or "summary").strip().lower() in ("summary", "brief")
        eff_limit = max(1, int(limit or 25))
        tracker = RequestTelemetry("kernel_trace", eff_mode)

        if eff_mode not in _BPFTRACE_MODES:
            return attach_envelope(
                {
                    "status": "INVALID_MODE",
                    "error": f"Modo '{raw_mode}' no soportado. Válidos: {list(_BPFTRACE_MODES.keys())}",
                    "valid_modes": list(_BPFTRACE_MODES.keys()),
                },
                tracker,
                verbosity=verbosity,
            )
        prefix = privilege_prefix()
        if prefix is None:
            if eff_mode == "network_sniff":
                pcap_shm = Path("/dev/shm/pcap_stream")
                if pcap_shm.exists():
                    from engine import net_telemetry

                    dissected = net_telemetry.dissect_shm_pcap_buffer(pcap_shm, limit=eff_limit)
                    return attach_envelope(
                        {
                            "status": "OK",
                            "capability_tier": "DIMINISHED",
                            "mode": eff_mode,
                            "pcap_dissection": dissected,
                            "message": "In-memory packet header dissection from /dev/shm/pcap_stream",
                        },
                        tracker,
                        verbosity=verbosity,
                        summary=f"Dissected {dissected.get('count', 0)} packet headers in-RAM.",
                    )
            return attach_envelope(
                {
                    "status": "DEGRADED",
                    "capability_tier": "DIMINISHED",
                    "message": "bpftrace requiere root (CAP_BPF) y no hay sudo -n disponible.",
                },
                tracker,
                verbosity=verbosity,
            )
        pmode = privilege_mode()
        clamped_dur = max(1, min(eff_dur, 30))
        script = _BPFTRACE_MODES[eff_mode].format(d=clamped_dur)
        try:
            res = subprocess.run(
                prefix + ["bpftrace", "-f", "json", "-e", script],
                capture_output=True,
                text=True,
                timeout=max(5, clamped_dur + 10),
                check=False,
            )
            if res.returncode != 0:
                return attach_envelope(
                    {
                        "status": "DEGRADED",
                        "capability_tier": "FULL",
                        "privilege_mode": pmode,
                        "message": "bpftrace falló pese a la escalada.",
                        "stderr": res.stderr.strip()[:300],
                    },
                    tracker,
                    verbosity=verbosity,
                )
            counts: dict[str, int] = {}
            for line in res.stdout.splitlines():
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "map":
                        for _, m in obj.get("data", {}).items():
                            if isinstance(m, dict):
                                for k, v in m.items():
                                    counts[str(k)] = int(v) if isinstance(v, (int, float)) else 0
                except Exception as e:
                    logger.debug("Failed parsing bpftrace line: %s", e)

            sorted_items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
            total_procs = len(sorted_items)
            total_events = sum(v for _, v in sorted_items)
            truncated = False
            if is_compact and total_procs > eff_limit:
                sorted_items = sorted_items[:eff_limit]
                truncated = True
            ordered_counts = dict(sorted_items)

            trace_data = {
                "status": "OK",
                "capability_tier": "FULL",
                "mode": eff_mode,
                "duration_sec": clamped_dur,
                "privilege_mode": pmode,
                "total_processes": total_procs,
                "total_events": total_events,
                "counts": ordered_counts,
            }
            if eff_mode == "network_sniff":
                pcap_shm = Path("/dev/shm/pcap_stream")
                if pcap_shm.exists():
                    from engine import net_telemetry

                    trace_data["pcap_dissection"] = net_telemetry.dissect_shm_pcap_buffer(pcap_shm, limit=eff_limit)
            return attach_envelope(
                trace_data,
                tracker,
                verbosity=verbosity,
                truncated=truncated,
                summary=f"eBPF {eff_mode} ({clamped_dur}s): {total_events} events across {total_procs} processes.",
            )
        except Exception as e:
            return attach_envelope({"status": "DEGRADED", "error": str(e)}, tracker, verbosity=verbosity)

    return await anyio.to_thread.run_sync(_run)


@mcp.tool(structured_output=False)
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
    limit: int = 5,
    verbosity: str = "summary",
    agent_id: str = "default",
) -> str:
    """
    [PICO-KANBAN UNIFICADO] Tablero de estados abstracto y ponderación agéntica (transparente al usuario).
    action:
      - 'board' (default): vista del tablero por lanes (BACKLOG/SYNTHESIZED/LINTED/CANARY/PROMOTED/REJECTED). En modo `summary`, muestra hasta `limit` tareas recientes por lane.
      - 'create' (o 'task_create', 'add'): crea una tarea atómica en BACKLOG (requiere `title`).
      - 'advance' (o 'move'): mueve una tarea de estado y recalcula su ponderación (requiere `task_id` y `to_state`).
      - 'promote': promueve el artefacto ligado como reutilizable si alcanza TRUST (requiere `task_id`).
      - 'demote': degrada explícitamente un artefacto a reusable=0 (requiere `artifact_name`).
      - 'reevaluate': re-pondera artefactos reusables y degrada solo los que tienen fallo demostrado.
      - 'archive': archiva (soft, reversible) tareas estancadas (apply=False -> DRY_RUN).
      - 'unarchive': reactiva una tarea archivada (requiere `task_id`).
    """

    def _run() -> str:
        act = (action or "board").strip().lower()
        tracker = RequestTelemetry("kanban_board", act)
        is_compact = (verbosity or "summary").strip().lower() in ("summary", "brief")
        eff_limit = max(1, int(limit or 5))
        tier_info = get_effective_chmod_tier()
        curr_tier = tier_info.get("tier", "6rw-")
        if act not in ("board", "list", "status", "query") and curr_tier in ("4r--", "5r-x"):
            return attach_envelope(
                {
                    "status": "DEGRADED",
                    "chmod_tier": curr_tier,
                    "action": act,
                    "message": f"Kanban mutation '{act}' disabled in read-only tier ({curr_tier}); board inspection only.",
                },
                tracker,
                verbosity=verbosity,
            )
        try:
            if act == "board":
                res = kanban.board(include_archived=include_archived)
                res.setdefault("status", "OK")
                truncated = False
                if is_compact and isinstance(res.get("lanes"), dict):
                    for lane_name, cards in list(res["lanes"].items()):
                        if isinstance(cards, list) and len(cards) > eff_limit:
                            sorted_cards = sorted(
                                cards,
                                key=lambda c: int(c.get("task_id", 0)) if isinstance(c, dict) else 0,
                                reverse=True,
                            )
                            res["lanes"][lane_name] = sorted_cards[:eff_limit]
                            truncated = True
                return attach_envelope(
                    res,
                    tracker,
                    verbosity=verbosity,
                    truncated=truncated,
                    summary=f"Kanban board loaded (counts={res.get('counts', {})}).",
                )
            elif act in ("create", "task_create", "add"):
                if not (title or "").strip():
                    return attach_envelope(
                        {"status": "PARAM_ERROR", "error": "Acción 'create' requiere 'title'."},
                        tracker, verbosity=verbosity,
                    )
                res = kanban.create_task(title.strip(), intent, category, artifact_name, agent_id=agent_id)
                return attach_envelope(res, tracker, verbosity=verbosity)
            elif act in ("advance", "move"):
                if task_id is None or not (to_state or "").strip():
                    return attach_envelope(
                        {"status": "PARAM_ERROR", "error": "Acción 'advance'/'move' requiere 'task_id' y 'to_state'."},
                        tracker, verbosity=verbosity,
                    )
                return attach_envelope(
                    kanban.advance(task_id, to_state.strip(), lint_passed, canary_passed, note),
                    tracker, verbosity=verbosity,
                )
            elif act == "promote":
                if task_id is None:
                    return attach_envelope(
                        {"status": "PARAM_ERROR", "error": "Acción 'promote' requiere 'task_id'."},
                        tracker, verbosity=verbosity,
                    )
                return attach_envelope(kanban.promote(task_id), tracker, verbosity=verbosity)
            elif act == "demote":
                if not (artifact_name or "").strip() and task_id is None:
                    return attach_envelope(
                        {"status": "PARAM_ERROR", "error": "Acción 'demote' requiere 'artifact_name' o 'task_id'."},
                        tracker, verbosity=verbosity,
                    )
                return attach_envelope(
                    kanban.demote(
                        artifact_name.strip() if artifact_name else None,
                        reason,
                        task_id=task_id,
                        target_state=target_state,
                    ),
                    tracker, verbosity=verbosity,
                )
            elif act == "reevaluate":
                return attach_envelope(kanban.reevaluate(), tracker, verbosity=verbosity)
            elif act == "archive":
                return attach_envelope(
                    kanban.archive(states=states, max_score=max_score, apply=apply),
                    tracker, verbosity=verbosity,
                )
            elif act == "unarchive":
                if task_id is None:
                    return attach_envelope(
                        {"status": "PARAM_ERROR", "error": "Acción 'unarchive' requiere 'task_id'."},
                        tracker, verbosity=verbosity,
                    )
                return attach_envelope(kanban.unarchive(task_id), tracker, verbosity=verbosity)
            else:
                return attach_envelope(
                    {
                        "status": "INVALID_ACTION",
                        "error": f"Acción '{action}' no reconocida. Acciones válidas: 'board', 'create', 'advance', 'promote', 'demote', 'reevaluate', 'archive', 'unarchive'.",
                        "valid_actions": [
                            "board",
                            "create",
                            "add",
                            "advance",
                            "move",
                            "promote",
                            "demote",
                            "reevaluate",
                            "archive",
                            "unarchive",
                        ],
                    },
                    tracker, verbosity=verbosity,
                )
        except Exception as e:
            return attach_envelope({"status": "ERROR", "error": str(e)}, tracker, verbosity=verbosity)

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
        "autoevol": autoevol,
        "kanban_board": kanban_board,
        "artifact_lint_and_build": artifact_lint_and_build,
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


@mcp.tool(structured_output=False)
async def playbook_run(
    action: str = "run",
    name: str | None = None,
    vars: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    stop_on_error: bool = True,
    description: str | None = None,
    intent_description: str | None = None,
    steps: list[dict[str, Any]] | str | None = None,
    params_contract: list[dict[str, Any]] | None = None,
    names: list[str] | None = None,
    apply: bool = False,
    verbosity: str = "summary",
    agent_id: str = "default",
    return_only: str = "all",
    select_fields: list[str] | None = None,
) -> str:
    """
    [PICO-PLAYBOOK UNIFICADO] Orquestación y ejecución de automatizaciones DAG parametrizables y pipelines efímeros.
    action:
      - 'run' (default): instancia y ejecuta un playbook en orden topológico (requiere `name`; `vars` o `params` hidrata marcadores `${var}`).
      - 'batch' | 'code' | 'ephemeral' | 'pipeline': ejecuta una secuencia efímera de pasos en un solo turno, reutilizando slots en RAM (/dev/shm) con Server-Side Field Projection.
      - 'create': define una automatización parametrizable y valida su DAG (requiere `name`, `description` y `steps`).
      - 'list': lista los playbooks guardados con su tasa de éxito, número de pasos y contratos.
      - 'prune': poda destructiva segura de playbooks con fallo demostrado (éxito < 0.70) o explícitos en `names` (apply=False -> DRY_RUN).
    Parámetros de batch:
      - `return_only`: 'all' (defecto), 'last' (solo output del último paso), o 'summary' (resumen booleano por paso).
      - `select_fields`: lista de dot-paths (ej: ['status', 'results.0.output.pid']) para proyectar la respuesta en RAM y ahorrar tokens.
    """
    act = (action or "run").strip().lower()
    tracker = RequestTelemetry("playbook_run", act)
    is_compact = (verbosity or "summary").strip().lower() in ("summary", "brief")
    effective_vars = vars if vars is not None else (params or {})
    effective_desc = (description or intent_description or "").strip()
    tier_info = get_effective_chmod_tier()
    curr_tier = tier_info.get("tier", "6rw-")
    if act in ("run", "create", "prune") and curr_tier == "4r--":
        return attach_envelope(
            {
                "status": "DEGRADED",
                "chmod_tier": "4r--",
                "action": act,
                "message": f"Playbook execution/mutation '{act}' disabled in auditor tier (4r--); validation and static listing only.",
            },
            tracker,
            verbosity=verbosity,
        )
    try:
        if act == "run":
            if not (name or "").strip():
                return attach_envelope(
                    {"status": "PARAM_ERROR", "error": "Acción 'run' requiere 'name'."},
                    tracker,
                    verbosity=verbosity,
                )
            pb = playbook_store.get(name.strip())
            if not pb:
                return attach_envelope(
                    {"status": "ERROR", "error": f"playbook '{name.strip()}' no existe"},
                    tracker,
                    verbosity=verbosity,
                )

            try:
                resolved = resolve_params(pb.get("params_contract") or [], effective_vars)
                hydrated_steps = hydrate_struct(pb["steps"], resolved, strict=True)
            except ValueError as e:
                return attach_envelope(
                    {"status": "PARAM_ERROR", "error": str(e), "contract": pb.get("params_contract") or []},
                    tracker,
                    verbosity=verbosity,
                )

            v = PlaybookStore.validate_and_order(hydrated_steps)
            if not v.get("ok"):
                return attach_envelope(
                    {"status": "BLOCKED", "verdict": v.get("verdict"), "logs": v.get("logs")},
                    tracker,
                    verbosity=verbosity,
                )

            eff_sid = (
                (effective_vars.get("session_id") if isinstance(effective_vars, dict) else None)
                or (params.get("session_id") if isinstance(params, dict) else None)
                or f"playbook-{name.strip()}"
            )
            eff_agent = agent_id or "default"
            slot = GLOBAL_SESSION_POOL.acquire(session_id=eff_sid, agent_id=eff_agent)

            dispatch = _playbook_dispatch()
            step_outputs: dict[str, Any] = {}
            prev_output: Any = None
            results: list[dict[str, Any]] = []
            all_ok = True
            slot_cache_dict = dict(
                GLOBAL_SESSION_POOL.cache_get(session_id=eff_sid, agent_id=eff_agent).get("cache", {})
            )

            try:
                for step in v["ordered_steps"]:
                    sid = str(step.get("id", f"s{len(results) + 1}"))
                    tool = step.get("tool")
                    step_params = dict(step.get("params", {}))

                    # Resolve variable piping from previous outputs (.*, .<id>.*, .*, .*)
                    step_params = resolve_step_refs(step_params, step_outputs, prev_output, slot_cache=slot_cache_dict)

                    fn = dispatch.get(tool)
                    if fn is None:
                        results.append({"id": sid, "tool": tool, "status": "NOT_ALLOWED", "ok": False})
                        all_ok = False
                        if stop_on_error:
                            break
                        continue

                    try:
                        sig = inspect.signature(fn)
                        if "agent_id" not in step_params and "agent_id" in sig.parameters:
                            step_params["agent_id"] = eff_agent

                        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                        if not has_var_kw:
                            step_params = {k: v for k, v in step_params.items() if k in sig.parameters}
                        if (
                            is_compact
                            and "verbosity" not in step_params
                            and ("verbosity" in sig.parameters or has_var_kw)
                        ):
                            step_params["verbosity"] = "summary"
                        raw = fn(**step_params)
                        if inspect.iscoroutine(raw):
                            raw = await raw
                        out = json.loads(raw) if isinstance(raw, str) else raw
                        st = out.get("status", "OK") if isinstance(out, dict) else "OK"
                        if is_compact and isinstance(out, dict):
                            out.pop("envelope", None)
                    except Exception as e:
                        st, out = "ERROR", {"error": str(e)}

                    ok = st not in _PLAYBOOK_FAIL
                    step_res = {"id": sid, "tool": tool, "status": st, "ok": ok, "output": out}
                    results.append(step_res)
                    step_outputs[sid] = out
                    prev_output = out

                    if ok:
                        GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, sid, out)
                        slot_cache_dict[sid] = out
                        if step.get("store_as"):
                            k_as = str(step["store_as"]).strip()
                            if k_as:
                                GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, k_as, out)
                                slot_cache_dict[k_as] = out

                    if not ok:
                        all_ok = False
                        if stop_on_error:
                            break
            finally:
                GLOBAL_SESSION_POOL.release(session_id=eff_sid, agent_id=eff_agent, clear_state=False)

            playbook_store.record_run(name.strip(), all_ok)

            ret_mode = (return_only or "all").strip().lower()
            pb_name = name.strip()

            base_res: dict[str, Any] = {
                "status": "OK" if all_ok else "PARTIAL",
                "playbook": pb_name,
                "all_ok": all_ok,
                "steps_run": len(results),
            }

            failed_steps = [
                {
                    "id": r["id"],
                    "tool": r["tool"],
                    "status": r["status"],
                    "error": (
                        (r.get("output") or {}).get("error") or (r.get("output") or {}).get("message")
                        if isinstance(r.get("output"), dict)
                        else str(r.get("output"))
                    ),
                }
                for r in results
                if not r.get("ok")
            ]
            if failed_steps:
                base_res["failed_steps"] = failed_steps

            if ret_mode == "last":
                base_res["output"] = prev_output
            elif ret_mode == "summary":
                base_res["steps_summary"] = [
                    {"id": r["id"], "tool": r["tool"], "status": r["status"], "ok": r["ok"]} for r in results
                ]
            else:  # "all"
                base_res["results"] = results

            base_res["ipc_slot"] = {
                "slot_id": slot["slot_id"],
                "agent_id": eff_agent,
                "reuse_count": slot["reuse_count"],
                "scratch_dir": str(slot["scratch_dir"]),
                "socket_path": str(GLOBAL_SOCKET_MUX.socket_path),
                "cached_keys": GLOBAL_SESSION_POOL.cache_get(session_id=eff_sid, agent_id=eff_agent).get("keys", []),
            }

            if select_fields and isinstance(select_fields, list):
                full_json = json.dumps(base_res)
                full_bytes = len(full_json.encode("utf-8"))

                projected_res = project_fields(base_res, select_fields)
                if "status" not in projected_res:
                    projected_res["status"] = base_res.get("status", "OK")
                if "playbook" not in projected_res:
                    projected_res["playbook"] = pb_name
                if failed_steps and "failed_steps" not in projected_res:
                    projected_res["failed_steps"] = failed_steps
                proj_json = json.dumps(projected_res)
                proj_bytes = len(proj_json.encode("utf-8"))

                saved_bytes = max(0, full_bytes - proj_bytes)
                savings_pct = round((saved_bytes / full_bytes * 100), 2) if full_bytes > 0 else 0.0

                projected_res["token_savings_estimate"] = {
                    "full_bytes": full_bytes,
                    "projected_bytes": proj_bytes,
                    "saved_bytes": saved_bytes,
                    "savings_pct": savings_pct,
                    "turns_saved": max(0, len(results) - 1),
                }
                final_res = projected_res
            else:
                full_json = json.dumps(base_res)
                full_bytes = len(full_json.encode("utf-8"))
                base_res["token_savings_estimate"] = {
                    "full_bytes": full_bytes,
                    "projected_bytes": full_bytes,
                    "saved_bytes": 0,
                    "savings_pct": 0.0,
                    "turns_saved": max(0, len(results) - 1),
                }
                final_res = base_res

            return attach_envelope(
                final_res,
                tracker,
                verbosity=verbosity,
                summary=f"Playbook '{pb_name}' finished ({len(results)} steps, all_ok={all_ok}).",
            )

        elif act == "create":
            if not (name or "").strip() or not effective_desc or not steps:
                return attach_envelope(
                    {"status": "PARAM_ERROR", "error": "Acción 'create' requiere 'name', 'description' y 'steps'."},
                    tracker, verbosity=verbosity,
                )
            allowed = set(_playbook_dispatch())
            bad = sorted({s.get("tool") for s in steps if isinstance(s, dict) and s.get("tool") not in allowed})
            if bad:
                return attach_envelope(
                    {"status": "LINT_ERROR", "invalid_tools": bad, "allowed_tools": sorted(allowed)},
                    tracker, verbosity=verbosity,
                )
            return attach_envelope(
                playbook_store.create(name.strip(), effective_desc, steps, params_contract),
                tracker, verbosity=verbosity,
            )

        elif act == "list":
            return attach_envelope({"status": "OK", "playbooks": playbook_store.list()}, tracker, verbosity=verbosity)

        elif act in ("batch", "code", "ephemeral", "pipeline"):
            raw_steps = steps
            if isinstance(raw_steps, str):
                try:
                    raw_steps = json.loads(raw_steps)
                except Exception as e:
                    return attach_envelope(
                        {"status": "PARAM_ERROR", "error": f"Formato JSON inválido en steps: {e}"},
                        tracker,
                        verbosity=verbosity,
                    )
            if not isinstance(raw_steps, list) or not raw_steps:
                return attach_envelope(
                    {
                        "status": "PARAM_ERROR",
                        "error": "Acción 'batch' requiere 'steps' (lista no vacía de diccionarios de pasos).",
                    },
                    tracker,
                    verbosity=verbosity,
                )

            if effective_vars:
                try:
                    raw_steps = hydrate_struct(raw_steps, effective_vars, strict=False)
                except Exception as e:
                    return attach_envelope(
                        {"status": "PARAM_ERROR", "error": f"Error hidratando parámetros de steps: {e}"},
                        tracker,
                        verbosity=verbosity,
                    )

            try:
                v = PlaybookStore.validate_and_order(raw_steps)
            except ValueError as e:
                return attach_envelope(
                    {"status": "PARAM_ERROR", "error": str(e)},
                    tracker,
                    verbosity=verbosity,
                )
            if not v.get("ok"):
                return attach_envelope(
                    {"status": "BLOCKED", "verdict": v.get("verdict"), "logs": v.get("logs")},
                    tracker,
                    verbosity=verbosity,
                )

            ordered_steps = v.get("ordered_steps") or raw_steps

            eff_sid = (
                (effective_vars.get("session_id") if isinstance(effective_vars, dict) else None)
                or (params.get("session_id") if isinstance(params, dict) else None)
                or "mcp-batch"
            )
            eff_agent = agent_id or "default"
            slot = GLOBAL_SESSION_POOL.acquire(session_id=eff_sid, agent_id=eff_agent)

            dispatch = _playbook_dispatch()
            step_outputs: dict[str, Any] = {}
            prev_output: Any = None
            results: list[dict[str, Any]] = []
            all_ok = True
            slot_cache_dict = dict(
                GLOBAL_SESSION_POOL.cache_get(session_id=eff_sid, agent_id=eff_agent).get("cache", {})
            )

            try:
                for step in ordered_steps:
                    sid = str(step.get("id", f"s{len(results) + 1}"))
                    tool = step.get("tool")
                    step_params = dict(step.get("params", {}))

                    # Resolve variable piping from previous outputs (.*, .<id>.*, .*, .*)
                    step_params = resolve_step_refs(step_params, step_outputs, prev_output, slot_cache=slot_cache_dict)

                    fn = dispatch.get(tool)
                    if fn is None:
                        err_res = {"id": sid, "tool": tool, "status": "NOT_ALLOWED", "ok": False}
                        results.append(err_res)
                        all_ok = False
                        if stop_on_error:
                            break
                        continue

                    try:
                        sig = inspect.signature(fn)
                        if "agent_id" not in step_params and "agent_id" in sig.parameters:
                            step_params["agent_id"] = eff_agent

                        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                        if not has_var_kw:
                            step_params = {k: v for k, v in step_params.items() if k in sig.parameters}
                        if (
                            is_compact
                            and "verbosity" not in step_params
                            and ("verbosity" in sig.parameters or has_var_kw)
                        ):
                            step_params["verbosity"] = "summary"
                        raw = fn(**step_params)
                        if inspect.iscoroutine(raw):
                            raw = await raw
                        out = json.loads(raw) if isinstance(raw, str) else raw
                        st = out.get("status", "OK") if isinstance(out, dict) else "OK"
                        if is_compact and isinstance(out, dict):
                            out.pop("envelope", None)
                    except Exception as e:
                        st, out = "ERROR", {"error": str(e)}

                    ok = st not in _PLAYBOOK_FAIL
                    step_res = {"id": sid, "tool": tool, "status": st, "ok": ok, "output": out}
                    results.append(step_res)
                    step_outputs[sid] = out
                    prev_output = out

                    if ok:
                        GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, sid, out)
                        slot_cache_dict[sid] = out
                        if step.get("store_as"):
                            k_as = str(step["store_as"]).strip()
                            if k_as:
                                GLOBAL_SESSION_POOL.cache_set(eff_sid, eff_agent, k_as, out)
                                slot_cache_dict[k_as] = out

                    if not ok:
                        all_ok = False
                        if stop_on_error:
                            break
            finally:
                GLOBAL_SESSION_POOL.release(session_id=eff_sid, agent_id=eff_agent, clear_state=False)

            ret_mode = (return_only or "all").strip().lower()
            batch_name = (name or "ephemeral-batch").strip()

            base_res: dict[str, Any] = {
                "status": "OK" if all_ok else "PARTIAL",
                "batch": batch_name,
                "all_ok": all_ok,
                "steps_run": len(results),
            }

            failed_steps = [
                {
                    "id": r["id"],
                    "tool": r["tool"],
                    "status": r["status"],
                    "error": (
                        (r.get("output") or {}).get("error") or (r.get("output") or {}).get("message")
                        if isinstance(r.get("output"), dict)
                        else str(r.get("output"))
                    ),
                }
                for r in results
                if not r.get("ok")
            ]
            if failed_steps:
                base_res["failed_steps"] = failed_steps

            if ret_mode == "last":
                base_res["output"] = prev_output
            elif ret_mode == "summary":
                base_res["steps_summary"] = [
                    {"id": r["id"], "tool": r["tool"], "status": r["status"], "ok": r["ok"]} for r in results
                ]
            else:  # "all"
                base_res["results"] = results

            base_res["ipc_slot"] = {
                "slot_id": slot["slot_id"],
                "agent_id": eff_agent,
                "reuse_count": slot["reuse_count"],
                "scratch_dir": str(slot["scratch_dir"]),
                "socket_path": str(GLOBAL_SOCKET_MUX.socket_path),
                "cached_keys": GLOBAL_SESSION_POOL.cache_get(session_id=eff_sid, agent_id=eff_agent).get("keys", []),
            }

            if select_fields and isinstance(select_fields, list):
                full_json = json.dumps(base_res)
                full_bytes = len(full_json.encode("utf-8"))

                projected_res = project_fields(base_res, select_fields)
                if "status" not in projected_res:
                    projected_res["status"] = base_res.get("status", "OK")
                if failed_steps and "failed_steps" not in projected_res:
                    projected_res["failed_steps"] = failed_steps
                proj_json = json.dumps(projected_res)
                proj_bytes = len(proj_json.encode("utf-8"))

                saved_bytes = max(0, full_bytes - proj_bytes)
                savings_pct = round((saved_bytes / full_bytes * 100), 2) if full_bytes > 0 else 0.0

                projected_res["token_savings_estimate"] = {
                    "full_bytes": full_bytes,
                    "projected_bytes": proj_bytes,
                    "saved_bytes": saved_bytes,
                    "savings_pct": savings_pct,
                    "turns_saved": max(0, len(results) - 1),
                }
                final_res = projected_res
            else:
                full_json = json.dumps(base_res)
                full_bytes = len(full_json.encode("utf-8"))
                base_res["token_savings_estimate"] = {
                    "full_bytes": full_bytes,
                    "projected_bytes": full_bytes,
                    "saved_bytes": 0,
                    "savings_pct": 0.0,
                    "turns_saved": max(0, len(results) - 1),
                }
                final_res = base_res

            return attach_envelope(
                final_res,
                tracker,
                verbosity=verbosity,
                summary=f"Ephemeral batch '{batch_name}' finished ({len(results)} steps, all_ok={all_ok}).",
            )

        elif act == "prune":
            return attach_envelope(playbook_store.prune(names=names, apply=apply), tracker, verbosity=verbosity)

        else:
            return attach_envelope(
                {
                    "status": "INVALID_ACTION",
                    "error": f"Acción '{action}' no reconocida. Acciones válidas: 'run', 'batch', 'create', 'list', 'prune'.",
                    "valid_actions": ["run", "batch", "create", "list", "prune"],
                },
                tracker, verbosity=verbosity,
            )
    except Exception as e:
        return attach_envelope({"status": "ERROR", "error": str(e)}, tracker, verbosity=verbosity)


# ---------------------------------------------------------------------------
# Tool #16: default_primitives (Milestone ONT-34)
# ---------------------------------------------------------------------------
@mcp.tool(structured_output=False)
async def default_primitives(
    action: str = "list",
    name: str | None = None,
    params: dict[str, Any] | None = None,
    args: list[str] | str | None = None,
    verbosity: str = "detail",
    agent_id: str = "default",
) -> str:
    """
    [DEFAULT PRIMITIVES] Sondas de diagnóstico e introspección nativas del sistema ejecutadas directamente en RAM.
    Permite descubrir y ejecutar sondas integradas sin requerir el ciclo de compilación de plantillas:
      - 'socket-monitor': sockets TCP/UDP vía kernel /proc/net (params: state='LISTEN'|'ESTABLISHED'|'').
      - 'fd-rescuer': inspección de /proc/PID/fd para deadlocks o fugas (params: pid=0 para self, o pid>0).
      - 'disk-usage': uso de disco del sistema de archivos vía statvfs / shutil (params: path='/').
      - 'mem-stat': reporte de RAM total, libre y disponible leyendo /proc/meminfo.
      - 'landlock-guard': auditoría del estado y compatibilidad de Landlock LSM en el kernel activo.
    Acciones:
      - 'list': lista todas las sondas por defecto con sus descripciones y parámetros.
      - 'info' | 'get': metadata y contrato de una sonda específica (requiere name).
      - 'run' | 'exec': ejecuta la sonda indicada bajo el tier chmod activo (fail-soft en 4r-- con PERMISSION_DENIED).
    """
    tracker = RequestTelemetry("default_primitives", action)
    from engine.primitives import (
        DEFAULT_PRIMITIVES_REGISTRY,
        execute_primitive,
        get_primitive_info,
        list_primitives,
        normalize_primitive_name,
    )

    act = (action or "list").strip().lower()

    effective_params: dict[str, Any] = dict(params or {})
    if args is not None:
        if isinstance(args, dict):
            effective_params.update(args)
        elif isinstance(args, str) and args.strip().startswith("{"):
            try:
                parsed_args = json.loads(args)
                if isinstance(parsed_args, dict):
                    effective_params.update(parsed_args)
            except (json.JSONDecodeError, ValueError):
                pass
        elif isinstance(args, list) and args:
            norm_name = normalize_primitive_name(name or "")
            if norm_name == "disk-usage":
                effective_params.setdefault("path", args[0])
            elif norm_name == "fd-rescuer":
                try:
                    effective_params.setdefault("pid", int(args[0]))
                except (ValueError, TypeError):
                    pass
            elif norm_name == "socket-monitor":
                effective_params.setdefault("state", str(args[0]))

    if act == "list":
        prims = list_primitives()
        if verbosity in ("summary", "brief", "terse"):
            displayed_prims = [
                {
                    "name": p["name"],
                    "category": p.get("category"),
                    "description": p.get("description", ""),
                }
                for p in prims
            ]
        else:
            displayed_prims = prims
        payload = {
            "status": "OK",
            "count": len(prims),
            "primitives": displayed_prims,
        }
        return attach_envelope(
            payload,
            tracker,
            verbosity=verbosity,
            summary=f"Listed {len(prims)} default system diagnostic primitives.",
            next_action="Invoke default_primitives(action='run', name=...) to execute a diagnostic probe in RAM.",
        )

    elif act in ("info", "get"):
        if not name or not name.strip():
            payload = {
                "status": "ERROR",
                "error": "El parámetro 'name' es obligatorio para la acción 'info'.",
                "available_primitives": list(DEFAULT_PRIMITIVES_REGISTRY.keys()),
            }
            return attach_envelope(
                payload,
                tracker,
                verbosity=verbosity,
                summary="Missing required 'name' parameter for info action.",
            )
        info = get_primitive_info(name)
        if not info:
            payload = {
                "status": "NOT_FOUND",
                "name": name,
                "error": f"Sonda primitiva '{name}' no encontrada.",
                "available_primitives": list(DEFAULT_PRIMITIVES_REGISTRY.keys()),
            }
            return attach_envelope(
                payload,
                tracker,
                verbosity=verbosity,
                summary=f"Primitive '{name}' not found.",
            )
        payload = {
            "status": "OK",
            "primitive": info,
        }
        return attach_envelope(
            payload,
            tracker,
            verbosity=verbosity,
            summary=f"Retrieved metadata for primitive '{info['name']}'.",
            next_action=f"Execute via default_primitives(action='run', name='{info['name']}')",
        )

    elif act in ("run", "exec"):
        if not name or not name.strip():
            payload = {
                "status": "ERROR",
                "error": "El parámetro 'name' es obligatorio para la acción 'run'.",
                "available_primitives": list(DEFAULT_PRIMITIVES_REGISTRY.keys()),
            }
            return attach_envelope(
                payload,
                tracker,
                verbosity=verbosity,
                summary="Missing required 'name' parameter for run action.",
            )

        eff_tier_info = get_effective_chmod_tier()
        active_tier = eff_tier_info["tier"]

        result = execute_primitive(name, params=effective_params, tier=active_tier)
        status_val = result.get("status", "OK")

        if status_val == "PERMISSION_DENIED":
            return attach_envelope(
                result,
                tracker,
                verbosity=verbosity,
                summary=result.get("summary", f"Execution of primitive '{name}' disabled under {active_tier}."),
                next_action="Elevate chmod tier or inspect primitive metadata with action='info'.",
            )
        elif status_val != "OK":
            return attach_envelope(
                result,
                tracker,
                verbosity=verbosity,
                summary=f"Primitive '{name}' execution failed: {result.get('error', 'unknown error')}",
            )

        return attach_envelope(
            result,
            tracker,
            verbosity=verbosity,
            summary=f"Primitive '{name}' executed successfully in RAM (tier={active_tier}).",
            next_action="Review primitive diagnostics or proceed with next workflow step.",
        )

    else:
        payload = {
            "status": "INVALID_ACTION",
            "error": f"Acción '{action}' no reconocida. Acciones válidas: 'list', 'info', 'run'.",
            "valid_actions": ["list", "info", "run"],
        }
        return attach_envelope(
            payload,
            tracker,
            verbosity=verbosity,
            summary=f"Invalid action '{action}'.",
        )



# ---------------------------------------------------------------------------
# Tool #17: autoevol (Milestone ONT-40) - read-only thread graph
# ---------------------------------------------------------------------------
_AUTOEVOL_ACTIONS = ("graph", "gaps", "thread", "log", "diff", "spec", "verify", "fix_test", "heal", "evolve")
_AUTOEVOL_OPS = ("spec", "verify", "fix_test", "heal", "evolve")
_AUTOEVOL_TEST_TIMEOUT_S = 120
_AUTOEVOL_GATE_TIMEOUT_S = 100  # C4 (condicion 10): tope por lote del gate final
_GATE_COLLECT_RE = re.compile(r"^(\S+\.py): (\d+)\s*$", re.MULTILINE)
_AUTOEVOL_JOB_TIMEOUT_S = 900  # F8: tope del job async (pueue) para que un cuelgue no deje el ciclo PENDING indefinido
_PUEUE_TERMINAL_RE = re.compile(r'"(?:Done|Failed)"\s*:|"status"\s*:\s*"(?:Done|Failed)\b')
_AUTOEVOL_ENV_EXIT_CODES = (126, 127)  # no ejecutable / no encontrado: fallo de entorno, no de logica


_AUTOEVOL_WRONG_TREE_EXIT = 97  # centinela: `engine` no resuelve bajo el arbol auditado
# Centinela y pytest en el MISMO proceso bwrap (cwd=tree, mismo env). argv[1]=arbol auditado, argv[2:]=args de pytest.
_AUTOEVOL_SENTINEL = (
    "import sys, pathlib\n"
    "tree = pathlib.Path(sys.argv[1]).resolve()\n"
    "try:\n"
    "    import engine\n"
    "    ok = pathlib.Path(engine.__file__).resolve().is_relative_to(tree)\n"
    "except Exception:\n"
    "    ok = False\n"
    "if not ok:\n"
    f"    sys.exit({_AUTOEVOL_WRONG_TREE_EXIT})\n"
    "import pytest\n"
    "sys.exit(pytest.main(sys.argv[2:]))\n"
)


def _autoevol_canonical_venv() -> Path:
    return REPO_ROOT / ".venv"


def _autoevol_interpreter(tree: Path) -> dict[str, Any] | None:
    """Cadena de interprete: tree/.venv -> REPO_ROOT/.venv -> None (SANDBOX_UNAVAILABLE, fail-closed).

    `tree/.venv` de un worktree es codigo NO confiable: se ejecuta, pero solo dentro de bwrap (ro, sin red). El venv
    canonico se monta como ro-bind explicito junto con la raiz base del interprete (uv); NUNCA REPO_ROOT, que expondria
    `.git`, el `engine` canonico y secretos al codigo no confiable (condicion 3).
    """
    tree = tree.resolve()
    for cand in (tree / ".venv", _autoevol_canonical_venv()):
        try:
            venv = cand.resolve()
            py = venv / "bin" / "python"
            real = py.resolve()
            if not (py.exists() and real.is_file()):
                continue
            # raiz base del interprete resuelto (p. ej. ~/.local/share/uv/python): mismo criterio que sandbox_run.
            base_root = real.parents[2] if len(real.parents) >= 3 else real.parents[1]
        except (OSError, RuntimeError, IndexError):
            continue
        if not base_root.exists():
            continue
        ro = list(dict.fromkeys(str(p) for p in (tree, venv, base_root)))
        return {"python": str(py), "ro_paths": ro}
    return None


def _autoevol_pytest_cmd(tree: Path, tests: list[str], interp: dict[str, Any] | None = None) -> str:
    """Comando pytest con TODOS los tests dados (sin truncar). El troceo N<=20 lo decide `plan_tests` aguas arriba.

    Un solo proceso: el centinela WRONG_TREE precede a pytest. Sin interprete utilizable falla (LookupError).
    """
    interp = interp or _autoevol_interpreter(tree)
    if interp is None:
        raise LookupError("no interpreter for autoevol tests")
    argv = [interp["python"], "-c", _AUTOEVOL_SENTINEL, str(tree.resolve()), "-q", "-p", "no:cacheprovider", *tests]
    return shlex.join(argv)


def _pytest_counts(parsed: Any) -> dict[str, Any] | None:
    py = parsed if isinstance(parsed, dict) and parsed.get("tool") == "pytest" else None
    if py is None and isinstance(parsed, dict) and isinstance(parsed.get("pytest"), dict):
        py = parsed["pytest"]
    if not isinstance(py, dict):
        return None
    counts: dict[str, Any] = {
        "ran": int(py.get("total", 0)),
        "passed": int(py.get("passed", 0)),
        "failed": int(py.get("failed", 0)),
        "errors": int(py.get("errors", 0)),
    }
    failing = [str(n) for n in (py.get("failing_nodes") or [])][:50]
    if failing:
        counts["failing"] = failing  # E1: ids que fallan (base) para `discriminating`
    return counts


def _autoevol_test_runner(tree: Path, trusted: bool, timeout_s: int = _AUTOEVOL_TEST_TIMEOUT_S) -> Any:
    """run_tests inyectado: sandbox_run(parse='pytest', N<=20, timeout 120). bwrap caido: plano solo en el arbol propio."""

    def run(tests: list[str]) -> dict[str, Any]:
        interp = _autoevol_interpreter(tree)
        if interp is None:
            return {"available": False}
        cmd = _autoevol_pytest_cmd(tree, tests, interp)

        async def _call() -> str:
            return await sandbox_run(
                command=cmd,
                parse="pytest",
                working_dir=str(tree),
                ro_paths=interp["ro_paths"],
                env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(tree.resolve())},
                timeout=timeout_s,
                verbosity="detail",
            )

        res = json.loads(anyio.from_thread.run(_call))
        if res.get("status") == "ERROR" and "timed out" in str(res.get("error", "")).lower():
            return {"timeout": True, "failed": 0, "errors": 0}
        exit_code = res.get("exit_code")
        if exit_code == _AUTOEVOL_WRONG_TREE_EXIT:  # C4: antes de 126/127/sin-resumen (serian SANDBOX_UNAVAILABLE)
            return {"wrong_tree": True}
        counts = _pytest_counts(res.get("parsed"))
        if "bwrap:" in str(res.get("stderr", "")) + str(res.get("stderr_tail", "")):
            return _autoevol_plain_pytest(tree, cmd) if trusted else {"available": False}
        if res.get("status") in ("DEGRADED", "PERMISSION_DENIED", "PARAM_ERROR"):
            return {"available": False}
        # F4: 126/127 o salida != 0 sin resumen de pytest = fallo de infraestructura (SANDBOX_UNAVAILABLE, ambiental).
        if exit_code in _AUTOEVOL_ENV_EXIT_CODES or (counts is None and (res.get("status") == "EXEC_FAILED" or exit_code)):
            return {"available": False}
        # F7: exit 1 sin fallos ni errores (p. ej. `No module named pytest`) es entorno, no logica: un pytest real
        # con exit 1 siempre reporta al menos un fallo.
        if counts is not None and exit_code == 1 and counts["failed"] + counts["errors"] == 0:
            return {"available": False}
        if counts is not None:
            return {**counts, "exit_code": exit_code} if isinstance(exit_code, int) else counts
        return {"ran": 0, "failed": 0, "errors": 0, "no_summary": True}

    return run


def _autoevol_gate_collect(tree: Path) -> dict[str, Any]:
    """C4: tests por archivo del arbol exportado (`pytest --collect-only -qq`) dentro de bwrap, mismo interprete y centinela."""
    interp = _autoevol_interpreter(tree)
    if interp is None:
        return {"available": False}
    argv = [interp["python"], "-c", _AUTOEVOL_SENTINEL, str(tree.resolve()), "-qq", "--collect-only", "-p", "no:cacheprovider"]

    async def _call() -> str:
        return await sandbox_run(
            command=shlex.join(argv),
            working_dir=str(tree),
            ro_paths=interp["ro_paths"],
            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(tree.resolve())},
            timeout=_AUTOEVOL_GATE_TIMEOUT_S,
            verbosity="detail",
        )

    res = json.loads(anyio.from_thread.run(_call))
    if res.get("exit_code") not in (0, None) or res.get("status") in ("DEGRADED", "PERMISSION_DENIED", "PARAM_ERROR", "ERROR"):
        return {"available": False}
    files = {m.group(1): int(m.group(2)) for m in _GATE_COLLECT_RE.finditer(str(res.get("stdout", "")))}
    return {"files": files} if files else {"available": False}


def _autoevol_gate_kit() -> Any:
    """C4: ejecutores del gate final. `trusted=False` siempre: jamas cae a pytest plano fuera del sandbox."""
    from engine import threads_evolve as te

    def run_batch(tree: Path, files: list[str]) -> dict[str, Any]:
        return _autoevol_test_runner(tree, False, _AUTOEVOL_GATE_TIMEOUT_S)(files)  # type: ignore[no-any-return]

    def post_verify(rec: dict[str, Any]) -> dict[str, Any]:
        """C6: verify post-merge. Falla si el plano vivo cayo al LKG tras el swap (unico camino no cubierto por el gate)."""
        if _get_live_meta().get("serving_from") == "lkg":
            return {"ok": False, "reason": "serving_lkg"}
        return {"ok": True}

    return te.GateKit(collect=_autoevol_gate_collect, run_batch=run_batch, post_verify=post_verify)


def _autoevol_swap_fence() -> Path:
    """Misma ubicacion que `aep_front.swap_fence_path` (AEP_SWAP_FENCE_PATH o REPO_ROOT/.aep_swap_fence)."""
    override = os.environ.get("AEP_SWAP_FENCE_PATH", "").strip()
    return Path(override) if override else REPO_ROOT / ".aep_swap_fence"


def _autoevol_live_check() -> dict[str, Any]:
    """Condicion 8: antes del push, `stale == false` y fingerprint cargado == disco (regla ONT-39 #10)."""
    return {
        "stale": _is_front_stale() or bool(_get_live_meta().get("serving_from") == "lkg"),
        "loaded": LOADED_FINGERPRINT,
        "disk": code_fingerprint(REPO_ROOT),
    }


def _autoevol_tree_fingerprint(tree: Path | str) -> str | None:
    """D-EV-1: huella del arbol juzgado; misma logica que `GitCli.candidate_tree` (indice temporal, HEAD + add -A filtrado)."""
    from engine import threads_gitport as gp

    return gp.GitCli(Path(tree), REPO_ROOT, _autoevol_swap_fence()).candidate_tree()


def _autoevol_evolve(tree: Path, *, gap: str | None, cycle: str | None, apply: bool, octal: int) -> dict[str, Any]:
    """`autoevol(evolve)`: GitPort inyectado. `apply` jamas actua sobre el repo canonico (solo sobre un worktree `root`)."""
    from engine import threads_evolve as te
    from engine import threads_gitport as gp

    if apply and tree.resolve() == REPO_ROOT.resolve():
        return {"status": "ERROR", "error": "evolve apply exige root=<worktree del parche>, no el repo canonico."}
    git = gp.GitCli(tree, REPO_ROOT, _autoevol_swap_fence())
    return te.run_evolve(
        te.EvolveStore(),
        git,
        _autoevol_live_check,
        cycle=cycle,
        gap=gap,
        apply=bool(apply),
        octal=octal,
        label=capability_tier(),
        kit=_autoevol_gate_kit(),
    )


def _autoevol_plain_pytest(tree: Path, cmd: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(  # noqa: S603 - argv literal, cwd del arbol propio, sin shell
            shlex.split(cmd), cwd=tree, capture_output=True, text=True, timeout=_AUTOEVOL_TEST_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        return {"timeout": True, "failed": 0, "errors": 0, "unsandboxed": True}
    except OSError:
        return {"available": False}
    if proc.returncode == _AUTOEVOL_WRONG_TREE_EXIT:
        return {"wrong_tree": True}
    if proc.returncode in _AUTOEVOL_ENV_EXIT_CODES:
        return {"available": False}
    counts = _pytest_counts(_parse_pytest_output(proc.stdout + "\n" + proc.stderr))
    if counts is None:
        return {"available": False} if proc.returncode else {"ran": 0, "failed": 0, "errors": 0, "no_summary": True}
    if proc.returncode == 1 and counts["failed"] + counts["errors"] == 0:  # F7: entorno, no logica
        return {"available": False}
    return {**counts, "exit_code": proc.returncode, "unsandboxed": True}


def _autoevol_dispatcher(tree: Path, trusted: bool) -> Any:
    """dispatch_job inyectado: async_job_dispatch (Pueue) cuando el lote supera N=20 tests o 60 s.

    Pueue ejecuta en el host sin bwrap: solo se despacha para el arbol propio (`trusted`). Un `root` ajeno se rechaza
    fail-closed (SANDBOX_UNAVAILABLE) en lugar de ejecutar codigo no confiable fuera del sandbox (F3).
    """

    def dispatch(tests: list[str]) -> dict[str, Any]:
        if not trusted:
            return {"job": None, "available": False}
        interp = _autoevol_interpreter(tree)
        if interp is None:
            return {"job": None, "available": False}

        async def _call() -> str:
            return await async_job_dispatch(
                action="dispatch",
                command=f"timeout {_AUTOEVOL_JOB_TIMEOUT_S} {_autoevol_pytest_cmd(tree, tests, interp)}",
                label="autoevol-verify",
                working_dir=str(tree),
                verbosity="summary",
            )

        res = json.loads(anyio.from_thread.run(_call))
        if res.get("status") == "queued":
            return {"job": str(res.get("task_id"))}
        return {"job": None, "available": False}

    return dispatch


def _autoevol_job_poller(job: str) -> dict[str, Any]:
    """Estado de un job async: PENDING hasta que el log trae el resumen de pytest; luego conteos."""
    if not str(job).isdigit():
        return {"available": False}

    async def _call() -> str:
        return await async_job_dispatch(action="log", task_id=int(job), lines=200, verbosity="summary")

    raw = json.dumps(json.loads(anyio.from_thread.run(_call)))
    counts = _pytest_counts(_parse_pytest_output(raw.replace("\\n", "\n")))
    if counts is not None:
        return counts
    # F8: tarea terminada en pueue (Done/Failed) sin resumen de pytest = fallo de infraestructura, no PENDING eterno.
    return {"available": False} if _PUEUE_TERMINAL_RE.search(raw) else {"status": "PENDING"}


@mcp.tool(structured_output=False)
async def autoevol(
    action: str = "graph",
    node: str | None = None,
    a: str | None = None,
    b: str | None = None,
    probe: bool = False,
    root: str | None = None,
    persist: bool = True,
    limit: int = 10,
    select_fields: list[str] | None = None,
    verbosity: str = "summary",
    agent_id: str = "default",
    gap: str | None = None,
    base: str | None = None,
    cycle: str | None = None,
    job: str | None = None,
    apply: bool = False,
    restart: bool = False,
) -> str:
    """
    [AUTOEVOL / THREAD GRAPH] Vista de solo lectura de la estructura y las promesas de AEP (ONT-40).
    Extrae un grafo de hilos (tools, acciones, capacidades, funciones, estado, tests, claims, presupuestos)
    con raíz Merkle R sobre la condensación SCC, brechas por omisión, drift declarado-vs-observado y ranking.
      - 'graph': R, conteos, SCC y brechas abiertas (terse < 300 tokens). Persiste la generación solo con tier >= 6rw-.
      - 'gaps': brechas rankeadas por score (severidad x centralidad x alcance); `limit`, `select_fields`.
      - 'thread': inspecciona un hilo (`node`): aristas, alcance, centralidad, hash e impacted_tests.
      - 'log': historial de generaciones del grafo (solo lectura).
      - 'diff': diff semántico entre dos R (`a`, `b`; `b` omitido = árbol actual) con impacted_tests.
    `probe=True` (tier >= 5r-x): observaciones de runtime en un hijo aislado, fuera de R.
    `select_fields` proyecta claves de primer nivel (ej: ["gaps"], no ["id"]).
    ONT-41 (self-healing, N0-N3): el agente parchea, la tool juzga. No razona ni modifica el repo (salvo heal+apply).
      - 'spec' (tier >= 4r--): mini-SDD determinista de un gap (`gap`); terse <= 400 tokens.
      - 'verify' (tier >= 5r-x): veredicto ACCEPT/REJECT/PENDING del arbol parcheado contra la base (`base` =
        snapshot; si no, git HEAD; si no, BASE_UNAVAILABLE). Respeta la barrera de recarga del front: SERVING_LKG
        rechaza; RELOAD_PENDING/RELOAD_FAILED llevan `retry_after_s`. `job` sondea un lote async.
      - 'fix_test' (tier >= 5r-x): ciclo re-entrante gap->parche->test. Sin `cycle` abre uno (id del servidor) y
        devuelve awaiting:'patch'; con `cycle` evalua el parche; maximo 3 iteraciones; la 3.a fallida es EXHAUSTED
        con la sugerencia de heal (bloqueo de 10 min salvo `restart`). Nunca revierte por su cuenta.
      - 'heal' (lectura/dry-run tier >= 4r--; `apply=True` exige tier >= 6rw- y un workspace_snapshot previo):
        restaura desde el LKG solo los modulos rotos. Un EXHAUSTED con tier < 6rw- queda en el JSONL de eventos
        hasta una llamada con tier >= 6rw- que lo espeja al ledger.
    El tier se resuelve en cada llamada; los tests corren en sandbox (N<=20, timeout 120 s).
      - 'evolve' (ONT-42c): promueve un ciclo fix_test ACCEPTED (`cycle`, `root`=worktree): commit en `autoevol/<ciclo>`;
        ff-merge a dev y push SOLO con etiqueta FULL (7rwx); 6rw-/DIMINISHED = commit local; 5r-x/4r-- y `apply=False` =
        plan. Re-entrante; BLOCKED_GIT con motivo si no es posible. Nunca fuerza ni toca main.
    """
    from engine import threads as _threads

    tracker = RequestTelemetry("autoevol", action)
    act = (action or "graph").strip().lower()

    def _project(payload: dict[str, Any]) -> dict[str, Any]:
        if select_fields and isinstance(select_fields, list):
            return project_fields(payload, select_fields)
        return payload

    if act not in _AUTOEVOL_ACTIONS:
        planned = act in _threads._PLANNED_ACTIONS
        payload: dict[str, Any] = {
            "status": "INVALID_ACTION",
            "error": f"Acción '{action}' {'prevista fuera de ONT-40' if planned else 'no reconocida'}. Válidas: {', '.join(_AUTOEVOL_ACTIONS)}.",
            "valid_actions": list(_AUTOEVOL_ACTIONS),
        }
        return attach_envelope(payload, tracker, verbosity=verbosity, summary=f"Invalid action '{action}'.")

    tree = Path(root).expanduser() if root else REPO_ROOT
    if root and (CapabilityGuard.is_path_blacklisted(str(tree)) or not tree.is_dir()):
        payload = {"status": "ERROR", "error": f"root '{root}' no es un directorio legible permitido."}
        return attach_envelope(payload, tracker, verbosity=verbosity, summary="Invalid root.")
    tier_info = get_effective_chmod_tier()
    octal = int(tier_info["octal"])
    terse = (verbosity or "").lower() in ("terse", "brief")

    def _ops() -> str:
        from engine import threads_ops as ops
        from engine import threads_spec, threads_verify

        trusted = not root or tree.resolve() == REPO_ROOT.resolve()
        if act in ("verify", "fix_test") and octal < ops.MIN_VERIFY_OCTAL:
            payload = {"status": "PERMISSION_DENIED", "error": f"{act} requiere tier >= 5r-x.", "chmod_tier": tier_info["tier"]}
            return attach_envelope(payload, tracker, verbosity=verbosity, summary=f"{act}: permission denied.")
        snapshot: Path | None = None
        if base:
            snapshot = Path(base).expanduser()
            if CapabilityGuard.is_path_blacklisted(str(snapshot)) or not snapshot.is_dir():
                payload = {"status": "ERROR", "error": f"base '{base}' no es un directorio legible permitido."}
                return attach_envelope(payload, tracker, verbosity=verbosity, summary="Invalid base.")
        barrier = get_reload_barrier()
        serving_lkg = bool(_get_live_meta().get("serving_from") == "lkg")
        if act == "spec":
            if not gap:
                result: dict[str, Any] = {"status": "ERROR", "error": "El parametro 'gap' es obligatorio para 'spec'."}
            else:
                result = threads_spec.build_spec(_threads.analyze(tree), gap, terse=terse)
        elif act == "heal":
            result = ops.run_heal(
                tree,
                apply=bool(apply and trusted),
                octal=octal if trusted else min(octal, 5),
                snapshot_fn=_lkg_snapshot_fn,
                terse=terse,
            )
            if _is_front_stale():  # ONT-42a: heal only points to the (read-only) reconnect plan
                result["next_action"] = RECONNECT_POINTER
        elif act == "evolve":
            result = _autoevol_evolve(tree, gap=gap, cycle=cycle, apply=apply, octal=octal)
        else:
            runner = _autoevol_test_runner(tree, trusted)
            dispatcher = _autoevol_dispatcher(tree, trusted)
            common: dict[str, Any] = {
                "gap": gap,
                "snapshot": snapshot,
                "barrier": barrier,
                "serving_lkg": serving_lkg,
                "run_tests": runner,
                "dispatch_job": dispatcher,
                "poll_job": _autoevol_job_poller,
                "job": job,
                "trusted": trusted,
                "terse": terse,
                "apply": bool(apply and trusted),  # B8: con apply no se aplica el tope de seleccion
                "base_runner": lambda t: _autoevol_test_runner(t, trusted),  # E1: seleccionados contra la BASE
            }
            if act == "fix_test":
                common["tree_fingerprint"] = _autoevol_tree_fingerprint
            if act == "verify":
                result = ops.run_verify(tree, **common)
            else:
                result = ops.run_fix_test(threads_verify.CycleStore(), tree, cycle=cycle, restart=restart, **common)
        mirror = ops.mirror_events(octal, str(tier_info["tier"]), agent_id) if act != "spec" else None
        if mirror and mirror.get("mirrored"):
            result["mirrored"] = mirror["mirrored"]
        return attach_envelope(
            _project(result), tracker, verbosity=verbosity, summary=f"autoevol {act}: {result.get('status', 'OK')}."
        )

    def _run() -> str:
        if act in _AUTOEVOL_OPS:
            return _ops()
        analysis = _threads.analyze(tree)
        probes_status: str | None = None
        if probe:
            from engine.threads_probes import run_probes

            probes = run_probes(tree, tier_octal=octal)
            probes_status = str(probes.get("status"))
            analysis_used = _threads.with_probes(analysis, {**probes, "observations": probes.get("observations", [])})
        else:
            analysis_used = analysis
        if act == "graph":
            payload = _threads.graph_payload(analysis_used, terse=terse)
            persisted = {"persisted": False, "reason": "persist=False"}
            if persist:
                persisted = _threads.persist_generation(analysis_used, tier_octal=octal, agent_id=agent_id)
            payload["persisted"] = bool(persisted.get("persisted"))
            if probes_status is not None:
                payload["probe"] = probes_status
            payload["status"] = "OK"
            return attach_envelope(
                _project(payload),
                tracker,
                verbosity=verbosity,
                summary=f"Thread graph R={analysis_used.root_hash[:12]} gaps_open={len(analysis_used.gaps)}.",
                next_action="Use autoevol(action='gaps') to rank open gaps.",
            )
        if act == "gaps":
            payload = _threads.gaps_payload(analysis_used, limit=min(limit, 3) if terse else limit)
            payload["status"] = "OK"
            if probes_status is not None:
                payload["probe"] = probes_status
            return attach_envelope(
                _project(payload),
                tracker,
                verbosity=verbosity,
                summary=f"{payload['gaps_open']} open gaps.",
                next_action="Inspect a gap node with autoevol(action='thread', node=<id>).",
            )
        if act == "thread":
            payload = _threads.thread_payload(analysis_used, node or "", limit=limit)
            return attach_envelope(_project(payload), tracker, verbosity=verbosity, summary=f"Thread {node}: {payload['status']}.")
        if act == "log":
            payload = _threads.list_generations(limit=limit)
            payload["status"] = "OK"
            return attach_envelope(_project(payload), tracker, verbosity=verbosity, summary=f"{payload['total']} generations.")
        if act == "diff":
            payload = _threads.diff_generations(a or "", b, current=analysis_used, limit=limit) if a else {
                "status": "ERROR",
                "error": "El parámetro 'a' (R o id de generación) es obligatorio para 'diff'.",
            }
            return attach_envelope(_project(payload), tracker, verbosity=verbosity, summary=f"diff: {payload['status']}.")
        return attach_envelope({"status": "INVALID_ACTION"}, tracker, verbosity=verbosity)

    return await anyio.to_thread.run_sync(_run)


# ---------------------------------------------------------------------------
# IPC Socket Pool & Mux Registration (Spec OM-7)
# ---------------------------------------------------------------------------
async def _handle_ipc_batch(req: dict[str, Any]) -> dict[str, Any]:
    raw = await playbook_run(
        action="batch",
        name=req.get("name") or "ipc-batch",
        steps=req.get("steps"),
        params=req.get("params"),
        vars=req.get("vars"),
        stop_on_error=bool(req.get("stop_on_error", True)),
        return_only=req.get("return_only", "all"),
        select_fields=req.get("select_fields"),
        agent_id=req.get("agent_id", "default"),
    )
    return json.loads(raw) if isinstance(raw, str) else raw


GLOBAL_SOCKET_MUX.set_batch_handler(_handle_ipc_batch)
try:
    ensure_ipc_server_started()
except Exception as e:
    logger.warning("No se pudo iniciar el daemon de IPC socket pool al cargar server.py: %s", e)


# Synchronize dynamic tool counts in discover docstring & metadata (D-11)
_total_fastmcp_tools = len(mcp._tool_manager._tools)
if discover.__doc__:
    discover.__doc__ = discover.__doc__.replace(
        "para las herramientas FastMCP",
        f"para las {_total_fastmcp_tools} herramientas FastMCP",
    )
_disc_tool = mcp._tool_manager._tools.get("discover")
if _disc_tool and _disc_tool.description:
    _disc_tool.description = _disc_tool.description.replace(
        "para las herramientas FastMCP",
        f"para las {_total_fastmcp_tools} herramientas FastMCP",
    )


if __name__ == "__main__":
    mcp.run()
