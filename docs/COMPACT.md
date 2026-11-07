# Context Compaction Guidance: AEP (ONT-42c: E1 y C1–C3 VERIFIED; C4–C7 pendientes)
Preserve: pipeline mode Short (default, cost control; Full only on user request or blast radius); active intent ONT-42c evolve; E1 and C1-C3 VERIFIED, C4-C7 pending.
Baseline: `dev` @ `9638056` (origin/dev @ `be78115`, no push). Suite 706 passed, 0 xfail, ruff clean.
Files and why: `engine/threads_evolve.py` and `engine/threads_gitport.py` (evolve state machine, ff-only); `engine/threads_verify.py` (fix_test ACCEPT bound to judged tree/root, TREE_MUTATED_DURING_JUDGE); `server.py` (autoevol actions).
Decisions taken by the user: AEP reloads only its own session (strict ancestry); Short by default; Graphos (not Hermon) records ONT-42c docs locally, no push.
Accepted risks and minors: M-2b (gitignored files outside the judged tree hash), M-1 (E1 scope to drift/public code), M-2 (weak discrimination signal), M-3 (stale evolve docstring).
Next 3 pending actions: (1) C4 final gate with run_tests_batched (red = no merge); (2) C5 ledger UNIQUE and persisted MAX_CYCLES; (3) C6 git revert rollback, then C7 Merkle R_before/R_after plus SDD sections 4/7/9.
Drop: pytest traces, intermediate diffs, subagent logs, already-harvested worktrees, E1/C1-C3 detail already verified in feature §16-19.
Recovery: after a crash, read the latest docs/pipeline/feature_*.md and this file, then `git fsck`.
