# Report: consumer-side verification of ONT-29 + new gaps (chrysalis-bridge, iteration 3)

**Date:** 2026-10-31
**Context:** after ONT-29 (`cd58bd9`) remediated the 7 gaps reported in
`2026-10-31_aep_gaps_from_chrysalis_bridge.md`, AEP was used again as a dependency of `chrysalis-bridge`
(T2 substrate ‖ T6 Z3, Short pipeline, parallel worktree tracks). This report verifies the fixes **from the
MCP client side** (what an external agent actually receives) and records new omissions.

## 1. Verification of ONT-29 fixes (client-observed)

| Gap | Client-side evidence | Verdict |
|---|---|---|
| GAP-OM-19 (double encoding) | Tool results now arrive as a single raw JSON object; no `{"result": "<escaped>"}` wrapper | ✅ Verified |
| GAP-OM-16 (envelope duplication) | No nested `envelope`; telemetry reduced to `t: {ms, tok}` | ✅ Verified |
| GAP-DOC-02 (terse discoverability) | `discover(capabilities, session_id, terse)` returns `session_hint` + `cache_status`; **208 tokens vs ~1,178 before (−82 %)** | ✅ Verified |
| GAP-CP-04 (workspace snapshot) | `aep_ctl(schema)` lists `backup.workspace_snapshot` / `workspace_restore`; description now says "RAM micro-snapshots (catalog only)" | ✅ Advertised (round-trip not exercised yet) |
| GAP-OM-18 (per-agent usage) | `audit.usage` advertised with `[session_id]` arg | ✅ Advertised (not exercised yet) |
| GAP-DX-04 (structured test parsing) | `sandbox_run` schema now exposes `parse` | ✅ Advertised (being exercised by sub-agents this iteration) |
| GAP-OM-17 (write-set hazards) | Server signature has `resources=...`, but the **client-advertised schema of `topos_audit_dag` does not include `resources`**, so a schema-validating MCP client cannot pass it (see GAP-DX-05) | ⚠️ Not reachable from this client |

**Bonus improvement observed:** `topos_audit_dag` now returns per-edge classification
(`edges: [{source, target, type: "dependency"}]`), as suggested in GAP-OM-17. Payload stays small
(75–290 tokens for 3–10 nodes).

### Token impact, same calls before/after ONT-29

| Call | Before | After | Δ |
|---|---|---|---|
| `discover(capabilities)` | ~1,178 tok (summary) | 208 tok (terse + session) | −82 % |
| `topos_audit_dag` 3 nodes | 125 tok | 75 tok | −40 % |
| `aep_ctl(schema)` | 721 tok (summary) | 530 tok (brief, 2 new domains/actions included) | −26 % |

## 2. New findings

| ID (proposed) | Area | Severity | Status in registry |
|---|---|---|---|
| GAP-DX-05 | Schema evolution | Medium | **Resolved in ONT-30 ✅** |
| GAP-RT-03 | Multi-harness lifecycle | Medium | **Resolved in ONT-30 ✅** |

### GAP-DX-05 — Tool-schema evolution is not signaled to connected clients
> [!NOTE]
> **Resolution Status**: **Resolved in ONT-30 ✅** — FastMCP initialization wraps `capabilities.tools.listChanged = True`, `server_version`, `git_commit`, and deterministic `schema_hash` are exposed across all verbosities in `discover(action="capabilities")`, and `topos_audit_dag` provides resilient fallback accepting task-level `writes`/`reads`/`contract` dictionaries when `resources` is omitted.

- **Evidence:** the `topos_audit_dag` schema the client holds lacks the new `resources` parameter
  (GAP-OM-17) although `server.py` declares it; `sandbox_run` (first loaded after ONT-29) does show the new
  `parse` parameter. AEP never emits `notifications/tools/list_changed` (no occurrence in `server.py`,
  `engine/`, `scripts/`), so whether a client sees a new parameter depends on when it first fetched the schema.
  Root cause of the stale schema in this specific client is **not fully confirmed** (client-side schema cache
  vs. server); the absence of `list_changed` is confirmed.
- **Impact:** fixes that add parameters can be invisible to already-connected agents; strict clients reject
  unknown params, so the feature is unusable until reconnect.
- **Improve:** (1) declare `capabilities.tools.listChanged = true` and send `tools/list_changed` after
  `aep-sync` hot-reload; (2) add `server_version` / `git_commit` + a `schema_hash` to
  `discover(capabilities)` so agents can detect drift; (3) when an unknown-but-new param is critical,
  accept it inside an existing free-form field as a fallback (e.g. `tasks=[{"id":..., "writes": [...]}]`).

### GAP-RT-03 — Stale AEP instances survive across harnesses
> [!NOTE]
> **Resolution Status**: **Resolved in ONT-30 ✅** — Exposed `pid`, `process_start_time` (ISO-8601), and `uptime_seconds` in `discover(action="capabilities")` and `process_inspect(pid=0)`; added `scripts/aep-sync.sh --audit` for non-destructive multi-harness diagnostic inspection of active instances.

- **Evidence:** two AEP server processes run from the same checkout: PID started 00:38 (parent:
  Antigravity language server) and PID started 02:33 (this Claude Code session). ONT-29 was committed at
  02:29 local, so the Antigravity instance still serves **pre-ONT-29 code** (double encoding, duplicated
  envelope) while the repository claims the gaps are closed.
- **Impact:** cross-harness inconsistency: the same "AEP" behaves differently per harness until each
  restarts; metrics and gap verification can be misattributed.
- **Improve:** expose `server_version`/`git_commit` and process start time in `discover(capabilities)`;
  `aep-sync` should detect running instances (`pgrep -f server.py` scoped to the checkout) and either signal
  them to reload or print a warning listing stale PIDs and parent harness. Never kill them automatically.

## 3. Usage metrics (iteration 3, orchestrator)

| Tool / action | Verbosity | Est. tokens (`t.tok`) | Useful | Note |
|---|---|---|---|---|
| `discover(capabilities, session_id)` | terse | 208 | high | once per session, as per RoE #8 |
| `topos_audit_dag` (10 nodes, two tracks) | terse | 290 | high | per-edge classification |
| `aep_ctl(schema)` | brief | 530 | high | revealed GAP-CP-04/OM-18 surfaces |
| `topos_audit_dag` (3 nodes, probe) | brief | 75 | medium | `resources` not passable → GAP-DX-05 |

### Sub-agent metrics (T2 ‖ T6 tracks)

| Agent / track | Tool / action | Verbosity | `t` (ms / tok) | Useful |
|---|---|---|---|---|
| Pragma A (T2) | `sandbox_run` pytest | brief | 1272 / 146 | yes |
| Pragma A (T2) | `sandbox_run` ruff check + format | brief | 23 / 133 | yes |
| Pragma B (T6, worktree) | `sandbox_run` ruff + pytest (2 runs) | brief | 2900–3900 / 204–404 | yes (exposed 2 failing legacy tests) |
| Dokimos A (T2) | `sandbox_run` pytest, `parse="pytest"` | brief | 1164 / 151 | yes |
| Dokimos A (T2) | `sandbox_run` ruff, `parse="ruff"` | brief | 25 / 136 | yes |
| Dokimos B (T6) | `sandbox_run` pytest, `parse="pytest"` (2 runs) | brief | 2705–3609 / 172 | yes (59 → 82 passed) |
| Pragma B fix (T6) | `sandbox_run` pytest / sh -c chain (2 runs) | brief | 3300 / 172 | partial (ruff output swallowed) |

| Orchestrator (post-merge) | `sandbox_run` pytest `parse="pytest"` + ruff `parse="ruff"` | brief | 3263 / 152 · 15 / 138 | yes (92/92, 0 violations) |

Iteration totals (orchestrator + 5 sub-agent stages + post-merge): 16 AEP calls, ~3.2k tokens — vs ~7.7k for 18 calls
in iterations 1–2 (**~−48 % tokens per call** after ONT-29).

**GAP-DX-04 verified from the client:** `parse="pytest"` returned
`{"passed":56,"failed":0,"errors":0,"skipped":0,"duration_s":0.71,"total":56}` and `parse="ruff"` returned
`{"violations":0,"fixable":0}`. Worktree `.venv` and the uv-managed interpreter were mounted correctly.

### Minor improvement points (no new GAP ID; candidates for a polish pass)
- **`brief` still echoes request inputs:** `ro_mounts`, `agent_id`, `share_net` and empty `stdout`/`stderr`
  strings remain in `brief`; with `parse=` the counts are the whole useful payload, yet ~130–150 tokens are
  fixed overhead. Suggest: in `brief` + `parse`, emit only `{status, exit_code, parsed, t}` (+ failing ids).
- **`parse="pytest"` failures detail:** on failure, include only failing test node ids (not full stdout).
- **Lint-fix in sandbox:** `working_dir` is mounted read-only, so `ruff format`/`ruff --fix` cannot run in the
  sandbox; agents fell back to plain shell. Suggest a documented recipe: `rw_paths=[<repo>]` +
  `share_net=False` for formatters, or a `mode="fix"` shortcut that mounts `working_dir` RW explicitly.
- **`parse=` swallows chained output:** with `command="sh -c 'ruff check . && pytest -q'"` and
  `parse="pytest"`, the parsed counts replace `stdout`, so the ruff result was lost and the agent re-ran ruff
  outside the sandbox. Suggest `parse="auto"` detecting multiple tools in one run
  (`parsed: {ruff: {...}, pytest: {...}}`), or keep a truncated `stdout_tail` when `parse` is set.
- **Adversarial/security probes bypass the sandbox:** Dokimos ran its SMT-LIB attack scripts (which found a
  segfault and arbitrary file writes in the consumer project) with plain Bash, because they need an RW scratch
  dir and a subprocess stdio client. These are exactly the runs that most need isolation. Suggest a playbook
  recipe "untrusted-input probe": `sandbox_run(working_dir=<repo>, rw_paths=[<scratch>], share_net=False)`
  and document that stdio subprocess clients work inside the jail.
- **Sub-agent adoption:** sub-agents did not use `playbook_run(action="batch")` to chain ruff + pytest
  (one agent noted a single `ruff && pytest` command would have saved a round trip). The playbook could
  recommend `parse="auto"` with a chained command for "lint + test" as the canonical verification call.
