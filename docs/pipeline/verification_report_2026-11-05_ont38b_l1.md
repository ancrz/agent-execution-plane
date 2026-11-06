# Verification Report: Milestone ONT-38b-L1 (AEP Verification Harness & Contract Stabilization)

- **Date:** 2026-11-05
- **Pipeline Mode:** SHORT (Topos Integrity Protocol)
- **Role:** Dokimos / Graphos (G2)
- **Branch:** `dev`
- **SSoT Version:** `0.2.8` (`v0.2.8`)
- **Status:** VERIFIED

---

## 1. Executive Summary

Milestone **ONT-38b-L1** executes Batch L1 of the AEP MCP stabilization roadmap derived from the live audit report (`docs/reports/2026-11-05_aep_mcp_live_audit_and_agy_harness.md`). All six scoped tasks were implemented, verified with comprehensive in-process tests and static analysis, and confirmed with zero regressions.

---

## 2. Tasks Executed & Verification Artifacts

### Task 1: In-Process Token Budget Suite (`tests/test_token_budgets.py`)
- **Passing Today (Normal Asserts):**
  - `discover(action="capabilities", verbosity="terse", session_id=...) <= 400 tokens` (measured: 301 tok).
  - `default_primitives(action="run", name="mem-stat") <= 250 tokens` (measured: 212 tok).
  - `topos_audit_dag(format="brief") <= 200 tokens` (measured: 75 tok).
  - `process_inspect(verbosity="brief", limit=5) <= 300 tokens` (measured: 218 tok).
- **Failing Today (strict=True xfail for D-01..D-05):**
  - `D-01`: `discover(action="schema", verbosity="summary") < 3000 tokens` (xfail: currently ~18k).
  - `D-02`: `playbook_run(action="list", verbosity="summary")` without `envelope` key (xfail: currently emits legacy envelope).
  - `D-03a`: `discover(action="playbook", select_fields=["nope"])` reports `unresolved_fields` (xfail: currently unhandled).
  - `D-03b`: `discover(..., select_fields=["suggested_capability.0.capability"])` preserves list type (xfail: currently converts to dict).
  - `D-04`: `aep_ctl(action="schema", verbosity="summary") < 1500 tokens` (xfail: currently ~3.8k).
  - `D-05`: `aep_ctl(domain="ipc", action="status", verbosity="summary")` without duplicated `mux.pool` (xfail: currently duplicated).

### Task 2: Headless Antigravity Probe Harness (`scripts/aep-agy-probe.sh`)
- Executable bash script (`set -euo pipefail`, clean under `shellcheck`).
- Wraps `agy -p` with canonical 8-test battery T1..T8 (`--mode plan`, `--output-format json`, `--print-timeout 300s`).
- Extracts `.response` JSON, saves probe result to `~/.local/share/agent-os/probes/<UTC-timestamp>_<commit>.json`.
- Prints single-line summary; exits 0 if passed >= `${AEP_PROBE_EXPECT:-8}`, else 1.
- Supports `--expect N`, `--model M`, and `--dry-run` (prints prompt without invoking agy).

### Task 3: D-08 Crash Forensics Apport Fallback
- `engine/privilege.py` (`capability_manifest`) and `server.py` (`discover` summary/brief compact caps):
  - When `coredumpctl` is absent but `/var/crash` exists, `crash_forensics` reports `ready=True` and `mode="apport_fallback"`.
  - When `coredumpctl` is installed, reports `ready=True` and `mode="coredumpctl"`.
  - When neither source exists, reports `ready=False` and `mode="none"`.
- Verified in `tests/test_d08_crash_forensics.py` (3/3 passing).

### Task 4: D-11 Dynamic Text & Counts Elimination
- Eliminated hardcoded counts in `server.py`:
  - `15 herramientas`: replaced in docstring and dynamically synchronized at module load time to match `len(tools)`.
  - `WF-1..WF-9`: derived dynamically from `pb.get("workflow_recipes", [])` range (`WF-1..WF-11`) in `next_action` and `_INSTRUCTIONS`.
  - Schema summary: derived dynamically from `len(tools)` and `len(domains)` (preventing `"15 tools, 0 domains"`).
- Verified via negative grep test in `tests/test_d11_dynamic_counts.py` (4/4 passing).

### Task 5: D-12 Single Source of Truth Versioning
- `pyproject.toml`: updated `version = "0.2.8"`.
- `server.py`: `_get_server_version()` reads version from `pyproject.toml` via `tomllib` with fallback to `"unknown"`, exposed as `SERVER_VERSION` (`"v0.2.8"`).
- `CHANGELOG.md`: added `[0.2.8] - 2026-11-05` summarizing ONT-29 through ONT-38 in 1 line per milestone.
- Verified in `tests/test_d12_version_ssot.py` (2/2 passing).

### Task 6: D-16 Sandbox Environment Ergonomics
- `server.py`: `sandbox_run` explicitly injects `AEP_IN_SANDBOX=1` via `--setenv` inside the jail.
- `tests/test_agent_experience_evaluation.py`: `test_sandbox_hides_the_host_workspace` decorated with `@pytest.mark.skipif(bool(os.environ.get("AEP_IN_SANDBOX")), ...)`.
- Verified in `tests/test_d16_sandbox_env.py` (3/3 passing).

---

## 3. Test Suite & Static Analysis Results

```
=============================== test session starts ===============================
platform linux -- Python 3.14.0a4, pytest-9.1.1, pluggy-1.5.0
rootdir: /home/ancruz/Documents/workspaces/agent-execution-plane
configfile: pyproject.toml
collected 175 items

169 passed, 6 xfailed, 6 warnings in 22.69s
```

- **ruff check .**: `All checks passed!`
- **scripts/aep-sync.sh --check**: `[ok] Validación superada (server importable, tools registradas).`
- **shellcheck scripts/aep-agy-probe.sh**: Clean (exit code 0).

---

## 4. Next Actions

- Milestone **ONT-38b-L1** is officially CLOSED.
- Next scheduled milestone: **ONT-39 (AEP Live Plane Hot-Swap)** as specified in `docs/sdd/sdd_ont39_live_plane_hot_swap.md`.
