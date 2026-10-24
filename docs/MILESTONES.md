# Agent Execution Plane (AEP) — Project Milestones

## 1. Intent Reinforcement Graph

```mermaid
flowchart LR
    I1["Intent: Tool Consolidation Roadmap (33 to 16 Tools)"]
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
    M17 --> M18["M18: Phase 5 Rollup & Release (Graphos G2/Hermon) ⏳"]
    M18 --> M19["M19: Phase 6 Crash Forensics Planning (Archon) ⏳"]
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
| **Consolidation 5** | Unify `async_dispatch` (`async_job_dispatch`, `inspect` -> `async_job_dispatch`) + FD Hardening | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `scripts/aep-sync.sh`, `engine/privilege.py` | **VERIFIED & COMPLETED (16 Tools) ✅** |
| **Consolidation 6** | Unify `crash_forensics` (`diagnose_system_crashes`, `check_crash_alerts` -> `diagnose_system_crashes`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **NEXT TARGET (Target: 15 Tools) ⏳** |
| **Consolidation 7** | Unify `orientation` & align `process_introspection` (1:1 capability parity) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **QUEUED (Target: 16 Tools Parity)** |
