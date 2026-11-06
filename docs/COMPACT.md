# Context Compaction Guidance — AEP (Milestone ONT-39 Live Plane Hot-Swap Synchronized)

**Preserve**:
- Pipeline State: Full Topos cerrado / ONT-39 Live Plane Hot-Swap implementado y verificado.
- Active Baseline: 16 FastMCP tools, dual-process architecture (`aep_front.py` stdio + `aep_backend.py` socketpair worker), pure stdlib `engine/fingerprint.py`, capabilities hot-swap telemetry (`backend_generation`, `code_fingerprint_disk`, `stale`). SSoT version `0.2.8` (`v0.2.8`).
- Verification Invariant: 175 passed (including 6 criteria e2e in `test_live_plane_ont39.py`), 6 xfailed (strict token budgets / contract gaps D-01..D-05), 0 failed. `ruff check .` clean, `aep-sync.sh --check` OK.
- Recent Milestones:
  - ONT-38b-L1: Verification harness (`aep-agy-probe.sh`), token budgets, SSoT versioning 0.2.8.
  - ONT-39: Live plane hot-swap (`aep_front.py`, `aep_backend.py`, `engine/fingerprint.py`), zero FD leaks, in-flight drain, fail-safe rollback, tier governance, Rule of Engagement #10.
- Next Milestone: L3 Token Budget optimization & contract gap fixes (D-01..D-05).

**Drop**:
- Verbose test runner logs, subagent execution traces, intermediate diffs, and resolved audit findings.
