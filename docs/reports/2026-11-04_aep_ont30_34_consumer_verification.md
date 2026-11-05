# Report: consumer-side verification of ONT-30..34 + new gaps (chrysalis-bridge, iteration 4)

**Date:** 2026-11-04
**Context:** chrysalis-bridge T3 (FlyHash ingest on sqlite-vec), Short pipeline. AEP used as optimization
plane by the orchestrator (Claude Code) and sub-agents. Findings decoupled from the host project.
**Prior reports:** `2026-10-31_aep_gaps_from_chrysalis_bridge.md`, `2026-10-31_aep_ont29_consumer_verification.md`.

## 1. Verification of fixes (client-observed)

| Gap | Client-side evidence | Verdict |
|---|---|---|
| GAP-OM-17 (write-set hazards) | `topos_audit_dag(resources={"store": {"writers": ["update","ingest"], "readers": [...]}})` without `contract` → `WARN` "Shared write-set hazard on resource 'store'…"; with one writer + `contract: "v2"` → `APPROVED`, resources echoed | ✅ Verified (now reachable from this client) |
| GAP-DX-05 (schema evolution) | `capabilities.tools.listChanged = True` declared in `server.py`; `resources` param now accepted by the client | ✅ Verified (reachable) |
| GAP-RT-03 (stale instances) | `discover` now returns `server_version`, `git_commit`, `schema_hash`, `pid`, `process_start_time`, `uptime_seconds` | ⚠️ **Partially — the stamp is misleading, see GAP-RT-04** |

## 2. New findings

| ID (proposed) | Area | Severity | Status in registry |
|---|---|---|---|
| GAP-RT-04 | Version stamp integrity | **High** | New (defeats GAP-RT-03's purpose) |
| GAP-RT-03 (re-open) | Multi-harness lifecycle | Medium | Still reproducible |

### GAP-RT-04 — `git_commit` reports the repository HEAD, not the code loaded in the process
- **Evidence:**
  - `discover(capabilities)` from this session returned `git_commit: "38b4080"`, `pid: 23734`,
    `process_start_time: 2026-11-04T12:31:44Z`.
  - `38b4080` (and the ONT-34 feature commit `cf5467c`) were committed at **16:31–16:32Z**, i.e. ~4 h
    **after** the process started. The process therefore runs pre-ONT-34 code but claims ONT-34.
  - Root cause: `server.py::_get_git_commit()` runs `git rev-parse --short HEAD` **at call time**.
  - Corroborating symptom: the same response reports `capabilities_count: 18` / summary "18 capabilities",
    while the ONT-34 code and server instructions state **19 capabilities / 16 tools** — consistent with
    stale loaded code, invisible through the stamp.
- **Impact:** the drift detector introduced for GAP-RT-03 can never detect drift: every stale instance
  reports the newest commit. Consumers (and gap verifications like this one) would attribute behavior to
  the wrong version.
- **Improve:**
  - Capture `LOADED_COMMIT` (and a hash of `server.py` + `engine/*.py`) **once at import time**.
  - Return `loaded_commit`, `repo_head` (call time) and `stale: loaded_commit != repo_head`.
  - When `stale`, set severity `WARN` and `next_action: "restart this AEP instance (pid …) to load <repo_head>"`.
  - Compute `schema_hash` from the **registered** tool schemas of the running process (it appears to be so;
    keep it that way) so clients can compare it with `tools/list`.
- **Acceptance test:** start server, create a new commit in the checkout, call `discover` → `stale: true`,
  `loaded_commit` unchanged.

### GAP-RT-03 (re-open) — stale instances per harness still occur
- **Evidence:** two AEP processes from the same checkout, both started before ONT-34:
  - PID 17848, started 08:29 local, parent **Antigravity** `language_server`;
  - PID 23734, started 08:31 local, parent **Claude Code** (`claude --resume`).
  - Neither was reloaded after ONT-34 (12:31 local). `listChanged` only helps when the schema changes in a
    running process; it does not reload code.
- **Improve:** with GAP-RT-04 fixed, `aep-sync.sh` can list instances whose `loaded_commit != HEAD` with
  their parent harness, and print a restart hint per harness. Never kill automatically.

### Reference fix for GAP-RT-04, validated in a consumer (chrysalis-bridge T7b)
Chrysalis extracted AEP's version-stamp idea and implemented it with the fix proposed above; Dokimos verified:
- `loaded_commit` and a sha256 over the package's `*.py` files are captured **at import**; `repo_head` and the
  current source hash are computed at call time (git result cached 5 s).
- `stale = (loaded_commit != repo_head, both known) or (loaded_source_hash != current_source_hash)`.
- Probes: patching git to return a new commit after import → `stale=true`, status `DEGRADED`, restart
  `next_action`, `loaded_commit` unchanged; editing a source file after import → `stale=true`; reverting → clears.
- The source-hash check also covers checkouts without `.git` and uncommitted edits picked up by hot-reload.
Reference implementation: `chrysalis-bridge/src/chrysalis_mcp/core/version.py` (Apache-2.0, same author) —
backport candidate for `server.py::_get_git_commit`.

### GAP-CP-05 (new) — No hardware / accelerator inventory capability
- **Evidence:** asked to "analyze the machine with AEP" to find an NPU, the only fitting tool was
  `sandbox_run`, but the jail hides `/dev`, `/sys/class` and `/etc/os-release`:
  `ls /dev/accel` → "No such file", `/sys/class/accel` → missing, `/etc/os-release` → missing
  (`EXEC_FAILED`, 203 tok). `aep_ctl` has no hardware domain; `discover(capabilities)` reports binaries
  (bwrap, go, …) but no accelerators. The facts had to be gathered outside AEP: AMD Ryzen 9 8945HS,
  NPU `1022:1502` (XDNA 1) on `/dev/accel/accel0` via in-kernel `amdxdna`, XRT 2.20 installed but
  `xrt-smi examine` → "0 devices found", iGPU Radeon 780M (`1002:1900`) on `/dev/dri/renderD128`, Mesa Vulkan 26,
  ROCm 7.1 HSA libs, ONNX Runtime 1.23 (providers: dnnl only).
- **Impact:** agents choosing an inference path (CPU / iGPU Vulkan / ROCm / NPU) cannot use AEP for the
  decision, although AEP's FULL tier could read these facts safely.
- **Improve:** read-only `aep_ctl(domain="hardware", action="inventory"|"accelerators")` returning CPU model,
  RAM, `/sys/class/accel/*` (vendor, device, driver, firmware present), `/dev/dri/*` render nodes + PCI ids,
  Vulkan devices (`vulkaninfo --summary`), XRT device count, ROCm agents (`rocminfo`), and whether the calling
  user can open each device node (ACL/groups). Add an `accelerators` block to `discover(capabilities)`.
  Keep the sandbox as is (hiding `/dev` is correct for untrusted code).

### Incident 2026-11-04 13:59:34 — desktop session crash caused by an agent-launched GPU workload
- **What happened:** the orchestrator launched `llama-server` (Gemma 4 26B-A4B Q4_0, 14.6 GB, `-ngl 99`, ctx 16k)
  on the Radeon 780M. The iGPU has 1 GiB VRAM carve-out + ~15 GiB GTT **shared with the desktop**. The load
  exhausted GTT → `amdgpu: [drm] *ERROR* Not enough memory for command submission!` → Mesa/libgallium `abort()`
  in `gnome-shell` (SIGABRT, apport `_usr_bin_gnome-shell.1000.crash`) → GDM restarted the graphical session,
  killing every app (both harnesses). The kernel did not reboot.
- **Signal that was ignored:** llama.cpp printed `common_fit_params: failed to fit params to free device memory:
  n_gpu_layers already set by user to 99, abort` before loading; the orchestrator classified it as a warning.
- **AEP worked well afterwards:** in the other harness, `diagnose_system_crashes(action="diagnose")` + `aep_ctl`
  + `playbook_run` reconstructed the root cause (apport crash, amdgpu error, systemd sequence). ✅

### GAP-CP-05 escalated (Medium → **High**) — resource admission before accelerator workloads
- The incident is the concrete cost of the missing hardware capability: a pre-flight read of
  `/sys/class/drm/card*/device/mem_info_{vram,gtt}_{total,used}` would have shown that a 14.6 GB model leaves
  < 1 GB GTT for the compositor.
- **Improve (in addition to the inventory proposal):** `aep_ctl(domain="hardware", action="admit",
  name="<required_gpu_mib>")` → `{admit: bool, gtt_free_mib, vram_free_mib, margin_mib, reason}` with a default
  desktop margin (e.g. 4 GiB GTT); and an optional watchdog (`async_job_dispatch` group with a kill condition on
  GTT free < margin) for long GPU jobs. cgroups cannot cap amdgpu GTT, so admission + watchdog is the only guard.

### GAP-OM-20 (new) — `diagnose_system_crashes` lags the ONT-29 contract and `alerts` misses apport crashes
- **Evidence (this session, fresh instance `loaded_commit=repo_head=19d6e22`, `stale=false`):**
  - `diagnose_system_crashes(action="alerts", verbosity="summary")` still returns the **pre-ONT-29 shape**:
    nested `envelope` duplicating top-level keys + full `telemetry` block (625 bytes / 156 tok for "0 alerts").
    Other tools (`discover`, `sandbox_run`, `topos_audit_dag`) use the new flat shape with `t`.
  - It reported `pending_count: 0` / `"coredumpctl ausente; enrutador inerte"` although an apport crash
    (`gnome-shell`, SIGABRT, 13:59:34) exists and the `diagnose` action does find apport crashes.
- **Impact:** a consumer polling `alerts` (the cheap periodic check) is told "all clear" after a real crash.
- **Improve:** route `alerts` through the same apport fallback as `diagnose`; migrate the tool to the shared
  `attach_envelope` (flat + `t`); contract test across all 16 tools asserting no nested `envelope` key.

### Verified in this session
- **GAP-RT-04 fixed:** `discover` returns `loaded_commit`, `repo_head`, `stale` (fresh instance: all equal,
  `stale=false`). ✅
- **`brief` no longer echoes request inputs** in `sandbox_run` (249-test run: 85 tok, only `parsed` + status). ✅

## 3. Usage metrics (iteration 4, orchestrator so far)

| Tool / action | Verbosity | `t.tok` | Useful | Note |
|---|---|---|---|---|
| `discover(capabilities, session_id)` | terse | 277 | high | version stamp fields (+69 tok vs ONT-29) — revealed GAP-RT-04 |
| `topos_audit_dag` (8 nodes + resources contract) | terse | 288 | high | per-edge classification + resources echo |
| `topos_audit_dag` (3 nodes, 2 writers, no contract) | terse | 122 | high | correct `WARN` (GAP-OM-17 verified) |

### Sub-agent metrics (T3 implement + verify)

| Agent | Tool / action | Verbosity | `t` (ms / tok) | Useful |
|---|---|---|---|---|
| Pragma | `sandbox_run` pytest `parse="pytest"` | brief | 4683 / **85** | yes (139 passed) |
| Pragma | `sandbox_run` ruff check `parse="ruff"` | brief | 20 / 70 | yes |
| Pragma | `sandbox_run` ruff format, `rw_paths=[<repo>]` | brief | 14 / 118 | yes |
| Dokimos | `sandbox_run` pytest `parse="pytest"` | brief | 4809 / 85 | yes |
| Dokimos | `sandbox_run` ruff check + format `parse="ruff"` | brief | 23 / 70 | partial (see below) |
| Dokimos | `sandbox_run` adversarial probe, `rw_paths=[<scratchpad>]` | brief | 585 / 238 | yes |

**Positive deltas verified:** `sandbox_run` brief + parse dropped from 151–172 tok (iteration 3) to **70–85 tok**
(~−50 %). `rw_paths` works for formatters (repo RW) and for untrusted-input probes (repo RO + scratch RW, no
network) — the "untrusted-input probe" recipe suggested in the previous report is now used in practice.

**Iteration totals (T3: implement + 2 fix cycles + 3 verifications):** 18 AEP calls, ~2.6k tokens
(orchestrator 3 / ~0.7k; Pragma 7 / ~0.6k; Dokimos 8 / ~1.3k, of which one uncapped probe stdout = 589 tok).
Average ~143 tok/call vs ~428 tok/call in iterations 1–2 (**−67 %**).

### Metrics T4+T5 and T7b (same day, same session)

| Stage | AEP calls | Tokens | Note |
|---|---|---|---|
| Orchestrator (2 `topos_audit_dag` with `resources`) | 2 | 575 | per-edge + resource echo |
| Pragma T4+T5 (incl. 4 failing pytest runs) | 6 | 1,975 | failing runs 431–506 tok each (useful: failure detail) |
| Pragma fix cycle | 1 | 85 | |
| Dokimos T4+T5 (2 rounds) | 5 | 855 | one call failed: `python` not on sandbox PATH (74 tok) |
| Pragma T7b | 2 | 155 | |
| Dokimos T7b (probes + suite) | 8 | 2,603 | probe stdout 351 / 624 / 761 tok at `brief` |
| **Total** | **24** | **~6.2k** | ~260 tok/call |

**Evidence for the `brief` stdout cap:** probe runs (stdout not parsed) account for ~2.1k of the 6.2k tokens
(34 %) while carrying a few lines of useful verdict each. A `stdout_tail` cap in `brief` would roughly halve
the iteration cost. Also: `python` is not on the sandbox `PATH` (only `.venv/bin/python` works) — either add the
venv `bin/` to `PATH` when `working_dir` has `.venv`, or say so in the tool description.

### Minor improvement points (no new GAP ID)
- **`parse="ruff"` hides which ruff sub-command ran:** for `ruff check && ruff format --check` only an
  aggregate `violations` count is returned; the agent could not tell whether formatting was checked.
  Suggest `parsed: {check: {violations, fixable}, format: {would_reformat}}`.
- **`uv run` is not resolvable inside the jail** (uv binary/cache not mounted); agents must call
  `.venv/bin/<tool>` directly. Either document it in the sandbox description or auto-mount `~/.local/bin/uv`
  + `UV_CACHE_DIR` read-only when `working_dir` contains `uv.lock`.
- **`brief` does not cap `stdout`:** a probe run returned 589 tok at `verbosity="brief"` because stdout is
  passed through uncapped (pytest/ruff runs stay at 70–85 tok only because `parse=` empties stdout).
  Suggest `brief` → `stdout_tail` of N lines (e.g. 20) + `stdout_bytes`, `detail` → full.
- **`env=` verified working** (Dokimos re-run used `env={"PYTHONPATH": "src"}` successfully).
- **`env=` discoverability:** agents prefixed commands with `env PYTHONPATH=…` instead of using the existing
  `env` parameter; one line in the tool description ("prefer `env={...}` over shell `env`") would fix it.
