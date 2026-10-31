# Agent Execution Plane (AEP) — Project Milestones

## 1. Intent Reinforcement Graph

```mermaid
flowchart LR
    I1["Intent: Tool Consolidation Roadmap (33 to 15 Tools)"]
    I1 --> M1["M1: Strategic Roadmap & Phase 1 Planning (Archon) ✅"]
    M1 --> M2["M2: Phase 1 Semantic Memory Fusion (Pragma) ✅"]
    M2 --> M3["M3: Phase 1 Verification 30 Tools (Dokimos) ✅"]
    M3 --> M4["M4: Phase 1 Documented & Committed (Graphos/Hermon) ✅"]
    M4 --> M5["M5: Phase 2 Baseline Registered (Graphos G1) ✅"]
    M5 --> M6["M6: Phase 2 Structural Audit (Ontos) ✅"]
    M6 --> M7["M7: Phase 2 Execution (Pragma) ✅"]
    M7 --> M8["M8: Phase 2 Verification 23 Tools (Dokimos) ✅"]
    M8 --> M9["M9: Phase 2 Rollup & Release (Graphos G2/Hermon) ✅"]
    M9 --> M10["M10: Phase 3 Automation Planning (Archon) ✅"]
    M10 --> M11["M11: Phase 3 Execution & Verification 20 Tools (Pragma/Dokimos) ✅"]
    M11 --> M12["M12: Phase 3 Rollup & Release (Graphos G2/Hermon) ✅"]
    M12 --> M13["M13: Phase 4 Synthesis Planning (Archon) ✅"]
    M13 --> M14["M14: Phase 4 Execution & Verification 17 Tools (Pragma/Dokimos) ✅"]
    M14 --> M15["M15: Phase 4 Rollup & Release (Graphos G2/Hermon) ✅"]
    M15 --> M16["M16: Phase 5 Async Dispatch Planning (Archon) ✅"]
    M16 --> M17["M17: Phase 5 Execution & Verification 16 Tools (Pragma/Dokimos) ✅"]
    M17 --> M18["M18: Phase 5 Rollup & Release (Graphos G2/Hermon) ✅"]
    M18 --> M19["M19: Phase 6 Crash Forensics Planning (Archon) ✅"]
    M19 --> M20["M20: Phase 6 Execution & Verification 15 Tools (Pragma/Dokimos) ✅"]
    M20 --> M21["M21: Phase 6 Rollup & Release (Graphos G2/Hermon) ✅"]
    M21 --> M22["M22: Phase 7 Orientation & Introspection Alignment 15 Tools Parity (Pragma/Dokimos/Graphos) ✅"]
    M22 --> M23["M23: Post-Consolidation Runtime Hardening & Secret Masking (Archon/Ontos/Pragma/Dokimos/Graphos) ✅"]
    M23 --> M24["M24: Complete Hardened Release & Hermon Commit (Hermon) ✅"]
    M24 --> M25["M25: Memory-Mapped Hybrid SQLite Optimization (Archon/Ontos/Pragma/Dokimos/Graphos) ✅"]
    M25 --> M26["M26: Code Modernization, Ruff Linting & Anti-Deadlock SQLite (Archon/Ontos/Pragma/Dokimos/Graphos) ✅"]
    M26 --> M27["M27: 5-Slot Hot Backup Engine & Offensive Countermeasures (Archon/Ontos/Pragma/Dokimos/Graphos) ✅"]
    M27 --> M28["M28: Atomic Release & Version Control Commit (Hermon) ✅"]
    M28 --> M29["M29: Milestone ONT-12 Setup & Python 3.14 Planning (Archon) ✅"]
    M29 --> M30["M30: Milestone ONT-12 Knowledge Graph Weave & Task 113 SYNTHESIZED (Graphos G1) ✅"]
    M30 --> M31["M31: Milestone ONT-12 Topos Structural & Interface Audit (Ontos) ✅"]
    M31 --> M32["M32: Milestone ONT-12 Execution of Bootstrapper & Tooling (Pragma) ✅"]
    M32 --> M33["M33: Milestone ONT-12 Multi-Gate Verification (Dokimos) ✅"]
    M33 --> M34["M34: Milestone ONT-12 Documentation Sync & Baseline Compaction (Graphos G2) ✅"]
    M34 --> M35["M35: Milestone ONT-12 Atomic Release & Version Control Commit (Hermon) ✅"]
    M35 --> M36["M36: Milestone ONT-13 Strategic Plan Formulation (Archon) ✅"]
    M36 --> M37["M37: Milestone ONT-13 Knowledge Graph Weave & Task 114 SYNTHESIZED (Graphos G1) ✅"]
    M37 --> M38["M38: Milestone ONT-13 Topos Structural & Interface Audit (Ontos) ✅"]
    M38 --> M39["M39: Milestone ONT-13 Implementation of Sandboxing & Backups (Pragma) ✅"]
    M39 --> M40["M40: Milestone ONT-13 Gate 2 Interception & Defect Recording (Dokimos/Graphos G2) ✅"]
    M40 --> M41["M41: Milestone ONT-13 Remediation Cycle (Pragma) ✅"]
    M41 --> M42["M42: Milestone ONT-13 Re-Verification All 7 Gates Passed (Dokimos) ✅"]
    M42 --> M43["M43: Milestone ONT-13 Documentation Sync & Baseline Compaction (Graphos G2) ✅"]
    M43 --> M44["M44: Milestone ONT-13 Atomic Release & Version Control Commit (Hermon) ✅"]
    M44 --> M45["M45: Milestone ONT-14 Public GitHub Release Plan Formulation (Archon) ✅"]
    M45 --> M46["M46: Milestone ONT-14 Baseline Weave & Task 115 SYNTHESIZED (Graphos G1) ✅"]
    M46 --> M47["M47: Milestone ONT-14 Topos Structural & Compliance Audit (Ontos) ✅"]
    M47 --> M48["M48: Milestone ONT-14 Implementation of License, EDR Warning & Git Hardening (Pragma) ✅"]
    M48 --> M49["M49: Milestone ONT-14 Multi-Gate Verification Pre-Deploy (Dokimos) ✅"]
    M49 --> M50["M50: Milestone ONT-14 Documentation Rollup & Verification Record (Graphos G2) ✅"]
    M50 --> M51["M51: Milestone ONT-14 GitHub Repository Creation, Remote Sync & Release (Hermon) ✅"]
    M51 --> M52["M52: Milestone ONT-15 Self-Evolutionary Suite & Kali Semantics (Archon/Pragma/Dokimos/Graphos) ✅"]
    M52 --> M53["M53: Milestone ONT-18 Anti-Cascade Battery Planning (Archon) ✅"]
    M53 --> M54["M54: Milestone ONT-18 Knowledge Graph Weave & Task 122 Registered (Graphos G1) ✅"]
    M54 --> M55["M55: Milestone ONT-18 Topos Structural Audit (Ontos) ✅"]
    M55 --> M56["M56: Milestone ONT-18 Anti-Cascade Implementation (Pragma) ✅"]
    M56 --> M57["M57: Milestone ONT-18 Verification 43/43 Tests (Dokimos) ✅"]
    M57 --> M58["M58: Milestone ONT-18 Documentation Sync & Baseline Compaction (Graphos G2) ✅"]
    M58 --> M59["M59: Milestone ONT-18 Atomic Release & Version Control Commit (Hermon) ✅"]
    M59 --> M60["M60: Milestone ONT-21 Spec OM-7 Planning (Archon) ✅"]
    M60 --> M61["M61: Milestone ONT-21 Knowledge Graph Weave & Task #129 Registered (Graphos G1) ✅"]
    M61 --> M62["M62: Milestone ONT-21 Topos Structural Audit (Ontos) ✅"]
    M62 --> M63["M63: Milestone ONT-21 Implementation of IPC Pool & Code Mode (Pragma) ✅"]
    M63 --> M64["M64: Milestone ONT-21 Multi-Gate Verification (Dokimos) ✅"]
    M64 --> M65["M65: Milestone ONT-21 Documentation Sync & Baseline Compaction (Graphos G2) ✅"]
    M65 --> M66["M66: Milestone ONT-21 Atomic Release & Version Control Commit (Hermon) ✅"]
    M66 --> M67["M67: Milestone ONT-22 Omission Gaps & Cache Piping (Orchestrator Inline Plan) ✅"]
    M67 --> M68["M68: Milestone ONT-22 Execution of Gaps 1-4 & Cache Piping (Pragma) ✅"]
    M68 --> M69["M69: Milestone ONT-22 Verification 62/62 Tests (Dokimos) ✅"]
    M69 --> M70["M70: Milestone ONT-22 3-Agent RAM Handoff & Rollup (Graphos G2) ✅"]
    M70 --> M71["M71: Milestone ONT-22 Atomic Commit & Push (Hermon) ✅"]
    M71 --> M72["M72: Milestone ONT-23 Pico-Triad Concurrency Isolation (Orchestrator Inline Plan) ✅"]
    M72 --> M73["M73: Milestone ONT-23 Execution of Pico-Triad Concurrency (Pragma) ✅"]
    M73 --> M74["M74: Milestone ONT-23 Verification 66/66 Tests (Dokimos) ✅"]
    M74 --> M75["M75: Milestone ONT-23 Documentation Rollup & Parity Gate (Graphos G2) ✅"]
    M75 --> M76["M76: Milestone ONT-23 Atomic Commit & Push (Hermon) ✅"]
    M76 --> M77["M77: Milestone ONT-24 Non-Pico Concurrency Protections (Pragma) ✅"]
    M77 --> M78["M78: Milestone ONT-24 Verification 69/69 Tests & Mermaid Lint (Dokimos) ✅"]
    M78 --> M79["M79: Milestone ONT-24 Kali-MCP Semantic Alignment & Rollup (Graphos G2) ✅"]
    M79 --> M80["M80: Milestone ONT-24 Atomic Commit & Push (Hermon) ✅"]
```

## 2. Milestone Matrix

| Phase | Milestone / Intent | Responsible Agents | Target Modules | Status |
| :---: | :--- | :--- | :--- | :---: |
| **Foundation** | Core FastMCP Server, memfd RAM execution, bubblewrap sandbox, dual-tier privilege | Archon, Pragma, Dokimos, Hermon | `server.py`, `engine/privilege.py` | **COMPLETED ✅** |
| **Forensics** | sqlite-vec memory, coredump routing, man-pages semantic store, eBPF tracing | Archon, Pragma, Dokimos, Hermon | `server.py`, `engine/docs_vectorizer.py` | **COMPLETED ✅** |
| **Discovery** | Pico-Playbooks, discover router, bilingual EN/ES lexical matching | Archon, Pragma, Dokimos, Hermon | `server.py`, `engine/matcher.py`, `engine/playbook.py` | **COMPLETED ✅** |
| **Hardening** | Template feedback, cold-aging immunity, Pico tools hardening, safe GC | Archon, Pragma, Dokimos, Hermon | `server.py`, `engine/kanban.py`, `engine/catalog.py` | **COMPLETED ✅** |
| **Consolidation 1** | Unify `semantic_memory` (`artifact_query`, `catalog`, `reindex`, `prune` -> `artifact_catalog`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **VERIFIED & COMMITTED (30 Tools) ✅** |
| **Consolidation 2** | Unify `task_management` (`kanban_*` 8 tools -> `kanban_board` polymorphic action router) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/kanban.py`, `engine/privilege.py` | **VERIFIED & COMMITTED (23 Tools) ✅** |
| **Consolidation 3** | Unify `automation` (`playbook_*` 4 tools -> `playbook_run` polymorphic action router) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/playbook.py`, `engine/privilege.py` | **VERIFIED & COMMITTED (20 Tools) ✅** |
| **Consolidation 4** | Unify `artifact_synthesis` (`template_*`, `artifact_hydrate`, `lint_and_build` -> `artifact_lint_and_build`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **VERIFIED & COMMITTED (17 Tools) ✅** |
| **Consolidation 5** | Unify `async_dispatch` (`async_job_dispatch`, `inspect` -> `async_job_dispatch`) + FD Hardening | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `scripts/aep-sync.sh`, `engine/privilege.py` | **VERIFIED & COMMITTED (16 Tools) ✅** |
| **Consolidation 6** | Unify `crash_forensics` (`diagnose_system_crashes`, `check_crash_alerts` -> `diagnose_system_crashes`) + Subprocess Hardening | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py`, `scripts/aep-sync.sh` | **VERIFIED & COMPLETED (15 Tools) ✅** |
| **Consolidation 7** | Unify `orientation` (`discover`) & dedicated `process_introspection` (`process_inspect`) (15 tools, 16 capabilities 1:1) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **VERIFIED & DOCUMENTED (15 Tools, 16 Capabilities 1:1 Parity) ✅** |
| **Runtime Hardening** | Post-Consolidation Runtime Hardening, Secret Masking & Full README Sync (7 gaps: GAP-SEC-01 to GAP-DOC-01) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `engine/security.py`, `server.py`, `engine/headless_display.py`, `engine/catalog.py`, `scripts/aep-ctl`, `engine/kanban.py`, `README.md` | **VERIFIED & COMPLETED (Task 109 PROMOTED 0.9949) ✅** |
| **Roadmap & Hardening Complete** | Complete 7-Phase Tool Consolidation & Runtime Hardening (33 → 15 Tools, 16 Capabilities) | All Pipeline Agents | Entire AEP Repository | **100% COMPLETED ✅** |
| **Memory-Mapped Hybrid SQLite (ONT-09)** | Standardize 5 SQLite touchpoints on `engine/db.py` (PRAGMA mmap_size 256MB, cache_size 64MB, WAL) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `engine/db.py`, `engine/catalog.py`, `engine/kanban.py`, `engine/crash_router.py`, `engine/playbook.py`, `engine/docs_vectorizer.py`, `server.py` | **COMPLETED & VERIFIED (Task 110 PROMOTED) ✅** |
| **Code Modernization & Concurrency (ONT-10)** | Modernize typing (PEP 585/604), Ruff SAST (P0-P3), AnyIO thread offloading, segregated RO/RW SQLite & BEGIN IMMEDIATE | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `engine/db.py`, `server.py`, `engine/*.py` | **VERIFIED & PROMOTED (Task 111 Score: 0.925 TRUST) ✅** |
| **Database Resilience & Security Hardening (ONT-11)** | 5-slot online hot backup rotation, atomic restore & self-healing, CapabilityGuard, RAM exec safety, multi-agent context segregation, bwrap hardening, SHA-256 audit log | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `engine/backup.py`, `engine/privilege.py`, `engine/db.py`, `engine/security.py`, `server.py`, `scripts/aep-ctl` | **VERIFIED & PROMOTED (Task 112 Score: 0.9250 TRUST) ✅** |
| **Autonomous Setup & Python 3.14 (ONT-12)** | Dual-mode bootstrapper & updater (`scripts/setup.sh`), Python 3.14 LTS migration, hermetic `uv` venv, Go toolchain self-provisioning, static probes (`socket-monitor`, `fd-rescuer`), Pueue daemon, bwrap, and 7 verification gates | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `pyproject.toml`, `scripts/setup.sh`, `scripts/aep-mcp-launch.sh`, `scripts/aep-sync.sh`, `diagnostic/go/`, `tests/test_setup_idempotency.sh`, `README.md` | **VERIFIED & COMMITTED (Task 113 PROMOTED 0.9250 TRUST) ✅** |
| **Kernel Sandboxing & Anti-Poisoning Backups (ONT-13)** | RE as SDD for Linux primitives (`docs/sdd/`), in-process Landlock LSM sandboxing (`engine/landlock.py`), anti-poisoning hot backup engine & quarantine (`engine/backup.py`), volatile RAM micro-snapshots (`engine/db.py`), eBPF security probing (`server.py`), Go static Landlock probe (`diagnostic/go/landlock-guard`), CLI integration (`scripts/aep-ctl`), and verification suite | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `docs/sdd/`, `engine/landlock.py`, `engine/backup.py`, `engine/db.py`, `server.py`, `diagnostic/go/`, `templates/`, `scripts/aep-ctl`, `tests/` | **VERIFIED & PROMOTED (Task 114 Score: 0.9250 TRUST) ✅** |
| **Public GitHub Release & Compliance (ONT-14)** | Apache 2.0 license (`LICENSE`), git config hardening (`.gitignore`, `.gitattributes`), EDR/sandbox warning & license in `README.md`, pre-deploy quality verification, public GitHub repo creation (`ancrz/agent-execution-plane`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `LICENSE`, `.gitignore`, `.gitattributes`, `README.md`, GitHub Remote | **VERIFIED & PROMOTED (Task 115 Score: 0.950 TRUST) ✅** |
| **Self-Evolutionary Suite & Kali Semantics (ONT-15)** | Hermetic clean-install bootstrap, single-source schema (`engine/privilege.py`), bwrap network isolation default (`share_net=False`), request telemetry envelopes, and Kali-MCP tactical playbook (`discover(action="playbook")`). | Archon, Pragma, Dokimos, Graphos, Hermon | `engine/catalog.py`, `engine/kanban.py`, `engine/privilege.py`, `server.py`, `engine/telemetry.py`, `scripts/aep-ctl`, `tests/` | **VERIFIED & PROMOTED (Task 120 Score: 0.950 TRUST) ✅** |
| **Topos Anti-Cascade Battery & Setup Hardening (ONT-18)** | Prevent SQLite `binary_blob` wipe cascade on setup re-run via `COALESCE` upsert, fix Pueue release regex in `scripts/setup.sh`, Step 8 quoted heredoc probe seeding (`socket_monitor`/`fd_rescuer`), and `setup.sh --check` schema/zero-canary verification. | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `engine/catalog.py`, `scripts/setup.sh`, `tests/test_agent_experience_evaluation.py`, `README.md` | **VERIFIED & PROMOTED (Task 122 Score: 0.9940 TRUST, 43/43 Tests) ✅** |
| **IPC Socket Pool & Ephemeral Batch/Code Mode (ONT-21)** | Spec OM-7: Shared-memory UNIX socket session pool (`/dev/shm/aep.sock`), Cloudflare-style ephemeral batch/code mode, server-side field projection (`fields: list[str]`), `ipc` control plane domain, and SDD documentation. | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `engine/ipc_pool.py`, `engine/playbook.py`, `engine/privilege.py`, `server.py`, `scripts/aep-ctl`, `docs/sdd/`, `tests/` | **VERIFIED & PROMOTED (Task 129 Score: 1.0 TRUST, 58/58 Tests) ✅** |
| **Spec OM-7 Omission Gaps & Cache Piping (ONT-22)** | Resolves GAP-OM22-1 (smart dot-path projection fallbacks), GAP-OM22-2 (`failed_steps` diagnostic preservation), GAP-OM22-3 (multi-agent cross-turn RAM session cache piping `$cache.<key>`), and GAP-OM22-4 (`kanban_board` / `artifact_lint_and_build` whitelist & signature filtering). | Orchestrator, Pragma, Dokimos, Graphos, Hermon | `engine/ipc_pool.py`, `server.py`, `engine/playbook.py`, `engine/privilege.py`, `scripts/aep-ctl`, `tests/test_spec_om7_ipc_batch.py`, `README.md` | **VERIFIED & PROMOTED (Task 130 Score: 0.9250 TRUST, 62/62 Tests) ✅** |
| **Pico-Triad Multi-Agent Concurrency Isolation (ONT-23)** | Resolves GAP-OM23-1 (`/dev/shm` Go build slot isolation + atomic `os.replace`), GAP-OM23-2 (`kanban.upsert_build_task` under `transaction_immediate`), GAP-OM23-3 (`playbook_run(action="run")` slot leasing, piping, projection parity), and GAP-OM23-4 (precomputed vector embeddings outside SQLite write transaction). | Orchestrator, Pragma, Dokimos, Graphos, Hermon | `engine/kanban.py`, `engine/catalog.py`, `server.py`, `tests/test_spec_om7_ipc_batch.py`, `README.md` | **VERIFIED & PROMOTED (Task 131 Score: 0.9250 TRUST, 66/66 Tests) ✅** |
| **Non-Pico Concurrency & Semantic Polish (ONT-24)** | Audit ledger mutex lock (`_AUDIT_LOCK`) + `transaction_immediate` preventing SHA-256 chain forks, thread-safe `:memory:` micro-snapshots (`_SNAPSHOT_LOCK` + `check_same_thread=False`), vectorizer double-checked lock, Kali-MCP semantic parity (`_INSTRUCTIONS`, Rule of Engagement #7, recipe `WF-6`), and zero-error Mermaid validation across all 79 diagrams. | Orchestrator, Pragma, Dokimos, Graphos, Hermon | `engine/security.py`, `engine/backup.py`, `server.py`, `engine/privilege.py`, `tests/test_spec_om7_ipc_batch.py`, `README.md`, `docs/` | **VERIFIED & PROMOTED (Task 132 Score: 0.9500 TRUST, 69/69 Tests) ✅** |
| **Omission Gaps Remediation (ONT-25)** | Full resolution of 6 omission gaps across 15 tools: GAP-OM-01 (Go lint/vet action in `artifact_lint_and_build`), GAP-OM-02 (`process_inspect` name/filter search), GAP-OM-03 (`artifact_execute_in_ram` env & stdin injection), GAP-OM-04 (`sandbox_run` env injection), GAP-OM-05 (`kanban_board` add/move aliases), and GAP-OM-06 (`async_job_dispatch` compact status pagination cutting tokens by 97.4%). | Orchestrator, Pragma, Dokimos, Graphos, Hermon | `server.py`, `tests/test_spec_om7_ipc_batch.py` | **VERIFIED & PROMOTED (Task 133 Score: 0.9500 TRUST, 75/75 Tests) ✅** |

---

## 3. Canonical Context Anchors & Architecture Artifacts

This section provides permanent physical context anchors to prevent hallucination and maintain zero-drift continuity across context compactions and LLM agent sessions.

| Milestone | Architecture & SDD Anchor | Strategic Plan & Execution Report | Verification Report & Test Suite | Core Modules & Infrastructure |
| :---: | :--- | :--- | :--- | :--- |
| **ONT-09** | [Hybrid SQLite Architecture](../README.md#2-architecture-overview) | [feature_mmap_hybrid_sqlite.md](pipeline/feature_20261024_115500_mmap_hybrid_sqlite_ram_persistence.md) | [verification_mmap_hybrid_sqlite.md](pipeline/verification_report_20261024_123000_mmap_hybrid_sqlite_ram_persistence.md) | [`engine/db.py`](../engine/db.py), [`engine/catalog.py`](../engine/catalog.py) |
| **ONT-10** | [Ruff SAST & Concurrency Model](../README.md#7-security--privilege-model) | [feature_code_modernization.md](pipeline/feature_20261024_171500_code_modernization_and_concurrency_optimization.md) | [verification_code_modernization.md](pipeline/verification_report_20261024_182500_code_modernization_and_concurrency_optimization.md) | [`engine/db.py`](../engine/db.py), [`server.py`](../server.py) |
| **ONT-11** | [Database Resilience & Backup Pool](../README.md#4-resilience-anti-poisoning--backup-engine) | [feature_backup_restore.md](pipeline/feature_20261025_031500_backup_restore_and_offensive_countermeasures.md) | [verification_backup_restore.md](pipeline/verification_report_20261025_035500_backup_restore_and_offensive_countermeasures.md) | [`engine/backup.py`](../engine/backup.py), [`engine/security.py`](../engine/security.py) |
| **ONT-12** | [Zero-Dependency Setup & Tooling](../README.md#1-installation--zero-dependency-setup) | [feature_autonomous_setup.md](pipeline/feature_20261025_051500_autonomous_setup_updater_and_python314_migration.md) | [verification_autonomous_setup.md](pipeline/verification_report_20261025_054000_autonomous_setup_updater_and_python314_migration.md) | [`scripts/setup.sh`](../scripts/setup.sh), [`scripts/aep-sync.sh`](../scripts/aep-sync.sh) |
| **ONT-13** | [SDD Linux Primitives & Quarantine](sdd/sdd_linux_primitives_and_anti_poisoning.md) | [feature_re_as_sdd_landlock.md](pipeline/feature_20261025_144500_re_as_sdd_landlock_ebpf_and_anti_poisoning_backups.md) | [verification_re_as_sdd_landlock.md](pipeline/verification_report_20261025_154500_re_as_sdd_landlock_ebpf_and_anti_poisoning_backups.md) | [`engine/landlock.py`](../engine/landlock.py), [`engine/backup.py`](../engine/backup.py) |
| **ONT-14** | [Public GitHub Release & License](../README.md#11-license--compliance) | [feature_github_release.md](pipeline/feature_20261028_235800_prepare_and_publish_github_repository_public_release.md) | [verification_github_release.md](pipeline/verification_report_20261028_235900_github_release_pre_deploy.md) | [`LICENSE`](../LICENSE), [`.gitignore`](../.gitignore), [`.gitattributes`](../.gitattributes) |
| **ONT-15** | [EAES & Kali Ergonomics](reports/2026-10-30_aep_agent_experience_evaluation.md) | [feature_self_evolutionary_suite.md](pipeline/feature_20261030_013500_self_evolutionary_suite_and_kali_semantics.md) | [`tests/test_agent_experience_evaluation.py`](../tests/test_agent_experience_evaluation.py) | [`engine/privilege.py`](../engine/privilege.py), [`server.py`](../server.py) |
| **ONT-18** | [Topos Anti-Cascade Specification](../README.md#topos-integrity-protocol) | [feature_ont18_anti_cascade.md](pipeline/feature_20261030_065200_ont18_topos_anti_cascade_battery_and_setup_hardening.md) | [verification_ont18_anti_cascade.md](pipeline/verification_report_20261030_072500_ont18_topos_anti_cascade_battery_and_setup_hardening.md) | [`engine/catalog.py`](../engine/catalog.py), [`scripts/setup.sh`](../scripts/setup.sh) |
| **ONT-21** | [SDD OM-7 UNIX Socket Pool & Batch](sdd/sdd_om7_ipc_socket_pool_and_code_batch_mode.md) | [feature_ont21_ipc_pool.md](pipeline/feature_20261030_110500_ont21_spec_om7_ipc_socket_pool_and_code_batch_mode.md) | [verification_ont21_ipc_pool.md](pipeline/verification_report_20261030_154500_ont21_spec_om7_ipc_socket_pool_and_code_batch_mode.md) | [`engine/ipc_pool.py`](../engine/ipc_pool.py), [`server.py`](../server.py) |
| **ONT-22** | [Omission Gaps & Cache Piping SDD](sdd/sdd_om7_ipc_socket_pool_and_code_batch_mode.md#multi-agent-shared-ram-cache-piping) | [execution_report_ont22.md](pipeline/execution_report_20261030_173000_ont22_spec_om7_omission_gap_remediation.md) | [verification_report_ont22.md](pipeline/verification_report_20261030_174000_ont22_spec_om7_omission_gap_remediation.md) | [`engine/ipc_pool.py`](../engine/ipc_pool.py), [`engine/playbook.py`](../engine/playbook.py) |
| **ONT-23** | [Pico-Triad Multi-Agent Isolation](../README.md#5-pico-triad-multi-agent-concurrency-isolation) | [execution_report_ont23.md](pipeline/execution_report_20261030_190000_ont23_pico_triad_concurrency_isolation.md) | [verification_report_ont23.md](pipeline/verification_report_20261030_193000_ont23_pico_triad_concurrency.md) | [`engine/kanban.py`](../engine/kanban.py), [`engine/catalog.py`](../engine/catalog.py) |
| **ONT-24** | [Non-Pico Concurrency Hardening](../README.md#6-non-pico-system-wide-concurrency-hardening) | [execution_report_ont24.md](pipeline/execution_report_20261030_210000_ont24_non_pico_concurrency_and_kali_semantics.md) | [verification_report_ont24.md](pipeline/verification_report_20261030_211500_ont24_non_pico_concurrency_and_kali_semantics.md) | [`engine/security.py`](../engine/security.py), [`engine/backup.py`](../engine/backup.py), [`server.py`](../server.py) |
| **ONT-25** | [Omission Gaps Remediation SDD](sdd/sdd_om7_ipc_socket_pool_and_code_batch_mode.md) | [aep_battery_and_omission_audit_report.md](../../../brain/efdbc8e5-f4fc-4ce1-9109-6ecce9ffe78b/aep_battery_and_omission_audit_report.md) | [`tests/test_spec_om7_ipc_batch.py`](../tests/test_spec_om7_ipc_batch.py#L750) | [`server.py`](../server.py), [`tests/test_spec_om7_ipc_batch.py`](../tests/test_spec_om7_ipc_batch.py) |

---

## 4. Master Context Anchors Directory

- **FastMCP Stdio Core**: [`server.py`](../server.py) (15 polymorphic tools, strict zero-bloat invariant)
- **Security & RBAC Guard**: [`engine/privilege.py`](../engine/privilege.py) (18 capabilities, dual-tier Unix chmod 777 semantics)
- **Shared-Memory IPC & Batch Engine**: [`engine/ipc_pool.py`](../engine/ipc_pool.py) (`/dev/shm/aep.sock`, 16-slot session pool)
- **Cryptographic Audit Ledger**: [`engine/security.py`](../engine/security.py) (SHA-256 chained tamper-evident audit log)
- **ACID Database & Anti-Poisoning Backups**: [`engine/backup.py`](../engine/backup.py), [`engine/db.py`](../engine/db.py) (5-slot rotation, quarantine, volatile RAM snapshots)
- **Pico Tooling Suite**: [`engine/kanban.py`](../engine/kanban.py) (Pico-Kanban), [`engine/catalog.py`](../engine/catalog.py) (Pico-Jenkins), [`engine/playbook.py`](../engine/playbook.py) (Pico-Ansible)
- **Linux Kernel LSM Sandbox**: [`engine/landlock.py`](../engine/landlock.py) (ABI v1-v4 unprivileged Landlock sandboxing)
- **Deterministic Control CLI**: [`scripts/aep-ctl`](../scripts/aep-ctl) (9 domains, typed JSON contracts)
- **Multi-Agent Ecosystem Sync**: [`scripts/aep-sync.sh`](../scripts/aep-sync.sh) (Claude Code, agy, Codex, Gemini)
- **Comprehensive Test Suite**: [`tests/test_spec_om7_ipc_batch.py`](../tests/test_spec_om7_ipc_batch.py), [`tests/test_agent_experience_evaluation.py`](../tests/test_agent_experience_evaluation.py), [`tests/test_engine_suite.py`](../tests/test_engine_suite.py)
