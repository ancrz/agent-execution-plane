# Second Report: AEP Agent Experience and Contract Evaluation

**Date:** 2026-10-30
**Method:** Short pipeline using the live AEP MCP as the primary control plane.
**Scope:** MCP contracts, clean-runtime bootstrap, schema coherence, sandbox ergonomics, asynchronous verification, and output efficiency. No runtime behavior changed.

## Verdict

AEP is effective as a typed Linux control-plane adapter: capability discovery, async jobs, process inspection, audit verification, and deterministic JSON all worked. Its main weakness is contract coherence: the agent must infer useful affordances that the server possesses, and a clean installation cannot start the MCP runtime.

The battery is executable: three current contracts pass and two strict `xfail` markers capture confirmed product gaps.

## Live-MCP evidence

| Probe | Result | Implication |
|---|---|---|
| `topos_audit_dag` | APPROVED | Evaluation DAG has no co-dependencies. |
| `async_job_dispatch` | 2 jobs completed | Ruff and pytest ran without blocking the agent. |
| `aep_ctl package check semgrep` | not installed | Security SAST was unavailable in this environment. |
| `aep_ctl audit verify` | 4/4 blocks valid | Audit-chain read contract worked. |
| `process_inspect(self)` | 42 threads, 616,556 KiB RSS, 28 FDs | Useful state, but no per-request baseline/delta. |

## Test battery

File: `tests/test_agent_experience_evaluation.py`

| Contract | Status | Purpose |
|---|---|---|
| CLI schema is machine-discoverable | PASS | No human-help parsing required. |
| Invalid control action returns alternatives | PASS | Recovery data is structured. |
| Default sandbox hides checkout | PASS | Workspace is not implicitly exposed. |
| Fresh HOME starts MCP runtime | XFAIL | Reproduces clean-install startup defect. |
| CLI schema matches MCP domains | XFAIL | Reproduces omitted `audit` domain. |

Executed via `async_job_dispatch`:

```text
ruff check tests/test_agent_experience_evaluation.py  -> PASS
pytest -q -p no:cacheprovider                         -> 34 passed, 2 xfailed
```

## Deep findings and improvements

### Clean bootstrap

`ArtifactCatalog._init_db()` calls `_migrate()` before `schemas/database.sql`. With an empty `HOME`, migration runs `ALTER TABLE artifacts ...` before the table exists, so importing `server` fails.

**Improve:** create the base schema before idempotent migrations; then convert the strict xfail into a normal passing test.

### Two schema sources

`server.py` implements special `audit`, `backup`, and `security` routes while `scripts/aep-ctl` has a separate `SCHEMA`. MCP advertises `audit`; the CLI schema omits it. The MCP schema path also needs an artificial `(domain, action="--schema")` call.

**Improve:** define metadata once and expose `aep_ctl(action="schema")`; generate CLI and MCP validation from the same source.

### Sandbox is secure but incomplete for agents

The Bubblewrap default correctly hides the checkout, but cannot run repository tests because there is no `working_dir` or allowlisted bind mount.

**Improve:** retain deny-by-default; add validated `ro_paths`, `rw_paths`, and `working_dir`; make network sharing opt-in (`share_net=false` by default).

### JSON is not automatically token-efficient

The diagnostic output can include complete listener inventories, mount trees, and journal metadata. In the first audit, detailed JSON cost more context than filtered shell output.

**Improve:** provide `verbosity="summary"|"detail"`, pagination/cursors, time windows, byte limits, and an `agent_brief` envelope with `summary`, `evidence`, `next_action`, `truncated`, and `cursor`.

### Discovery precision and resource attribution

For an AEP source audit, `discover` selected `backup_admin` and `audit_read`, not code or contract analysis. The live process grew from about 454 MiB / 18 FDs to about 617 MiB / 28 FDs after semantic discovery and dispatch. This is not proof of a leak, but AEP cannot attribute the cost to a request.

**Improve:** add labeled intent precision tests and `NO_HIGH_CONFIDENCE_MATCH`; report request ID, latency, output bytes, cache state, and RSS/FD deltas per tool; run a soak test before diagnosing a leak.

## Role opinions

### Pragma

The battery is narrow, reproducible, and does not mutate production behavior. AEP async dispatch is suitable for verification; the sandbox requires an explicit workspace policy before it can become the default repository runner.

### Dokimos

The artifact is verified: 34 tests pass, two expected failures accurately record confirmed defects, and Ruff is clean. Semgrep was unavailable, so no zero-findings security claim is made.

### Graphos

The two xfails convert observations into durable, executable state. Bootstrap ordering is the first remediation; schema unification is the next.

## Priority

1. Fix clean bootstrap and promote its xfail to PASS.
2. Unify CLI/MCP schema and promote its xfail to PASS.
3. Add capability readiness, compact output, and request-level resource telemetry.
4. Add allowlisted sandbox workspace mounts and network opt-in.

## Token conclusion

No exact savings can be asserted: AEP records neither serialized response bytes nor model token counts. In this evaluation, AEP improved control-flow reliability but did not reduce context. Compact-output instrumentation is required before claiming token efficiency.
