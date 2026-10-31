# Report: AEP omission gaps detected while used as a dependency (chrysalis-bridge, iteration 1)

**Date:** 2026-10-31
**Context:** AEP used as the optimization plane of an external project (`chrysalis-bridge`), Short pipeline,
orchestrator + sub-agents (Pragma, Graphos, Hermon). Decoupled from that project's goal: only AEP findings.
**Method:** live MCP calls with measured payloads; cross-checked against `docs/` gap registry
(GAP-OM-01..15, GAP-CP/DOC/DX/RT/SEC) to avoid duplicates.

## Summary

| ID (proposed) | Area | Severity | Evidence | Status in registry |
|---|---|---|---|---|
| GAP-OM-16 | Output efficiency | Medium | Envelope duplicated + telemetry on every verbosity | Resolved in ONT-29 ✅ |
| GAP-OM-17 | Topos audit | High | Shared-write-set co-dependency undetectable | Resolved in ONT-29 ✅ |
| GAP-DOC-02 | Discoverability | Medium | `terse`/`cached` + `session_id` (ONT-28) not advertised to agents | Resolved in ONT-29 ✅ |
| GAP-CP-04 | Backup semantics | Medium | `micro_snapshot` scope is AEP's own SQLite; no workspace snapshot | Resolved in ONT-29 ✅ |
| GAP-OM-18 | Inheritance attestation | Low | No per-`agent_id` usage accounting | Resolved in ONT-29 ✅ |

## Findings

### GAP-OM-16 — Envelope duplication survives every verbosity level
- **Evidence:** `topos_audit_dag(verbosity="brief")` and `verbosity="terse"` both returned 501 bytes.
  `status`, `severity`, `summary`, `truncated`, `cursor`, `next_action` appear at top level **and** again
  inside `envelope`; a `telemetry` block (~230 bytes) is always attached. Useful payload (`verdict`,
  `details`) was ~80 bytes → **~84 % overhead**. Same pattern on `aep_ctl(ipc, stats, brief)` (548 bytes).
- **Impact:** for small, frequent calls (DAG audits, status probes) the envelope dominates token cost,
  partially negating the efficiency premise.
- **Improve:** in `brief`/`terse`, emit the envelope once (top-level only) and make telemetry opt-in
  (`telemetry=False` default for `brief`/`terse`, or a single `t:{ms,tok}` stub). Add a contract test
  asserting `output_bytes(brief) < output_bytes(summary)` for every tool, and no duplicated keys.

### GAP-OM-17 — `topos_audit_dag` cannot see co-dependency through shared mutable state
- **Evidence:** a 9-node module graph where `memory.update` and `memory.ingest` write the same store that
  `memory.recall` reads was APPROVED. Correct for declared edges, but the tool has no notion of
  resources or write sets, so a real co-dependency expressed as "two modules mutating the same state
  without a contract" is invisible unless the agent manually models the store as nodes.
- **Impact:** the Topos protocol's core invariant (no co-dependency) is only partially machine-checked;
  agents may over-trust APPROVED.
- **Improve:** accept optional `resources={"store": {"writers": [...], "readers": [...], "contract": "v1"}}`.
  Flag `WARN` when a resource has ≥2 writers or reader/writer pairs without a declared `contract`;
  `BLOCKED` when writers also read each other's outputs without an interface node. Report the
  classification (dependency / interdependency / co-dependency) per edge, not only a cycle verdict.

### GAP-DOC-02 — ONT-28 savings are not discoverable from the agent's entry points
- **Evidence:** ONT-28 (GAP-OM-15) implemented `verbosity="terse"|"cached"` and `session_id` caching for
  `discover`. Neither the MCP server instructions nor `discover(action="playbook")` rules of engagement
  mention `terse`/`cached`; they recommend `summary`/`brief`. In practice the orchestrator and a sub-agent
  each paid ~1.2k tokens for `capabilities` and ~1.9k for `playbook` in the same session.
- **Impact:** the re-discovery tax remains in real multi-agent sessions despite being solved server-side.
- **Improve:** add a rule to the playbook and server instructions: "Orchestrator: `discover(..., session_id=<run>)`
  once; sub-agents: `discover(..., session_id=<run>, verbosity="terse")`". Have `capabilities`
  return a `cache_key`/`session_hint` field so the orchestrator can pass it in spawn prompts.

### GAP-CP-04 — "Snapshot before mutation" is ambiguous; no workspace snapshot primitive
- **Evidence:** `aep_ctl(action="schema")` describes the backup domain as "5-slot hot SQLite backups, RAM
  micro-snapshots, canary integrity" — i.e. AEP's own catalog DB. Playbook rule 5 says "SNAPSHOT BEFORE
  MUTATION" (scoped to "database or catalog" only in the detail text). A consuming project codified
  `micro_snapshot` as the pre-mutation step for **project files**, which it does not cover; the commit
  agent correctly fell back to a git backup branch.
- **Impact:** misapplied safety step → false sense of rollback for file-level mutations.
- **Improve:** (1) rename/clarify in schema: `micro_snapshot` → "AEP catalog snapshot"; (2) add
  `backup(action="workspace_snapshot"|"workspace_restore", name, path)` using a tarball or reflink copy in
  `/dev/shm/aep_pool` (or `git stash create` when `path` is a git repo), honoring Landlock and size caps.

### GAP-OM-18 — No attestation of AEP use per agent
- **Evidence:** calls carry `agent_id`, but `aep_ctl(ipc, stats)` reported `total_requests: 0`,
  `active_clients: 0` after several direct MCP calls (stats only cover the UNIX socket pool). There is no
  per-session, per-`agent_id` usage summary.
- **Impact:** an orchestrator cannot verify that sub-agents honored an "AEP is mandatory where it fits"
  directive; in this session two of three sub-agents made no AEP calls and this was only known from
  their self-reports.
- **Improve:** `aep_ctl(domain="audit", action="usage", name=<session_id>)` returning calls, tokens and
  bytes grouped by `agent_id` and tool, sourced from the existing telemetry/audit ledger.

## Iteration 2 findings (T1 implementation of chrysalis-mcp)

| ID (proposed) | Area | Severity | Evidence | Status in registry |
|---|---|---|---|---|
| GAP-OM-19 | Output efficiency | Medium | Every tool result arrives double-encoded | Resolved in ONT-29 ✅ |
| GAP-DX-04 | Test ergonomics | Low | `sandbox_run` returns no structured test counts | Resolved in ONT-29 ✅ |

### GAP-OM-19 — Double-encoded JSON in every tool result
- **Evidence:** all AEP tools return a `str` (pre-serialized JSON). The client receives
  `{"result": "{\"status\": \"OK\", ...}"}`: the JSON is escaped inside another JSON object, so every
  quote costs two characters and newlines become `\n` literals. Observed on `discover`, `aep_ctl`,
  `topos_audit_dag` and `sandbox_run` in this session (orchestrator and Pragma both reported it).
- **Root cause (measured in chrysalis-mcp, which extracted AEP's pattern and inherited it):** a FastMCP
  tool annotated `-> str` gets an auto-generated `outputSchema {result: string}`; each call then sends the
  payload **twice**: once as `content[0].text` and again escaped inside `structuredContent.result`.
  `tools/list` also grows by the advertised output schema.
- **Measured impact:** same response, client-side bytes 628 → 371 (**−41 %**) after the fix; the saving
  grows with payload size. Applies to all 15 AEP tools (all return pre-serialized `str`).
- **Improve:** `@mcp.tool(..., structured_output=False)` on every tool (one-line change each, keeps
  `-> str` and `attach_envelope` intact), or return a `dict` and drop the manual serialization. Contract
  test (pattern available in chrysalis-bridge `tests/test_stdio_e2e.py`): via a real `stdio_client`,
  assert `structuredContent is None` and the payload appears exactly once.

### GAP-DX-04 — `sandbox_run` lacks structured outcome fields for test runners
- **Evidence:** `sandbox_run(".venv/bin/pytest -q")` returned exit code and stdout tail only (896 bytes,
  ~40 % envelope + telemetry). No `passed` / `failed` / `errors` counts; the caller must parse stdout.
- **Improve:** optional `parse="pytest"|"ruff"|"auto"` that adds `{passed, failed, errors, skipped,
  duration_s}` or `{violations}`; with `verbosity="brief"` return only those counts plus failing test ids.

### Positive confirmation
- `sandbox_run` resolved `.venv` symlinks and auto-mounted the uv-managed interpreter
  (`~/.local/share/uv/python`) read-only; tests ran with `share_net=False` and exit 0. The RO mount
  design works for uv projects without extra flags.

## Usage metrics (AEP tools used in this iteration, from response telemetry)

| Tool / action | Calls | Bytes per call | Est. tokens per call | Useful payload | Note |
|---|---|---|---|---|---|
| `discover(capabilities, summary)` | 2 (orchestrator + Pragma) | 4,714 | 1,178 | high (manifest) | second call avoidable → GAP-DOC-02 |
| `discover(playbook, summary)` | 1 | 7,425 | 1,856 | high | rules omit `terse` |
| `topos_audit_dag` (3–9 nodes, brief/terse/summary) | 6 | 501–557 | 125–139 | ~80 bytes | overhead ~84 % → GAP-OM-16; terse = brief |
| `aep_ctl(schema, summary)` | 1 | 2,884 | 721 | high | revealed GAP-CP-04 |
| `aep_ctl(ipc, stats, brief)` | 1 | 548 | 137 | low | revealed GAP-OM-18 |
| `topos_audit_dag` (iteration 2, T1 plan, 7 nodes) | 1 | 501 | 125 | ~80 bytes | same overhead |
| `sandbox_run(pytest+ruff, summary)` (Pragma) | 1 | 896 | 224 | medium | exit code useful; no counts → GAP-DX-04 |
| `sandbox_run(pytest / ruff, summary)` (Dokimos) | 2 | 795–876 | 199–219 | medium | one-line result in ~800 bytes; no stdout-only mode |
| `sandbox_run` (Pragma fix cycle, summary) | 1 | 924 | 231 | medium | `46 passed` read from stdout |
| `sandbox_run` (Dokimos re-verify, **brief**) | 2 | 751–804 | 188–201 | medium | brief vs summary: only **−8 %** (876→804, 795→751) |
| **Total (iterations 1–2)** | **18** | ~31.3 KB | **~7.7k** | | latency 0.15–10.9 ms; `fd_delta` always 0 (no leaks) |

**Verbosity effectiveness (evidence for GAP-OM-16):** on `sandbox_run`, `brief` saves only ~8 % vs
`summary` because it trims telemetry fields but keeps the duplicated `envelope` and the double encoding.
For comparison, chrysalis-mcp (which extracted AEP's envelope with GAP-OM-16 and GAP-OM-19 fixed)
returns an equivalent status response in 371 bytes at `terse`, versus ~750–880 bytes for AEP's
one-line `sandbox_run` result.

Note: the stdio e2e, adversarial and clamp probes did not use `sandbox_run` because they spawn a
subprocess stdio client and write scratch files; `rw_paths` exists but the agent did not discover it
needed it → candidate doc hint for GAP-DX-04 (a "test harness" recipe in the playbook).

**Positive signals:** zero FD leaks, sub-millisecond latency on audits, stable RSS (+~5 MB since startup),
deterministic verdicts. The cost problem is payload shape, not runtime.

## Suggested acceptance tests
1. `brief`/`terse` responses contain no duplicated envelope keys; telemetry absent unless requested.
2. `topos_audit_dag` with two writers on one resource and no contract → `WARN`/`BLOCKED`.
3. Playbook output contains the substring `terse` and a `session_id` rule.
4. `workspace_snapshot` + `workspace_restore` round-trips a temp directory byte-identically.
5. `audit usage` groups calls by `agent_id` for direct MCP calls, not only socket-pool calls.

---

## Remediation Verification: Milestone ONT-29 (2026-10-31)

All 7 gaps identified in this report have been formally resolved and verified under Milestone `ONT-29`:
- **`GAP-OM-19`**: Single-encoded FastMCP response applied via `@mcp.tool(structured_output=False)` across all 15 tools. Eliminates double-encoded JSON escaping in `structuredContent.result` (−41% payload bytes).
- **`GAP-OM-16`**: Envelope deduplication and compact telemetry stubs in `brief` and `terse` modes (`output_bytes(brief) < output_bytes(summary)`).
- **`GAP-OM-17`**: Added optional `resources` parameter to `topos_audit_dag`. Emits `ToposVerdict.WARN` on uncoordinated writers without contract; emits `ToposVerdict.BLOCKED` on mutual reader/writer coupling without interface node; classifies edges into `dependency`, `interdependency`, `co-dependency`.
- **`GAP-CP-04`**: Added `workspace_snapshot` and `workspace_restore` actions to `aep_ctl(domain="backup")` with 50MB size limit and `CapabilityGuard` path blacklisting. Disambiguated `micro_snapshot` as catalog-only.
- **`GAP-OM-18`**: Implemented `aep_ctl(domain="audit", action="usage")` aggregating calls, bytes, tokens, and latency grouped by `agent_id` and `tool_name`.
- **`GAP-DX-04`**: Added `parse="pytest"|"ruff"|"auto"` to `sandbox_run`, returning structured summary metrics and suppressing raw stdout in brief mode.
- **`GAP-DOC-02`**: Advertised `session_hint` in `discover(action="capabilities")` and documented RAM session caching in server `_INSTRUCTIONS` and `tactical_playbook` under Rule of Engagement #8.

Verified via automated suite [`tests/test_ont29_bridge_stabilization.py`](../tests/test_ont29_bridge_stabilization.py) (8/8 gates passed) and Dokimos verification report [`docs/pipeline/verification_report_20261031_022000_ont29_aep_external_consumption_gaps_remediation.md`](../pipeline/verification_report_20261031_022000_ont29_aep_external_consumption_gaps_remediation.md).

