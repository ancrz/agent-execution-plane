# Agent Execution Plane (AEP) — Project Premise & Intent

## 1. Base Premise & Intent

Agent Execution Plane (AEP) is a deterministic, typed, non-blocking systems execution runtime and control plane for AI agents on Ubuntu/Linux.

Traditional shell terminals present severe operational frictions for autonomous agents:
- Interactive pagers and blocking prompts (`less`, `more`, interactive `sudo`).
- Unstructured text output requiring fragile string parsing (`grep`, `awk`, `sed`) that consumes context tokens.
- Ephemeral filesystem clutter and disk contention.

AEP solves these systemic bottlenecks through:
1. **In-RAM Binary Execution**: Volatile execution via Linux `memfd_create` and `/proc/self/fd/`, executing Go ELF binaries directly from memory without secondary disk writes.
2. **Ephemeral Bubblewrap Sandboxing (`bwrap`)**: Strong namespace filesystem isolation preventing destructive side-effects.
3. **Non-blocking Asynchronous Dispatch**: Pueue-backed task execution returning instantaneous `task_id` handles.
4. **Hybrid Semantic Memory (sqlite-vec)**: Dual-signal retrieval matching capabilities and artifacts via `engine/matcher.py` (BM25F) and `engine/ponder.py` (multidimensional trust & confidence scoring).
5. **Pico Engineering Automation Trilogies**:
   - **Pico-Ansible / Hydrator**: Go code synthesis from curated templates.
   - **Pico-Jenkins / Quality Gate**: Static analysis (`go vet` / `golangci-lint`) and compilation with 1-step template-to-binary shortcut.
   - **Pico-Kanban**: Autonomous task state machine (`BACKLOG` -> `SYNTHESIZED` -> `LINTED` -> `CANARY` -> `PROMOTED` / `REJECTED`).
   - **Pico-Playbooks**: Topos-validated DAG workflow orchestration with variable contracts.

## 2. Architectural Invariants

1. **Agents-for-Agents Delivery (P0)**: The primary deliverable is the compiled, verified artifact and autonomous capability expansion without human intervention on deterministic engineering steps.
2. **Dual Engine Architecture**:
   - `engine/ponder.py`: Universal trust arbiter (confidence, multidimensional metrics, veto power, bands: `TRUST`, `CAUTION`, `WARNING`, `REJECT`).
   - `engine/matcher.py`: Universal relevance engine (BM25F multi-signal ranking, token matching, bilingual lexical tags).
3. **Pico-Lifecycle & Memory**:
   - Closed telemetry loop: every tool execution records latency, exit code, and success rates.
   - Kanban state progression: `BACKLOG` -> `SYNTHESIZED` -> `LINTED` -> `CANARY` (auto-advanced by in-RAM run) -> `PROMOTED`.
   - Safe GC: Templates and proven artifacts are protected from pruning; cold-aging never demotes artifacts with 100% success rate.
4. **Tool Reach & Security Boundaries (P1)**:
   - Tool consolidation shrinks tool sprawl while maintaining 100% capability reach.
   - Two-tier privilege model (`FULL` via passwordless `sudo -n` vs. `DIMINISHED` self-scope) mapped to Unix octal permissions (`rwx`).
   - Non-recursion security guarantee: automation tools cannot invoke themselves recursively within playbooks.
   - Ergonomic shortcuts: atomic template-to-binary compilation in RAM.
5. **Subprocess & Descriptor Isolation**:
   - Background daemons must never be launched through `artifact_execute_in_ram`.
   - Volatile in-RAM binary executions explicitly isolate open file descriptors (`pass_fds=(fd,)`) and enforce strict timeouts (`timeout=30`).
   - Daemons (`pueued`) must be spawned detached using `DEVNULL` stdio, `close_fds=True`, and `start_new_session=True` to prevent deadlocks on inherited communication pipes.

## 3. Roadmap: Complete Tool Consolidation (33 → 15 Tools) — 100% COMPLETE

AEP is undergoing a structured 7-phase consolidation roadmap to achieve 1:1 parity between FastMCP tool endpoints and system capabilities:
- **Phase 1: Semantic Memory** (`33 -> 30 tools`) — VERIFIED & COMMITTED.
- **Phase 2: Task Management** (`30 -> 23 tools`) — VERIFIED & COMMITTED.
- **Phase 3: Automation** (`23 -> 20 tools`) — VERIFIED & COMMITTED.
- **Phase 4: Artifact Synthesis** (`20 -> 17 tools`) — VERIFIED & COMMITTED.
- **Phase 5: Async Dispatch & Subprocess Hardening** (`17 -> 16 tools`) — VERIFIED & COMMITTED.
- **Phase 6: Crash Forensics** (`16 -> 15 tools`) — VERIFIED & COMPLETED.
- **Phase 7: Orientation & Introspection Alignment** (`15 tools / 16 capabilities 1:1 parity`) — VERIFIED & COMPLETED.
- **Roadmap Status**: **100% COMPLETE** (All 7 phases verified, 33 → 15 FastMCP tools covering 18 capabilities with 1:1 mapping).
- **Milestone ONT-09: Memory-Mapped Hybrid SQLite Optimization** (`PRAGMA mmap_size 256MB`, 64MB Cache) — VERIFIED & COMMITTED (Task 110 PROMOTED).
- **Milestone ONT-10: Code Modernization & Concurrency** (Python 3.12, Ruff SAST, AnyIO offloading, segregated RO/RW SQLite, BEGIN IMMEDIATE) — VERIFIED & COMMITTED (Task 111 PROMOTED).
- **Milestone ONT-11: Database Resilience & Security Hardening** (5-slot hot backup engine, atomic restore & self-healing, CapabilityGuard, RAM exec safety, multi-agent context segregation, Bubblewrap `--cap-drop ALL`, SHA-256 audit log) — VERIFIED & PROMOTED (Task 112 PROMOTED).
\n
- **Milestone ONT-12: Autonomous Setup & Python 3.14** (Dual-mode bootstrapper & updater `scripts/setup.sh`, Python 3.14 Production LTS migration, hermetic `uv` venv, Go toolchain self-provisioning, static probes `socket-monitor` & `fd-rescuer`, Pueue daemon, bwrap, 7 verification gates) — VERIFIED & PROMOTED (Task 113 PROMOTED 0.9250 TRUST) ✅.
