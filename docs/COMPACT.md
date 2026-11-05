# Context Compaction Guidance — AEP (Milestone ONT-38 SSoT Synchronized)

**Preserve**:
- Pipeline State: Standby / Ready for next directive. dev/main synced at commit 377c3f1. Working tree clean.
- Active Baseline: 16 FastMCP tools, 19 capabilities, 9 control-plane domains (4-tier chmod 7rwx-4r--).
- Verification Invariant: 153/153 tests passing (100%), ruff check clean, aep-sync clean.
- Recent Milestones: ONT-36 (GPU 4096 MiB margin), ONT-37 (UMA routing, Apport RFC822, Pytest anti-masking), ONT-38 (README SSoT sync).
- Pending Backlog (Chrysalis proposals in docs/reports/2026-11-05_aep_ont36_consumer_verification.md):
  1. Scratchpad RO mounting in sandbox_run (script=<path> or discover alias).
  2. playbook_run recipe for A/B migration tree testing.
  3. Per-agent suitability/warning matrix (recommended|neutral|discouraged|experimental).
  4. SSoT deferred: Nushell/jc (non-critical).

**Drop**:
- Verbose test runner logs, subagent execution traces, intermediate diffs, and resolved audit findings.
