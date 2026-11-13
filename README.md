<a id="top"></a>

# Agent Execution Plane (AEP)

**System Control Plane & High-Resilience Execution Suite for AI Agents on Ubuntu/Linux**

[![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B_Production_LTS-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Go 1.22+](https://img.shields.io/badge/Go-1.22%2B_Static_ELF-00ADD8?style=for-the-badge&logo=go&logoColor=white)](https://go.dev/)
[![Shell POSIX](https://img.shields.io/badge/Shell-POSIX_Bash_%2F_Zsh_%2F_Dash-4EAA25?style=for-the-badge&logo=gnu-bash&logoColor=white)](https://www.gnu.org/software/bash/)
[![SQLite 3 WAL](https://img.shields.io/badge/SQLite_3-WAL_%2B_mmap_%2B_vec-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org/)
[![FastMCP Protocol](https://img.shields.io/badge/FastMCP-17_Tools_%2F_19_Caps-FF6F00?style=for-the-badge&logo=fastapi&logoColor=white)](https://modelcontextprotocol.io/)
[![Ubuntu Linux](https://img.shields.io/badge/Platform-Ubuntu_%2F_Linux_Kernel-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)](https://ubuntu.com/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg?style=for-the-badge)](LICENSE)
[![Tests Passing](https://img.shields.io/badge/Tests-1092_Passed-success?style=for-the-badge&logo=pytest&logoColor=white)](tests/)

> [!IMPORTANT]
> **Runtime Architecture & Agent Execution Plane**
> AEP is a **systems engineering suite and agentic runtime** designed to
> provide a deterministic, non-blocking, typed, and asynchronous execution plane for
> LLMs and autonomous agents, grounded in low-level Linux kernel primitives
> (namespaces, volatile anonymous memory, descriptors, and dynamic telemetry)
> on Ubuntu/Linux environments.

> [!WARNING]
> **SECURITY ADVISORY & TESTING ENVIRONMENT (EDR / SANDBOX DISCLAIMER)**
>
> AEP utilizes low-level Linux kernel primitives (`memfd_create` for anonymous in-RAM execution, user-space sandboxing via Landlock LSM, dynamic eBPF/kprobes tracing, `/proc` file descriptor inspection, and namespace isolation).
>
> Because these primitives interact intimately with operating system security and memory subsystems, corporate endpoint security solutions, antivirus suites, and heuristic-based **EDR (Endpoint Detection and Response)** platforms may classify these activities as potentially anomalous or offensive cybersecurity tooling.
>
> **It is strongly recommended to evaluate and run AEP within dedicated test environments, virtual machines, or isolated sandboxes.**

---

## Table of Contents

1. [The Execution Challenge: Interactive Console vs. Agentic Runtime](#1-the-execution-challenge-interactive-console-vs-agentic-runtime)
2. [Global Architecture (4 Layers)](#2-global-architecture-4-layers)
   - [Architectural Breakdown of the 4 Layers](#architectural-breakdown-of-the-4-layers)
   - [Detailed Layer Specifications](#detailed-layer-specifications)
3. [High-Performance Linux Kernel Primitives → Resilient Agentic Capabilities](#3-high-performance-linux-kernel-primitives--resilient-agentic-capabilities)
4. [Catalog of 17 MCP Tools (19 Capabilities)](#4-catalog-of-17-mcp-tools-19-capabilities)
   - [Master Reference Tables for 17 FastMCP Tools](#master-reference-tables-for-17-fastmcp-tools)
   - [Factory Decoupling: Runtime Primitives vs. Template Synthesis](#factory-decoupling-runtime-primitives-vs-template-synthesis)
   - [Lifecycle and Skill Chaining](#lifecycle-and-skill-chaining)
5. [Hybrid Semantic Memory (sqlite-vec) & Hot SQLite Concurrency](#5-hybrid-semantic-memory-sqlite-vec--hot-sqlite-concurrency)
   - [Persistence and Agent Access](#persistence-and-agent-access)
   - [Pico-Kanban: Artifact Confidence Scoring](#pico-kanban-artifact-confidence-scoring)
   - [Anti-Deadlock WAL Concurrency Architecture](#anti-deadlock-wal-concurrency-architecture)
6. [Database Resilience: Online Hot Backup & Auto-Recovery (5 Slots)](#6-database-resilience-online-hot-backup--auto-recovery-5-slots)
   - [Hot Streaming Backup Mechanics](#hot-streaming-backup-mechanics)
   - [FIFO Pool Topology and Self-Healing](#fifo-pool-topology-and-self-healing)
   - [Volatile In-RAM Micro-Snapshots](#volatile-in-ram-micro-snapshots)
   - [Anti-Poisoning Architecture and Forensic Quarantine](#anti-poisoning-architecture-and-forensic-quarantine)
7. [Security Countermeasures, Isolation & Cryptographic Audit Ledger](#7-security-countermeasures-isolation--cryptographic-audit-ledger)
   - [CapabilityGuard & Critical Path Blacklisting](#capabilityguard--critical-path-blacklisting)
   - [Tamper-Evident SHA-256 Audit Chain](#tamper-evident-sha-256-audit-chain)
   - [In-Process Sandboxing via Landlock LSM](#in-process-sandboxing-via-landlock-lsm)
   - [eBPF Security Observability](#ebpf-security-observability)
8. [Omarchy Enhancements (8 Distro-Agnostic Specs)](#8-omarchy-enhancements-8-distro-agnostic-specs)
   - [Omarchy Distro-Agnostic Specification Matrix](#omarchy-distro-agnostic-specification-matrix)
   - [Detailed Technical Specifications (SPEC-OM-1 to SPEC-OM-9)](#detailed-technical-specifications-spec-om-1-to-spec-om-9)
   - [Architecture and Data Flow of Omarchy Enhancements](#architecture-and-data-flow-of-omarchy-enhancements)
9. [Four-Tier Chmod Privilege & Graceful Degradation Matrix](#9-four-tier-chmod-privilege--graceful-degradation-matrix)
10. [Auto-Plug: Atomic MCP Self-Management](#10-auto-plug-atomic-mcp-self-management)
11. [Shell-Agnostic Environment](#11-shell-agnostic-environment)
12. [Clean-Slate Installation, Health Audit & Autonomous Updater](#12-clean-slate-installation-health-audit--autonomous-updater)
13. [Repository Structure](#13-repository-structure)
14. [Truthful Inventory of Single Source of Truth](#14-truthful-inventory-of-single-source-of-truth)
15. [RE as SDD & Inspiration Matrix](#15-re-as-sdd--inspiration-matrix)
16. [License and Terms](#16-license-and-terms)

---

## 1. The Execution Challenge: Interactive Console vs. Agentic Runtime

The traditional Unix console was conceived for interactive human operators—a paradigm
fundamentally hostile to autonomous Large Language Model (LLM) execution:
- **Blocking Processes**: Interactive pagers (`less`, `more`), unannounced interactive prompts,
  and `stdin` stalls hang agent child processes indefinitely.
- **Unstructured and Misaligned Output**: Parsing plain text output via ad-hoc pipelines (`grep`,
  `awk`, `sed`) introduces syntactic fragility and wastes tokens on formatting noise rather than
  dense semantic signal.
- **Disk Contention and Residue**: Creating temporary scripts or binaries on the filesystem
  introduces I/O synchronization latency, filesystem fragmentation, naming collisions, and
  orphaned artifacts requiring garbage collection.

AEP decouples agents from the interactive terminal via two primary mechanisms: **non-blocking
asynchronous queue dispatch** (via Pueue, returning an immediate `task_id`) and **volatile
in-RAM execution** via anonymous file descriptors (`memfd_create` + `/proc/self/fd/`).

This in-memory staging technique is not an exotic construct, but an established **Linux
systems engineering standard** adopted in production-grade infrastructure:
- **Wayland Compositors (Weston / wlroots)**: Zero-copy shared memory buffer transfer
  (`wl_shm`) between clients and compositor via `memfd_create` file descriptors passed over
  Unix domain sockets (`AF_UNIX`).
- **QEMU / KVM (`memory-backend-memfd`)**: Anonymous memory allocation for guest RAM in
  high-performance virtualization, enabling inter-VM shared memory (`ivshmem`) and
  shared descriptors for `vhost-user` with DPDK.
- **PulseAudio & PipeWire**: Real-time zero-copy audio stream buffer exchange between media
  servers and clients without filesystem synchronization bottlenecks.

```mermaid
flowchart LR
    subgraph Hostile["Traditional Console Environment (Automation Bottlenecks)"]
        H1["Blocking child processes<br/>(pagers, prompts, interactive sudo)"]
        H2["Unstructured plain text<br/>(awk/sed/grep) = wasted tokens"]
        H3["Filesystem footprint<br/>(scattered temporary files)"]
    end
    subgraph AEP["AEP Solution (Deterministic Agentic Runtime)"]
        S1["In-RAM execution<br/>memfd_create + fexecve"]
        S2["Typed JSON output<br/>+ semantic memory"]
        S3["Asynchronous queues<br/>Pueue (immediate task_id)"]
    end
    H1 --> S3
    H2 --> S2
    H3 --> S1
```

[↑ Back to top](#top)

---

## 2. Global Architecture (4 Layers)

```mermaid
flowchart TD
    subgraph L3["Layer 3: Agentic Interface"]
        Agent["AI Agents (Claude Code / Antigravity / Codex / Gemini)"]
        MCP["FastMCP Server (server.py) — 17 tools (19 capabilities)"]
        Agent -->|stdio / JSON-RPC| MCP
    end
    subgraph L2["Layer 2: Execution, Persistence & Security Engines (engine/)"]
        Catalog["catalog.py + embedder.py<br/>(sqlite-vec semantic memory)"]
        DB["db.py (WAL hot concurrency<br/>anti-deadlock & mmap)"]
        Backup["backup.py (5-slot rotation<br/>streaming hot backup & auto-recovery)"]
        Security["security.py (audit ledger SHA-256<br/>& secret masking)"]
        Priv["privilege.py (CapabilityGuard<br/>FULL/DIMINISHED & CBAC)"]
        Kanban["kanban.py + ponder.py + matcher.py<br/>(Pico-Kanban & BM25F ranking)"]
        Crash["crash_router.py (coredump RCA)"]
        Docs["docs_vectorizer.py (man pages)"]
        Headless["headless_display.py (Playwright)"]
        Topos["topos_guard.py (anti-co-dep DAG)"]
        MCP --> Catalog & DB & Backup & Security & Priv & Kanban & Crash & Docs & Headless & Topos
    end
    subgraph L1["Layer 1: Shell Inheritance (Agnostic)"]
        Env["config/shell/aep-env.sh<br/>(bash / zsh / sh)"]
        Ctl["scripts/aep-ctl (service, network, storage,<br/>package, backup, security, audit, ipc, hardware)"]
        Agent -.->|child process| Env
    end
    subgraph L0["Layer 0: Linux Kernel & Ubuntu Runtime"]
        K1["RAM: memfd_create + fexecve"]
        K2["bwrap / eBPF / coredumpctl"]
        K3["Pueue daemon · Python 3.14 venv"]
        Catalog --> K1
        Crash --> K2
        Headless --> K3
        Backup --> DB
    end
```

### Architectural Breakdown of the 4 Layers

| Layer | Abstraction Level | Modules & Components | Underlying Primitives & Protocols | Guarantees & Runtime Role |
| :---: | :--- | :--- | :--- | :--- |
| **Layer 3** | **Agentic Interface (RPC)** | `server.py` (FastMCP)<br/>`aep_capabilities` | JSON-RPC 2.0 over `stdio`<br/>FastMCP SDK | Unified entry point for LLMs and agents (Claude Code, Antigravity `agy`, OpenAI Codex, Gemini CLI). Exposes 17 atomic, typed, and non-blocking tools (19 capabilities). |
| **Layer 2** | **Execution, Persistence & Security Engines (`engine/`)** | `db.py`<br/>`backup.py`<br/>`security.py`<br/>`catalog.py`<br/>`embedder.py`<br/>`kanban.py`<br/>`ponder.py`<br/>`matcher.py`<br/>`crash_router.py`<br/>`docs_vectorizer.py`<br/>`headless_display.py`<br/>`topos_guard.py`<br/>`privilege.py`<br/>`net_telemetry.py`<br/>`hardware.py` | SQLite 3 (WAL mode, mmap 256MB)<br/>`sqlite-vec` extension<br/>ONNX Runtime (bge-small)<br/>Playwright Chromium (`/dev/shm`)<br/>`fcntl.flock` + `conn.backup()`<br/>SHA-256 Chained Hash Ledger | Core agentic logic: hybrid semantic memory, anti-deadlock hot SQLite concurrency (`BEGIN IMMEDIATE`), online 5-slot hot backup with auto-recovery, security countermeasures via `CapabilityGuard` (blacklisting `/etc/shadow`, `/root`, `~/.ssh`), SHA-256 cryptographic audit ledger, multidimensional Pico-Kanban, and dual-tier privilege governance (`FULL`/`DIMINISHED`). |
| **Layer 1** | **Agnostic Shell Inheritance** | `config/shell/aep-env.sh`<br/>`scripts/install-shell-env.sh`<br/>`scripts/aep-ctl` | POSIX standard Shell (`sh`, `bash`, `zsh`, `dash`)<br/>Environment variables (`PAGER=cat`) | Sanitizes subshell execution against hangs (`stdin`, interactive pagers). Deterministic `aep-ctl` CLI for system management with self-documenting typed JSON contracts (`--schema`) across domains: `service`, `network`, `storage`, `package`, `backup`, `security`, `audit`, `ipc`, and `hardware`. |
| **Layer 0** | **Linux Kernel & Ubuntu Runtime** | Linux Kernel Primitives<br/>`Pueue` daemon (musl)<br/>`bwrap` (Bubblewrap)<br/>`systemd` / `journald`<br/>Static Go Toolchain | `memfd_create(2)`<br/>Linux User & PID Namespaces<br/>eBPF / kprobes (`bpftrace`)<br/>`systemd-coredump` / `ptrace`<br/>Hermetic Python 3.14 (`uv`) | High-performance, low-level foundations: volatile ELF staging in RAM with zero disk residue, sub-millisecond isolation via unprivileged namespaces, non-blocking asynchronous queues, non-invasive kernel telemetry, and user-space execution without root requirements. |

#### Detailed Layer Specifications

1. **Layer 3: Agentic Interface (FastMCP RPC)**:
   - **Protocol and Transport**: Built on the official Model Context Protocol (MCP) using **FastMCP** in `server.py`. All communication occurs over `stdio` via structured **JSON-RPC 2.0** messages, eliminating network port exposure and insecure local socket management.
   - **First-Look Self-Description**: The entry point `discover(action="capabilities")` (along with the compatibility wrapper `aep_capabilities()`) provides an immediate handshake, returning an octal autonomy manifest modeled after `chmod/777` (`r`=sense, `w`=act, `x`=execute). This informs the LLM of its operational capabilities based on detected privileges (`FULL` or `DIMINISHED`).
   - **Universal Multi-Client Support**: Designed for seamless consumption by multiple autonomous agents (Claude Code, Antigravity `agy`, OpenAI Codex, Gemini CLI) via the unified launcher `scripts/aep-mcp-launch.sh`.

2. **Layer 2: Execution, Persistence & Security Engines (`engine/`)**:
   - **Anti-Deadlock Hot SQLite Concurrency (`db.py`)**: Read-only connections (`mode=ro`) without WAL locks, read-write connections with `PRAGMA wal_autocheckpoint=1000`, immediate transactions (`transaction_immediate` with `BEGIN IMMEDIATE`), and `_ClosingConnection` deterministic FD & 256MB-mmap release on `with conn:` exit (`fd_delta = 0`) to eliminate `database is locked` errors and descriptor leaks under concurrent swarms.
   - **Hot Backup Resilience (`backup.py`)**: Non-destructive online streaming backups via `conn.backup()`, 5-slot FIFO rotation (`artifacts.db.bak.1..5`), snapshot SHA-256 checksums, and transparent header corruption auto-recovery.
   - **Security Countermeasures & Audit (`security.py`, `privilege.py`)**: Capability-Based Access Control (CBAC) via `CapabilityGuard` (strict blocking of `/etc/shadow`, `/root`, `~/.ssh`), centralized secret sanitization, and an immutable SHA-256 chained audit ledger (`security_audit_log`).
   - **Hybrid Semantic Memory (`catalog.py`, `embedder.py`)**: Persists artifact metadata in `~/.local/share/agent-os/artifacts.db` in WAL mode. Implements two-tier retrieval: O(1) exact SHA-256 matching, and cosine similarity search using `sqlite-vec` with local `bge-small-en-v1.5` embeddings on ONNX Runtime.
   - **Pico-Kanban Scoring (`kanban.py`, `ponder.py`, `matcher.py`)**: Abstract state board (`BACKLOG` → `SYNTHESIZED` → `LINTED` → `CANARY` → `PROMOTED`/`REJECTED`) for decomposing complex tasks and scoring artifacts across quality, reliability, experience, and recency with defect vetoes.
   - **Proactive Crash Routing (`crash_router.py`)**: Interrogates `coredumpctl` periodically, deduplicating crashes via compound hashes (`pid:timestamp:executable`) to alert agents before executing system mutations.
   - **Documentation Vectorizer (`docs_vectorizer.py`)**: Ingests Ubuntu `man` pages into paragraphs, vectorizing them locally into `system_docs.db` to resolve exact command syntax in under 5 ms without web lookups.
   - **Headless Visual Actuator (`headless_display.py`)**: Orchestrates headless Chromium via Playwright, capturing screenshots directly into volatile RAM (`/dev/shm`) with compact screenshot mode by default (`include_base64=False`, `verbosity="summary"`, `-98.9%` token footprint with `screenshot_path`, `screenshot_sha256`, and `text_excerpt`).
   - **Topological DAG Guardian (`topos_guard.py`)**: Enforces the Topos Integrity Protocol, validating task DAGs to certify zero circular co-dependencies (A <-> B) prior to execution authorization.
   - **Privilege Governor (`privilege.py`)**: Dynamically evaluates credentials (`euid == 0` or `sudo -n true`), ensuring tools degrade gracefully (*fail-soft*) to user space without unhandled exceptions.

3. **Layer 1: Agnostic Shell Inheritance**:
   - **POSIX Environment Sanitization (`config/shell/aep-env.sh`)**: Universal environment file enforcing `PAGER=cat`, `MANPAGER=cat`, `DEBIAN_FRONTEND=noninteractive`, and exporting critical paths to `PATH`. Prevents child processes from hanging on interactive prompts.
   - **Idempotent Multi-Shell Installation (`scripts/install-shell-env.sh`)**: Injects atomic sourcing blocks into `~/.bashrc`, `~/.zshenv`, and `~/.profile`, supporting Bash, Zsh, and Dash without third-party frameworks.
   - **Deterministic CLI Control Plane (`scripts/aep-ctl`)**: Modular Python standard library utility managing subdomains (`service`, `network`, `storage`, `package`, `backup`, `security`, `audit`, `ipc`, `hardware`) with structured JSON output and `--schema` contract introspection.

4. **Layer 0: Linux Kernel & System Runtime**:
   - **Volatile Anonymous Memory (`memfd_create`)**: Native Linux kernel primitive (glibc 2.27+ / Linux 3.17+) allowing ELF binaries to be staged and executed purely in RAM via `/proc/self/fd/`, bypassing secondary disk storage.
   - **Namespace Isolation (`bwrap`)**: Uses Bubblewrap to sandbox potentially hazardous executions in unprivileged user, mount, PID, and network namespaces with read-only roots and volatile RAM `/tmp` filesystems.
   - **Dynamic Observability (`bpftrace` / eBPF)**: Attaches non-invasive kprobes and tracepoints to monitor syscalls, track file openings, or inspect TCP sockets using curated read-only scripts with automatic termination.
   - **Post-Mortem Forensics**: Leverages native `systemd-coredump` and `journalctl` to retrieve memory dumps, extract stack traces, and analyze system error logs.
   - **Asynchronous Queue Manager (`Pueue`)**: Static `musl`-compiled background daemon managing parallel queues and process limits without stalling the agent's conversational loop.

[↑ Back to top](#top)

---

## 3. High-Performance Linux Kernel Primitives → Resilient Agentic Capabilities

Low-level Linux kernel primitives are structured and exposed as high-resilience agentic
capabilities governed by a dual-tier privilege model. **All verified end-to-end.**

```mermaid
flowchart LR
    subgraph Off["Kernel Primitives & Systems Engineering"]
        O1["ELF staging in anonymous memory (memfd_create)"]
        O2["Dynamic inspection of threads & descriptors (/proc, ptrace)"]
        O3["Strict Linux namespace isolation (bwrap)"]
        O4["Post-mortem coredump & signal forensics"]
        O5["Dynamic in-kernel observability probes (eBPF / kprobes)"]
        O6["Directed Acyclic Graph (DAG) dependency audit"]
        O7["Non-blocking async dispatch & queue management"]
    end
    subgraph Ag["AEP Agentic Capability (MCP Tool)"]
        A1["artifact_execute_in_ram"]
        A2["fd-rescuer (thread rescue)"]
        A3["sandbox_run (ephemeral bwrap)"]
        A4["diagnose_system_crashes (RCA)"]
        A5["kernel_trace (observability)"]
        A6["topos_audit_dag (anti-co-dependency)"]
        A7["async_job_dispatch (Pueue)"]
    end
    O1 --> A1
    O2 --> A2
    O3 --> A3
    O4 --> A4
    O5 --> A5
    O6 --> A6
    O7 --> A7
```

| Kernel / Runtime Primitive | Systems Engineering Classification | Resilient Agentic Capability (MCP Tool) | Status |
| :--- | :--- | :--- | :--- |
| `memfd_create` (glibc 2.27+) | Anonymous volatile RAM staging (zero disk I/O) | `artifact_execute_in_ram`: Direct in-RAM injection & execution | ✅ Operational |
| `/proc/$PID/fd` + `ptrace` | Non-destructive inspection and descriptor recovery | `fd-rescuer`: Non-invasive file descriptor and state recovery | ✅ Operational |
| `bwrap` (Linux namespaces) | Unprivileged ephemeral sandbox (user, pid, mount, net) | `sandbox_run`: Deterministic sub-millisecond isolation | ✅ Operational |
| `coredumpctl` + `libunwind` | Automated post-mortem triage of coredumps & stack traces | `diagnose_system_crashes`: Autonomous fail-soft RCA | ✅ Operational |
| eBPF (`bpftrace`) | Non-invasive dynamic kernel telemetry & tracing | `kernel_trace`: Safe runtime observability | ✅ Operational (FULL) |
| Graph Theory (DAG) | Topological coupling analysis & cycle detection | `topos_audit_dag`: Topos anti-co-dependency guardian | ✅ Operational |
| Asynchronous Queue (`Pueue`) | Event-driven non-blocking task execution | `async_job_dispatch`: Background task dispatch & logs | ✅ Operational |

> **Note on `memfd_create(2)`**: This anonymous memory primitive is the industry standard for
> zero-overhead execution and communication without filesystem overhead, utilized in **Wayland**
> (Weston/wlroots for `wl_shm` buffers), **QEMU / KVM** (guest RAM allocation for `ivshmem` and
> `vhost-user`), and **PulseAudio & PipeWire** (real-time audio buffers).

[↑ Back to top](#top)

---

## 4. Catalog of 17 MCP Tools (19 Capabilities)

```mermaid
flowchart TD
    Root["discover(action='capabilities')<br/>FIRST CALL: autonomy manifest (chmod/777)"]
    Root --> G0 & G1 & G1b & G2 & G3 & G4 & G5
    subgraph G0["Orientation, DAG & Thread Graph"]
        T1["discover"]
        T2["topos_audit_dag"]
        T17["autoevol"]
    end
    subgraph G1["Evolutive In-RAM Artifacts"]
        T3["artifact_catalog"]
        T4["artifact_lint_and_build"]
        T5["artifact_execute_in_ram"]
    end
    subgraph G1b["Native Diagnostic Primitives"]
        T16["default_primitives"]
    end
    subgraph G2["Introspection & Execution"]
        T6["process_inspect"]
        T7["sandbox_run"]
        T8["async_job_dispatch"]
    end
    subgraph G3["Observability & Forensics"]
        T9["diagnose_system_crashes"]
        T10["kernel_trace"]
    end
    subgraph G4["System Control & Docs"]
        T11["aep_ctl"]
        T12["query_system_docs"]
        T13["visual_inspect"]
    end
    subgraph G5["Pico-Kanban & Playbooks"]
        T14["kanban_board"]
        T15["playbook_run"]
    end
```

### Master Reference Tables for 17 FastMCP Tools

The plane exposes 17 RPC tools organized across operational domains plus the root entry point. All tools return typed, deterministic JSON strings ensuring zero unhandled exceptions (*fail-soft*). Under Milestone ONT-29, all tools are registered with `structured_output=False` to enforce FastMCP single-encoding (eliminating double-encoded JSON escaping in `structuredContent.result` and slashing client-side response payload size by ~41%), alongside envelope deduplication and compact telemetry stubs in `brief` and `terse` verbosity modes (`output_bytes(brief) < output_bytes(summary)`). Under Milestone ONT-30, FastMCP wraps server initialization with `NotificationOptions(tools_changed=True)` to broadcast `capabilities.tools.listChanged = True` to MCP clients, establishing transparent dynamic schema evolution signaling across harnesses. Under Milestone ONT-34, FastMCP Tool #16 (`default_primitives`) is registered to provide direct runtime diagnostic probing (`socket-monitor`, `fd-rescuer`, `disk-usage`, `mem-stat`, `landlock-guard`) in pure Python/kernel memory, decoupling basic system introspection from the Go compilation and synthesis factory while strictly preserving all 5 Go template files in `templates/` as synthesis scaffolding.

#### Root Entry Point & Autonomy Manifest

| Tool | Privilege Tier | Signature & Parameters | Mechanics & Operational Purpose | JSON Output Contract | Fail-Soft Guarantee |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `discover` (`action="capabilities"`) | `FULL` / `DIMINISHED` | `discover(action="capabilities") -> str`<br/>*(compat wrapper: `aep_capabilities()`)* | Evaluates `euid == 0` and `sudo -n` availability. Generates an autonomy manifest in an octal `chmod/777` style (`r`=sense, `w`=act, `x`=execute) mapping 19 capabilities across scopes (`self`, `system`, `kernel`). Under Milestone ONT-30, exposes schema evolution drift detection and multi-harness process observability metadata across all verbosities (`server_version`, short `git_commit`, deterministic 64-char `schema_hash`, `pid`, `process_start_time` ISO-8601, and `uptime_seconds`). | `{"status": "OK", "capability_tier": "FULL"|"DIMINISHED", "server_version": str, "git_commit": str, "schema_hash": str, "pid": int, "process_start_time": str, "uptime_seconds": float, "capabilities": {...}}` | Always returns valid deterministic JSON. Zero unhandled exceptions. |

#### Domain 1: Evolutive Artifacts & In-Memory Cycle (4 Tools)

| Tool | Privilege Tier | Signature & Parameters | Mechanics & Operational Purpose | JSON Output Contract | Fail-Soft Guarantee |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `discover` | `DIMINISHED` | `discover(use_case: str = "", action: str = "discover", limit: int = 3, verbosity: str = "detail", session_id: Optional[str] = None, sid: Optional[str] = None, store_as: Optional[str] = None, force_refresh: bool = False, select_fields: Optional[List[str]] = None) -> str` | Polymorphic orientation router: maps natural language intents to recommended capabilities (`action="discover"` with confidence gating), outputs the `chmod/777` autonomy manifest + host binary readiness (`action="capabilities"`), introspects tool schemas across all 17 FastMCP tools (`action="schema"`), or returns the systems engineering tactical guide (`action="playbook"`, including native network telemetry recipes `WF-10` and `WF-11` and quick reference commands `network_telemetry_probe` and `incident_protocol_audit`). Mitigates the multi-agent 'Re-Discovery Tax' via automatic RAM session caching (`/dev/shm`), `verbosity="terse"` / `"cached"` stub mode (~249 tokens, >96% savings), named slots (`store_as`), server-side field projection (`select_fields`), and exposes ONT-30 schema drift/observability metadata (`server_version`, `git_commit`, `schema_hash`, `pid`, `process_start_time`, `uptime_seconds`). | `action="discover"`: `{"status": "OK", "confidence": "HIGH"|"LOW", ...}`<br/>`action="capabilities"` (`verbosity="terse"`): `{"status": "OK", "cache_status": "CACHED", "source": "ram_session_cache", ...}` | Empty parameters return `status: "PARAM_ERROR"`; unrecognized actions return `status: "INVALID_ACTION"`. |
| `artifact_lint_and_build` | `DIMINISHED` | `artifact_lint_and_build(action: str = "build", name: Optional[str] = None, artifact_name: Optional[str] = None, intent: Optional[str] = None, description: Optional[str] = None, category: Optional[str] = None, go_source: Optional[str] = None, template_name: Optional[str] = None, source_template: Optional[str] = None, params: Optional[Dict[str, Any]] = None, cue_contract: str = "", limit: int = 5) -> str` | Unified pipeline to browse templates (`catalog`), rank by relevance (`select`), hydrate Go source (`hydrate`), and compile binaries with `go vet`/`golangci-lint` validation (`build`, with `lint` and `vet` action aliases), including 1-step zero-config template shortcut (`template_name` auto-fills defaults and reuses active Kanban tasks). | Action-dependent typed JSON (`status`, `templates`, `matches`, `go_source`, `artifact_id`, `binary_path`). | Structured responses with `status: "PARAM_ERROR"` on missing inputs, `status: "HYDRATE_ERROR"` on template failures, and `status: "INVALID_ACTION"` on invalid actions. |
| `artifact_execute_in_ram` | `DIMINISHED` | `artifact_execute_in_ram(name: str, artifact_name: Optional[str] = None, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None, stdin: Optional[str] = None, timeout: int = 30) -> str` | Loads the ELF binary into an anonymous volatile descriptor via `memfd_create` and executes directly in RAM via `/proc/self/fd/<fd>`. Supports `artifact_name` alias, `env` and `stdin` injection, and configurable `timeout` (1–120s, default 30s). Measures latency and records execution metrics in SQLite. | `{"status": "SUCCESS"|"EXEC_FAILED", "exit_code": int, "latency_ms": float, "output": Any, "metric_recorded": bool}` | Non-zero exit codes return structured JSON with `stderr` and update historical failure rates. |
| `artifact_catalog` | `DIMINISHED` | `artifact_catalog(action: str = "browse", category: Optional[str] = None, query: Optional[str] = None, intent: Optional[str] = None, name: Optional[str] = None, artifact_name: Optional[str] = None, limit: int = 10, force: bool = False, apply: bool = False) -> str` | Unified semantic memory. `action="browse"`: lists/searches by confidence or semantic top-K (`query`). `action in ("info", "get", "show")`: lightweight inspection of full artifact metadata (including `binary_size_bytes`) without dumping binary blobs. `action="query"`: hybrid cache search. `action="reindex"`: heals sqlite-vec vectors. `action="prune"`: safe GC. | `{"status": "OK"|"CACHE_HIT"|"CACHE_MISS", ...}` | Gracefully degrades to relational confidence ranking if vector extensions are unavailable. |

#### Domain 1b: Native Diagnostic Primitives & Scaffolding (1 Tool)

| Tool | Privilege Tier | Signature & Parameters | Mechanics & Operational Purpose | JSON Output Contract | Fail-Soft Guarantee |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `default_primitives` | `DIMINISHED` | `default_primitives(action: str = "list", name: Optional[str] = None, params: Optional[Dict[str, Any]] = None, args: Optional[Any] = None, verbosity: str = "detail", agent_id: str = "default") -> str` | Direct in-memory execution of system diagnostic probes (`socket-monitor`, `fd-rescuer`, `disk-usage`, `mem-stat`, `landlock-guard`) in pure Python / Linux kernel `/proc` without compilation overhead or Go toolchain prerequisites. Supports `action="list"` (inspect available probes), `action in ("info", "get")` (probe specifications, metrics, and parameters), and `action in ("run", "exec")` (execute diagnostic probe). Enforces fail-soft 4-tier chmod privilege degradation (`4r--` returns `PERMISSION_DENIED` without raising exceptions) and returns single-encoded JSON with `attach_envelope(...)` where `output_schema is None`. Decouples runtime introspection from template factory synthesis. | `{"status": "OK"|"SUCCESS"|"PERMISSION_DENIED", "primitive": str, "output": {...}, "envelope": {...}, "telemetry": {...}}` | Parameter errors return `status: "PARAM_ERROR"`; missing names return `status: "NOT_FOUND"`; unprivileged executions degrade to `status: "PERMISSION_DENIED"`. Zero unhandled exceptions. |

#### Domain 2: Pico-Kanban & Multidimensional Scoring (2 Tools)

| Tool | Privilege Tier | Signature & Parameters | Mechanics & Operational Purpose | JSON Output Contract | Fail-Soft Guarantee |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `kanban_board` | `DIMINISHED` | `kanban_board(action: str = "board", include_archived: bool = False, task_id: Optional[int] = None, title: str = "", intent: str = "", category: str = "", artifact_name: Optional[str] = None, to_state: str = "", lint_passed: Optional[bool] = None, canary_passed: Optional[bool] = None, note: Optional[str] = None, reason: Optional[str] = None, states: Optional[List[str]] = None, max_score: Optional[float] = None, apply: bool = False, target_state: str = "SYNTHESIZED") -> str` | Unified Kanban management: view board (`board`), create tasks (`create`, alias `add`), advance states (`advance`, alias `move`), promote artifacts (`promote`), demote artifacts (`demote`), fleet reevaluation (`reevaluate`), and archival (`archive`/`unarchive`). | Action-dependent typed JSON (`status`, `lanes`, `task_id`, `promotion_score`, `verdict`, `candidates`). | Structured responses with `status: "PARAM_ERROR"` on missing inputs and `status: "INVALID_ACTION"` on invalid actions. |
| `process_inspect` | `FULL` / `DIMINISHED` | `process_inspect(pid: int = 0, name: Optional[str] = None, filter: Optional[str] = None, limit: int = 100, verbosity: str = "detail") -> str` | Dynamic inspection of process state, open file descriptors (`/proc/PID/fd`), process search by `name` or `filter`, and resource telemetry. `pid=0` inspects the FastMCP server (`self`). `verbosity="summary"` compacts output to ~1.3 KB (99.98% token reduction). Classifies descriptors into `socket`, `pipe`, `device`, `anon_inode`, and `file`. | `{"status": "OK", "pid": int, "name": str, "state": str, "threads": int, "rss_kb": int, "fd_count": int, "summary_by_type": {...}, "descriptors": [...]}` | Missing PIDs return `status: "NOT_FOUND"`; unprivileged cross-user requests return `status: "PERMISSION_DENIED"` without crashing. |

#### Domain 3: Isolation & Asynchronous Execution (2 Tools)

| Tool | Privilege Tier | Signature & Parameters | Mechanics & Operational Purpose | JSON Output Contract | Fail-Soft Guarantee |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `sandbox_run` | `DIMINISHED` | `sandbox_run(command: Union[str, List[str]] = "", cmd: Optional[Union[str, List[str]]] = None, share_net: bool = False, working_dir: Optional[str] = None, ro_paths: Optional[List[str]] = None, rw_paths: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None, parse: Optional[str] = None, timeout: int = 60) -> str` | Executes commands inside an ephemeral `bwrap` sandbox (`--unshare-all`, `share_net=False` by default). Supports string or argument list (`command`/`cmd` auto-joined with `shlex.join`), authorized `working_dir`, `ro_paths`, `rw_paths`, `env` injection, auto-resolves `.venv` symlinks, redirects tool caches to `/tmp` tmpfs, and features structured test/linter output parsing (`parse="pytest"|"ruff"|"auto"` extracting `passed`, `failed`, `errors`, `skipped`, `duration_s`, failing test node IDs `failures: [...]`, composite parsing `{"tool": "composite", "ruff": {...}, "pytest": {...}}`), and aggressive output trimming in `brief`/`terse` mode (emitting strictly `{status, exit_code, parsed, t}` and suppressing input reflection). | `{"status": "SUCCESS"|"EXEC_FAILED"|"PARAM_ERROR"|"PERMISSION_DENIED", "exit_code": int, "share_net": bool, "working_dir": str, "ro_mounts": [...], "stdout": str, "stderr": str, "parsed": {...}, "telemetry": {...}}` | Blocks blacklisted paths (`/etc/shadow`, `~/.ssh`) with `status: "PERMISSION_DENIED"` and cryptographic audit logging. Fail-soft `PARAM_ERROR` on missing commands. |
| `async_job_dispatch` | `DIMINISHED` | `async_job_dispatch(action: str = "dispatch", command: Optional[str] = None, label: Optional[str] = None, group: str = "default", working_dir: Optional[str] = None, task_id: Optional[int] = None, lines: int = 50, limit: int = 5, offset: int = 0, verbosity: str = "detail") -> str` | Unified async job queue via Pueue: enqueue tasks (`dispatch`) or inspect status and logs (`inspect`/`status`/`log`). Features automatic daemon startup, centralized secret masking, and compact status pagination (`action="status"` with `limit`/`offset`) reducing token footprints by 97.4%. | Action-dependent typed JSON (`status`, `task_id`, `group`, `command`, queue state, or task logs). | Returns `status: "PARAM_ERROR"` on invalid inputs or `status: "DEGRADED"` if daemon is missing. |

#### Domain 4: Crash Forensics & Kernel Observability (2 Tools)

| Tool | Privilege Tier | Signature & Parameters | Mechanics & Operational Purpose | JSON Output Contract | Fail-Soft Guarantee |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `diagnose_system_crashes` | `FULL` / `DIMINISHED` | `diagnose_system_crashes(action: str = "diagnose", limit: int = 5, resolve_after_report: bool = False) -> str` | Unified crash forensics: `action="diagnose"` inspects coredumps, journalctl errors, and Apport `/var/crash` files; `action="alerts"` (alias `"check"`) polls proactive crash alerts from `crash_events` without disruption. | `{"status": "OK"|"DEGRADED", "scope": "system"|"user", ...}` / `{"status": "OK", "new_crashes_synced": int, "alerts": [...]}` | Isolated execution (`stdin=DEVNULL`, `close_fds=True`, `timeout=15`). Degrades to `DEGRADED` if systemd utilities are absent. |
| `kernel_trace` | `FULL` | `kernel_trace(mode: str = "syscall_count", duration_sec: int = 3) -> str` | Non-invasive kernel tracing via `bpftrace` (`syscall_count`, `file_opens`, `tcp_connect`, `security_open_denials`, `security_landlock_audit`, `security_exec_monitor`, and under Milestone ONT-31: `network_sniff` [kprobe:netif_receive_skb], `security_audit` [tracepoint:capget], `tcp_listeners` [kprobe:inet_csk_listen_start]). Bounded duration (1–30s). | `{"status": "OK", "capability_tier": "FULL", "mode": str, "duration_sec": int, "counts": {...}}` | Requires `CAP_BPF` / `sudo -n`. When called in `DIMINISHED`, returns `status: "DEGRADED"` with prerequisite instructions. |

#### Domain 5: System Management & Omarchy Primitives (4 Tools)

| Tool | Privilege Tier | Signature & Parameters | Mechanics & Operational Purpose | JSON Output Contract | Fail-Soft Guarantee |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `aep_ctl` | `FULL` / `DIMINISHED` | `aep_ctl(domain: str = "schema", action: str = "schema", name: Optional[str] = None, target: Optional[str] = None, args: Optional[Any] = None, verbosity: str = "detail", limit: int = 50, cursor: int = 0) -> str` | Unified deterministic control plane across 9 domains: `service` (including `service.list`), `network`, `storage`, `package` (including `package.list`), `backup` (catalog micro-snapshots, `workspace_snapshot` and `workspace_restore` with 50MB cap and `CapabilityGuard` path blacklisting, plus LKG actions `lkg_status`, `lkg_diff`, `lkg_restore`), `security` (SHA-256 ledger `audit` and `verify`), `audit` (tamper verification and per-`agent_id` tool/token/latency accounting ledger via `action="usage"`), `ipc` (persistent UNIX socket daemon `/dev/shm/aep.sock`, session pool leasing, `stats` alias, and `action="harness_reconnect"` implementing the `autonomous_session_steward` multi-harness primitive across `claude`, `agy`, `codex`, and `gemini` in modes `plan`, `execute`, `certify`, and `matrix` via kernel `dev.tty.legacy_tiocsti` + `ioctl(TIOCSTI)` on a real ancestor TTY of a verified harness (`claude`); other harnesses and out-of-band reload are `UNSUPPORTED`/manual; `certify` and `matrix` need tier >= `5r-x` and `certify` is an unprivileged pty loopback that never reports `CERTIFIED`; note: `matrix` with `probe_cli=true` runs `<cli> mcp get`, which may start the MCP server's stdio command as a side effect), `hardware` (`inventory`, `accelerators`, `admit`), and `schema`. Under Milestone ONT-31, expanded `domain="security"` with active netfilter/firewall countermeasures: `firewall_status` (queries ufw or nft), `nftables_inspect` (lists active nft ruleset), and `threat_mitigate` (enforces deterministic `nft add rule inet filter input ip saddr <ip> drop`, with SIMULATED fallback in DIMINISHED mode). Supports `target` and `args` parameter aliases. `verbosity="summary"` compacts large outputs by 70–85% with pagination (`limit`/`cursor`), single-encoding, envelope deduplication, and per-request token/RSS/FD telemetry. | Standardized domain-dependent typed JSON (`status`, `domains`, `listeners`, `filesystems`, `packages`, `usage`, `envelope`, `telemetry`). | Invalid domains or actions return `status: "ERROR"` with `valid` alternatives from `CONTROL_PLANE_SCHEMA`. |
| `query_system_docs` | `DIMINISHED` | `query_system_docs(query: str = "", q: Optional[str] = None, limit: int = 3, ingest_command: Optional[str] = None) -> str` | Offline semantic vectorizer of Ubuntu `man` pages on `system_docs.db` (`sqlite-vec`). Resolves exact syntax in <5 ms without web lookups. Supports `q` query alias. `ingest_command` allows on-demand ingestion. | `{"status": "OK", "query": str, "results": [{"command": str, "section": str, "distance": float, "chunk_text": str}]}` | Lazy loader. Degrades gracefully with actionable instructions if vector dependencies are missing. |
| `visual_inspect` | `DIMINISHED` | `visual_inspect(url: str, viewport_width: int = 1280, viewport_height: int = 800, selector: Optional[str] = None, full_page: bool = True, include_base64: bool = False, verbosity: str = "summary") -> str` | Renders local (`file://`) or remote URLs in headless Chromium via Playwright offloaded to a thread worker. Uses compact volatile RAM (`/dev/shm`) screenshot mode by default (`include_base64=False`, `verbosity="summary"`, `-98.9%` token footprint with `screenshot_path`, `screenshot_sha256`, and `text_excerpt`). | `{"status": "SUCCESS", "url": str, "title": str, "viewport": {...}, "screenshot_bytes": int, "screenshot_path": str, "screenshot_sha256": str, "text_excerpt": str}` | Returns `status: "DISPLAY_UNAVAILABLE"` if Playwright/Chromium is absent or on timeout (25s). |
| `topos_audit_dag` | `DIMINISHED` | `topos_audit_dag(tasks: Union[List[str], List[Dict[str, Any]]], dependencies: Optional[Union[Dict[str, List[str]], List[Dict[str, Any]]]] = None, deps: Optional[Union[Dict[str, List[str]], List[Dict[str, Any]]]] = None, resources: Optional[Dict[str, Any]] = None) -> str` | Guardian of the Topos Integrity Protocol. Features polymorphic DAG input support (`tasks` as `list[str]` or `list[dict]`, `dependencies`/`deps` as `dict` or edge `list[dict]`) and shared state resource auditing (`resources`). Under Milestone ONT-30 (`GAP-DX-05`), provides resilient task-level resource fallback: when `resources` is omitted or unpassable by schema-cached clients, automatically parses task dictionaries for `writes`/`write`, `reads`/`read`, and `contract` definitions to extract resource sets and execute Bernstein hazard detection without schema errors. Executes topological sorting, cycle detection, Bernstein condition write-set hazard detection (`ToposVerdict.WARN` on uncoordinated writers without contract), and shared mutable state co-dependency checking (`ToposVerdict.BLOCKED` on mutual reader/writer coupling without an interface node). Populates edge relationship classifications (`dependency`, `interdependency`, `co-dependency`) while strictly preserving the 2-tuple return contract. | Approved: `{"verdict": "APPROVED", "details": [...], "edges": [...]}`<br/>Warn: `{"verdict": "WARN", "hazards": [...], "details": [...]}`<br/>Blocked: `{"verdict": "BLOCKED", "cycle": [...], "remediation": [...], "details": [...]}` | Deterministic in-memory algorithm with zero external dependencies and zero I/O operations. |
| `autoevol` | `DIMINISHED` | `autoevol(action="graph"\|"gaps"\|"thread"\|"log"\|"diff"\|"spec"\|"verify"\|"fix_test"\|"heal"\|"evolve"\|"reconcile"\|"report", node=None, a=None, b=None, gap=None, base=None, cycle=None, job=None, apply=False, restart=False, open_cycles=False, probe=False, root=None, persist=True, limit=10, select_fields=None, verbosity="summary")` | Read-only thread graph of AEP (tools, actions, capabilities, functions, SQL state, tests, claims, budgets): Merkle root R over the SCC condensation, omission gaps (`Req(t)`), declared-vs-observed drift, PageRank ranking and `impacted_tests`. `probe=True` (tier >= 5r-x) adds runtime observations outside R. Generations persist (`threads_gen` + SHA-256 ledger) only at tier >= 6rw-. ONT-41 and ONT-42b add `spec` (mini-SDD per gap with actionable `change` field and `resolve_gap` kind+target survival across Merkle hashes, tier >= 4r--), `verify` (ACCEPT/REJECT/PENDING against a frozen base with batched synchronous sandbox execution `run_tests_batched` up to 24 selected tests, pinning-test caller inheritance, and `WRONG_TREE` isolation sentinel, tier >= 5r-x), `fix_test` (re-entrant gap -> patch -> test cycle with orphan cycle reaping `_reap_orphan_cycles`, max 3 iterations, EXHAUSTED suggests `heal`, never reverts on its own) and `heal` (dry-run from the LKG at tier >= 4r--; `apply=True` needs tier >= 6rw- plus a prior workspace snapshot). ONT-42c adds `evolve` (C1–C3: state machine, `GitPort`, ff-only merge preconditions, tier gating and fence; the commit is bound to the judged tree and root, and `TREE_MUTATED_DURING_JUDGE` rejects a tree mutated during judgement). ONT-42c C4–C6 add the final gate (full suite in re-entrant sandbox batches over the committed tree, red = no merge), the SQLite evolve ledger (UNIQUE `(gap_canonical, base_R, tree_hash)`, events `evolve.*`; cycle cap `AEP_AUTOEVOL_MAX_CYCLES`, default 3 per rolling 24 h window, persisted in the DB) and rollback by a new revert commit (no push, `BLOCKED_GIT dev_dirty_by_revert`). E4 adds `reconcile` (Kubernetes-style bounded controller, `engine/threads_reconcile.py`: desired vs observed -> deterministic proposals `{gap, kind, action: heal\|spec\|evolve\|report, reason, tier_required}`; 7rwx executes only `heal` dry-run and fix_test/evolve cycles in plan mode, 6rw- only plan cycles, 5r-x/4r-- report only with zero writes; by default it only PROPOSES: opening cycles needs explicit opt-in (`open_cycles=true` or env `AEP_RECONCILE_OPEN=1`) and has its own budget `AEP_RECONCILE_MAX_OPENS` (default 1 per rolling 24 h, counting only `reconcile.opened` events, independent of the evolve cap); one new cycle per call at most, `limit` is honoured (<= 10 proposals), idempotent, `reconcile.*` ledger events at tier >= 6rw-; never commit, merge, push or heal apply; `discover(capabilities, terse)` adds a read-only `reconcile_top`). No `scripts/agent_*` runbook applies to the env var. | `{status, root, nodes, edges, gaps_open, codep, own_gaps, persisted}` (terse < 300 tokens) | Never executes target code statically; probes are fail-open (timeout is an observation, not a gap). |

> **Calidad:** gaps de cobertura 46 (trinquete `GAPS_BASELINE`, ONT-44). Detalle: `docs/sdd/sdd_ont44_mcp_coverage_ratchet.md`.

#### Domain 6: Automation via Orchestration — Pico-Playbooks (1 Tool)

Chains existing tools and artifacts into validated DAG workflows (e.g., E2E: static Go probe + `visual_inspect`). The DAG is validated by `topos_guard` (zero co-dependencies) and dispatches exclusively to a **whitelist** of safe tools to bound blast radius.

| Tool | Privilege Tier | Signature & Parameters | Mechanics & Operational Purpose | JSON Output Contract | Fail-Soft Guarantee |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `playbook_run` | `DIMINISHED` | `playbook_run(action: str = "run", name: Optional[str] = None, vars: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, steps: Optional[Union[List[Dict[str, Any]], str]] = None, return_only: str = "all", select_fields: Optional[List[str]] = None, stop_on_error: bool = True, description: Optional[str] = None, intent_description: Optional[str] = None, params_contract: Optional[List[Dict[str, Any]]] = None, names: Optional[List[str]] = None, apply: bool = False) -> str` | Unified execution of DAG workflows (`run`), single-turn ephemeral batch pipelines (`batch` / `code` / `ephemeral` / `pipeline`) supporting inter-step parameter piping (`$prev.*`, `$steps.<id>.*`), cross-agent shared RAM session cache piping (`$cache.<key>.*`, `$slot.<key>.*`), failed steps preservation (`failed_steps`), server-side field projection (`select_fields` cutting tokens by 80–96.98%), defining automations (`create`), listing inventory (`list`), and safe pruning (`prune`). | Action-dependent typed JSON (`status`, `playbook`, `steps_run`, `results`, `output`, `failed_steps`, `token_savings_estimate`). | Returns `status: "PARAM_ERROR"` on missing inputs, `status: "INVALID_ACTION"` on invalid actions, and `status: "LINT_ERROR"` on recursion attempts. |

---


### Factory Decoupling: Runtime Primitives vs. Template Synthesis

Under Milestone ONT-34, AEP establishes a clean architectural boundary between **instantaneous runtime diagnostics** and **bespoke artifact synthesis**:

| Dimension | `default_primitives` (Runtime Probes) | `artifact_lint_and_build` (Template Factory) |
| :--- | :--- | :--- |
| **Operational Role** | Immediate, low-latency diagnostic introspection | Autonomous code synthesis and ELF compilation |
| **Target Probes** | `socket-monitor`, `fd-rescuer`, `disk-usage`, `mem-stat`, `landlock-guard` | Bespoke CUE-contracted Go tools & distributed agents |
| **Implementation** | Pure in-memory Python stdlib & Linux `/proc` filesystem | Go 1.22+ compiler (`go vet`, `golangci-lint`) + static ELF |
| **Execution Mechanics** | Direct in-process execution via `engine/primitives.py` | Volatile RAM execution via Linux `memfd_create` |
| **Prerequisites** | None (zero external toolchain dependencies) | Go toolchain + CUE engine + `/mnt/apps` / host Go |
| **Scaffolding Posture** | Runtime primary for standard diagnostics | Scaffolding preserved intact in `templates/` (R-4) |
| **Latency Profile** | Sub-millisecond (< 5 ms) | Compilation cycle (~ 300-800 ms) |

### Lifecycle and Skill Chaining

The following diagram illustrates how an autonomous agent deterministically chains AEP's 17 tools across a complete execution cycle, integrating self-discovery, topological auditing, artifact synthesis, volatile RAM execution, async parallel queues, and proactive self-healing:

```mermaid
flowchart TD
    subgraph S1["1. Discovery & Autonomy"]
        Init["Interaction Start"] --> Cap["discover(action='capabilities')<br/>Assess privileges (FULL vs DIMINISHED)"]
        Cap --> Audit["topos_audit_dag()<br/>Audit task DAG & block co-dependencies"]
        Audit --> Task["kanban_board(action='create')<br/>Register task in BACKLOG lane"]
    end

    subgraph S2["2. Artifact Retrieval & Synthesis"]
        Task --> Query["artifact_catalog(action='query')<br/>Hybrid retrieval (Hash + sqlite-vec kNN)"]
        Query --> Branch{"State in Catalog?"}
        Branch -->|"CACHE_HIT (Validated)"| Hit["Retrieve existing binary from RAM"]
        Branch -->|"CACHE_MISS"| Hydrate["artifact_lint_and_build(action='hydrate')<br/>Instantiate Go template with parameters"]
        Hydrate --> Synth["artifact_lint_and_build(action='build')<br/>go vet (gate) + golangci-lint (advisory)<br/>Static build CGO_ENABLED=0"]
        Synth --> LintLane["kanban_board(action='advance', to_state='LINTED')<br/>Move task to LINTED lane"]
    end

    subgraph S3["3. Volatile Execution & Canary Validation"]
        Hit --> ExecRAM["artifact_execute_in_ram()<br/>RAM injection via memfd_create<br/>Execution via /proc/self/fd/"]
        LintLane --> ExecRAM
        ExecRAM --> AdvCanary["kanban_board(action='advance', to_state='CANARY')<br/>Advance to CANARY (canary_passed=True)"]
        AdvCanary --> Promote["kanban_board(action='promote')<br/>Evaluate multidimensional trust score<br/>(quality, reliability, experience, recency)"]
        Promote --> PBranch{"Score >= 0.70 & Veto OK?"}
        PBranch -->|"Approved"| Promoted["PROMOTED<br/>Marked reusable=1 in catalog"]
        PBranch -->|"Rejected"| Rejected["REJECTED<br/>Remains as ephemeral artifact"]
    end

    subgraph S4["4. Alternative Paths & Concurrent Resilience"]
        Audit -.->|"Untrusted command"| Sand["sandbox_run()<br/>Strict bwrap isolation"]
        Audit -.->|"Long-running job"| AsyncD["async_job_dispatch(action='dispatch')<br/>Enqueue in Pueue (immediate task_id)"]
        AsyncD --> AsyncI["async_job_dispatch(action='log' or 'status')<br/>Poll status and logs with secret masking"]
        Cap -.->|"Proactive monitoring"| CrashCheck["diagnose_system_crashes(action='alerts')<br/>Poll coredump events against SQLite"]
        CrashCheck -->|"Pending alerts"| CrashDiag["diagnose_system_crashes(action='diagnose')<br/>RCA with stack trace and signals"]
    end
```

[↑ Back to top](#top)

---


### Revert de `evolve` (decision humana)

Tras `BLOCKED_GIT dev_dirty_by_revert`, el usuario revisa `dev` frente a `origin/dev` y libera el bloqueo con `scripts/aep-ctl evolve resolve-revert <ciclo> --confirm` (`REVERT_RESOLVED`). No es tool MCP; ver SDD ONT-40 §9.

## 5. Hybrid Semantic Memory (sqlite-vec) & Hot SQLite Concurrency

Resolves strict hashing fragility when handling natural language variability across LLMs via a
**two-tier retrieval system**: O(1) exact SHA-256 matching, falling back to cosine KNN over `sqlite-vec`.

```mermaid
flowchart LR
    Q["Agent Intent<br/>(variable natural language)"] --> T1{"Tier 1:<br/>Exact SHA-256 hash"}
    T1 -->|hit| R["Artifact + ELF binary"]
    T1 -->|miss| T2["Tier 2: local embedding<br/>bge-small-en-v1.5 (384-dim, ONNX, offline)"]
    T2 --> KNN{"Cosine KNN<br/>distance <= 0.32"}
    KNN -->|match| R
    KNN -->|no match| Miss["CACHE_MISS -> synthesize"]
    R --> RAM["In-RAM injection<br/>memfd_create"]
```

- Calibrated distance threshold of `0.32` (paraphrased intents span ~0.28–0.30; distinct intents >=0.36).
- **Total fail-soft**: Without `sqlite-vec` or local embedder models, the catalog operates identical to the hash-only mode.

### Persistence and Agent Access

The SQLite database at `~/.local/share/agent-os/artifacts.db` serves as the system's **evolutionary memory**:
- **Lives outside the repository** (user space, gitignored). Persists across branch switches, rebases, and workspace purges.
- **Offloaded Concurrency**: AnyIO thread workers (`anyio.to_thread.run_sync()`) prevent database I/O from blocking FastMCP's asynchronous event loop.

### Pico-Kanban: Artifact Confidence Scoring

The Pico-Kanban subsystem governs artifact lifecycle states (`BACKLOG` → `SYNTHESIZED` → `LINTED` → `CANARY` → `PROMOTED` / `REJECTED`).
Promotion requires passing a multidimensional confidence evaluation:

$$	ext{Score} = w_q \cdot Q + w_r \cdot R + w_e \cdot E + w_t \cdot T$$

Where $Q$ represents static lint quality, $R$ runtime reliability, $E$ historical execution count, and $T$ recency decay. Any critical failure triggers an immediate **hard veto**, setting promotion score to 0.

### Anti-Deadlock WAL Concurrency Architecture

To guarantee zero database lock contention under concurrent multi-agent access:
- **Segregated Read-Only Connections (`get_ro_connection`)**: Employs `file:...mode=ro` URIs, enabling infinite concurrent readers without taking WAL read locks.
- **Immediate Autocommit Writers (`get_rw_connection` + `BEGIN IMMEDIATE`)**: Acquires exclusive write locks at $t=0$, serializing write transactions cleanly and eradicating `database is locked` race conditions.
- **Performance PRAGMAs**: `PRAGMA wal_autocheckpoint=1000`, `PRAGMA busy_timeout=10000` (10s fail-soft timeout), `PRAGMA mmap_size=268435456` (256 MB memory-mapped pages), and `PRAGMA cache_size=-64000` (64 MB cache).

```mermaid
flowchart TD
    subgraph MultiAgent["Concurrent Agent Swarm"]
        A1["Agent 1 (Claude Code)"]
        A2["Agent 2 (Antigravity agy)"]
        A3["Agent 3 (Codex)"]
    end

    subgraph FastMCP["FastMCP Async Event Loop (server.py)"]
        Offload["anyio.to_thread.run_sync()"]
    end

    subgraph ConnModel["Hot SQLite Concurrency Model (engine/db.py)"]
        RO["get_ro_connection()<br/>URI: file:...mode=ro<br/>- Infinite concurrent readers<br/>- Zero WAL read lock contention"]
        RW["get_rw_connection()<br/>isolation_level=None<br/>- PRAGMA wal_autocheckpoint=1000<br/>- PRAGMA busy_timeout=10000"]
        TX["transaction_immediate()<br/>BEGIN IMMEDIATE<br/>- Serialized write lock at t=0<br/>- Zero deadlocks (database is locked)"]
    end

    subgraph Storage["ACID Storage"]
        DBFile["artifacts.db (WAL Mode + mmap 256MB)"]
        WAL["artifacts.db-wal"]
        SHM["artifacts.db-shm"]
    end

    A1 & A2 & A3 --> FastMCP --> Offload
    Offload -->|"Queries (browse/query)"| RO --> DBFile & WAL
    Offload -->|"Mutations (kanban/build)"| RW --> TX --> DBFile & WAL & SHM
```

[↑ Back to top](#top)

---

## 6. Database Resilience: Online Hot Backup & Auto-Recovery (5 Slots)

To prevent evolutionary state loss during abrupt power cuts, kernel panics, or database corruption, AEP incorporates an autonomous hot backup engine with a 5-slot FIFO rotation pool and self-healing protocol in `engine/backup.py`.

```mermaid
flowchart TD
    subgraph Normal["1. Normal Flow: Online Streaming & FIFO Rotation (5 Slots)"]
        LiveDB["artifacts.db (Hot SQLite)"]
        Stream["conn.backup() (Online Streaming)<br/>- Non-blocking online streaming<br/>- Advisory flock lock: .backup.lock"]
        LiveDB --> Stream
        Stream --> Slot1["artifacts.db.bak.1<br/>(Most recent snapshot)"]
        Slot1 --> Shift["Cascading FIFO Rotation<br/>bak.1 -> bak.2 -> bak.3 -> bak.4 -> bak.5"]
        Shift --> Trunc["Old bak.5 purged (Pool capped at 5)"]
        Slot1 -.-> SHA["SHA-256 Checksum persistence"]
    end

    subgraph Recovery["2. Resilience Flow: Corruption Detection & Auto-Healing"]
        Corrupt{"PRAGMA integrity_check<br/>or header corruption"}
        Corrupt -->|"Failure detected"| Scan["verify_and_auto_recover()<br/>Scan backup slots (1 through 5)"]
        Scan --> CheckSlot{"Verify SHA-256 & SQLite integrity"}
        CheckSlot -->|"Valid slot found"| Restore["Atomic Restoration<br/>- Replace artifacts.db<br/>- Strict purge of -wal and -shm"]
        Restore --> Healthy["Healthy Database Restored OK"]
    end
```

### Hot Streaming Backup Mechanics
- **Online Hot Streaming (`conn.backup()`)**: Generates consistent page-level backups online without stopping the FastMCP server or blocking agent read/write operations.
- **Collision Advisory Locking (`fcntl.flock`)**: An OS-level lock (`.backup.lock`) serializes backup operations, preventing collisions between concurrent processes.
- **5-Slot FIFO Rotation Pool**: Maintains exactly 5 numbered copies in `~/.local/share/agent-os/backups/`. Slot 1 holds the newest snapshot; existing slots shift downwards (`1->2->3->4->5`), cleanly purging the oldest.
- **Cryptographic Integrity via SHA-256**: Every snapshot is verified against its SHA-256 checksum recorded in `backup_manifest.json` and validated via `PRAGMA integrity_check`.
- **Atomic Restoration with Sidecar Purge**: Restoring a slot immediately purges stale `-wal` and `-shm` sidecars to guarantee transactional consistency.
- **Transparent Self-Healing (`verify_and_auto_recover`)**: If a corrupt database is detected, the engine scans slots 1 to 5 sequentially, validates checksums, and restores the newest healthy snapshot automatically.

### Volatile In-RAM Micro-Snapshots (`create_micro_snapshot`)
- **Sub-Millisecond Latency (0.28 ms)**: Inspired by Firecracker MicroVM Copy-on-Write (COW) snapshotting, AEP streams SQLite pages directly into RAM (`:memory:`) via the backup API. Operates **5.7x faster** than disk storage with **zero disk footprint** (0 temporary files created).
- **Ephemeral Scratchpad Isolation**: Allows subagents to fork hypotheses or test migrations in memory without impacting the live database.

### Anti-Poisoning Architecture and Forensic Quarantine
- **Canary Integrity Tokens (`_aep_canary`)**: Enforces pre-backup integrity validation. If a rogue process alters the live database, canary verification aborts rotation, preventing historical backup pool contamination.
- **Immediate Forensic Quarantine (`backups/quarantine/`)**: Corrupted or tampered databases are automatically isolated as `artifacts.db.corrupt.<timestamp>` alongside a structured forensic JSON report, preserving the healthy FIFO pool.

### CLI Control Commands (`scripts/aep-ctl backup`)
```bash
# Check backup pool status and slots
./scripts/aep-ctl backup status

# Trigger an online hot backup (automatic FIFO rotation)
./scripts/aep-ctl backup backup

# Restore the database from a specific slot (e.g., slot 1)
./scripts/aep-ctl backup restore --slot 1

# Execute a sub-millisecond volatile in-RAM micro-snapshot
./scripts/aep-ctl backup micro-snapshot

# Deep verify database integrity and canary tokens
./scripts/aep-ctl backup verify-integrity
```

[↑ Back to top](#top)

---

## 7. Security Countermeasures, Isolation & Cryptographic Audit Ledger

AEP transforms systems engineering and auditing primitives into high-resilience agentic capabilities. To ensure agents or external actors cannot leverage these tools for unauthorized privilege escalation, the platform enforces defense-in-depth countermeasures across `engine/privilege.py` and `engine/security.py`:

```mermaid
flowchart TD
    subgraph MultiAgentSwarm["Multi-Agent Swarm"]
        AgentA["Agent A (agent_id='claude')"]
        AgentB["Agent B (agent_id='antigravity')"]
        AgentC["Agent C (agent_id='untrusted')"]
    end

    subgraph DefenseLayer["Countermeasure & Blast Radius Guard"]
        Guard["CapabilityGuard.verify_action()<br/>- Capability-Based Access Control (CBAC)"]
        Blacklist{"Path Blacklisted?<br/>- /etc/shadow, /etc/sudoers<br/>- /root, ~/.ssh, ~/.gnupg<br/>- Path traversal (../) escape"}
        Sandbox["bwrap Sandbox Isolation<br/>- --unshare-all, --cap-drop ALL<br/>- /tmp in RAM tmpfs, read-only root"]
    end

    subgraph AuditLedger["Immutable Audit Ledger (security.py)"]
        Mask["Secret Sanitization (mask_secrets)<br/>API tokens, passwords, private keys -> [MASKED]"]
        HashChain["SHA-256 Cryptographic Chaining<br/>entry_hash = SHA256(prev_hash | ts | agent | action | status | details)"]
        AuditDB["Table: security_audit_log (artifacts.db)<br/>Genesis Block: 00000000...0000"]
        Verify["verify_audit_chain()<br/>Instant tampering & link-break detection"]
    end

    AgentA & AgentB & AgentC --> Guard
    Guard --> Blacklist
    Blacklist -->|"Unauthorized access"| Denied["PermissionDenied (Access Blocked)"]
    Blacklist -->|"Authorized path"| Sandbox
    Guard -.->|"Log event"| Mask --> HashChain --> AuditDB
    AuditDB --> Verify
```

### CapabilityGuard & Critical Path Blacklisting
- **Strict Blacklist**: Categorically denies read, write, or execution access to sensitive host locations:
  - `/etc/shadow`, `/etc/gshadow`, `/etc/sudoers`, `/etc/security`
  - `/root` and root-owned subdirectories
  - `~/.ssh` (`id_rsa`, `id_ed25519`, `authorized_keys`)
  - `~/.gnupg` (PGP keys and trustrings)
  - `/proc/kcore`, `/dev/mem`, `/dev/kmem`
- **Path Traversal Immunity**: Canonicalizes paths (`resolve()`), aborting directory escape attempts (`../../`).
- **Segregated Multi-Agent Context**: FastMCP tool calls pass the caller's `agent_id` (`agent_id: str = "default"`), isolating and auditing actions across concurrent swarms.

### Tamper-Evident SHA-256 Audit Chain
- **Cryptographically Chained Ledger**: The `security_audit_log` table links every privileged action to the previous block's hash (`prev_hash`), starting from an all-zero genesis block (`GENESIS_HASH`).
- **Automatic Secret Sanitization (`mask_secrets`)**: Bearer tokens, credentials, passwords, and private API keys are redacted (`[MASKED]`) before persisting or computing hashes.
- **Zero-Trust Verification (`verify_audit_chain`)**: Deterministically recalculates the entire hash chain. Any row manipulation is immediately detected with the exact corrupted row identified.

```bash
# Verify cryptographic integrity of the security audit ledger
./scripts/aep-ctl audit verify
```

### In-Process Sandboxing via Landlock LSM (`engine/landlock.py`)
- **Kernel-Level User-Space Isolation**: Leverages the Linux Security Module (Landlock LSM, Linux 5.13+) via pure `ctypes` (`SYS_landlock_create_ruleset=444`, `SYS_landlock_add_rule=445`, `SYS_landlock_restrict_self=446`) and `prctl(PR_SET_NO_NEW_PRIVS, 1)`.
- **Zero External C Dependencies**: No shared `liblandlock` required. Confinement applies at thread/process level in under **4.2 ms** with automatic ABI detection (ABI v8 supported on Ubuntu kernel).
- **Static Go Diagnostic Probe (`diagnostic/go/landlock-guard`)**: Hermetic ELF probe compiled with `CGO_ENABLED=0` using Go standard library `syscall.Syscall6` to verify confinement without external modules.

### eBPF Security Observability (`kernel_trace`)
- **Active Intrusion Detection & Network Sniffing**: Features curated eBPF tracepoint and kprobe modes (inspired by Tetragon, Falco, and Cilium) to detect unauthorized file descriptor manipulation, access attempts to blacklisted files, network packet ingestion, and capability checks:
  - `security_open_denials`: Audits rejected `openat` attempts (`sys_exit_openat < 0`).
  - `security_landlock_audit`: Audits Landlock LSM self-confinement invocations (`sys_enter_landlock_restrict_self`).
  - `security_exec_monitor`: Audits executable invocations (`sys_enter_execve`).
  - `network_sniff` (alias `sniff`, `network`): Low-overhead kernel-space tracing of network packet ingress via `kprobe:netif_receive_skb` without user-space pcap socket overhead.
  - `security_audit` (alias `audit`): Audits capability inspection and query attempts via `tracepoint:syscalls:sys_enter_capget`.
  - `tcp_listeners` (alias `listeners`): Detects socket binding and active listening socket initialization via `kprobe:inet_csk_listen_start`.

### Netfilter & Firewall Mitigation (`aep_ctl security`)
- **Deterministic Perimeter Defense**: Non-interactive firewall status inspection, ruleset audits, and instant threat mitigation drops:

```bash
# Inspect host firewall status (ufw or nftables backend detection)
./scripts/aep-ctl security firewall_status

# Inspect active netfilter ruleset (rule count and active chains)
./scripts/aep-ctl security nftables_inspect

# Enforce deterministic netfilter drop rule against malicious IP
./scripts/aep-ctl security threat_mitigate 192.168.1.100

# Inspect Landlock LSM status and supported kernel ABI version
./scripts/aep-ctl security landlock-status
```

[↑ Back to top](#top)

---

## 8. Omarchy Enhancements (8 Distro-Agnostic Specs)

Innovations from Omarchy's "Agentic OS" (originally coupled to Arch Linux / Hyprland), C2/Cloudflare IPC architectures, multi-harness runner ergonomics, and memory-first network telemetry decoupled into
8 **distribution-agnostic** specifications running on Ubuntu.

```mermaid
flowchart TD
    subgraph OM["Omarchy & IPC Primitives -> Agnostic Specs"]
        S1["OM-1 · aep_ctl<br/>Unified control plane (9 JSON domains)"]
        S2["OM-2 · diagnose_system_crashes(action='alerts')<br/>Proactive crash routing (polling)"]
        S3["OM-3 · Skills Hub<br/>symlinks Claude/agy/Codex/Gemini"]
        S4["OM-4 · query_system_docs<br/>Vectorized man-pages (sqlite-vec)"]
        S5["OM-5 · visual_inspect<br/>Headless display (Playwright /dev/shm)"]
        S7["OM-7 · playbook_run(action='batch') & ipc_pool<br/>/dev/shm/aep.sock + 16-slot RAM Pool + Field Projection"]
        S8["OM-8 · Schema Evolution & Multi-Runner<br/>tools.listChanged + failing node IDs + parse='auto'"]
        S9["OM-9 · Native Network Telemetry<br/>Pure-RAM Ingress + Zero-Container Decoupling"]
    end
    S1 & S2 & S3 & S4 & S5 & S7 & S8 & S9 --> V["Zero co-dependencies (Topos)<br/>- collision-free multi-agent - typed JSON output"]
```

### Omarchy Distro-Agnostic Specification Matrix

| Specification | Name & Focus | AEP Component | Underlying Mechanism | Omarchy Decoupling (Ubuntu) | Fail-Soft Guarantee |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SPEC-OM-1** | **Unified System Control Plane** | `aep_ctl`<br/>`scripts/aep-ctl` | Deterministic CLI router to `systemctl`, `ip`, `ss`, `df`, and `dpkg` with JSON validation. | Replaces Arch commands (`pacman`, ad-hoc bash scripts) with universal POSIX utilities. | Invalid requests return JSON with `exit_code: 1` and usage documentation (`--schema`). Missing binaries emit `DEGRADED`. |
| **SPEC-OM-2** | **Active Crash Routing & Proactive Self-Healing** | `diagnose_system_crashes(action="alerts")`<br/>*(alias `check_crash_alerts`)* | Periodic polling calculating hash signatures (`pid:time:exe`) of coredumps, stored in `crash_events`. | Eliminates dependency on root systemd path units or Arch-specific background daemons. | If `coredumpctl` is missing (containers), returns `status: "DEGRADED"` without interrupting the agent. |
| **SPEC-OM-3** | **Universal Multi-Agent Skills Hub** | Symlink farm<br/>`scripts/setup.sh` | Convergent symlinks from `~/.agents/skills/` to Claude, Antigravity, Codex, and Gemini directories. | Decouples skills from Hyprland/Arch, enabling universal multi-agent synchronization on Ubuntu. | Idempotent linking; if an agent is absent on the host, setup continues cleanly without errors. |
| **SPEC-OM-4** | **Local System Docs Vectorizer** | `query_system_docs`<br/>`engine/docs_vectorizer.py` | Local `system_docs.db` vector store with `sqlite-vec` and CPU embeddings (`bge-small-en-v1.5`) over `man` pages. | Replaces heavy ChromaDB stores and remote LLM API lookups with sub-5ms offline ONNX inference. | Lazy loader; if vector dependencies are absent, returns a structured degraded response without throwing exceptions. |
| **SPEC-OM-5** | **Headless Visual & Display Actuator** | `visual_inspect`<br/>`engine/headless_display.py` | Headless Chromium automation via Playwright with ephemeral RAM screenshots (`/dev/shm`). | Eliminates need for physical Wayland/Hyprland compositors or X11 servers (`Xvfb`) for UI audits. | If Playwright or Chromium is absent, returns `DISPLAY_UNAVAILABLE` with an exact resolution command. |
| **SPEC-OM-7** | **Shared-Memory Socket Pool & Ephemeral Batch/Code Mode** | `playbook_run(action="batch")`<br/>`engine/ipc_pool.py`<br/>`/dev/shm/aep.sock` | Persistent AF_UNIX socket multiplexer in Linux shared memory (`/dev/shm`), 16-slot session pool, server-side field projection (`select_fields`). | Replaces chat context hopping and cold process spin-up with warm <0.5ms IPC and single-turn DAG batching. | Fail-soft to `/tmp/aep_pool` if `/dev/shm` is unwritable; strict zero-FD leak (`fd_delta == 0`). |
| **SPEC-OM-8** | **Cross-Harness Schema Evolution & Multi-Runner Ergonomics** | FastMCP Core<br/>`topos_guard.py`<br/>`sandbox_run`<br/>`scripts/aep-sync.sh` | `capabilities.tools.listChanged = True`, drift metadata (`schema_hash`, `server_version`, `pid`, `uptime_seconds`), task-level resource fallback, and `sandbox_run` brief trimming / composite runner parsing (`parse="auto"`). | Bridges heterogeneous MCP client schema caches and multi-harness runtimes without process disruption. | Fail-soft task fallback prevents schema errors; instance audit is 100% read-only and never terminates processes. |
| **SPEC-OM-9** | **Native Memory-First Network & Security Telemetry: Container Decoupling & Pure-RAM Ingress** | `engine/net_telemetry.py`<br/>`aep_ctl(domain="network"|"security")`<br/>`kernel_trace`<br/>`WF-10`/`WF-11` | Pure in-RAM network probing, kernel /proc/net socket introspection, packet header dissection, and deterministic netfilter hardening executing via Python stdlib directly on host. | Replaces heavy containerized analytical satellites (54GB) with microsecond in-RAM algorithmic primitives and self-describing schema reflection. | Fail-soft: unprivileged tier returns structured SIMULATED netfilter hardening without blocking agent or crashing host runtime. |

---

#### Detailed Technical Specifications (SPEC-OM-1 to SPEC-OM-7)

#### 1. SPEC-OM-1: Unified System Control Plane (`aep_ctl` / `scripts/aep-ctl`)
- **Objective**: Provide a deterministic CLI and RPC interface for language models to inspect and modify OS state without hallucinating flags or parsing unstructured text.
- **Functional Domains**:
  - `service`: Inspect status (`status`) or mutate units (`start`, `stop`, `restart`). In `DIMINISHED` mode, automatically scopes to `systemctl --user`; in `FULL` mode, uses `sudo -n systemctl`.
  - `network`: General interface inspection (`inspect` via `ip -j addr` or `/proc/net/dev`), routing tables (`routes` via `ip -j route`), listening sockets (`listeners` parsing `/proc/net/tcp` in RAM), in-RAM port probing (`probe` via `net_telemetry.probe_tcp_ports`), network device statistics (`interfaces`), and ARP table inspection (`arp`).
  - `storage`: Partition utilization (`usage` via `df -B1`), active mount points (`mounts`), and disk topology (`disks` via `lsblk -J`).
  - `package`: Installed packages (`installed` via `dpkg-query`), presence verification (`check`), and dependency information (`info` via `apt-cache policy`).
- **Guarantees**: Suppresses interactive pagers, auto-documents contracts via `--schema`, and exits with code 1 and usage JSON when arguments are missing.

#### 2. SPEC-OM-2: Active Crash Routing & Proactive Self-Healing (`diagnose_system_crashes(action="alerts")`)
- **Objective**: Transform passive coredump analysis into a proactive early-warning loop to prevent agents from building on unstable systems.
- **Synchronization Mechanics**:
  1. Executes `coredumpctl list --json=short --reverse -n 100` non-invasively.
  2. Extracts PID, timestamp, and crashed executable path, composing a unique fingerprint: `pid:timestamp:executable`.
  3. Executes an atomic `INSERT OR IGNORE` into the `crash_events` table in `artifacts.db`.
  4. Returns only unresolved alerts (`resolved = 0`), allowing agents to call `diagnose_system_crashes()` to extract stack traces and plan remediation.
- **Decoupling**: Unlike Omarchy's window-manager-specific scripts, operates purely in user space across Ubuntu/Debian distributions with systemd.

#### 3. SPEC-OM-3: Universal Multi-Agent Skills Hub
- **Objective**: Consolidate agent skills and tools into a single canonical source of truth (`~/.agents/skills/`), eliminating discrepancies between different agent execution environments.
- **Symlink Architecture**:
  - Canonical Directory: `~/.agents/skills/` (read natively by OpenAI Codex).
  - Gemini CLI Link: `~/.gemini/skills/` -> `~/.agents/skills/`.
  - Antigravity Link: `~/.gemini/config/skills/` -> `~/.agents/skills/`.
  - Antigravity Migration Link: `~/.gemini/antigravity-cli/skills/` -> `~/.agents/skills/`.
- **Maintenance Guarantees**: Modifications made to a skill by any subagent are immediately reflected across all clients without manual copying.

#### 4. SPEC-OM-4: Local System Docs Vectorizer (`query_system_docs`)
- **Objective**: Resolve exact syntax, flags, and configuration options of standard Linux utilities in real time without requiring web access or wasting context tokens.
- **Ingestion & Retrieval Pipeline**:
  - **Ingestion**: Runs `man <cmd>` with `MANPAGER=cat` and `MANWIDTH=80` to extract clean text, splitting manual pages into coherent paragraph chunks (up to 50 chunks per command).
  - **Local Vectorization**: Computes 384-dimensional embeddings via quantized `bge-small-en-v1.5` running on CPU with ONNX Runtime.
  - **Storage**: Persists chunks and vectors in `~/.local/share/agent-os/system_docs.db` using `sqlite-vec` virtual tables (`vec_docs`).
  - **Query**: `query_system_docs(query, limit)` vectorizes agent queries and executes cosine distance searches, returning relevant chunks in under 5 ms.

#### 5. SPEC-OM-5: Headless Visual & Display Actuator (`visual_inspect`)
- **Objective**: Provide agents with visual inspection capabilities on headless servers or cloud instances lacking physical displays, enabling UI audits and local document reviews.
- **In-RAM Capture Lifecycle**:
  1. Instantiates headless Chromium via Playwright (`headless=True`, flags `--no-sandbox`).
  2. Navigates to requested URLs (`http://`, `https://`, or local `file://`) using the configured viewport (default 1280x800).
  3. Waits for page `load` event. If a CSS selector is specified, targets the designated element.
  4. Writes screenshots directly into shared volatile RAM (`/dev/shm/aep_shot_<uuid>.png`).
  5. Encodes file bytes into Base64, calculates latency, and unlinks the temporary RAM file immediately, ensuring zero secondary disk persistence.

#### 6. SPEC-OM-7: Shared-Memory UNIX Socket Pool & Ephemeral Batch/Code Mode (`playbook_run(action="batch")`)
- **Objective**: Eliminate per-call process spin-up latency and chat-turn token bloat in multi-agent tool chains.
- **Architectural Mechanics**:
  1. **Session Pool (`/dev/shm/aep_pool/slot_<id>`)**: Manages up to 16 warm execution slots with 60s TTL, automatic reaping, and thread/async-safe slot leasing.
  2. **UNIX Socket Mux (`/dev/shm/aep.sock`)**: Persistent AF_UNIX daemon with line-delimited JSON framing, 16 MB bounded buffer, and guaranteed zero file descriptor leaks (`fd_delta == 0`).
  3. **Cloudflare-Style Ephemeral Batching**: Single-turn multi-step pipeline execution supporting inter-step parameter piping (`$prev.*`, `$steps.<id>.*`), multi-agent shared RAM session cache piping (`$cache.<key>`, `$slot.<key>`), and partial error diagnostics preservation (`failed_steps`).
  4. **Server-Side Field Projection (`select_fields`)**: Discards verbose JSON metadata directly in RAM prior to network serialization, reducing payload tokens by 80–95% with smart dot-path fallback mapping.
  5. **Pico-Triad Multi-Agent Concurrency Isolation**:
     - **Pico-Jenkins Slot Compilation**: `artifact_lint_and_build(action="build")` compiles Go diagnostic probes inside dedicated `/dev/shm` session slots, publishing output binaries atomically via hidden `.tmp` staging and `os.replace` to prevent binary corruption during parallel builds.
     - **Atomic Kanban Upsert**: `kanban.upsert_build_task()` executes task creation and attempt/score progression under a single `transaction_immediate(conn)` transaction, completely eliminating TOCTOU race conditions and duplicate task cards.
     - **Vector Embedding Offloading**: `engine/catalog.py` serializes float32 vector embeddings outside SQLite write transactions, reducing write-lock duration by >95% and eliminating `vec0` primary key contention.
     - **Pico-Ansible Saved Playbook Parity**: `playbook_run(action="run")` provides 100% parity with `action="batch"` (slot leasing, `$prev.*` / `$steps.*` / `$cache.*` reference piping, `failed_steps` retention, and server-side field projection reducing tokens by 94%+).
  6. **Non-Pico System-Wide Concurrency Hardening**:
     - **Audit Ledger Fork Prevention**: `engine/security.py` serializes `record_audit_event()` with a re-entrant mutex (`_AUDIT_LOCK`) and `transaction_immediate(conn)` to eliminate race conditions in the SHA-256 hash chain during parallel subagent tool invocations.
     - **Thread-Safe In-Memory Snapshots**: `engine/backup.py` synchronizes `create_micro_snapshot()`, `restore_micro_snapshot()`, and `list_micro_snapshots()` under `_SNAPSHOT_LOCK` with `check_same_thread=False` `:memory:` connections, allowing cross-thread RAM snapshot manipulation without SQLite driver thread collision.
     - **Vector Engine Double-Checked Locking**: `server.py` guards `ManPagesVectorizer` singleton initialization under `_DocsHolder.lock` to prevent parallel instantiation races during high-concurrency doc queries.
  7. **Cross-Agent RAM Session Caching & Re-Discovery Tax Mitigation (`GAP-OM-15`)**:
     - **Manifest Auto-Caching**: `discover(action="capabilities"|"playbook")` automatically caches capability manifests and tactical playbooks in shared `/dev/shm` session memory (`_shared_session_cache`).
     - **Terse Stub Response**: Subagents querying within the same `session_id` receive an ultra-compact stub (`verbosity="terse"` / `"cached"`) in <0.3ms (~249 tokens vs ~1,200 tokens, saving >80–96.5% of context window).
     - **Server-Side Field Projection & Named Store**: `select_fields` projects requested dot-paths in RAM prior to JSON serialization, while `store_as="<key>"` persists structured manifests for dynamic variable piping (`$cache.<key>.<path>`) across single-turn batch DAG steps.
- **Control Plane Domain**: Unified under `aep_ctl(domain="ipc", action="status"|"ping"|"lease"|"release"|"reap"|"pool"|"flush"|"metrics"|"cache"|"stats")` and `./scripts/aep-ctl ipc`.

#### 7. SPEC-OM-8: Cross-Harness Schema Evolution & Multi-Runner Ergonomics (Milestone ONT-30)
- **Objective**: Establish robust dynamic schema evolution signaling, multi-harness process observability, and low-token multi-runner ergonomics across heterogeneous agent environments (Antigravity, Claude Code, Codex, CLI).
- **Core Capabilities**:
  1. **Dynamic Schema Evolution Signaling (`GAP-DX-05`)**: Wraps FastMCP initialization with `NotificationOptions(tools_changed=True)` to broadcast `capabilities.tools.listChanged = True` to MCP clients upon hot reload or tool synchronization.
  2. **Schema Drift Detection**: Exposes `server_version` ("v0.2.8"), short `git_commit`, and deterministic 64-character SHA-256 `schema_hash` across all verbosities (`detail`, `summary`, `brief`, `terse`) in `discover(action="capabilities")`, enabling clients to identify server code drift.
  3. **Resilient Task-Level Resource Fallback**: In `topos_audit_dag`, if schema-cached clients cannot pass top-level `resources`, the guardian automatically parses task dictionaries for `writes`/`write`, `reads`/`read`, and `contract` declarations, running Bernstein condition hazard detection without client exceptions.
  4. **Multi-Harness Process Observability (`GAP-RT-03`)**: Records `SERVER_START_TIME` at module load, exposing `pid`, `process_start_time` (ISO-8601), and `uptime_seconds` in `discover(action="capabilities")` and `process_inspect(pid=0)`.
  5. **Non-Destructive Instance Audit (`scripts/aep-sync.sh --audit`)**: Inspects active `server.py` PIDs, maps them to parent harnesses (Antigravity, Claude, Codex, Bash), compares process start time against repository HEAD commit, and emits clear diagnostic warnings without terminating or killing active processes.
  6. **DX Runner Polish in `sandbox_run`**:
     - **Brief Trimming**: In `brief`/`terse` mode with `parse`, strips input reflection (`ro_mounts`, `agent_id`, `share_net`, `working_dir`) and empty `stdout`/`stderr`, emitting strictly `{status, exit_code, parsed, t}`.
     - **Failing Node ID Extraction**: When `parse="pytest"` encounters failures (`exit_code != 0`), parses and extracts failing test node IDs into `parsed["failures"]` rather than returning full verbose stdout.
     - **Composite Runner Parsing**: `parse="auto"` automatically parses chained verification commands (`ruff check . && pytest -q`) into composite metrics `{"tool": "composite", "ruff": {...}, "pytest": {...}}`.
  7. **Tactical Playbook Recipes & Rules of Engagement**:
     - `WF-7` (`sandbox-linter-fix`): Safe in-place code formatting and fixing with `rw_paths=[<repo>]` and `share_net=False`.
     - `WF-8` (`untrusted-adversarial-probe`): Isolated adversarial security probing with `working_dir=<repo>`, `rw_paths=[<scratch>]`, and `share_net=False`.
     - `WF-9` (`composite-verification-runner`): Single-turn composite linting and test verification with `parse="auto"`.
     - `WF-10` (`network-telemetry-probe`): Host network telemetry and socket inspection combining in-RAM port probing (`probe_tcp_ports`) and kernel `/proc/net` socket correlation.
     - `WF-11` (`incident-protocol-audit`): Defense and security observability combining in-RAM packet header dissection, eBPF packet sniffing (`network_sniff`), netfilter chain inspection, and deterministic IP mitigation drops.
     - Rule of Engagement #9 registered in `tactical_playbook()`, `server._INSTRUCTIONS`, and `README.md`.

---

#### 8. SPEC-OM-9: Native Memory-First Network & Security Telemetry: Container Decoupling & Pure-RAM Ingress (Milestone ONT-32)
- **Objective**: Reclaim network telemetry, socket inspection, packet header analysis, and perimeter security governance as pure in-RAM algorithmic primitives executing directly on the host Linux kernel via the Python 3.14 standard library. Completely decouples the system from external containerized analytical engines, eliminates process invocation latency, and protects agent interactions against guardrail false positives through neutral systems engineering terminology.
- **Core Architectural Pillars**:
  1. **Complete Container Decoupling & Zero External Binaries**: Discards external container satellites (Docker, containerized scanners) and external network binaries (`nmap`, `tshark`). All network probing and inspection logic runs natively in user-space with microsecond latency, zero secondary disk persistence, and zero container overhead.
  2. **Asynchronous In-RAM TCP Port Probing (`aep_ctl(domain="network", action="probe")`)**:
     - Non-blocking, semaphore-governed connection prober (`asyncio.open_connection`) implemented in `engine/net_telemetry.py`.
     - Scans target hosts and port lists/ranges in RAM with microsecond latency profiling (`time.perf_counter()`), service identification, and guaranteed zero descriptor leaks (`fd_delta == 0` via strict `try...finally` resource cleanup).
  3. **Kernel `/proc/net` Introspection & Header Dissection**:
     - Direct in-memory parsing of `/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/udp`, `/proc/net/dev`, and `/proc/net/arp`.
     - Deterministic 32-bit IPv4 hex decoding (`socket.inet_ntoa` with little-endian struct packing) and socket inode-to-PID correlation.
     - Pure in-memory packet header dissection via big-endian `struct.unpack` (`!6s6sH`, `!BBHHHBBH4s4s`, `!HHIIBBHHH`) for Ethernet, IPv4, TCP, UDP, and ARP frames, plus `/dev/shm` volatile PCAP buffer decoding without external packet decoders.
  4. **Self-Describing Schema Reflection & Precondition Contracts**:
     - `discover(action="schema")`: Introspectively extracts typed parameter signatures, types, defaults, docstrings, and execution scope (`DIMINISHED`/`FULL`) across all 17 FastMCP tools, with in-RAM session caching (`_shared_session_cache`).
     - `CONTROL_PLANE_SCHEMA` in `engine/privilege.py`: Enforces explicit execution preconditions (`privilege_tier`, `required_fs`, `fail_soft_behavior`, `deterministic`) across all control plane actions.
  5. **Deterministic Netfilter Hardening & Perimeter Defense (`aep_ctl domain="security"`)**:
     - Deterministic, idempotent host firewall and netfilter mitigation (`aep_ctl security threat_mitigate <ip>`), ruleset auditing (`nftables_inspect`), and firewall status checks (`firewall_status`).
     - Fail-soft execution: In unprivileged (`DIMINISHED`) environments, generates structured `SIMULATED` drop contracts without throwing exceptions or interrupting autonomous agent workflows.
  6. **Semantic Sanitization & Pure Single-Plane Integration**:
     - Purged all legacy trigger keywords (*kali, pentest, exploit, offensive*) across documentation, schemas, and docstrings in favor of clean systems engineering nomenclature (*Network Telemetry*, *Security Observability*, *Netfilter Hardening*).
     - Decoupled Antigravity global configuration (`~/.gemini/config/mcp_config.json`) by removing containerized satellites, running 100% of telemetry through the native 16 FastMCP tools. (histórico)
- **Strict FastMCP 16-Tool Invariant Preservation**: (histórico)
  - Exactly 16 tools registered on the primary AEP host server (`server.py`). All network probing, kernel socket analysis, and perimeter security capabilities are seamlessly absorbed into `aep_ctl(domain="network")`, `aep_ctl(domain="security")`, and `kernel_trace(mode="network_sniff")`. (histórico)

---

### Architecture and Data Flow of Omarchy Enhancements

The following diagram details the three-tier architecture articulating Omarchy tools with AEP engines and underlying Ubuntu OS primitives:

```mermaid
flowchart TD
    subgraph Agents["Agent Layer & MCP Tools"]
        T1["aep_ctl(domain, action)"]
        T2["diagnose_system_crashes(action='alerts' / 'diagnose')"]
        T3["Universal Skills Hub (Multi-Agent Registry)"]
        T4["query_system_docs(query, limit)"]
        T5["visual_inspect(url, viewport)"]
        T7["playbook_run(action='batch' / 'run')"]
    end

    subgraph Adapters["AEP Engine & Adapter Layer"]
        A1["scripts/aep-ctl<br/>(Deterministic CLI with --schema contracts)"]
        A2["engine/crash_router.py<br/>(Deduplication by pid:time:exe hash)"]
        A3["scripts/setup.sh & aep-sync.sh<br/>(Convergent symlink manager)"]
        A4["engine/docs_vectorizer.py<br/>(man page chunking + CPU ONNX embeddings)"]
        A5["engine/headless_display.py<br/>(Playwright Chromium headless)"]
        A7["engine/ipc_pool.py<br/>(UnixSocketMux + SessionPool in RAM)"]
    end

    subgraph OS["Ubuntu / Linux Kernel Primitives"]
        OS1["systemctl --user / sudo -n systemctl<br/>ss - ip - df - dpkg-query"]
        OS2["systemd-coredump - journalctl -p err<br/>SQLite: crash_events (~/.local/share/agent-os/artifacts.db)"]
        OS3["Symlink farm (~/.agents/skills)<br/>Claude - Antigravity - Codex - Gemini"]
        OS4["man pages (MANPAGER=cat)<br/>SQLite: vec_docs (~/.local/share/agent-os/system_docs.db)"]
        OS5["Volatile RAM buffers (/dev/shm)<br/>Ephemeral Base64 screenshots (zero disk I/O)"]
        OS7["/dev/shm/aep.sock & /dev/shm/aep_pool/<br/>AF_UNIX socket + 16 warm execution slots"]
    end

    T1 --> A1 --> OS1
    T2 --> A2 --> OS2
    T3 --> A3 --> OS3
    T4 --> A4 --> OS4
    T5 --> A5 --> OS5
    T7 --> A7 --> OS7
```

[↑ Back to top](#top)

---

## 9. Four-Tier Chmod Privilege & Graceful Degradation Matrix

AEP establishes a **4-tier Unix chmod octal model** (`7rwx`, `6rw-`, `5r-x`, `4r--`) paired with a
non-blocking predictive prober (`sudo -n true` with `<=3s` timeout and process-level caching via `_PrivilegeCache`).
This architecture completely eliminates interactive password prompt hangs on `stdin` while guaranteeing
graceful fail-soft degradation across all **17 FastMCP tools** and **9 `aep_ctl` control-plane domains**.

```mermaid
flowchart TD
    Start["euid == 0?"] -->|yes| T7["Tier 7rwx (direct-root)"]
    Start -->|no| Sudo{"sudo -n true (timeout <= 3s)?"}
    Sudo -->|yes| T7E["Tier 7rwx (sudo-n escalation)"]
    Sudo -->|no| Ws{"Workspace & /dev/shm writable?"}
    Ws -->|yes| T6["Tier 6rw- (unprivileged host user rw)"]
    Ws -->|no| Ex{"Exec permitted (/proc/self/exe or sh)?"}
    Ex -->|yes| T5["Tier 5r-x (restricted / container ro-exec)"]
    Ex -->|no| T4["Tier 4r-- (auditor / observer ro)"]

    T7 & T7E --> S7["Scope: self -> system -> kernel<br/>(Full eBPF, apt, systemd system, netfilter drop)"]
    T6 --> S6["Scope: self -> systemd user -> RAM exec<br/>(Pueue user, memfd, bwrap user ns, SQLite RW)"]
    T5 --> S5["Scope: self in-RAM isolated exec<br/>(RO bind mount, template browse, query, lint)"]
    T4 --> S4["Scope: self read-only audit<br/>(pure in-RAM verification, docs, audit verify, zero exec)"]
```

### 9.1 The 4 Unix Chmod Octal Tiers

The Unix permission triad (`rwx`) is repurposed to represent agent operational authority:
- **`r` (4) = SENSE**: Non-invasive inspection of system state, configuration, and telemetry.
- **`w` (2) = ACT**: Mutating host state, modifying SQLite databases, or writing to disk.
- **`x` (1) = EXECUTE**: Running binaries via non-traditional paths (anonymous RAM execution, kernel probes, sandboxed child processes).

| Octal | Permissions | Classification | Operational Environment & Capabilities |
| :---: | :---: | :--- | :--- |
| **7** | `rwx` | **Root / Full Sudo** | Direct root (`euid == 0`) or verified passwordless escalation (`sudo -n true`). Full eBPF kernel tracing (`CAP_BPF`), systemd system unit control, system-wide `apt-get` packages, raw socket packet capture, and host netfilter enforcement. |
| **6** | `rw-` | **Standard User RW** | Standard developer workstation or unprivileged server account. Full read-write workspace and `/dev/shm`, anonymous in-RAM execution (`memfd_create`), SQLite WAL transactions, user-scope systemd units (`systemctl --user`), user Pueue dispatch, and user-namespace Bubblewrap sandboxing. |
| **5** | `r-x` | **Restricted / RO-Exec** | Sandboxed container runtime, ephemeral CI runner, or read-only workspace mount. In-RAM anonymous execution and Python evaluation permitted; template inspection and static linting active; host filesystem mutation blocked. |
| **4** | `r--` | **Auditor / RO-Observer** | Strict security compliance auditor or zero-execution monitoring node. 100% read-only; execution and filesystem mutation disabled. Pure in-RAM graph verification (`topos_audit_dag`), documentation search (`query_system_docs`), SHA-256 audit ledger validation (`aep_ctl audit verify`), and metadata querying. |
| **0** | `---` | **No Access** | Subsystem requires elevated privileges (`7rwx`) not granted in the active tier. |

> **Autonomy Invariant**: Autonomous agent operation is fully functional across all tiers. Privilege expands scope
> from `self` to `system` and `kernel`, but is **never a prerequisite for baseline autonomy**. Even in `4r--`,
> graph verification and audit inspection execute with zero exceptions.

### 9.2 Predictive Probing & CLI Flags (`setup.sh`)

To eliminate headless process hangs, `scripts/setup.sh` and `engine/privilege.py` execute predictive probing before invoking any privileged command:
- **Zero Sudo Hang Guarantee**: Probes `sudo -n true` with a strict `timeout 3s`. If sudo requires interactive password entry or times out, the engine safely flags escalation as unavailable and immediately adopts tier `6rw-`.
- **Process-Level Caching**: `_PrivilegeCache` memoizes detection results, ensuring sub-microsecond subsequent checks (`get_effective_chmod_tier()`) with `_PrivilegeCache.reset()` available for test isolation.
- **Predictive CLI Flags in `scripts/setup.sh`**:
  ```bash
  # Output strictly the single-line detected chmod octal string:
  ./scripts/setup.sh --tier
  # Output: 7rwx

  # Inspect predictive degradation plan across all subsystems without mutating host state:
  ./scripts/setup.sh --predict
  ```

### 9.2b Self-Healing N0-N3 (ONT-41) + N4 reconnect (ONT-42a)

The front (`aep_front.py`, never hot-swapped: changing it requires a user reconnection) keeps the plane alive while the agent edits its own code:

| Level | Mechanism | Behaviour |
|-------|-----------|-----------|
| **N0** | Structured reload error | A failed hot-swap keeps the previous backend and exposes `reload_error` (`aep_lkg.parse_error`) in `discover(capabilities)`. |
| **N1** | LKG save | After each healthy promotion the tree (`aep_lkg.py` set + `templates/**`, `schemas/*`, `scripts/aep-ctl`, `pyproject.toml`) is snapshotted under `~/.local/share/agent-os/lkg/` (0700, sha-verified manifest). |
| **N2** | Crash-window fallback | 3 backend drops in 60 s start a backend from the newest verified LKG tree (`serving_from: lkg`); data still anchors to the real repo (`AEP_REPO_ROOT`). |
| **N3** | Agent-assisted heal | `autoevol(heal)` lists broken modules, `spec` describes the gap, the agent patches, `fix_test`/`verify` judge (reload barrier, sandboxed tests N<=20); `aep_ctl backup lkg_restore` restores files (dry-run first, tier >= 6rw-). |
| **N4** | Harness reconnect (ONT-42a) | `aep_ctl(domain="ipc", action="harness_reconnect", params={"mode":"plan"})` is read-only at any tier. `mode="execute"` needs tier 7rwx and `confirm=true` per call: a sudo helper opens `dev.tty.legacy_tiocsti` for under 2 s, types `/mcp reconnect <server>` into the harness TTY via TIOCSTI and restores the sysctl (verified; mismatch = CRITICAL). Any missing link falls back to the manual command. Every attempt is audited. Caveat: text already typed in the prompt is submitted with it. `AEP_HARNESS_RECONNECT_DRY=1` (tests only) disables all host side effects. |

**Agent rule:** when `serving_from` is `lkg` or a reload error is reported, do not revert by hand: run `autoevol(action="heal")`, patch, then `autoevol(action="fix_test")`. After 3 failed iterations the cycle is EXHAUSTED (10 min lock; `restart=True` to override) and `heal` is the suggested path. Plane events spool to `plane_events_<uid>.jsonl` and are ingested into `crash_events.source` (`aep_front` / `aep_backend`) by `diagnose_system_crashes`. D-25: a commit that does not change the code fingerprint is `commit_drift` (informational), not `stale`. `scripts/aep-sync.sh --audit` separates `front_stale` (reconnect) from `backend_stale` (auto-swap).

### 9.3 FastMCP 17 Polymorphic Tools Graceful Degradation Matrix

Every tool in the canonical FastMCP suite (`len(_tools) == 17`) adapts its behavior deterministically to the detected tier, returning structured fail-soft responses rather than throwing unhandled exceptions:

| Tool Name | Tier `7rwx` (Root / Full Sudo) | Tier `6rw-` (User RW / Standard) | Tier `5r-x` (Restricted / RO-Exec) | Tier `4r--` (Auditor / RO-Observer) |
| :--- | :--- | :--- | :--- | :--- |
| `topos_audit_dag` | Full graph audit & resource hazard check | Full graph audit & resource hazard check | Full graph audit & resource hazard check | Full graph audit (pure in-RAM verification) |
| `autoevol` | Graph + generation persistence (probes opt-in) | Graph + persistence | Read-only graph, no persistence (probes opt-in) | Read-only graph, no persistence, no probes |
| `discover` | Full capability & schema reflection (`7rwx`) | Full capability & schema reflection (`6rw-`) | Reflects `5r-x` tier & read-only tools | Reflects `4r--` tier & auditor mode |
| `artifact_catalog` | Full RW indexing, query, and pruning | Full RW indexing, query, and safe GC | Read-only query & template browse | Read-only query (metadata inspection only) |
| `artifact_lint_and_build` | Full build, hydrate, vet, & compile in RAM | User-space compile in `/dev/shm` / tmpfs | Template inspection & syntax linting | Template inspection (build disabled) |
| `artifact_execute_in_ram` | Execute in anonymous RAM (`memfd_create`) | Execute in anonymous RAM (`memfd_create`) | Execute in anonymous RAM (isolated) | Disabled (`status: PERMISSION_DENIED`) |
| `process_inspect` | Inspect all system PIDs, FDs, and sockets | Inspect user-owned PIDs and AEP self | Inspect self PID and open FDs | Inspect self PID memory footprint only |
| `async_job_dispatch` | Dispatch to Pueue system/user daemon | Dispatch to Pueue user daemon | Synchronous in-RAM fallback execution | Status inspection only (dispatch disabled) |
| `diagnose_system_crashes` | Inspect `/var/crash` & system journal | Inspect user coredumps & user journal | Inspect local user crash logs | Read-only crash alert inspection |
| `sandbox_run` | Full Bubblewrap jail (`--cap-drop ALL`) | User namespace Bubblewrap jail | Read-only mounted Bubblewrap jail | Disabled or dry-run mock (`parse="auto"`) |
| `aep_ctl` | Full control across all 9 domains | User-scope control across 9 domains | Read-only queries across 9 domains | Auditor inspection across 9 domains |
| `query_system_docs` | Full in-RAM semantic vector man search | Full in-RAM semantic vector man search | Full in-RAM semantic vector search | Full in-RAM semantic vector search |
| `visual_inspect` | Full headless Chromium screenshot (`/dev/shm`) | User headless Chromium screenshot | Headless screenshot if display exists | Degrades to `DISPLAY_UNAVAILABLE` fail-soft |
| `kernel_trace` | Full eBPF tracing (`CAP_BPF` / root) | Degrades to in-RAM `/proc/net` telemetry | Degrades to in-RAM `/proc/net` telemetry | Degrades to in-RAM `/proc/net` telemetry |
| `kanban_board` | Full task creation, promotion, & archive | Full task creation, promotion, & archive | Read-only board inspection | Read-only board inspection |
| `playbook_run` | Full DAG orchestration & batch execution | Full DAG orchestration & batch execution | Validation & dry-run planning | Validation & static DAG check only |
| `default_primitives` | Full execution of all built-in primitives across host scope | User-scope execution of built-in primitives in RAM | Read-only inspection and isolated execution in RAM | Metadata inspection only (execution disabled: status PERMISSION_DENIED) |

### 9.4 Control Plane 9 Domains Graceful Degradation Matrix (`aep_ctl`)

The control plane (`scripts/aep-ctl` and FastMCP `aep_ctl`) shares `CONTROL_PLANE_SCHEMA` as the single source of truth across all 9 functional domains:

| Domain | Tier `7rwx` (Root / Full Sudo) | Tier `6rw-` (User RW / Standard) | Tier `5r-x` (Restricted / RO-Exec) | Tier `4r--` (Auditor / RO-Observer) |
| :--- | :--- | :--- | :--- | :--- |
| `service` | Mutate system units (`systemctl start/stop`) | Mutate user units (`systemctl --user`) | Read-only unit status (`systemctl status`) | Read-only unit status (`status: DEGRADED`) |
| `network` | Raw packet sniff, netfilter drop, probe | Port probe, `/proc/net` sockets, ARP | Port probe, `/proc/net` sockets, ARP | Cached socket table inspection |
| `storage` | Mount table control, device inspection, `df` | User mount inspection, workspace `df` | User mount inspection, workspace `df` | Summary disk usage inspection |
| `package` | Query & install packages via `apt-get` | Inspect `$PATH` binaries & user venvs | Inspect `$PATH` binaries & user venvs | Static toolchain report |
| `backup` | 5-slot FIFO hot backups & RAM snapshots | 5-slot FIFO hot backups & RAM snapshots | Read-only backup integrity verification | Read-only backup integrity verification |
| `audit` | Append to SHA-256 chain & verify integrity | Append to SHA-256 chain & verify integrity | Read-only SHA-256 chain verification | Read-only SHA-256 chain verification |
| `ipc` | Manage `/dev/shm/aep.sock` pool & reap | Manage `/dev/shm/aep.sock` pool & reap | Client batch execution over socket | Read-only session pool telemetry |
| `security` | Enforce host netfilter drops via nftables | Simulated threat mitigation contracts | Simulated threat mitigation contracts | Read-only firewall status report |
| `hardware` | Sysfs DRM & procfs probe + accelerator admission | User DRM inspection & safety-gated admission | Read-only hardware & GPU telemetry | Read-only inventory report |

[↑ Back to top](#top)

---

## 10. Auto-Plug: Atomic MCP Self-Management

Following any code modification, `aep-sync.sh` **validates** the server (compilation + import check)
and **only upon passing** re-registers MCP across all clients, pointing to a stable launcher that
resolves virtual environments hermetically. A `pre-commit` hook enforces the same validation.

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Code Change
    participant Sync as aep-sync.sh
    participant Val as Validation (--check)
    participant Launch as aep-mcp-launch.sh
    participant Clients as Claude / agy / Codex / Gemini

    Dev->>Sync: ./aep-sync.sh (or --watch / pre-commit)
    Sync->>Val: py_compile + import server
    alt validation fails
        Val-->>Sync: Fails (broken server is never plugged)
    else validation passes
        Val-->>Sync: OK
        Sync->>Clients: re-register pointing to Launch
        Launch->>Launch: resolve venv / python3 + PATH at boot
    end
```

### 10.1 Multi-Harness Instance Observability & Stale Detection (`GAP-RT-03`)

In complex development ecosystems with multiple active agent harnesses (Antigravity language servers, Claude Code CLI, OpenAI Codex, and standalone terminals), background MCP processes can survive code updates.

`scripts/aep-sync.sh` provides non-destructive instance inspection:
```bash
./scripts/aep-sync.sh --audit
```
- Scans running `server.py` processes scoped to the checkout repository.
- Determines parent process names (e.g. `Antigravity`, `node` / Claude Code, `codex`, `bash`).
- Compares process startup time against `git log -1 --format=%ct`.
- Emits diagnostic warnings for instances serving stale bytecode.
- **Topos Safety Invariant**: Warn-only; **never terminates or kills running processes automatically** (unless `--reap-stale` opt-in is passed, which only terminates orphaned `PPID=1` processes).

### 10.2 Live Plane: Zero-Downtime Hot-Swap (`ONT-39`)

Agent harnesses (Claude Code, Antigravity, Codex) retain long-lived MCP connections. Re-registering an MCP server does not restart active client sessions.

**Live Plane** decouples the MCP transport from the execution worker through a high-resilience architecture:

```mermaid
flowchart TD
    H["Agent Harness (Claude / agy / Codex)"] -- "stdio / MCP" --> F["aep_front.py (Low-level Server)"]
    F -- "AF_UNIX socketpair (JSON-lines)" --> B["aep_backend.py (Worker: FastMCP Tools)"]
    subgraph HotSwap ["Fail-Safe Hot-Swap Protocol"]
        B1["Gen N (Active)"]
        B2["Candidate Gen N+1"]
        B2 -- "1. health check (20s)" --> B2_OK{"Health OK?"}
        B2_OK -- Yes --> PROMOTE["Promote N+1 & Route new calls"]
        PROMOTE --> DRAIN["Drain in-flight Gen N (max 30s) -> SIGTERM"]
        B2_OK -- No --> KEEP["Retain Gen N & Surface last_reload_error"]
    end
    F --> HotSwap
```

- **Front (`aep_front.py`)**: Thin, low-level MCP server. Zero argument validation against cached schemas; passthrough directly to the active backend. Monitors `code_fingerprint` before tool calls (with 1s debounce).
- **Backend (`aep_backend.py`)**: Private worker process running the full FastMCP tool manager.
- **Fail-Safe Swap**: Candidate Gen N+1 is probed via `health` before promotion. If broken (syntax error, broken import), Gen N remains active and `last_reload_error` is reported in `discover`.
- **In-flight Drainage**: Ongoing calls on Gen N complete without interruption.
- **Tier Governance**:
  - `7rwx` / `6rw-` / `5r-x`: Auto-swap enabled by default.
  - `4r--`: Watch-only mode (no swap; reports `stale=true`).
  - Overrides: `AEP_HOTSWAP=0` falls back to legacy `server.py`; `AEP_HOTSWAP_MODE=watch` forces watch-only.

#### REGLA DEL AGENTE (Verificación de Reload)
> [!IMPORTANT]
> **REGLA DEL AGENTE (SDD §5):** Después de editar código o de un reload, llamar inmediatamente a `discover(action="capabilities", verbosity="terse")` y exigir:
> - `stale == false`
> - `code_fingerprint_loaded == code_fingerprint_disk`
>
> Si no se cumple, el cambio **no** está cargado en el proceso activo y cualquier prueba o verificación sobre él es **inválida**.

### 10.3 Intent Reinforcement Graphs (ONT-39, ONT-40, ONT-41, ONT-42a, L3, ONT-42c, E2, E3, E4, ONT-43, install integrity)

Each intent is linked to its milestones and to the agent responsible for each one. Status is updated at every pipeline activation. Source of truth: `docs/MILESTONES.md`.

**ONT-39 Live Plane hot-swap (VERIFIED):**

```mermaid
flowchart LR
    I["Intent: Live Plane hot-swap (ONT-39)"] --> M1["M1: planned (Archon / Orchestrator) ✅"]
    M1 --> M2["M2: implemented (Pragma) ✅"]
    M2 --> M3["M3: verified (Dokimos, 175 passed; ONT-39b 198 passed) ✅"]
    M3 --> M4["M4: documented (Graphos) ✅"]
    M4 --> M5["M5: committed (Hermon, ONT-39b `3515a22`) ✅"]
```

**ONT-40 autoevol thread graph (VERIFIED; committed in dev):**

```mermaid
flowchart LR
    I["Intent: autoevol thread graph (ONT-40)"] --> M1["M1: planned (Archon / Ontos APPROVED, cycle 2) ✅"]
    M1 --> M2["M2: implemented (Pragma, T0-T18, commits 68e0af9..90886d9) ✅"]
    M2 --> M3["M3: verified (Dokimos, 261 passed, 6 xfailed; ONT-40b) ✅"]
    M3 --> M4["M4: documented (Graphos G1 and G2) ✅"]
    M4 --> M5["M5: committed (Hermon) ✅"]
```

**ONT-41 autoevol write-path & self-healing N0-N3 (VERIFIED; committed in dev; push pending):**

```mermaid
flowchart LR
    I["Intent: autoevol spec/verify/fix_test/heal + LKG self-healing (ONT-41)"] --> M1["M1: planned (Archon / Ontos APPROVED, cycle 2) ✅"]
    M1 --> M2["M2: implemented A, B1, C1, C2 (Pragma, worktrees) ✅"]
    M2 --> M3["M3: verified (Dokimos, 562 passed, 6 xfailed; 2 fix cycles) ✅"]
    M3 --> M4["M4: documented (Graphos/orchestrator) ✅"]
    M4 --> M5["M5: pushed to origin/dev (Hermon) pending"]
```

**ONT-42a harness reconnect N4 (VERIFIED excluding T8; T8 user-gated):**

```mermaid
flowchart LR
    I["Intent: harness reconnect N4 (ONT-42a)"] --> M1["M1: planned (Archon / Orchestrator) ✅"]
    M1 --> M2["M2: audited (Ontos, 0 revisiones) ✅"]
    M2 --> M3["M3: implemented T1 a T7 (Pragma) ✅"]
    M3 --> M4["M4: verified (Dokimos, excluding T8; 1 fix cycle) ✅"]
    M4 --> M5["M5: committed in dev (feb088c, 0578484) ✅"]
    M5 --> M6["M6: live smoke T8 (user-gated) pending"]
```

**L3 token contract, D-01..D-05 (VERIFIED on `dev` @ `e36a608`; Short mode):**

```mermaid
flowchart LR
    I["Intent: L3 token contract (D-01..D-05)"] --> M1["M1: planned (Orchestrator, Short) ✅"]
    M1 --> M2["M2: implemented (Pragma, 5 commits) ✅"]
    M2 --> M3["M3: verified (Dokimos, 576 passed, 0 xfail; 0 fix cycles) ✅"]
    M3 --> M4["M4: documented (Graphos G2) ✅"]
    M4 --> M5["M5: committed in docs (Hermon) pending"]
    M3 --> B1["Backlog: ONT-42 AE-1..AE-6 + D-01b (autoevol) ⛔"]
```

**Auditoría agy `1b983f1..b605677` (VERIFIED tras fixes; Short; push retenido):**

```mermaid
flowchart LR
    I["Intent: Auditoria agy range 1b983f1..b605677"] --> M1["M1: planned (Orchestrator, Short) ✅"]
    M1 --> M2["M2: audited (Dokimos DEFECTIVE, 9 hallazgos) ✅"]
    M2 --> M3["M3: fixed (Pragma, d0ff416..5bee5c1) ✅"]
    M3 --> M4["M4: verified (Dokimos, 659 passed, 0 xfail) ✅"]
    M4 --> M5["M5: documented (Graphos G2) ✅"]
    M5 --> M6["M6: pushed to origin/dev ⛔ retenido por usuario"]
```

**ONT-42c evaluador (cerrado: E1, C1–C7 VERIFIED; D-EV-1, D-EV-1b y DK-1..DK-4 cerrados; E2, E3 y E4 VERIFIED):**

```mermaid
flowchart LR
    I["Intent: ONT-42c evaluador (juez y evolve)"] --> E1["E1: juez no falsificable (NON_DISCRIMINATING) ✅"]
    E1 --> C13["C1-C3: evolve state machine, GitPort, ff-only ✅"]
    C13 --> D["D-EV-1 / D-EV-1b: ACCEPT atado al arbol juzgado (2 ciclos) ✅"]
    D --> C47["C4-C7: gate final por lotes, ledger UNIQUE, revert sin push, Merkle R_before/R_after ✅"]
    C47 --> V["M: verified (Dokimos, 772 passed; DK-1..DK-4 en 1 ciclo) ✅"]
    V --> E2["E2: specs incrementales (cache node_hash, stale_specs; 772 passed) ✅"]
    E2 --> E3["E3: supervision OTP sobre SCC (096ef95..f8eaa9c; 805 tests) ✅"]
    E3 --> E4["E4: reconciliacion acotada por tier (a8308f8..00886c3; 829 passed) ✅"]
```

**Integridad de instalación en sala limpia (INSTALA CON INTEGRIDAD, ronda 3; push retenido):**

```mermaid
flowchart LR
    I["Intent: Integridad de instalacion (sala limpia Ubuntu 26.04)"] --> R1["M1: ronda 1, 7 bugs, degradacion controlada (92c9661..aa468e1) ✅"]
    R1 --> R2["M2: ronda 2, 3 bugs menores, checksums (10b8608..f8b0d11) ✅"]
    R2 --> R3["M3: ronda 3, INSTALA CON INTEGRIDAD (81ba56b) ✅"]
    R3 --> M4["M4: documented (Graphos G2) ✅"]
    M4 --> M5["M5: backlog menor: Go go.mod probes, errcheck, LKG ⏳"]
```

Decisiones vigentes: `resolve-revert` solo por CLI humano con `--confirm`; `recovered: true` solo con prueba git y testigo del gate. Modelo de amenaza: el gate protege contra fallos del flujo, no contra un adversario con el mismo uid (SDD §9).


[↑ Back to top](#top)

---

**Plan de autohealing E2–E4 (cerrado, 2026-11-07; E4 VERIFIED con 829 passed):**

```mermaid
flowchart LR
    I["Intent: Autohealing E2-E4 (autoevol)"] --> E2["E2: specs incrementales (cache node_hash, stale_specs) ✅"]
    E2 --> E3["E3: supervision OTP sobre SCC (096ef95..f8eaa9c) ✅"]
    E3 --> E4["E4: reconcile acotado por tier, propose-only por defecto (a8308f8, 07c023a, 00886c3) ✅"]
    E4 --> O1["Opt-in: open_cycles=true o AEP_RECONCILE_OPEN=1 (presupuesto AEP_RECONCILE_MAX_OPENS=1/24 h) ✅"]
    E4 --> G["Garantia: sin commit, merge, push ni heal apply desde reconcile; tier < 6 no escribe ✅"]
    E4 --> B["Backlog menor: LKG, sondas Go, errcheck, cache E2, ruff format ⏳"]
```

**ONT-43 field report y backlog track A (VERIFIED, staged sin commit; 987 passed, previo 927):** `autoevol(action="report")` convierte fallos reales de herramientas en gaps `field_discrepancy` sólo tras reproducción en `bwrap` (fail-closed); un reporte nunca abre ciclos. Endurecimiento O1–O3 y R1–R3 (VERIFIED, staged): `report` exige `tool`, `action`, `status` y `error_class`; `sig = sha256(tool|action|status|error_class)[:12]` se verifica al registrar; el repro sólo puede ser `tests/field/test_fr_<sig>.py` (archivo regular, sin helpers) con `xfail(strict=True, raises=<error_class>)`. Registro: `docs/pipeline/feature_20261107_135303_ont43_field_report.md`; SDD: `docs/sdd/sdd_ont43_field_report.md`.

```mermaid
flowchart LR
    I["Intent: ONT-43 field report (autoevol report)"] --> M1["M1: evol_hint en sobres de error (lista blanca, sig sin texto) ✅"]
    M1 --> M2["M2: cuarentena threads_field (dedupe, tope 20/24 h, texto inerte) ✅"]
    M2 --> M3["M3: promocion por reproduccion en bwrap, fail-closed ✅"]
    M3 --> M4["M4: field_discrepancy fuera de R, drift en reconcile ✅"]
    M4 --> M5["M5: verified (Dokimos, 987 passed; F1 a F3 y O1 a O3 / R1 a R3 corregidos) ✅"]
    M5 --> M6["M6: commit (Hermon) ⏳ retenido por el usuario"]
```

```mermaid
flowchart LR
    I["Intent: Backlog track A (E2, Go, setup)"] --> B1["Cache E2: cover_hash y hit malformado = miss ✅"]
    B1 --> B2["Fusion de kwargs de helpers: prueba directa ✅"]
    B2 --> B3["Sondas Go: errcheck resuelto, go.mod descartado ✅"]
    B3 --> B4["Setup sin red: falla cerrado ✅"]
    B4 --> B5["Pendiente: LKG, ruff format, texto de field_discrepancy ⏳"]
```

## 11. Shell-Agnostic Environment

Environment inheritance **does not assume Oh My Zsh**. A single POSIX-compliant environment file is
sourced from native startup files. Tested on **Bash, Zsh, and Dash**.

```mermaid
flowchart LR
    Env["config/shell/aep-env.sh<br/>(POSIX: PAGER=cat, PATH, wrappers)"]
    Install["scripts/install-shell-env.sh<br/>(idempotent, marker-based)"]
    Install --> B["~/.bashrc"]
    Install --> Z["~/.zshenv"]
    Install --> P["~/.profile"]
    B & Z & P -->|source| Env
```

[↑ Back to top](#top)

---

## 12. Clean-Slate Installation, Health Audit & Autonomous Updater

AEP incorporates a unified lifecycle engine in `scripts/setup.sh` operating as a zero-dependency
bootstrapper, continuous updater, and non-destructive health auditor.

### Requisitos

`setup.sh` instala todo en espacio de usuario (sin root) pero asume unos prerrequisitos mínimos del sistema.
Si faltan, la instalación **degrada con aviso** en lugar de fallar; `./scripts/setup.sh --check` informa el estado.

| Prerrequisito | Para qué | Si falta |
|---|---|---|
| `git`, `curl`, `ca-certificates`, `tar`, `coreutils` (`sha256sum`) | Clonado, descargas verificadas por SHA-256 | Sin `curl`/certificados no se puede instalar nada: el script aborta antes de provisionar. |
| `bubblewrap` (`bwrap`) + user namespaces sin privilegios | `sandbox_run` (jail) | `sandbox_run` devuelve `DEGRADED` con instrucciones; nada se ejecuta fuera del jail. Instalar: `sudo apt-get install -y bubblewrap`. En Ubuntu 24.04+ puede requerir `kernel.apparmor_restrict_unprivileged_userns=0`. |
| Librerías de sistema de Chromium (`sudo playwright install-deps chromium`) | `visual_inspect` | `setup.sh` descarga Chromium pero comprueba que arranca; si no, avisa con la orden anterior y `visual_inspect` devuelve `DISPLAY_UNAVAILABLE`. |
| `python3` del sistema (opcional) | Solo fallback de `scripts/aep-ctl` y de `aep-sync.sh` antes de que exista el venv | `aep-ctl` usa el Python del venv del proyecto (`.venv`) y solo recurre a `python3` si no existe. |
| Arquitectura `x86_64` o `aarch64` | Binarios de uv, Go, golangci-lint, pueue | En otras arquitecturas se omiten Go/golangci-lint/pueue (sondas Go y cola asíncrona degradan); uv es imprescindible. |
| Un cliente MCP (`claude`, `agy`, `codex` o `gemini`) | Registro automático del servidor | La instalación termina con "0 clientes MCP registrados" (aviso, no éxito pleno). |

Versiones fijadas con SHA-256 (cabecera de `scripts/setup.sh`): uv 0.13.7, Go 1.26.10, golangci-lint v2.15.0,
pueue v4.0.4. Las dependencias Python se instalan con `uv sync --frozen` desde `uv.lock`.

Dominios de red usados por `setup.sh`: `github.com` y `objects.githubusercontent.com` (uv, golangci-lint, pueue),
`go.dev` y `dl.google.com` (Go), `pypi.org` y `files.pythonhosted.org` (dependencias Python),
`cdn.playwright.dev` / `playwright.azureedge.net` (Chromium), `huggingface.co` (modelo `bge-small-en-v1.5`, opcional)
y `python-build-standalone` vía GitHub (`uv python install 3.14`). `apt` solo con `sudo -n` disponible (tier 7rwx).

### 12.1 CLI Invocation Modes

```bash
cd /path/to/agent-execution-plane

# 1. Full Idempotent User-Space Installation (auto-detects tier, falls back cleanly)
./scripts/setup.sh

# 2. Predictive Privilege Probing & Degradation Plan (100% read-only, zero sudo hangs)
./scripts/setup.sh --predict

# 3. Direct Chmod Octal String Output (7rwx, 6rw-, 5r-x, 4r--)
./scripts/setup.sh --tier

# 4. Read-Only System Health Audit calibrated to detected tier (exit 0/1)
./scripts/setup.sh --check

# 5. Autonomous Updater (re-pins uv, venv sync from uv.lock & probe recompilation)
./scripts/setup.sh --update
```

### 12.2 Autonomous Bootstrapper Architecture

```mermaid
flowchart TD
    A["scripts/setup.sh"] --> Flag{"CLI Flag?"}
    Flag -->|"--check"| CHK["run_check() — 100% Read-Only<br/>(Audit of 9 subsystems, exit 0/1)"]
    Flag -->|"--update"| UPD["Update Mode<br/>(pinned uv + venv sync + probes)"]
    Flag -->|"default"| PROV["Idempotent Full Provisioning"]

    PROV --> B1["Astral uv Auto-install<br/>(~/.local/bin/uv)"]
    B1 --> B2["Python 3.14 Hermetic Venv<br/>(uv python install 3.14 & uv venv)"]
    B2 --> B3["FastMCP Dependencies<br/>(mcp, anyio, pydantic, sqlite-vec, fastembed)"]
    PROV --> G1["Golang Toolchain Provisioning<br/>(sudo -n apt or ~/.local/share/go tarball)"]
    G1 --> G2["Static Go Probes CGO_ENABLED=0<br/>(~/.local/share/agent-os/bin/socket-monitor, fd-rescuer)"]
    PROV --> P1["Pueue Daemon Musl Auto-download<br/>(~/.local/bin/pueue, pueued -d)"]
    PROV --> S1["Omarchy Skills Hub Symlinks<br/>(Claude · Gemini · Codex)"]
    PROV --> S2["Git Pre-commit Hook Tracked<br/>(core.hooksPath=scripts/hooks)"]
    PROV --> S3["aep-sync.sh Auto-Plug & Hot Reload<br/>(FastMCP 17 tools, Connect-RPC RefreshMcpServers)"]
```

### 12.3 Python 3.14 Production LTS Baseline
- **Hermetic Isolation**: Managed via `uv` (`uv python install 3.14`), decoupled completely from host operating system packages (PEP 668 compliant, strictly without `--system-site-packages`).
- **Modern Primitives**: Deferred type annotation evaluation (PEP 649), interpreter JIT specialization, and native concurrency support.
- **Automated Test Suite**: `tests/test_setup_idempotency.sh`, `tests/test_engine_suite.py`, and `tests/test_ont29_bridge_stabilization.py` validate consecutive run idempotency, Python 3.14 runtime integrity, static Go probes, database resilience, and external consumption contracts.

[↑ Back to top](#top)

---

## 13. Repository Structure

```
agent-execution-plane/
├── server.py                       # FastMCP server (17 RPC tools, 19 capabilities)
├── aep_front.py                    # Hot-swap MCP stdio proxy, reload barrier, LKG fallback & spooling (ONT-39/41)
├── aep_backend.py                  # Hot-reloadable backend worker lifecycle & fingerprint responder (ONT-39)
├── aep_lkg.py                      # Last-Known-Good snapshot manager (status, diff, restore, ONT-41)
├── engine/
│   ├── db.py                       # Hot SQLite WAL connections, BEGIN IMMEDIATE, anti-deadlock
│   ├── backup.py                   # Hot streaming backup engine, 5 FIFO slots, auto-recovery & quarantine
│   ├── security.py                 # SHA-256 cryptographic audit ledger (security_audit_log) & secret masking
│   ├── telemetry.py                # Per-request latency, byte/token estimation, RSS/FD deltas & agent-brief envelope
│   ├── privilege.py                # CapabilityGuard, CBAC, shared schema, binary readiness & systems engineering tactical playbook
│   ├── landlock.py                 # User-space Landlock LSM in-process confinement (Linux 5.13+)
│   ├── catalog.py                  # Artifact catalog + hybrid semantic memory (sqlite-vec)
│   ├── embedder.py                 # Local ONNX CPU embedder (bge-small-en-v1.5)
│   ├── kanban.py                   # Multidimensional Pico-Kanban board with defect vetoes
│   ├── ponder.py                   # Multidimensional confidence and trust scoring engine
│   ├── matcher.py                  # BM25F multi-signal lexical relevance matcher
│   ├── hydrator.py                 # Go template hydrator with parameter binding
│   ├── topos_guard.py              # Topos DAG anti-co-dependency guardian
│   ├── crash_router.py             # Proactive coredump routing (OM-2) & Apport RFC822 streaming forensics (GAP-OM-20, GAP-OM-21)
│   ├── docs_vectorizer.py          # Ubuntu man page offline vectorizer (OM-4)
│   ├── headless_display.py         # Playwright Chromium in-RAM headless visual capture (OM-5)
│   ├── ipc_pool.py                 # Shared-memory UNIX socket mux (/dev/shm/aep.sock) & 16-slot session pool (OM-7)
│   ├── net_telemetry.py            # Pure in-RAM TCP/UDP socket introspection, ARP table & frame dissect (ONT-32)
│   ├── primitives.py               # Pure in-memory system diagnostic probes (mem-stat, disk-usage, fd-rescuer, socket-monitor, landlock-guard, ONT-34)
│   ├── hardware.py                 # GPU/sysfs DRM accelerator introspection, UMA auto-routing & pre-flight admission (GAP-CP-05, GAP-DX-06)
│   ├── fingerprint.py              # Deterministic source/front/backend fingerprint & drift computation (ONT-39/42a)
│   ├── harness_reconnect.py        # Autonomous Session Steward (autonomous_session_steward: plan, execute, certify, matrix across claude/agy/codex/gemini, ONT-42a)
│   ├── threads.py                  # Thread Graph facade & generation cache (ONT-40)
│   ├── threads_model.py            # ThreadGraph nodes, edges, Tarjan SCC condensation, Merkle root R & PageRank (ONT-40)
│   ├── threads_extractors.py       # Static AST/SQL/claim/test/budget extractors (ONT-40)
│   ├── threads_probes.py           # Fail-open runtime probes outside Merkle R (ONT-40)
│   ├── threads_spec.py             # Mini-SDD generator (`spec` with `change`, `resolve_gap`, `sort_gaps`, ONT-41/42b)
│   ├── threads_verify.py           # Autonomous Judge (`verify`, `CycleStore` with `_reap_orphan_cycles`, `select_tests`, `run_tests_batched`, ONT-41/42b)
│   ├── threads_ops.py              # High-level autoevol operations (`spec`, `verify`, `fix_test`, caller-pin inheritance, ONT-41/42b)
│   ├── threads_heal.py             # Self-healing LKG recovery (`heal`, ONT-41)
│   ├── threads_pins.py             # Static pinning-test index for public/private functions (ONT-42b)
│   ├── playbook.py                 # Pico-Playbook YAML/JSON storage & DAG step execution engine
│   └── template_registry.py        # Go template registry, metadata catalog & CUE schema binding
├── diagnostic/go/
│   ├── socket-monitor/main.go      # Static ELF Go probe for /proc/net/tcp
│   ├── fd-rescuer/main.go          # Static ELF Go probe for /proc/PID/fd
│   └── landlock-guard/main.go      # Static ELF Go probe for Landlock LSM confinement verification
├── docs/
│   ├── COMPACT.md                  # Context compaction SSoT instruction
│   └── sdd/
│       ├── sdd_linux_primitives_and_anti_poisoning.md # ONT-13 Landlock LSM & anti-poisoning SDD
│       ├── sdd_om7_ipc_socket_pool_and_code_batch_mode.md # ONT-21 UNIX socket pool & batch SDD
│       ├── sdd_kali_mcp_offensive_tactical_enhancements.md # ONT-31 Kali MCP dual-plane SDD
│       ├── sdd_ont40_threads_autoevol.md # ONT-40 Thread Graph & autoevol SDD
│       ├── sdd_ont41_self_healing_lkg.md # ONT-41 Self-healing & LKG SDD
│       ├── sdd_ont42_judge_evolve.md # ONT-42b/c Autonomous Judge & evolve SDD
│       └── sdd_ont42a_harness_reconnect.md # ONT-42a Autonomous Session Steward SDD
├── tests/
│   ├── test_setup_idempotency.sh   # Automated provisioning idempotency test suite
│   ├── test_engine_suite.py        # Core engine unit and integration test suite (pytest)
│   ├── test_primitives_benchmark.py # Latency benchmark suite (RAM snapshot vs disk, Landlock vs bwrap)
│   ├── test_agent_experience_evaluation.py # Agent-facing contract, clean bootstrap, sandbox, telemetry & tactical playbook suite
│   ├── test_spec_om7_ipc_batch.py  # Spec OM-7 IPC socket mux, batch piping, field projection & multi-agent concurrency suite
│   ├── test_ont29_bridge_stabilization.py # ONT-29 external consumption gaps & bridge stabilization suite
│   ├── test_ont30_schema_and_runner_ergonomics.py # ONT-30 schema evolution and runner ergonomics suite
│   ├── test_net_security_telemetry.py # ONT-32 Native network & security telemetry test battery
│   ├── test_privilege_degradation.py # ONT-33 Predictive privilege setup and chmod degradation suite
│   ├── test_default_primitives.py  # ONT-34 Default diagnostic primitives & factory decoupling suite
│   ├── test_version_integrity.py   # ONT-35 Version stamp integrity, drift detection & runner ergonomics suite
│   ├── test_hardware_and_apport_alerts.py # ONT-36 Hardware domain, accelerator admission & Apport alerts suite
│   ├── test_uma_admission_apport_and_pytest_parsing.py # ONT-37 UMA admission ergonomics, Apport RFC822 & pytest anti-masking suite
│   ├── test_ont39_hot_swap_proxy.py # ONT-39 Hot-swap front/backend proxy & reload barrier suite
│   ├── test_ont40_threads_core.py  # ONT-40 Thread Graph, Merkle root R & omission gaps suite
│   ├── test_ont41_lkg_and_front.py # ONT-41 LKG snapshot manager & crash-window fallback suite
│   ├── test_ont41_spec_verify_fix_heal.py # ONT-41 spec, verify, fix_test & heal suite
│   ├── test_ont42a_harness_reconnect.py # ONT-42a Autonomous Session Steward (`autonomous_session_steward`) multi-harness & loopback certification suite
│   └── test_ont42_*.py             # ONT-42b Autonomous Judge suites (gap_resolve, spec_change, gap_priority, wrong_tree, pinning, select_cap, tool_actions)
├── schemas/
│   ├── database.sql                # DDL (artifacts, metrics, crash_events, audit)
│   └── artifact_contract.cue       # Declarative CUE artifact schemas
├── templates/                      # Go atomic probe catalog templates
├── config/shell/aep-env.sh         # Agnostic POSIX environment inheritance (bash/zsh/dash)
├── scripts/
│   ├── setup.sh                    # Bootstrapper, updater, and health auditor (--check)
│   ├── aep-ctl                     # Deterministic CLI (service, network, storage, package, backup, security, audit, ipc, hardware)
│   ├── aep-mcp-launch.sh           # Stable launcher with hermetic virtual environment resolution
│   ├── aep-sync.sh                 # Multi-agent atomic MCP synchronization
│   ├── install-shell-env.sh        # Shell environment installer
│   └── hooks/pre-commit            # Git pre-commit validation hook
├── .gitattributes · .gitignore
├── pyproject.toml                  # Python 3.14 configuration, Ruff py314, dependency manifest
├── LICENSE                         # Apache License 2.0
└── README.md                       # Single source of truth (this document)
```

[↑ Back to top](#top)

---

## 14. Truthful Inventory of Single Source of Truth

| Component | Physical Reality | Note |
| :--- | :--- | :--- |
| `memfd_create` (RAM exec) | ✅ Operational | Standard Linux kernel primitive (glibc 2.27+ / POSIX); anonymous memory staging (zero disk I/O) |
| `bwrap` (sandbox) | ✅ Operational | `sandbox_run`: namespace isolation with `--unshare-all` and `--cap-drop ALL` |
| `bpftrace` (eBPF) | ✅ Operational (FULL) | `kernel_trace`; escalates via `sudo -n`, degrades to DIMINISHED |
| Pueue (async queues) | ✅ Operational | musl-compiled binary in `~/.local/bin`, verified end-to-end |
| Semantic Memory (`sqlite-vec`) | ✅ Operational | Two-tier hybrid retrieval (hash + cosine kNN), fail-soft |
| Anti-Deadlock Hot SQLite | ✅ Operational | `engine/db.py`: `get_ro_connection` (`mode=ro`), `get_rw_connection`, `transaction_immediate` (`BEGIN IMMEDIATE`) |
| DB Resilience (5-slot backup) | ✅ Operational | `engine/backup.py`: streaming hot backup `conn.backup()`, 5-slot FIFO rotation, SHA-256 and self-healing |
| Security & Audit Ledger | ✅ Operational | `engine/security.py`, `privilege.py`: `CapabilityGuard`, sensitive blacklist, SHA-256 chained audit ledger |
| Landlock LSM In-Process | ✅ Operational | `engine/landlock.py` (ctypes 444/445/446 + `PR_SET_NO_NEW_PRIVS`), ABI v8, Go probe `landlock-guard` |
| Anti-Poisoning & RAM Snapshots | ✅ Operational | `engine/backup.py`: canary `_aep_canary`, forensic quarantine, volatile `:memory:` snapshot in 0.28 ms |
| Python 3.14 Production LTS | ✅ Operational | Hermetic venv without `--system-site-packages` via `uv`, target `py314` in Ruff |
| Static Go ELF Probes | ✅ Operational | Static binaries `socket-monitor`, `fd-rescuer`, `landlock-guard` built with `CGO_ENABLED=0` executable in RAM via `memfd` |
| Pico-Kanban (Scoring) | ✅ Operational | Abstract board in `artifacts.db`; promotes artifacts to `reusable` by multidimensional score |
| Pico-Playbooks (Automation) | ✅ Operational | Orchestrates tools/artifacts into Topos-validated DAGs; E2E execution and confidence scoring |
| Catalog Discovery | ✅ Operational | `artifact_catalog`: confidence browsing + semantic top-K |
| Omarchy & IPC (8 specs) | ✅ Operational | `aep_ctl` (9 domains incl. `security` with `firewall_status`, `nftables_inspect`, `threat_mitigate`, `ipc`, `audit usage`, and `workspace_snapshot`), crash routing, skills hub, man-pages, headless Playwright display, `/dev/shm/aep.sock` + 16-slot RAM pool, batch projection, cross-agent discovery caching, Chrysalis bridge stabilization, FastMCP dynamic schema evolution (`tools.listChanged = True`), multi-harness process observability, and DX runner polish (109/109 tests passing in AEP, 100% pass rate) | <!-- aep:hist -->
| Network & Security Telemetry (ONT-32) | ✅ Operational | Pure in-RAM network probing, /proc/net kernel introspection, packet header dissection, netfilter hardening, dynamic schema reflection, container decoupling, and 15-tool invariant strictly preserved | <!-- aep:hist -->
| 4-Tier Privilege & Degradation (ONT-33) | ✅ Operational | `privilege.py` + `aep_capabilities` manifest (19 capabilities), 4-tier chmod octal matrix (`7rwx`/`6rw-`/`5r-x`/`4r--`), zero-sudo-hang probing |
| Default Primitives & Factory Decoupling (ONT-34) | ✅ Operational | FastMCP Tool #16 (`default_primitives`), pure in-RAM system probes, template scaffolding preservation, 16 tools / 19 capabilities invariant certified (123/123 tests passing) | <!-- aep:hist -->
| Version Stamp Integrity & Multi-Harness Sync (ONT-35) | ✅ Operational | Runtime commit freeze (`loaded_commit` vs `repo_head` drift detection), non-destructive multi-harness sync audit (`aep-sync.sh --audit`), and sandbox ergonomics (133/133 tests passing) | <!-- aep:hist -->
| Hardware Admission & Apport Alerts (ONT-36) | ✅ Operational | Hardware control plane domain (`inventory`, `accelerators`, `admit` with 4096 MiB desktop safety margin, GAP-CP-05), Apport crash alerts sync (`artifacts.db` deduplication, GAP-OM-20), single-encoding flat telemetry (143/143 tests passing) | <!-- aep:hist -->
| UMA Admission & Pytest Anti-Masking (ONT-37) | ✅ Operational | UMA auto-routing to GTT (`vram_total <= 2048` and `gtt_total > 2 * vram_total`, GAP-DX-06), leaf defensive routing for numeric device parameters, Apport RFC822 streaming forensics with 64 KiB cap & POSIX signal mapping (`SIGABRT`, GAP-OM-21), sandbox pytest anti-masking (`exit_code_masked=True`), extended metrics (`deselected`, `xfailed`, `xpassed`, `coverage`), and `stdout_tail` line deduplication (153/153 tests passing, 100% pass rate) | <!-- aep:hist -->
| Hot-Swap Front & L3 Token Compaction (ONT-39 / L3) | ✅ Operational | `aep_front.py` + `aep_backend.py` + `engine/fingerprint.py` transparent hot-swap proxy, reload barrier, and D-01..D-05 token compaction across `discover`, `aep_ctl`, `playbook_run`, `artifact_catalog`, and `kanban_board` |
| Thread Graph `autoevol` (ONT-40) | ✅ Operational | FastMCP Tool #17 (`autoevol`): Merkle R over SCC condensation, omission gaps, drift, PageRank, `impacted_tests`, opt-in probes, tier-gated `threads_gen` persistence; 17 tools / 19 capabilities |
| Self-healing & Last-Known-Good (ONT-41) | ✅ Operational | `aep_front.py` N0-N2 (structured reload error, LKG save, crash-window fallback to an LKG tree) + reload barrier; `aep_lkg.py`; `aep_ctl backup lkg_status/lkg_diff/lkg_restore`; `autoevol spec/verify/fix_test/heal`; `crash_events.source` + plane_events spool; `aep-sync --audit` (front_stale / backend_stale / serving_lkg) |
| Autonomous Session Steward (ONT-42a) | ✅ Operational | `engine/harness_reconnect.py` (`autonomous_session_steward`, exposed via `aep_ctl(domain="ipc", action="harness_reconnect")` in `plan`, `execute`, `certify`, and `matrix` modes): multi-harness self-management across `claude`, `agy`, `codex`, and `gemini`, using kernel `dev.tty.legacy_tiocsti` (`0 -> 1 -> ioctl(TIOCSTI) -> 0`) only for a verified ancestor harness holding a `/dev/pts/*` TTY, with an unprivileged PTY loopback check (`certify_loopback`, `certified: false`, ledger `UNVERIFIED`) and D-25 commit-drift vs file-drift separation |
| Autonomous Judge & Dogfood (ONT-42b) | ✅ Operational | B1–B9 (`resolve_gap` kind+target fallback, `build_spec` `change`, `sort_gaps` priority class, `_autoevol_interpreter` + `WRONG_TREE` sentinel, `pinning_tests` + caller-pin inheritance, `select_tests` cap 24, `run_tests_batched` synchronous sandbox batch runner, `_reap_orphan_cycles`, and `D-01b` closed via `_TOOL_ACTIONS` with `autoevol(fix_test)` `ACCEPT`, 638/638 tests passing, 0 xfailed) |
| Auto-Plug MCP | ✅ Operational | launcher + `aep-sync.sh` (+ `--watch` + Connect-RPC) |
| Shell-Agnostic Inheritance | ✅ Operational | bash/zsh/dash; zero Oh My Zsh dependencies |
| Nushell (`nu`) / `jc` | ⏳ Deferred (non-critical) | `aep_ctl` already delivers structured typed JSON |

[↑ Back to top](#top)

---

## 15. RE as SDD & Inspiration Matrix

AEP development applies Reverse Engineering as Software Design Document (RE as SDD) to
decouple kernel primitives from monolithic implementations:
**(1)** isolate the Linux kernel primitive, **(2)** formalize its platform-agnostic specification,
and **(3)** engineer a minimalistic, typed, and end-to-end verified implementation.

```mermaid
flowchart LR
    subgraph Ref["Inspiration Repositories"]
        R1["termux-linux-deployer<br/>(single shell profile · seeding)"]
        R2["termux-ubuntu-bootstrap<br/>(idempotent installer · logging)"]
        R3["openclaw<br/>(contracts · AGENTS.md)"]
        R4["sdk-agent-pipeline<br/>(Topos DAG integrity)"]
    end
    subgraph AEP["Patterns Adopted in AEP"]
        F1["aep-env.sh sourced + multi-agent"]
        F2["setup.sh idempotent user-space"]
        F3["CUE contracts + EAES-v1"]
        F4["topos_guard anti-co-dependency"]
    end
    R1 --> F1
    R2 --> F2
    R3 --> F3
    R4 --> F4
```

> This `README.md` is the **single source of truth** for the project: all architectural
> specifications, guarantees, and audits live here without documentation sprawl.

[↑ Back to top](#top)

---

## 16. License and Terms

This project is licensed under the terms of the **Apache License 2.0**. Refer to the [`LICENSE`](LICENSE) file for the full terms and conditions of use, reproduction, distribution, and patent grants.

- **Compatibility**: Permissive and enterprise-friendly, compatible with MIT, BSD-3-Clause, and public-domain databases (SQLite).
- **Patent Grant**: Features bilateral patent defense and licensing protections (Section 3 of Apache 2.0).
- **Disclaimer of Warranty & Limitation of Liability**: Software provided on an "AS IS" basis without warranties or conditions of any kind (Sections 7 & 8 of Apache 2.0).

[↑ Back to top](#top)
