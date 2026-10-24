# Agent Execution Plane (AEP) — Project Milestones

## 1. Intent Reinforcement Graph

```mermaid
flowchart LR
    I1["Intent: Tool Consolidation Roadmap (33 to 16 Tools)"]
    I1 --> M1["M1: Strategic Roadmap & Phase 1 Planning (Archon) ✅"]
    M1 --> M2["M2: Phase 1 Semantic Memory Fusion (Pragma) ✅"]
    M2 --> M3["M3: Phase 1 Verification 30 Tools (Dokimos) ✅"]
    M3 --> M4["M4: Phase 1 Documented & Committed (Graphos/Hermon) ✅"]
    M5 --> M6["M6: Phase 2 Baseline Registered (Graphos G1) ✅"]
    M6 --> M7["M7: Phase 2 Structural Audit (Ontos) ✅"]
    M7 --> M8["M8: Phase 2 Execution (Pragma) ✅"]
    M8 --> M9["M9: Phase 2 Verification 23 Tools (Dokimos) ✅"]
    M9 --> M10["M10: Phase 2 Rollup & State Sync (Graphos G2) ✅"]
    M10 --> M11["M11: Phase 2 Release Commit (Hermon) ⏳"]
    M11 --> M12["M12: Phase 3 Automation Planning (Archon) ⏳"]
```

## 2. Milestone Matrix

| Phase | Milestone / Intent | Responsible Agents | Target Modules | Status |
| :---: | :--- | :--- | :--- | :---: |
| **Foundation** | Core FastMCP Server, memfd RAM execution, bubblewrap sandbox, dual-tier privilege | Archon, Pragma, Dokimos, Hermon | `server.py`, `engine/privilege.py` | **COMPLETED ✅** |
| **Forensics** | sqlite-vec memory, coredump routing, man-pages semantic store, eBPF tracing | Archon, Pragma, Dokimos, Hermon | `server.py`, `engine/docs_vectorizer.py` | **COMPLETED ✅** |
| **Discovery** | Pico-Playbooks, discover router, bilingual EN/ES lexical matching | Archon, Pragma, Dokimos, Hermon | `server.py`, `engine/matcher.py`, `engine/playbook.py` | **COMPLETED ✅** |
| **Hardening** | Template feedback, cold-aging immunity, Pico tools hardening, safe GC | Archon, Pragma, Dokimos, Hermon | `server.py`, `engine/kanban.py`, `engine/catalog.py` | **COMPLETED ✅** |
| **Consolidation 1** | Unify `semantic_memory` (`artifact_query`, `catalog`, `reindex`, `prune` -> `artifact_catalog`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **VERIFIED & COMMITTED (30 Tools) ✅** |
| **Consolidation 2** | Unify `task_management` (`kanban_*` 8 tools -> `kanban_board` polymorphic action router) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/kanban.py`, `engine/privilege.py` | **VERIFIED & COMPLETED (23 Tools) ✅** |
| **Consolidation 3** | Unify `automation` (`playbook_*` 4 tools -> `playbook_run`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/playbook.py`, `engine/privilege.py` | **NEXT TARGET (Target: 20 Tools) ⏳** |
| **Consolidation 4** | Unify `artifact_synthesis` (`template_*`, `artifact_hydrate`, `lint_and_build` -> `artifact_synthesize`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/hydrator.py` | **QUEUED (Target: 17 Tools)** |
| **Consolidation 5** | Unify `async_dispatch` (`async_job_dispatch`, `inspect` -> `async_job`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **QUEUED (Target: 16 Tools)** |
| **Consolidation 6** | Unify `crash_forensics` (`diagnose_system_crashes`, `check_crash_alerts` -> `crash_forensics`) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **QUEUED (Target: 15 Tools)** |
| **Consolidation 7** | Unify `orientation` & align `process_introspection` (1:1 capability parity) | Archon, Ontos, Pragma, Dokimos, Graphos, Hermon | `server.py`, `engine/privilege.py` | **QUEUED (Target: 16 Tools Parity)** |
