# SDD: ONT-42a `harness_reconnect` (RE-as-SDD)

- **Document ID**: `sdd_ont42a_harness_reconnect.md`
- **Milestone**: ONT-42a
- **re_source**: `orchestrator-inference-trace-2026-11-06`
- **re_mode**: `compatible`
- **Pipeline Mode**: Full (Archon -> Graphos G1 -> Ontos APPROVED with C1-C14 -> Pragma)
- **Status**: IMPLEMENTED (T8 live smoke test is user-gated and not run by Pragma)

## 1. Specify

**Problem.** After a hot-swap or an `aep_front.py` change, the MCP front serves old code until the
harness (Claude Code) reconnects the `agent-execution-plane` MCP server. The user has to type
`/mcp reconnect agent-execution-plane` by hand.

**Goal.** Let an authorised orchestrator trigger that single command in its own harness TTY, with
the smallest possible privilege window, and fall back to a manual instruction whenever the
primitive is unavailable.

**Inference trace (8 steps, from the orchestrator).**
1. `front_stale=true` is the only reliable signal that a harness reconnect is needed.
2. The reconnect command is a slash command typed into the harness prompt.
3. The harness is an ancestor of the front (`claude` -> MCP front), so its TTY is derivable from `/proc`.
4. The only keyboard-free way to feed a TTY from another process is `ioctl(TIOCSTI)`.
5. Since Linux 6.2 `TIOCSTI` is gated by `dev.tty.legacy_tiocsti` (default 0 here).
6. Flipping that sysctl needs root; `sudo -n` is NOPASSWD on this host.
7. The sysctl must be open for the shortest time possible and always restored.
8. If any link is missing (sysctl absent, EPERM, no harness, no pts) the answer is `manual`, not a hack.

**Acceptance criteria.** See section 4.

## 2. Plan

**Placement.** `aep_ctl(domain="ipc", action="harness_reconnect", params={"mode": "plan"|"execute", "confirm": bool, "server": str?})`.
Logic lives in `engine/harness_reconnect.py` (pure functions, injected dependencies, no import of `server`).
Rejected: `autoevol(action="heal")` (read-only semantic invariant of the thread graph).

**Harness table.** `HARNESS_RECONNECT = {"claude": "/mcp reconnect {server}"}`. Any other harness -> `manual`.

**Decision tree (`decision_tree`).** `front_stale=false` -> `noop`; harness not found / unknown ->
`manual`; no pts TTY -> `manual` (or `gui_unsupported` on a Wayland session); sysctl absent -> `manual`
(`unsupported`); otherwise `tty_inject`.

**Execute gates, fail-closed, in order.** tier 7rwx -> `confirm=true` (per call, never cached) ->
`front_stale` -> harness ancestry -> payload allowlist -> `flock` (non-blocking) -> open TTY and validate ->
audit `attempt` -> helper -> sysctl verification -> audit `result`.

**Privileged helper.** Fixed script `HELPER_SCRIPT`, run as
`sudo -n /usr/bin/python3 -I -S -c <script> -- <major> <minor> <payload_hex>` with minimal `env`,
`start_new_session=True` and a timeout (SIGTERM to the process group).
Amendment (orchestrator, binding, supersedes C2): sudo closes fds >= 3, so `pass_fds` never reaches the
helper. The already-opened and validated TTY fd is given as **stdin (fd 0)** of the sudo subprocess.
The helper never receives a path. It re-validates `fstat(0)` (char device, major 136, rdev equals the
expected one from argv, `isatty`), re-validates the decoded payload against the allowlist, reads the
original sysctl, installs SIGTERM/SIGINT/SIGHUP handlers plus `try/finally` to restore it, sets it to 1,
injects byte by byte, restores, re-reads and reports JSON. The parent re-reads the sysctl in its own
`finally`; a mismatch is `FAIL` with `severity=CRITICAL`.

**TTY safety (C2/C3).** Ancestry resolved once. `/proc/<pid>/exe` basename equals `claude`, the process
uid equals `os.getuid()`, the harness is a real ancestor. The TTY is opened as the user with
`O_RDWR|O_NOCTTY|O_NOFOLLOW`, and on the open fd the parent requires `isatty`, `S_ISCHR`, major 136,
`st_uid == getuid()` and `rdev == tty_nr` from `/proc/<harness>/stat`.

**Payload (C5).** Exactly `/mcp reconnect <server>` + `\r`; server matches `^[a-z0-9][a-z0-9_-]{0,63}$`.

**Lock (C7).** `flock(LOCK_EX|LOCK_NB)` on `$XDG_RUNTIME_DIR/aep_harness_reconnect.lock` (0600), falling back
to `/run/user/<uid>`, else reject. A held lock returns `BUSY`.

**Audit (C8).** `engine.security.record_audit_event` on a RW connection. Rejections and executions try the
ledger; failure logs and returns `audit_degraded=true`. Details carry harness, tty rdev, server and sysctl
values, never the raw payload.

**Schema (C1).** Preconditions are per action: `harness_reconnect` uses `privilege_tier: "FULL"`
(valid tiers are FULL/DIMINISHED). `plan` works at any tier; the handler rejects `execute` when the tier is not 7rwx.

**D-25.** `commit_stale` is removed from `is_stale`. `is_stale = fp_stale or serving_from == "lkg"`, plus
the conservative case "HEAD changed and the loaded fingerprint is unavailable/`unknown`" (C10d).
`commit_drift` is emitted only when true. `next_action` distinguishes docs-only drift (no restart) from
fingerprint drift and points to `harness_reconnect` (plan) when `front_stale`.

**Tool reach (P1).** stdlib only (`os`, `subprocess`, `fcntl`, `termios`). Tool Awareness Cascade resolves at
step 1. Blast radius: `plan` read-only; `execute` one global sysctl for under 2 s and keystrokes in one TTY.
Tests never touch the real sysctl, a real TTY or a real `sudo`.

**Dependency classification.** engine -> privilege, engine -> security (dep); schema <-> ipc branch (interdep,
same commit); `discover` stale <-> `threads_heal.next_action` (interdep); no co-dependency.

## 3. Tasks

T1 SDD + feature doc. T2a pure functions. T2b `execute` + `HELPER_SCRIPT`. T3+T4 schema and ipc branch.
T5 D-25 and `next_action`. T6b conftest isolation fixture and session guard. T7 docs. T8 live smoke (user-gated).

## 4. Validate

- Unit tests with doubles for every gate, every fail-closed branch and sysctl restore on helper raise or timeout.
- D-25 tests: docs-only commit with equal fingerprint -> `stale=false`, `commit_drift=true`; code-changing commit -> `stale=true`;
  `serving_from=lkg` -> `stale=true`; HEAD changed with unknown loaded fingerprint -> `stale=true`.
- Schema tests, `test_token_budgets.py` green, discover terse <= 400 tokens in `front_stale` + SERVING_LKG.
- `dev.tty.legacy_tiocsti` identical before and after the suite (read-only check).
- T8 (user-gated): `plan` -> `execute confirm=true` -> `discover terse` shows `front_stale=false`, a new pid, sysctl 0.

**Discarded routes.** Kill the front PID (the harness does not respawn it reliably and loses session state);
`/mcp reconnect all` (reconnects unrelated servers); ydotool/xdotool/wtype GUI injection (needs a GUI focus
guarantee, unavailable on GNOME Wayland, wrong window risk); Ctrl-U prefix (behaviour in Claude Code unverified).

**Fallback `unsupported` -> `manual`.** If the sysctl file is missing, `ioctl` returns EPERM, the helper reports a
stdin mismatch, or sudo needs a password, the result is `unsupported` with `route=manual` and the exact command for the
user to type. No state changes.

**Known limitations (caveats).**
1. Typed-prompt hazard (accepted by the orchestrator): if the user has a half-typed prompt, the injected
   text is appended to it and `\r` submits everything. Not mitigated (no Ctrl-U, idle state is not detectable).
2. `TIOCSTI` is a legacy, security-sensitive interface; the sysctl is global for under 2 s, so any process of the same
   session could also inject during that window.
3. If `sudo` is configured with `use_pty`, it may replace stdin with a fresh pty. The helper's `fstat(0)` rdev check
   then fails closed (`unsupported` -> `manual`). Confirmed or ruled out only by the T8 smoke test.

## 5. Multi-Harness Standardization (`dimensional_bridge_4d`)

To elevate `harness_reconnect` from a Claude-only workaround into a universal out-of-band ("4th-dimension") agentic bridge (`PRIMITIVE_NAME = "dimensional_bridge_4d"`), `engine/harness_reconnect.py` and `aep_ctl(domain="ipc", action="harness_reconnect")` standardize four harness profiles across two out-of-band control transports:

| Harness ID | Process Signatures (`/proc/<pid>/exe` / `cmdline`) | Preferred Transport | Out-of-Band Mechanism / Fallback |
|------------|---------------------------------------------------|---------------------|----------------------------------|
| `claude` | `claude`, `/.local/share/claude/versions/*` | `tty_inject` | Kernel `dev.tty.legacy_tiocsti` (brief flip `< 2s`) + `ioctl(TIOCSTI)` `/mcp reconnect <server>\r` on ancestor `/dev/pts/*` |
| `agy` | `agy`, `antigravity`, `language_server_linux*` | `rpc_reload` | Local Connect-RPC `RefreshMcpServers` on `language_server_linux_x64` (`--csrf_token` + dynamic localhost port); fallback: AGY Command Palette |
| `codex` | `codex`, `codex-cli` | `rpc_reload` | `codex app-server proxy --sock $XDG_RUNTIME_DIR/codex/app-server-control.sock` JSON-RPC `config/mcpServer/reload` (fallback: `tty_inject` `/mcp\r`) |
| `gemini` | `gemini`, `gemini-cli` | `tty_inject` | Kernel `dev.tty.legacy_tiocsti` + `ioctl(TIOCSTI)` `/mcp refresh\r` on ancestor `/dev/pts/*` |

**Extended `params` contract (`aep_ctl(domain="ipc", action="harness_reconnect")`)**:
- `harness?: "claude" | "agy" | "codex" | "gemini"` — explicit target harness override (useful when invoking an RPC-capable harness whose server process is a sibling rather than a direct `/proc` ancestor).
- `force?: bool` — when `True`, allows on-demand out-of-band execution even when `front_stale=False` (still strictly gated by `tier == "7rwx"` and per-call `confirm=True`).

