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
    M43 --> M44["M44: Milestone ONT-13 Atomic Release & Version Control Commit (Hermon) ⏳"]
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
