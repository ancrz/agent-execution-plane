# Feature Chain Rollup: Pipeline Milestone History (Documents 1–16)

- **Document ID**: `feature_rollup.md`
- **Rollup Period**: 2026-10-23T04:41:56Z — 2026-10-30T06:52:00Z
- **Trigger**: Consolidated Pipeline Rollup Across Documents 1 to 21 (Autonomous Zero-Dependency Setup & Updater, Python 3.14 Production LTS Migration & Complete Tooling Self-Provisioning Complete)
- **Current Active Document**: [`feature_20261030_065200_ont18_topos_anti_cascade_battery_and_setup_hardening.md`](feature_20261030_065200_ont18_topos_anti_cascade_battery_and_setup_hardening.md)
- **Author**: Graphos (Universal State Manager & Knowledge Graph Custodian)

---

## 1. Executive Summary

This rollup breaks recursive token overload across historical pipeline artifacts by consolidating architectural decisions, invariants, and milestone achievements from the pipeline documents into a single dense summary.

```mermaid
flowchart LR
    subgraph RollupChain["Consolidated Pipeline History (Docs 1 to 21)"]
        direction LR
        D1["Doc 1: 044156<br/>(AEP FastMCP Core & Privilege Tiers)"]
        D2["Doc 2: 054100<br/>(sqlite-vec Memory & Crash Forensics)"]
        D3["Doc 3: 125603<br/>(Pico-Playbooks & Discover Router)"]
        D4["Doc 4: 120700<br/>(Template Feedback, Pico Hardening & 33 Tools)"]
        D5["Doc 5: 235900<br/>(Roadmap 33 to 16 Tools & Phase 1 Semantic Memory)"]
        D6["Doc 6: 003200<br/>(Phase 2 Task Management Unification & 23 Tools)"]
        D7["Doc 7: 010200<br/>(Phase 3 Automation Tool Unification & 20 Tools)"]
        D8["Doc 8: 013100<br/>(Phase 4 Artifact Synthesis & 17 Tools)"]
        D9["Doc 9: 015800<br/>(Phase 5 Async Dispatch & FD Hardening: 16 Tools)"]
        D10["Doc 10: 025400<br/>(Phase 6 Crash Forensics & Hardening: 15 Tools)"]
        D11["Doc 11: 034500<br/>(Phase 7 Orientation & Introspection Alignment: 15 Tools Parity)"]
        D12["Doc 12: 102000<br/>(Runtime Hardening, Secret Masking & Full README Sync: 7 Gaps Closed)"]
        D13["Doc 13: 115500<br/>(Memory-Mapped Hybrid SQLite Optimization: PRAGMA mmap_size 256MB)"]
        D14["Doc 14: 171500<br/>(Code Modernization, Ruff SAST, AnyIO & Anti-Deadlock SQLite)"]
        D15["Doc 15: 031500<br/>(5-Slot Hot Backup Engine, Offensive Countermeasures & Multi-Agent Segregation)"]
        D16["Doc 16: 051500<br/>(Autonomous Setup/Updater, Python 3.14 LTS Migration & Self-Provisioning)"]

                D17["Doc 17: 144500<br/>(ONT-13: Landlock LSM, Anti-Poisoning Backups & RAM Micro-Snapshots)"]
        D18["Doc 18: 235800<br/>(ONT-14: Public GitHub Release & Compliance)"]
        D19["Doc 19: 003000<br/>(AEP Agent Experience Evaluation Suite: 39 Passed)"]
        D20["Doc 20: 013500<br/>(ONT-15: Self-Evolutionary Suite & Kali Semantics)"]
        D21["Doc 21: 065200<br/>(ONT-18: Topos Anti-Cascade Battery & Setup Hardening)"]

        D1 --> D2 --> D3 --> D4 --> D5 --> D6 --> D7 --> D8 --> D9 --> D10 --> D11 --> D12 --> D13 --> D14 --> D15 --> D16 --> D17 --> D18 --> D19 --> D20 --> D21
    end
```

---

## 2. Document Evolution Matrix

| Doc # | Filename | Primary Scope & Architectural Additions | Resulting Tool Count | Key Invariants Established |
| :---: | :--- | :--- | :---: | :--- |
| **1** | `feature_20261023_044156.md` | Core FastMCP stdio server architecture; bubblewrap sandbox (`sandbox_run`); memfd in-RAM binary execution (`artifact_execute_in_ram`); headless visual inspection (`visual_inspect`); Unix octal privilege tiers (`FULL` / `DIMINISHED`). | 12 | Root is never assumed; escalation is per-tool via `sudo -n`; fail-soft degradation. |
| **2** | `feature_20261023_054100.md` | SQLite vector search with `sqlite-vec`; crash forensics (`diagnose_system_crashes`, `check_crash_alerts`); local man-page semantic store (`query_system_docs`); eBPF tracing (`kernel_trace`). | 18 | Auto-indexing at write-time; local offline man-pages prevent hallucinated CLI flags; crash dumps inspected without root panic. |
| **3** | `feature_20261023_125603_pico_playbooks_and_discovery.md` | Pico-Playbooks execution engine (`playbook_create`, `playbook_run`, `playbook_list`); semantic orientation router (`discover`); bilingual EN/ES lexical matching in `matcher.py`. | 24 | Discover is the primary agent entrypoint; playbooks enforce DAG dispatch with strict step verification; bilingual tags prevent English query misses. |
| **4** | `feature_20261023_120700_template_feedback_and_pico_hardening.md` | Template feedback loop (`source_template` + `proven` blocks); Pico tools hardening (kebab/snake normalization, SQLite blob in-RAM fallback, Pueue `DEGRADED` fail-soft); safe GC with cold-aging immunity; `playbook_prune` (tool 33); closed 5 tool-graph omission gaps. | 33 | 100% of tools mapped to capabilities; single-use successful artifacts immune to cold-aging; playbooks output full intermediate steps; RAM executions auto-canary Kanban tasks (`LINTED` → `CANARY`). |
| **5** | `feature_20261023_235900_phase1_semantic_memory_unification.md` | 7-Phase Tool Consolidation Roadmap (33 → 16 tools); Phase 1 fusion of `semantic_memory` (`artifact_query`, `artifact_catalog`, `artifact_reindex`, `artifact_prune` into polymorphic `artifact_catalog(action=...)`); Kanban Task 95 promoted to `PROMOTED` at `0.8875 TRUST`. | 30 (VERIFIED) | 1 capability fusion per phase; backward-compatible playbook dispatch aliases; zero disruption to underlying SQLite database; Semgrep 0 findings; all 4 actions + error guards validated. |
| **6** | `feature_20261024_003200_phase2_task_management_unification.md` | Phase 2 fusion of `task_management` (8 `kanban_*` tools into polymorphic `kanban_board(action=...)`); Kanban Task 97 promoted to `PROMOTED` at `0.925 TRUST`. | 23 (VERIFIED) | Polymorphic dispatcher covering 8 actions; strict parameter guards (`PARAM_ERROR`); invalid action handling (`INVALID_ACTION`); Semgrep 0 findings across 1,198 rules; 23 FastMCP schemas verified. |
| **7** | `feature_20261024_010200_phase3_automation_unification.md` | Phase 3 fusion of `automation` (4 `playbook_*` tools into polymorphic `playbook_run(action=...)`); non-recursion invariant enforced; Kanban Task 101 promoted to `PROMOTED` at `0.9979 TRUST`. | 20 (VERIFIED) | Polymorphic dispatcher covering 4 actions (`run`, `create`, `list`, `prune`); parameter guards (`PARAM_ERROR`); invalid action handling (`INVALID_ACTION`); recursion attempt triggers `LINT_ERROR`; Semgrep 0 findings; 20 FastMCP schemas verified. |
| **8** | `feature_20261024_013100_phase4_artifact_synthesis_unification.md` | Phase 4 fusion of `artifact_synthesis` (4 tools `template_catalog`, `template_select`, `artifact_hydrate`, `artifact_lint_and_build` into polymorphic `artifact_lint_and_build(action=...)`); 1-Step Template-to-Binary shortcut; Kanban Task 102 promoted to `PROMOTED` at `0.9964 TRUST`. | 17 (VERIFIED) | Polymorphic dispatcher covering 4 actions (`build`, `catalog`, `select`, `hydrate`); 1-step compilation shortcut; parameter guards (`PARAM_ERROR`, `HYDRATE_ERROR`, `INVALID_ACTION`); Semgrep 0 findings; 17 FastMCP schemas verified. |
| **9** | `feature_20261024_015800_phase5_async_dispatch_unification.md` | Phase 5 fusion of `async_dispatch` (2 tools `async_job_dispatch`, `async_job_inspect` into polymorphic `async_job_dispatch(action=...)`); Subprocess/FD Hardening (Gaps A, B, C); Kanban Task 105 promoted to `PROMOTED` at `0.9955 TRUST`. | **16 (VERIFIED)** | Polymorphic dispatcher covering 4 actions (`dispatch`, `inspect`, `status`, `log`); fail-soft `DEGRADED`; `pass_fds=(fd,)` + `timeout=30` in `artifact_execute_in_ram`; detached auto-start in `_ensure_pueue_daemon()`; schema pruning in `aep-sync.sh`; Semgrep 0 findings; 16 FastMCP schemas verified. |
| **10** | `feature_20261024_025400_phase6_crash_forensics_unification.md` | Phase 6 fusion of `crash_forensics` (2 tools `diagnose_system_crashes`, `check_crash_alerts` into polymorphic `diagnose_system_crashes(action="diagnose"|"alerts")`); Subprocess/FD Hardening in `_safe_run` (`stdin=DEVNULL`, `close_fds=True`, `timeout=15`); Kanban Task 106 promoted to `PROMOTED` at `0.8208 TRUST`. | **15 (VERIFIED)** | Polymorphic dispatcher covering actions (`diagnose`, `alerts`) + alias `check`; subprocess isolation with `close_fds=True`, `stdin=DEVNULL`, `timeout=15`; backward-compatible playbook lambda alias; auto-pruning of `check_crash_alerts.json`; Semgrep 0 findings; 15 FastMCP schemas verified. |
| **11** | `feature_20261024_034500_phase7_orientation_and_process_introspection.md` | Complete Tool Consolidation Roadmap (33 → 15 Tools) — Phase 7: Orientation & Process Introspection Alignment. Unify `discover` and `aep_capabilities` into polymorphic `discover(use_case, action="discover"|"capabilities", limit=3)`. Decouple `process_introspection` from `artifact_execute_in_ram` into dedicated `process_inspect(pid=0, limit=100)`. Synchronize `_CAPABILITIES` (16 capabilities) and bilingual `_CAP_KEYWORDS`. Kanban Task 108 promoted to `PROMOTED` at `0.8208 TRUST`. | **15 (16 Capabilities, 1:1 Parity)** | 100% 1:1 capability mapping (GAP-CP-01, GAP-CP-02, GAP-CP-03 closed); fail-soft process introspection (`/proc/PID/fd` safe classification into socket/pipe/device/file); zero unhandled exceptions on PID termination or permission denials; backward compatibility in playbook dispatchers. Roadmap 100% Complete. |
| **12** | `feature_20261024_102000_runtime_hardening_secrets_and_readme_sync.md` | Post-Consolidation Runtime Hardening, Secret Masking & Full README Sync. Remediated 7 operational gaps: GAP-SEC-01 (secret masking in logs and outputs), GAP-RT-01 (visual_inspect event loop decoupling via ThreadPoolExecutor), GAP-RT-02 (coredumpctl check harmonization across server.py and crash_router.py with exit code 1 handling), GAP-DX-01 (optional category in artifact_catalog query for cross-category kNN search), GAP-DX-02 (socket-to-PID correlation in aep_ctl network listeners), GAP-DX-03 (kanban demotion ergonomics supporting task_id), GAP-DOC-01 (full README sync to 15-tool bundle and diagram harmonization). Kanban Task 109 promoted to `PROMOTED` at `0.9949 TRUST`. | **15 (16 Capabilities, 1:1 Parity)** | Zero credential leakage in outputs and Pueue dumps; zero event loop collisions in headless Playwright; coredumpctl returns clean empty list when no dumps exist; artifact catalog supports global cross-category search; network listeners correlate to PIDs and processes; kanban demote accepts task_id or artifact_name; README.md in 100% sync with active FastMCP tools; Semgrep 0 findings across 1,198 rules. |
| **13** | `feature_20261024_115500_mmap_hybrid_sqlite_ram_persistence.md` | Memory-Mapped Hybrid SQLite Optimization (PRAGMA mmap_size 256MB & 64MB Cache). Standardized all 5 SQLite touchpoints (`catalog.py`, `kanban.py`, `crash_router.py`, `playbook.py`, `docs_vectorizer.py`) onto centralized factory `engine/db.py`. Enforces 256MB mmap zero-copy reads, 64MB RAM page cache, WAL journal mode, 10s busy timeout, normal synchronous, memory temp_store. Exposed live `storage_engine` and `db_telemetry` in `artifact_catalog(action="reindex")`. Passed 1,000-op multithreaded WAL stress test with 0 lock errors in 0.125s. Kanban Task 110 promoted to `PROMOTED` at `0.9958 TRUST`. | **15 (16 Capabilities, 1:1 Parity)** | RAM-speed vector searches and metadata queries backed by 100% Linux kernel zero-copy memory mapping; multi-agent concurrent access without lock contention; 100% ACID persistence on disk for cross-agent reuse; Semgrep 0 findings across 1,198 rules. |
| **14** | `feature_20261024_171500_code_modernization_and_concurrency_optimization.md` | Milestone ONT-10: Python 3.12 code modernization, strict Ruff SAST adherence (0 errors across E,W,F,I,UP,S,BLE,PLW,FURB), FastMCP stdio concurrency offloading via AnyIO worker thread pool (<2ms loop jitter), segregated RO/RW SQLite factory (`get_ro_connection` mode=ro vs `get_rw_connection` autocommit), explicit `transaction_immediate` (`BEGIN IMMEDIATE`) anti-deadlock context manager, WAL autocheckpoint tuning (1000 pages ~4MB), PLW1510 subprocess hardening with POSIX FD isolation (`pass_fds=(fd,)`, `timeout=30`, `close_fds=True`). Passed 6 Dokimos verification gates (1,000 concurrent ops in 0.14s with 0 lock errors); Task 111 promoted to `PROMOTED` at `0.9250 TRUST`. | **15 (16 Capabilities, 1:1 Parity)** | Multi-agent concurrent FastMCP stdio requests never stall event loop; SQLite lock-upgrade deadlocks eliminated; zero silent exception swallows; zero unchecked subprocesses; Semgrep 0 findings across 1,352 rules. |
| **15** | `feature_20261025_031500_backup_restore_and_offensive_countermeasures.md` | Milestone ONT-11: 5-slot online hot backup rotation pool (`conn.backup()`), SHA-256 pre-promotion checksums, atomic restore purging stale `-wal`/`-shm`, self-healing auto-recovery (`verify_and_auto_recover`), `CapabilityGuard` CBAC, in-RAM execution path blacklist (`/etc/shadow`, `/root`, `~/.ssh`), multi-agent caller context segregation (`agent_id: str = "default"`), hardened Bubblewrap (`--unshare-all`, `--cap-drop ALL`, isolated tmpfs), cryptographic SHA-256 hash-chain audit log (`security_audit_log`). Passed 7 Dokimos verification gates; Task 112 promoted to `PROMOTED` at `0.9250 TRUST`. | **15 (18 Capabilities, 1:1 Parity)** | Native SQLite Backup API mandatory for WAL backups (raw copy prohibited); atomic restore must unlink `-wal` and `-shm`; in-RAM binaries cannot access sensitive paths; Bubblewrap drops all capabilities; SHA-256 audit log is immutable with cryptographic hash-chaining; `agent_id` segregates multi-agent contexts. |
| **16** | `feature_20261025_051500_autonomous_setup_updater_and_python314_migration.md` | Milestone ONT-12: Autonomous zero-dependency bootstrapper, updater & health auditor (`scripts/setup.sh`), Python 3.14 Production LTS migration (`requires-python = ">=3.14"`, `target-version = "py314"`), hermetic Astral `uv` toolchain, user-space Golang auto-provisioning, static CGO_ENABLED=0 Go diagnostic probes (`socket-monitor`, `fd-rescuer`), Pueue daemon musl auto-download, bubblewrap containerization, Omarchy skills hub multi-agent symlinking, 6-gate idempotency test suite (`test_setup_idempotency.sh`). Passed 7 Dokimos verification gates (FastMCP parity 15 tools / 18 capabilities, read-only `--check`, idempotency, py314 hermetic venv, static probes, Ruff 0 errors, Semgrep 0 findings); Task 113 promoted to `PROMOTED` at `0.9250 TRUST`. | **15 (18 Capabilities, 1:1 Parity)** | DIR-ONT-01 flag short-circuiting for `--check` (100% read-only, 0 mutations); DIR-ONT-02 atomic staging traps (`rm -rf "$TMP_DIR"`); DIR-ONT-03 subshell PATH injection; DIR-ONT-04 pure hermetic venv without host package pollution (PEP 668); pure user-space non-root fallback; dotfile idempotency (zero duplicate exports). |

| **17** | `feature_20261025_144500_re_as_sdd_landlock_ebpf_and_anti_poisoning_backups.md` | Milestone ONT-13: RE as SDD for Linux primitives (`docs/sdd/`), in-process Landlock LSM sandboxing (`engine/landlock.py`), anti-poisoning hot backup engine & quarantine (`engine/backup.py`), volatile RAM micro-snapshots (`engine/db.py`), eBPF security probing (`server.py`), Go static Landlock probe (`diagnostic/go/landlock-guard`), CLI integration (`scripts/aep-ctl`), and verification suite. Passed 7 Dokimos verification gates; Task 114 promoted to `PROMOTED` at `0.9250 TRUST`. | **15 (18 Capabilities, 1:1 Parity)** | Landlock restricts kernel unprivileged paths; volatile RAM micro-snapshots bypass disk WAL corruption during incident response; backup quarantine isolates malicious payloads. |
| **18** | `feature_20261028_235800_prepare_and_publish_github_repository_public_release.md` | Milestone ONT-14: Public GitHub Release & Compliance. Apache 2.0 license (`LICENSE`), git config hardening (`.gitignore`, `.gitattributes`), EDR/sandbox security warnings & license badge in `README.md`, pre-deploy verification suite, remote sync preparation. Task 115 promoted to `PROMOTED` at `0.950 TRUST`. | **15 (18 Capabilities, 1:1 Parity)** | Zero leaked credentials or test DB artifacts in repository tree; deterministic reproducible builds. |
| **19** | `feature_20261030_003000_aep_agent_experience_evaluation.md` | Agent Experience Evaluation Suite (Gemini Flash 3.8 High & ChatGPT Terra Medium reports). Benchmarked 15 FastMCP tools, evaluated developer ergonomics, token overhead, and error recovery workflows. 39 passed in `tests/test_agent_experience_evaluation.py`. | **15 (18 Capabilities, 1:1 Parity)** | Empirical measurement of LLM agent interaction patterns, tool telemetry, and failure mode recovery. |
| **20** | `feature_20261030_013500_self_evolutionary_suite_and_kali_semantics.md` | Milestone ONT-15: Self-Evolutionary Suite & Kali-Style Semantic Ergonomics. Hermetic clean-install bootstrap in `catalog.py`/`kanban.py` (table guards on `_migrate`), single-source `CONTROL_PLANE_SCHEMA` in `privilege.py`, bwrap network isolation default (`share_net=False`), `RequestTelemetry` and envelope formatting, `discover` playbook `EAES-v2-Kali-Semantic`. 39/39 passed. Task 120 `PROMOTED`. | **15 (18 Capabilities, 1:1 Parity)** | Hermetic bootstrap without pre-existing HOME; bwrap sandbox blocks private paths by default; response token payloads reduced 70-85%. |
| **21** | `feature_20261030_065200_ont18_topos_anti_cascade_battery_and_setup_hardening.md` | Milestone ONT-18: Topos Anti-Cascade Omission Battery & Installation Pipeline Hardening. COALESCE `binary_blob`/`hash` upsert in `engine/catalog.py` to prevent ELF payload wipe on setup re-run, Pueue release tag regex fix in `scripts/setup.sh`, Step 8 quoted heredoc probe seeding with probe aliases (`socket_monitor`/`fd_rescuer`), `setup.sh --check` schema validation & zero-canary verification, 43 regression tests suite, doc badges. Task 122 `PROMOTED` (Score: 0.9940 TRUST, 43/43 Tests Passed). | **15 (18 Capabilities, 1:1 Parity)** | $X_1 \not\to X_2 \not\to X_1$: Re-running installer never wipes compiled binary payloads; diagnostics never mutate production state. |

---

## 3. Core System Invariants (Preserved Across All Phases)

1. **Agents-for-Agents Delivery (P0)**: The primary deliverable is the compiled, validated artifact and autonomous capability expansion without human intervention on deterministic engineering steps.
2. **Dual Engine Architecture**:
   - `engine/ponder.py`: Universal trust arbiter (confidence, multidimensional metrics, veto power, bands: `TRUST`, `CAUTION`, `WARNING`, `REJECT`).
   - `engine/matcher.py`: Universal relevance engine (BM25F multi-signal ranking, token matching, bilingual lexical tags).
3. **Pico-Lifecycle & Memory**:
   - Closed telemetry loop: every tool execution records latency, exit code, and success rates.
   - Kanban state progression: `BACKLOG` → `SYNTHESIZED` → `LINTED` → `CANARY` (auto-advanced by in-RAM run) → `PROMOTED`.
   - Safe GC: Templates and proven artifacts are protected from pruning; cold-aging never demotes artifacts with 100% success rate.
4. **Tool Reach & Security Boundaries (P1)**:
   - Tool consolidation shrinks tool sprawl while maintaining 100% capability reach.
   - All tools strictly operate within local authorizations (FastMCP stdio, bubblewrap, memfd_create).
   - Strict non-recursion invariant: meta-tools like `playbook_run` cannot be dispatched recursively within playbooks.
   - Ergonomic shortcuts: `artifact_lint_and_build(action="build")` executes atomic template-to-binary synthesis without intermediate agent round-trips.
5. **Subprocess & Descriptor Isolation Invariant**:
   - Long-running daemons must never be launched through `artifact_execute_in_ram`.
   - Volatile RAM binary executions must explicitly pass only intended descriptors via `pass_fds=(fd,)`, enforce strict timeouts (`timeout=30`), and guarantee cleanup in `finally` blocks.
   - Background daemons (like `pueued`) must be spawned detached with `stdin=DEVNULL`, `stdout=DEVNULL`, `stderr=DEVNULL`, `close_fds=True`, and `start_new_session=True` to prevent deadlocks on inherited communication pipes.
6. **Hot SQLite Anti-Deadlock Invariant**:
   - Readers strictly use read-only URIs (`file:...?mode=ro`, `query_only = ON`) and never acquire write locks or contend with writer transactions.
   - Writers configure autocommit mode (`isolation_level = None`) and execute write transactions exclusively through `transaction_immediate(conn)` which issues `BEGIN IMMEDIATE` upfront, acquiring the RESERVED lock at transaction start and eliminating lock upgrade deadlocks.
   - `PRAGMA wal_autocheckpoint = 1000` bounds WAL files to ~4MB, preventing fsync latency spikes.
   - Rejection of `multiprocessing` forks with open SQLite WAL file descriptors prevents POSIX lock and shared memory corruption.
7. **FastMCP Event Loop Concurrency Invariant**:
   - All 15 FastMCP tools in `server.py` are declared as non-blocking `async def` coroutines.
   - Synchronous blocking calls (SQLite queries, vector similarity scans, disk I/O, subprocess execution) must be offloaded to worker threads via `await anyio.to_thread.run_sync()`, guaranteeing stdio JSON-RPC loop jitter remains <2.0ms.
8. **Database Resilience & Disaster Recovery Invariant**:
   - SQLite backups under WAL mode must exclusively utilize the native SQLite Backup API (`conn.backup()`); raw filesystem copying (`shutil.copyfile`, `cp`) is strictly prohibited.
   - The backup rotation pool is strictly bounded to 5 FIFO slots (`artifacts.db.bak.1..5`) tracked in `backups_manifest.json` with SHA-256 byte checksums.
   - Atomic database restore must purge stale `-wal` and `-shm` sidecars prior to atomic file replacement (`os.replace`) to prevent catastrophic index desynchronization.
   - Automated self-healing corruption recovery (`verify_and_auto_recover`) automatically falls back to the newest healthy backup slot on corruption.
9. **Offensive Primitive Containment & Multi-Agent Segregation Invariant**:
   - In-RAM binary execution via `artifact_execute_in_ram` is bounded by strict canonical path blacklists (`/etc/shadow`, `/root`, `~/.ssh`, kernel memory nodes) and network egress policy boundaries.
   - `CapabilityGuard` enforces capability-based access control, preventing unprivileged agents from escalating privileges across tools or accessing sensitive operations.
   - Bubblewrap sandboxes enforce complete namespace unsharing (`--unshare-all`), total Linux capability dropping (`--cap-drop ALL`), and ephemeral isolated memory mounts (`--tmpfs /tmp`).
   - All 15 FastMCP tools enforce explicit `agent_id: str = "default"` caller context segregation with per-agent scratchpad directories and Pueue queue groups (`agent_{agent_id}`).
   - All security actions are recorded in an immutable cryptographic SHA-256 hash-chained audit log with universal secret masking ($H_n = \text{SHA256}(H_{n-1} + \dots)$) and active tamper detection.
10. **Autonomous Tooling Provisioning & Environment Hermeticity Invariant**:
    - System bootstrapping and updates must be autonomous and zero-dependency, self-provisioning `uv`, Python 3.14, Go, and Pueue in user-space if non-root.
    - Read-only health inspection (`--check`) must short-circuit upfront before any directory creation or network fetch (DIR-ONT-01), guaranteeing zero disk mutations and deterministic exit codes.
    - Remote downloads must be guarded with atomic cleanup traps (`rm -rf "$TMP_DIR"` on EXIT/INT/TERM, DIR-ONT-02).
    - Subshell and child processes must receive canonical PATH injection (`~/.local/bin`, `~/.local/share/go/bin`, `~/.local/share/agent-os/bin`, DIR-ONT-03).
    - Python virtual environments must be purely hermetic without host system site-packages (DIR-ONT-04), fully compliant with PEP 668.
    - Idempotency guards must prevent duplicate shell environment exports in user dotfiles.
11. **Topos Anti-Cascade & Idempotent Catalog Seeding Invariant**:
    - Artifact upserts in SQLite (`register_artifact`) must use `COALESCE(excluded.binary_blob, artifacts.binary_blob)` and `COALESCE(excluded.binary_hash, artifacts.binary_hash)` on name conflict, preventing binary_blob wipe cascades ($X_1 \not\to X_2 \not\to X_1$) during repeated installer or bootstrap executions.
    - Diagnostics and verification gates (`setup.sh --check`) must never seed canary artifacts into production catalogs (`auto_seed_canary=False`) and must assert schema column integrity directly against active SQLite stores.
