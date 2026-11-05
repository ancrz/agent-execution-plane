# Stage 4 Execution Report: ONT-36 / M97 (Hardware Domain & Apport Crash Alerts Synchronization)

- **Milestone:** ONT-36 / M97 (Full Pipeline)
- **Approved Plan Reference:** `PLAN-ONT36-20261105-HARDWARE-DOMAIN-AND-APPORT-ALERTS-REV2`
- **Plan File:** [`docs/pipeline/feature_20261105_025500_ont36_hardware_domain_and_apport_alerts.md`](feature_20261105_025500_ont36_hardware_domain_and_apport_alerts.md)
- **Executor:** Pragma (Stage 4 — Execution Engine)
- **Repository Root:** `/home/ancruz/Documents/workspaces/agent-execution-plane` (`dev` branch)
- **Execution Date:** 2026-11-05
- **Status:** **STAGE4_EXECUTED ✅ (All 8 Tasks T1-T8 Complete, 10/10 Gates Passed, 143/143 Regression Passed, 0 Ruff / 0 Semgrep Errors)**

---

## 1. Task Execution Summary (DAG T1 —► T8)

| Task ID | Component / Target | Remediations Preserved | Status | Summary of Execution |
| :--- | :--- | :--- | :---: | :--- |
| **Task T1** | `engine/hardware.py` | R-3 (DRM fail-soft)<br/>R-1 (4096 MiB safety margin) | **COMPLETE ✅** | Created sysfs & procfs hardware prober with `probe_hardware_inventory()`, fail-soft `probe_accelerators()`, and `admit_accelerator(margin_mib=4096)` enforcing the mandatory 4096 MiB desktop safety margin on GTT to prevent GNOME Shell/Mesa compositor crashes. |
| **Task T2** | `engine/privilege.py`<br/>`scripts/setup.sh`<br/>Peer Test Suites | R-5 (9-domain matrix sync) | **COMPLETE ✅** | Added `hardware` to `CONTROL_PLANE_SCHEMA` (actions: `inventory`, `accelerators`, `admit`) and expanded `CHMOD_DEGRADATION_MATRIX` across all 4 tiers (`7rwx` to `4r--`). Synchronized `setup.sh` banner and peer tests (`test_privilege_degradation.py`, `test_net_security_telemetry.py`) to 9 domains. |
| **Task T3** | `scripts/aep-ctl` | R-1 (admit safety margin)<br/>CLI determinism | **COMPLETE ✅** | Implemented `domain_hardware` supporting `inventory`, `accelerators`, and `admit auto <vram> <gtt> [margin]`. Dispatched via `DOMAINS["hardware"]`. Resolved domain-specific `--schema` CLI parsing. |
| **Task T4** | `engine/crash_router.py` | R-4 (Permission-safe Apport)<br/>GAP-OM-20 | **COMPLETE ✅** | Implemented `sync_apport(crash_dir=Path("/var/crash"))` with `try...except (PermissionError, OSError)` and `os.stat` fallback for unreadable crash dumps. Fingerprinted via `apport:<name>:<mtime>` in SQLite `crash_events`. Updated `CrashRouter.check()` to report `source: "apport"` and `status: "OK"` when `coredumpctl` is missing. |
| **Task T5** | `server.py` | FastMCP 16-tool invariant<br/>GAP-CP-05 & GAP-OM-20 | **COMPLETE ✅** | Added `elif d == "hardware":` dispatch in `aep_ctl` tool; exposed `accelerators` overview block in `discover(action="capabilities")`; modernized `diagnose_system_crashes(action="alerts")` with Apport alert reporting. Verified strict FastMCP 16-tool invariant (`len(_tools) == 16`). |
| **Task T6** | `engine/telemetry.py`<br/>Peer Test Suites | R-2 (flat `t` stub parity)<br/>GAP-OM-19 | **COMPLETE ✅** | Modernized `attach_envelope()`: compact modes (`summary`, `brief`, `terse`, `cached`) omit redundant nested `payload["envelope"]` and emit flat keys + lightweight `payload["t"] = {"ms": elapsed_ms, "tok": estimated_tokens}`. Synchronized tests in `test_agent_experience_evaluation.py` and `test_default_primitives.py`. |
| **Task T7** | `tests/test_hardware_and_apport_alerts.py` | All contracts (Gates 1-10) | **COMPLETE ✅** | Authoritative 10-gate test suite covering FastMCP 16-tool invariant, control plane 9-domain schema reflection, hardware inventory, fail-soft DRM enumeration, pre-flight accelerator admission & 4096 MiB margin, permission-safe Apport forensics, deduplication, flat telemetry, and 4-tier degradation. 10/10 passed. |
| **Task T8** | Documentation & Milestones | M97 / ONT-36 Rollup | **COMPLETE ✅** | Updated `README.md` (143/143 tests badge, 4 layers diagram, Layer 2 modules, Section 9 degradation matrix), `docs/MILESTONES.md` (M97 graph node, status tables, context anchors), `docs/COMPACT.md`, and feature doc status. |

---

## 2. Dry Run & Logic Trace Findings

1. **AMDGPU GTT vs Desktop Compositor Hazard (GAP-CP-05):**
   - *Logic Trace:* On the development workstation (AMD Ryzen 7 PRO 7840U with Radeon 780M iGPU), VRAM dedicated carve-out is 1024 MiB and GTT is 15179 MiB. `gnome-shell` and Wayland compositor allocate buffers directly from GTT.
   - *Resolution:* `engine/hardware.py::admit_accelerator` calculates `gtt_available = max(0, gtt_free_mib - margin_mib)`. With `margin_mib = 4096`, any request demanding > 10944 MiB is immediately rejected with reason `insufficient_gtt_safety_margin`.
2. **Headless / Container / Non-AMD Compatibility (R-3):**
   - *Logic Trace:* On CI containers, WSL, cloud VMs, or NVIDIA/Intel hosts, `/sys/class/drm` may not exist or may not contain AMDGPU sysfs nodes (`mem_info_*`).
   - *Resolution:* `probe_accelerators()` and `probe_hardware_inventory()` wrap directory accesses with fail-soft guards returning `[]` and zero accelerators without raising `FileNotFoundError` or unhandled exceptions.
3. **Apport Unreadable Crash File Permission Traps (R-4):**
   - *Logic Trace:* Crashes from root daemon services in `/var/crash` (e.g. `_usr_sbin_daemon.0.crash`) are chmod 0600 root-owned. An unprivileged agent reading line-by-line would raise `PermissionError`.
   - *Resolution:* `sync_apport()` wraps file open in `try...except (PermissionError, OSError)`. Upon catch, it falls back to parsing the executable path from the file name stem (`_usr_bin_foo.1000.crash` -> `/usr/bin/foo`) and file modification timestamp via `os.stat()`.
4. **Subagent Re-Discovery Token Tax (Terse Byte Trimming):**
   - *Logic Trace:* In `server.py::discover(action="capabilities", verbosity="terse")`, subagents call terse discovery to reuse RAM session caching. Adding a 212-byte verbose GPU dictionary pushed the response from ~1314 bytes to 1517 bytes, tripping the `< 1500 bytes` bound in `test_gap_om15_discover_ram_caching_and_terse_subagent_savings`.
   - *Resolution:* In `terse` mode, `caps_meta["accelerators"]` is compactly represented as `[acc.get("device") for acc in accels_overview]` (`["card1"]`, 9 bytes), preserving detail for `detail`/`summary` while keeping terse responses under 1320 bytes.

---

## 3. Static Analysis & Verification Results

| Tool | Scope | Status | Result / Findings Summary |
| :--- | :--- | :---: | :--- |
| **Ruff Linter / SAST** | Repository-wide (`.venv/bin/ruff check .`) | **PASS ✅** | All checks passed (0 errors, 0 warnings). Import sorting and removeprefix modernization applied. |
| **Semgrep SAST** | Modified & Core Modules (`engine/hardware.py`, `engine/privilege.py`, `engine/crash_router.py`, `engine/telemetry.py`, `server.py`, `scripts/aep-ctl`) | **PASS ✅** | Ran 1198 rules on 6 files: **0 findings (0 blocking, 0 warnings)**. Clean OWASP and security profile. |
| **FastMCP Invariant** | `len(server.mcp._tool_manager._tools)` | **PASS ✅** | **Exactly 16 tools** (`len(_tools) == 16`). Strict architectural invariant preserved. |
| **Control Plane Schema** | `len(CONTROL_PLANE_SCHEMA)` & `aep_ctl` | **PASS ✅** | **Exactly 9 domains** (`service`, `network`, `storage`, `package`, `backup`, `security`, `audit`, `ipc`, `hardware`). |

---

## 4. Test Execution Battery

### 4.1 Dedicated ONT-36 Test Suite (`tests/test_hardware_and_apport_alerts.py`)
- **Execution Command:** `.venv/bin/pytest tests/test_hardware_and_apport_alerts.py -v`
- **Result:** **10 passed in 0.35s (100% pass rate)**
  - Gate 1: FastMCP 16-tool invariant (`len(_tools) == 16`) — PASSED
  - Gate 2: Control plane 9 domains & schema reflection (`CONTROL_PLANE_SCHEMA` + CLI) — PASSED
  - Gate 3: Hardware inventory probe (`/proc/cpuinfo`, `/proc/meminfo`, sysfs DRM) — PASSED
  - Gate 4: Fail-soft accelerator enumeration on DRM/headless/container (R-3) — PASSED
  - Gate 5: Pre-flight accelerator admission & 4096 MiB desktop safety margin (R-1) — PASSED
  - Gate 6: Permission-safe Apport forensics & header parsing fallback (R-4) — PASSED
  - Gate 7: Apport deduplication & fallback source (`source: "apport"`, `status: "OK"`) — PASSED
  - Gate 8: Modernized compact flat telemetry (`t: {"ms": ..., "tok": ...}`) (R-2) — PASSED
  - Gate 9: `discover(action="capabilities")` exposes accelerators summary block — PASSED
  - Gate 10: 4-tier degradation matrix across 9 domains (`7rwx` to `4r--`) — PASSED

### 4.2 Full Repository Regression Test Suite
- **Execution Command:** `.venv/bin/pytest tests/ -q`
- **Result:** **143 passed, 0 failures, 6 warnings in 16.08s (100% pass rate)**
  - Baseline before ONT-36: 133 tests passed
  - New test battery: +10 tests passed
  - Total tests: 143 tests passed across entire test harness
  - Regressions: **0**

---

## 5. Fix-First Resolution Log

1. **`scripts/aep-ctl` CLI Schema Dispatch:**
   - *Finding:* Running `scripts/aep-ctl hardware --schema` previously triggered the top-level schema due to `if "--schema" in args:`, skipping the domain-level schema block.
   - *Fix:* Refactored dispatch to `if not args or args[0] in ("schema", "--schema"):` for top-level schema, allowing `args = ["hardware", "--schema"]` to fall through to `action in ("--schema", "schema")` for domain schema emission.
2. **`server.py` Terse Capabilities Byte Trimming:**
   - *Finding:* Adding the 212-byte GPU dictionary into `caps_meta` caused `discover(action="capabilities", verbosity="terse")` to reach 1517 bytes in `test_gap_om15_discover_ram_caching_and_terse_subagent_savings`, exceeding the 1500-byte assertion limit.
   - *Fix:* In `terse` mode, `accelerators` is populated as a compact device name list `["card1"]` (9 bytes), saving >200 bytes while detail mode receives the complete dictionary.
3. **Ruff Imports Cleanup in Test Suite:**
   - *Finding:* `tests/test_hardware_and_apport_alerts.py` had unused imports (`asyncio`, `os`, `shutil`) and unsorted import blocks; `engine/crash_router.py` triggered FURB188.
   - *Fix:* Ran `.venv/bin/ruff check --fix .` resolving all 5 findings cleanly.

---

## 6. Files Created / Modified

- **`engine/hardware.py` (New):**
  Pure sysfs and procfs hardware prober and pre-flight accelerator admission engine with 4096 MiB desktop safety margin.
- **`engine/privilege.py` (Modified):**
  Registered `"hardware"` domain across all 4 tiers of `CHMOD_DEGRADATION_MATRIX` and `CONTROL_PLANE_SCHEMA`. Updated docstrings to 9 domains.
- **`engine/crash_router.py` (Modified):**
  Implemented `sync_apport()`, fingerprint deduplication, permission-safe fallback, and `status: "OK"` / `source: "apport"` check response.
- **`engine/telemetry.py` (Modified):**
  Modernized `attach_envelope()` with flat `t: {"ms": ..., "tok": ...}` stub in compact modes, omitting redundant nested envelopes.
- **`server.py` (Modified):**
  Added `elif d == "hardware":` dispatch in `aep_ctl`; added `accelerators` overview in `discover`; updated `diagnose_system_crashes(action="alerts")`.
- **`scripts/aep-ctl` (Modified):**
  Implemented `domain_hardware` (`inventory`, `accelerators`, `admit`) and registered in `DOMAINS`.
- **`scripts/setup.sh` (Modified):**
  Updated banner to `"9 Domains Fail-Soft Degradation"`.
- **`tests/test_hardware_and_apport_alerts.py` (New):**
  10-gate test suite for GAP-CP-05 and GAP-OM-20 contracts.
- **Peer Test Suites (Modified):**
  `tests/test_privilege_degradation.py`, `tests/test_net_security_telemetry.py`, `tests/test_agent_experience_evaluation.py`, `tests/test_default_primitives.py`.
- **Documentation (Modified):**
  `README.md`, `docs/MILESTONES.md`, `docs/COMPACT.md`, `docs/pipeline/feature_20261105_025500_ont36_hardware_domain_and_apport_alerts.md`.

---

## 7. Stage 4 Execution Sign-off

Stage 4 (Pragma Execution Engine) has successfully implemented all tasks T1 through T8 as specified in `PLAN-ONT36-20261105-HARDWARE-DOMAIN-AND-APPORT-ALERTS-REV2`, honoring all 5 Ontos remediations (R-1 through R-5) with 0 regressions and 143/143 tests passing.

Ready for routing by Orchestrator to **Dokimos (Stage 5 — Verification)**.
