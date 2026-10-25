# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Full (Topos Integrity Protocol).
- Active Intent / Milestone: ONT-12 (Autonomous Setup & Python 3.14 LTS Migration) — Stage 2 G2 VERIFIED (Task 113 PROMOTED 0.9250 TRUST; 7/7 Gates Passed).
- Target Modules & Verified Scope: `pyproject.toml` (py314 LTS), `scripts/setup.sh` (dual-mode engine + `--check` + `--update`), `scripts/aep-mcp-launch.sh`, `scripts/aep-sync.sh`, Go static probes (`socket-monitor`, `fd-rescuer`), `tests/test_setup_idempotency.sh`.
- Open Defects: 0 (All 7 Dokimos gates passed; Ruff 0 errors; Semgrep 0 findings; 0 regressions).
- Decisions Taken: Hermetic Python 3.14 via Astral `uv`; zero-dependency bootstrapper in user-space; non-interactive `sudo -n` with static tarball fallbacks (`go`, `pueue`); static probe compilation; DIR-ONT-01 short-circuit `--check`.
- Next Pending Action:
  - Hermon (Stage 6): Atomic release commit, conventional changelog, and version tagging.

Drop: Tool outputs already summarized, intermediate test logs, superseded plans, resolved errors.
