# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Full (ONT-18 Stage 2: Graphos G2 Record) -> Hermon (Stage 6).
- Active Intent / Milestone: ONT-18 (Topos Anti-Cascade Battery & Setup Hardening) — VERIFIED & PROMOTED ✅ (Task #122 Score: 0.9940 TRUST).
- Files Changed: `engine/catalog.py` (COALESCE upsert), `scripts/setup.sh` (Pueue regex, Step 8 heredoc, --check integrity), `tests/test_agent_experience_evaluation.py` (anti-cascade battery), `README.md` (badge 43/43, zero-FD, /dev/shm, DAG, snapshot docs), stray root `artifacts.db` unlinked.
- Verification Status: pytest 43/43 passed, 0 ruff errors, 0 semgrep findings, setup.sh --check HEALTHY (exit 0), audit chain 18 blocks valid, Kanban Task #122 PROMOTED.
- Readiness & Next Actions: Ready for Hermon (Stage 6) git commit & push, followed by ONT-19 Short-mode self-evolution loop.
Drop: raw AEP tool outputs, intermediate debug traces, superseded test execution logs.
