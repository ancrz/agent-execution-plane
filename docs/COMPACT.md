# Context Compaction Guidance — AEP (Milestone ONT-38b-L1 Synchronized)

**Preserve**:
- Pipeline State: L1 cerrado / Standby for ONT-39 Live Plane (`docs/sdd/sdd_ont39_live_plane_hot_swap.md`).
- Active Baseline: 16 FastMCP tools, 19 capabilities, 9 control-plane domains (4-tier chmod 7rwx-4r--). SSoT version `0.2.8` (`v0.2.8`).
- Verification Invariant: 169 passed, 6 xfailed (strict token budgets / contract gaps D-01..D-05), 0 failed, ruff check clean, aep-sync clean.
- Recent Milestones:
  - ONT-38: README SSoT sync and directory tree alignment.
  - ONT-38b-L1: Verification harness (`aep-agy-probe.sh`), token budgets (`test_token_budgets.py`), SSoT versioning 0.2.8 (`pyproject.toml` + `server.py` + `CHANGELOG.md`), D-08 Apport fallback, D-11 dynamic counts, D-16 sandbox env.
- Next Milestone:
  - **ONT-39 (AEP Live Plane Hot-Swap)**: Dual-process split (stable stdio front vs swappable worker backend over socketpair) to eliminate STALE instances and reload server code without killing client harness sessions. See `docs/sdd/sdd_ont39_live_plane_hot_swap.md`.

**Drop**:
- Verbose test runner logs, subagent execution traces, intermediate diffs, and resolved audit findings.
