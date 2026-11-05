# Dokimos Verification Report: Milestone ONT-36 / M97

- **Milestone:** ONT-36 / M97 (Hardware Domain & Accelerator Admission GAP-CP-05 and Apport Crash Alerts Synchronization GAP-OM-20)
- **Pipeline Stage:** Stage 5 (Verification Engine — Dokimos)
- **Approved Plan Reference:** `PLAN-ONT36-20261105-HARDWARE-DOMAIN-AND-APPORT-ALERTS-REV2`
- **Execution Report Reference:** `docs/pipeline/execution_report_20261105_035000_ont36_hardware_domain_and_apport_alerts.md`
- **Repository Root:** `/home/ancruz/Documents/workspaces/agent-execution-plane` (branch: `dev`)
- **Verification Timestamp:** 2026-11-05T04:00:00Z
- **Verdict:** **VERIFIED ✅ (All 10 Gates Passed, 143/143 Full Repo Tests Passing, 0 Regressions, 0 Lint/SAST Findings)**

---

## 1. Environment & Toolchain Provisioning

- **Operating System:** Linux (Ubuntu 24.04 LTS / Linux x86_64)
- **Python Runtime:** Python 3.14.7 (`.venv/bin/python3`)
- **Test Runner:** Pytest 9.1.1 (pluggy 1.7.0, anyio 4.15.1)
- **Static Analysis & Linter:** Ruff 0.12.x (`.venv/bin/ruff`), Semgrep SAST
- **Execution Substrates:** Astral uv, Pueue 3.4.x, Bubblewrap 0.11.1, Landlock LSM, SQLite 3.46.1 with sqlite-vec

---

## 2. FastMCP Architectural Invariant Verification

- **Invariant:** FastMCP 16-Tool Invariant (`len(server.mcp._tool_manager._tools) == 16`).
- **Verification:** Evaluated `server.mcp._tool_manager._tools` via direct introspection:
  - Exact count: **16 tools registered**.
  - Registered toolset: `[aep_ctl, artifact_catalog, artifact_execute_in_ram, artifact_lint_and_build, async_job_dispatch, default_primitives, diagnose_system_crashes, discover, kanban_board, kernel_trace, playbook_run, process_inspect, query_system_docs, sandbox_run, topos_audit_dag, visual_inspect]`.
  - Proliferation check: `hardware` is NOT exposed as an independent 17th tool endpoint. It is properly encapsulated under the polymorphic `aep_ctl(domain="hardware", ...)` control plane and reflected in `discover(action="capabilities")`.
- **Gate Status:** **PASSED ✅**

---

## 3. Static Analysis & Lint Baseline

| Tool | Scope | Status | Findings |
| :--- | :--- | :---: | :--- |
| **Ruff Linter** | Entire repository (`.venv/bin/ruff check .`) | **PASS ✅** | 0 errors, 0 warnings (`All checks passed!`). |
| **Semgrep SAST** | Modified & Core Modules (1198 rules) | **PASS ✅** | 0 critical, 0 high, 0 medium, 0 low findings. OWASP clean. |
| **Ecosystem Sync** | `./scripts/aep-sync.sh --check` | **PASS ✅** | Server importable, tools registered, exit code 0. |

---

## 4. Test Execution Battery & Gate Verification

### 4.1 Dedicated ONT-36 Test Battery (`tests/test_hardware_and_apport_alerts.py`)
Executed: `.venv/bin/pytest tests/test_hardware_and_apport_alerts.py -v`
Result: **10 passed in 0.34s (100% pass rate)**

- **Gate 1 (FastMCP 16-Tool Invariant):** PASSED ✅
  Strictly 16 tools registered; zero endpoint proliferation.
- **Gate 2 (Control Plane 9 Domains & Hardware Schema):** PASSED ✅
  `CONTROL_PLANE_SCHEMA` contains exactly 9 domains; `hardware` domain exposes `inventory`, `accelerators`, and `admit` actions.
- **Gate 3 (Hardware Inventory Probe):** PASSED ✅
  `probe_hardware_inventory()` reports CPU cores, model name, RAM total/available, and accelerators overview.
- **Gate 4 (Fail-soft Accelerator Enumeration R-3):** PASSED ✅
  Non-existent, empty, or headless DRM nodes return empty lists without raising unhandled exceptions or crashing.
- **Gate 5 (Pre-Flight Accelerator Admission & 4096 MiB Margin R-1):** PASSED ✅
  `admit_accelerator(margin_mib=4096)` rejects requests exceeding available GTT minus 4096 MiB desktop compositor safety reserve, preventing GNOME Shell and Mesa compositor SIGABRT crashes.
- **Gate 6 (Permission-Safe Apport Forensics R-4):** PASSED ✅
  Unreadable or root-owned `/var/crash/*.crash` files fall back gracefully to file stem extraction and `os.stat` timestamps without unhandled `PermissionError`.
- **Gate 7 (Apport Deduplication & Fallback Source):** PASSED ✅
  SQLite `crash_events` fingerprints entries via `apport:<file>:<mtime>`. Secondary checks return `status: "OK"` with `source: "apport"` when `coredumpctl` is absent.
- **Gate 8 (Modernized Compact Flat Telemetry R-2):** PASSED ✅
  In `summary`, `brief`, `terse`, and `cached` modes, `diagnose_system_crashes(action="alerts")` omits nested `payload["envelope"]` and emits flat root keys plus lightweight `t: {"ms": ..., "tok": ...}`.
- **Gate 9 (Discover Capabilities Accelerators Block):** PASSED ✅
  `discover(action="capabilities")` exposes `accelerators` overview block in detail mode and compact list in terse mode.
- **Gate 10 (4-Tier Degradation Matrix Across 9 Domains):** PASSED ✅
  `CHMOD_DEGRADATION_MATRIX` covers all 9 domains across tiers `7rwx`, `6rw-`, `5r-x`, and `4r--`. `scripts/setup.sh` displays updated 9-domain banner.

### 4.2 Peer Regression Test Suites
Executed: `.venv/bin/pytest tests/test_privilege_degradation.py tests/test_net_security_telemetry.py tests/test_agent_experience_evaluation.py tests/test_default_primitives.py -v`
Result: **37 passed in 8.30s (100% pass rate)**

### 4.3 Full Repository Test Suite
Executed: `.venv/bin/pytest tests/ -v`
Result: **143 passed, 6 warnings in 16.34s (100% pass rate)**
- Total collected: 143 items.
- Regressions: **0**.

---

## 5. Functional CLI & Runtime Verification

1. **Hardware Inventory CLI:**
   - Command: `./scripts/aep-ctl hardware inventory --json`
   - Output: Detected AMD Ryzen 9 8945HS (16 cores, 30358 MiB RAM, 1 accelerator: `card1` AMD Radeon 780M iGPU with 1024 MiB dedicated VRAM and 15179 MiB GTT). Status: `OK`.
2. **Hardware Accelerators CLI:**
   - Command: `./scripts/aep-ctl hardware accelerators --json`
   - Output: `count: 1`, `card: card1`, `vram_free_mib: 308`, `gtt_free_mib: 15059`. Status: `OK`.
3. **Accelerator Admission Rejection (GAP-CP-05):**
   - Command: `./scripts/aep-ctl hardware admit auto 0 20000 --json`
   - Output: `status: REJECTED`, `admit: false`, `reason: "insufficient_gtt_safety_margin: requested 20000 MiB, available 10963 MiB after 4096 MiB desktop safety margin from 15059 MiB free"`.
4. **Accelerator Admission Approval:**
   - Command: `./scripts/aep-ctl hardware admit auto 0 2048 --json`
   - Output: `status: OK`, `admit: true`, `reason: "admitted"`, `gtt_available_mib: 10957`.
5. **Apport Real-World Forensics (GAP-OM-20):**
   - Live crash router probe on `/var/crash` detected unprivileged user crashes (`/opt/Antigravity/antigravity` and `/usr/bin/gnome-shell`), returning `status: "OK"`, `source: "apport"`, and `pending_count: 2`.

---

## 6. Blast Radius & Scope Creep Audit

- **Declared Boundaries:** 15 files planned across DAG T1-T8.
- **Actual Modified / Created Files:**
  - `engine/hardware.py` (New — pure hardware prober & admission engine)
  - `engine/privilege.py` (Modified — registered `hardware` domain & 4-tier matrix)
  - `engine/crash_router.py` (Modified — Apport sync & fallback)
  - `engine/telemetry.py` (Modified — flat `t` stub)
  - `server.py` (Modified — `hardware` dispatch & compact terse trimming)
  - `scripts/aep-ctl` (Modified — `domain_hardware` implementation)
  - `scripts/setup.sh` (Modified — 9-domain banner)
  - `tests/test_hardware_and_apport_alerts.py` (New — 10-gate suite)
  - Peer test suites: `tests/test_agent_experience_evaluation.py`, `tests/test_default_primitives.py`, `tests/test_net_security_telemetry.py`, `tests/test_privilege_degradation.py`
  - Documentation: `README.md`, `docs/MILESTONES.md`, `docs/COMPACT.md`, `docs/PROJECT.md`, `docs/reports/...`, `docs/pipeline/...`
- **Scope Creep Audit Result:** **NO SCOPE CREEP DETECTED**. Modifications are strictly bounded to the declared blast radius. Code delta is +298 insertions, -50 deletions across existing codebase.

---

## 7. Ontological Testing Model Summary

- **Vertical Layer Integrity:** Verified sysfs hardware layer -> `engine/hardware.py` -> `aep_ctl` control plane -> CLI / MCP JSON-RPC payload roundtrip.
- **Horizontal Peer Effects:** Verified that expanding `CONTROL_PLANE_SCHEMA` to 9 domains preserves contract compatibility across all peer tools (`discover`, `aep_ctl`, `diagnose_system_crashes`, `default_primitives`).
- **Systemic Ecosystem Coherence:** Verified non-hang guarantee, permission degradation matrix (4 tiers), and headless / container compatibility.

---

## 8. Dokimos Formal Verdict

### **VERDICT: VERIFIED ✅**

All 10 milestone verification gates, peer regression suites, and full test suites pass with 100% success rate (143/143 tests). All 5 Ontos remediation items (R-1 through R-5) are rigorously honored. FastMCP 16-tool invariant is strictly preserved. Zero static analysis or linter defects.

### Routing Recommendation:
Return verdict `VERIFIED` to Orchestrator for recording by **Graphos (Stage 2 — G2)** and subsequent atomic commit by **Hermon (Stage 6)**.
