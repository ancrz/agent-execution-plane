# Context Compaction Guidance: AEP (integridad de instalación VERIFIED; E3 VERIFIED; siguiente E4)
Preserve: pipeline mode Short (default, cost control; Full only on user request or blast radius); active intent: E4 reconciliación por tier.
Baseline: `dev` @ `f8eaa9c` (origin/dev @ `550875f`, 24 commits ahead, NO push; push is user-gated). Suite 805 tests collected; 805 passed reported by Dokimos; ruff clean (reported).
Files and why: `scripts/setup.sh`, `scripts/aep-sync.sh`, `scripts/aep-ctl`, `server.py` (install integrity, `aep_ctl` via sys.executable); `engine/threads_supervise.py`, `engine/threads_heal.py` (E3 OTP); `docs/reports/2026-11-07_aep_clean_room_install_retest.md`; `docs/pipeline/feature_20261107_113335_install_integrity_e3.md`.
Decisions taken by the user: Short by default; Graphos records docs locally, no push; O-2 budget inherited after reap; `resolve-revert` only via human CLI with `--confirm`; `recovered: true` only with git proof plus gate witness; E2 spec informative only.
Accepted risks and minors: E2 hardening optional (node_hash of tests/pins in key; validate `_lookup` hit shape); M-2b open; threat model: gate does not protect against a same-uid adversary; clean-room round 3 did not run pytest; pueue pin has no official checksum (SHA calculated).
Open backlog (minor): Go probes without go.mod; errcheck in socket-monitor (1) and landlock-guard (4); LKG old (622fa0a7…) should be refreshed; ruff format pending in 76 files; download-failure branch (network down) not exercised.
Next 3 pending actions: (1) E4 reconciliation bounded by tier (Archon in Full / orchestrator in Short); (2) minor install backlog (Go go.mod probes, errcheck); (3) LKG refresh and ruff format scope (user decision).
Also pending: `feature_rollup.md` overdue (chain more than five docs since last rollup).
Drop: pytest traces, intermediate diffs, subagent logs, superseded plans, resolved clean-room rounds 1-2 detail, resolved E3 defect investigation.
Recovery: after a crash, read the latest docs/pipeline/feature_*.md and this file, then `git fsck`.
