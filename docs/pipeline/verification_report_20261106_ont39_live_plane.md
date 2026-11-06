# Verification Report: Milestone ONT-39 (Live Plane Hot-Swap)

- **Date:** 2026-11-06
- **Pipeline Mode:** FULL (Topos Integrity Protocol)
- **Role:** Dokimos / Graphos (G2)
- **Branch:** `dev`
- **SSoT Version:** `0.2.8` (`v0.2.8`)
- **Status:** VERIFIED

---

## 1. Executive Summary

Milestone **ONT-39 (Live Plane Hot-Swap)** implements the dual-process architecture specified in normative document `docs/sdd/sdd_ont39_live_plane_hot_swap.md` (addressing findings D-09 and D-10 from the AEP MCP live audit). The architecture splits the runtime into:
1. A permanent, low-level MCP front (`aep_front.py`) bound to stdio that never restarts, preserves client sessions (Claude Code, Antigravity/agy), detects code changes via SHA-256 fingerprinting with 1s debounce, and notifies clients via `notifications/tools/list_changed`.
2. A swappable, sandboxed worker backend (`aep_backend.py`) connected via private `AF_UNIX` socketpair.
3. Live capabilities telemetry in `server.py` (`discover(action="capabilities")`) across all verbosities (including terse) exposing generation, fingerprints, and staleness.

All 8 tasks and all 6 automated acceptance criteria defined in SDD §8 were implemented, tested, and verified with zero regressions.

---

## 2. Tasks Executed & Verification Artifacts

### T-01: Code Fingerprint Engine (`engine/fingerprint.py`)
- Pure Python standard library implementation (`hashlib`, `os`, `pathlib`).
- Zero heavy dependencies; avoids importing FastAPI, MCP, or runtime engines.
- Benchmarked execution time <1.1 ms for all ~28 tracked repository files.
- Restores bitwise identical hash on file touch/reversion.

### T-02: Backend Worker (`aep_backend.py`)
- Independent Python process communicating over `AF_UNIX` socketpair using JSON-lines protocol.
- Integrates directly with `server.mcp` FastMCP tool manager to service `list`, `call`, `health`, and `set_meta` requests.
- Validates parameters inside the backend domain; forwards output envelopes directly to front.

### T-03: Front Supervisor & Hot-Swap Engine (`aep_front.py`)
- Low-level MCP `Server` from `mcp.server.lowlevel` over standard I/O transport.
- Uses `validate_input=False` to forward raw tool arguments to the backend without premature local schema validation.
- Emits `notifications/tools/list_changed` upon successful backend swaps.
- Fail-safe swap protocol: spawns candidate backend Gen N+1, performs health probe, swaps active socket atomically on success, and drains in-flight Gen N calls with configurable timeout.
- Governed by chmod tier:
  - `7rwx` (full execution), `6rw-` (development), `5r-x` (audit/read-only): auto-swap enabled.
  - `4r--` (restricted read-only): watch-only mode (fingerprint tracked, no auto-spawn).
  - Explicit env override: `AEP_HOTSWAP=0` disables swap; `AEP_HOTSWAP_MODE=watch` forces watch mode.

### T-04: Capabilities Telemetry & Rule #10 (`server.py`, `engine/privilege.py`)
- Added all SDD §5 fields to `discover(action="capabilities")` across all verbosities (`detailed`, `summary`, `brief`, `terse`):
  - `loaded_commit`, `repo_head`, `code_fingerprint_loaded`, `code_fingerprint_disk`, `stale`, `backend_generation`, `last_swap_at`, `last_reload_error`, `hotswap_mode`.
- Added Rule of Engagement #10: "VERIFY LOADED CODE" to `server._INSTRUCTIONS` and `discover(action="playbook")`.

### T-05: Mux Concurrency & Multi-Instance Coexistence
- Verified `/dev/shm/aep.sock` multi-backend coexistence.
- Socket ownership tracking ensures secondary instances probe existing listeners and avoid destroying active sockets on shutdown.

### T-06: Scripts Modernization (`scripts/aep-mcp-launch.sh`, `scripts/aep-sync.sh`)
- `scripts/aep-mcp-launch.sh`: Updated default launcher to execute `aep_front.py` under the repo virtualenv.
- `scripts/aep-sync.sh`:
  - Added HTTP status verification for agy reload commands.
  - Added `--audit` post-sync validation flag.
  - Added `--reap-stale` opt-in flag strictly gated to orphaned processes (`PPID=1`).
  - Added `--print-fingerprint` utility flag.

### T-07: Documentation & Architecture Diagram (`README.md`)
- Added Section 10.2 "Live Plane (ONT-39)" to `README.md` containing the dual-process architecture diagram in Mermaid and the agent verification protocol.

### T-08: Test Suite (`tests/test_live_plane_ont39.py`)
- Implemented comprehensive automated tests covering SDD §8 Criteria 1 through 6.

---

## 3. SDD §8 Acceptance Criteria Results

| Criterion | Description | Test Case | Status | Detail |
|---|---|---|---|---|
| **1** | Clean code reload on save | `test_criterion_1_clean_code_reload_on_save` | **PASS** | Gen 1 -> Gen 2 incremented, stale=False, fingerprint updated, list_changed notified |
| **2** | Broken candidate rejected | `test_criterion_2_broken_candidate_rejected` | **PASS** | Gen 1 retained, last_reload_error captured, front remains operational |
| **3** | In-flight calls not killed | `test_criterion_3_inflight_calls_not_killed` | **PASS** | Long in-flight call completes successfully during swap; old backend drained |
| **4** | Zero FD leaks | `test_criterion_4_zero_fd_leaks` | **PASS** | Baseline FD count maintained after 5 consecutive swaps (fd_delta == 0) |
| **5** | Multi-instance non-destructive | `test_criterion_5_concurrent_clients_non_destructive` | **PASS** | Concurrent front instances co-exist without clobbering `/dev/shm/aep.sock` |
| **6** | Watch-only mode on Tier 4 | `test_criterion_6_watch_only_mode_on_tier_4` | **PASS** | Under Tier 4 (4r--), code changes mark stale=True without auto-swapping |

---

## 4. Full Test Suite & Static Analysis Results

```
=============================== test session starts ===============================
platform linux -- Python 3.14.0a4, pytest-9.1.1, pluggy-1.5.0
rootdir: /home/ancruz/Documents/workspaces/agent-execution-plane
configfile: pyproject.toml
collected 181 items

175 passed, 6 xfailed, 6 warnings in 33.79s
```

- **ruff check .**: `All checks passed!`
- **scripts/aep-sync.sh --check**: `[ok] Validación superada (server importable, tools registradas).`
- **scripts/aep-sync.sh --print-fingerprint**: Generates SHA-256 fingerprint cleanly.
- **process_inspect FD telemetry**: `fd_count=13`, `fd_delta=0`.
- **Claude Code configuration**: User-level registration points directly to `scripts/aep-mcp-launch.sh`.

---

## 5. Conclusion & Routing

- Milestone **ONT-39 (Live Plane Hot-Swap)** is fully verified and ready for atomic commits by Hermon.
- Verdict: **VERIFIED**.
