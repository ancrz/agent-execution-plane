# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Short.
- Active intent: agent-experience evaluation; battery and second report added.
- Files changed: `tests/test_agent_experience_evaluation.py`, report, and pipeline feature record.
- Verification: Ruff clean; pytest `34 passed, 2 xfailed`; Semgrep unavailable.
- Open product gaps: clean HOME bootstrap fails before schema creation; CLI schema omits MCP `audit` domain.
- AEP evidence: async dispatch passed; sandbox lacks allowlisted workspace mounts; detailed JSON is token-heavy.
- Next actions: fix bootstrap ordering; unify MCP/CLI schema; add bounded summary output and resource deltas.
Drop: raw AEP outputs, completed dispatch logs, superseded first-report conclusions.
