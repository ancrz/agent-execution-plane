# Context Compaction Guidance: AEP (ONT-42c cerrado: C4–C7 VERIFIED)
Preserve: pipeline mode Short (default, cost control; Full only on user request or blast radius); active intent none (ONT-42c evolve closed); C4–C7 and DK-1..DK-4 VERIFIED.
Baseline: `dev` @ `be9887c` (origin/dev @ `3d2ef4e`, no push). Suite 754 passed (reported by Dokimos), ruff clean. Doc commit: local, no push.
Files and why: `engine/threads_evolve.py` (state machine, gate, ledger, revert, recovery); `engine/threads_gitport.py` (ff-only, export_tree with safe_extract); `engine/threads_verify.py` (judge, WRONG_TREE, run_tests_batched); `server.py` (autoevol actions); `docs/sdd/sdd_ont40_autoevol_thread_graph.md` §9 (threat model).
Decisions taken by the user: `resolve-revert` only via human CLI with `--confirm`; `recovered: true` only with git proof plus gate witness; AEP reloads only its own session; Short by default; Graphos records docs locally, no push.
Accepted risks and minors: M-2b (gitignored files outside the judged tree hash, still open); M-1, M-2, M-3 documented; threat model: gate does not protect against a same-uid adversary.
Open to verify: AP-1 restricted to FULL (C7 plan) not reported in closure; no push to origin/dev (user-gated).
Next 3 pending actions: (1) user decision on pushing dev (user-gated) and verify AP-1; (2) tests for the `recovered: true` branch; (3) E2–E4 backlog (incremental specs, OTP over SCC, tier-bound reconciliation).
Drop: pytest traces, intermediate diffs, subagent logs, Dokimos first-pass detail already in feature §20, superseded plans, resolved DK findings.
Recovery: after a crash, read the latest docs/pipeline/feature_*.md and this file, then `git fsck`.
