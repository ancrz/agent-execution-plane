# Feature Pipeline Document: Autonomous Zero-Dependency Setup & Updater, Python 3.14 Production LTS Migration & Complete Tooling Self-Provisioning

- **Document ID**: `feature_20261025_051500_autonomous_setup_updater_and_python314_migration.md`
- **Previous Document**: [`feature_20261025_031500_backup_restore_and_offensive_countermeasures.md`](feature_20261025_031500_backup_restore_and_offensive_countermeasures.md)
- **Chain Rollup Summary**: [`feature_rollup.md`](feature_rollup.md) (Consolidated History Docs 1-16)
- **Next Document**: `Hermon (Stage 6) Atomic Conventional Release & Push`
- **Pipeline Mode**: `Full` (Topos Integrity Protocol — Archon Strategic Plan & Ontos Structural Audit)
- **Kanban Task ID**: `Task 113` (`feat:autonomous_setup_updater_and_python314_migration`) in `/home/ancruz/.local/share/agent-os/artifacts.db` — Status: `PROMOTED` (Promotion Score: `0.9250`, Verdict: `TRUST`, Confidence: `1.00`, Attempts: 3)
- **Plan Scope**: Establishes complete self-contained deployment autonomy, deterministic zero-dependency bootstrapping, and Python 3.14 Production LTS migration for the Agent Execution Plane (AEP). Eliminates external environment fragility by engineering `scripts/setup.sh` into an autonomous dual-mode bootstrapper, updater, and health auditor. Provisions all tooling in user-space or via non-interactive sudo: Astral `uv` toolchain, hermetic Python 3.14 virtual environment with isolated semantic dependencies, automated Golang toolchain self-provisioning (APT or user-space static tarball fallback), static compilation of Go diagnostic probes (`socket-monitor`, `fd-rescuer`), Bubblewrap (`bwrap`) containerization with fail-soft degradation, Pueue daemon musl binary auto-download and user-space service activation, automated Playwright Chromium provisioning, Omarchy universal skills hub linking, tracked git pre-commit hooks, and atomic MCP multi-agent auto-plugging with Connect-RPC hot reload.
- **Current Status**: `STAGE 2 (G2): POST-DOKIMOS VERIFIED & KNOWLEDGE GRAPH FINALIZED (ROUTING TO HERMON STAGE 6)`
- **Timestamp**: 2026-10-25T05:45:00Z (G2 Finalization)
- **Author**: Graphos (Universal State Manager & Knowledge Graph Custodian — Stage 2 G2)
- **Target Blast Radius**:
  - `pyproject.toml`: Modernization to Python 3.14 LTS (`requires-python = ">=3.14"`, `target-version = "py314"`).
  - `scripts/setup.sh`: Complete rewrite into a dual-mode engine supporting full provisioning, `--update`/`--upgrade`, and `--check` read-only health inspection.
  - `scripts/aep-mcp-launch.sh`: Launcher interpreter resolution ensuring hermetic Python 3.14 venv execution.
  - `scripts/aep-sync.sh`: Auto-plug delegation and Connect-RPC hot reload for Antigravity / Codex.
  - `templates/tpl_socket_monitor.go` & `templates/tpl_fd_rescuer.go`: Output targets in `~/.local/share/agent-os/bin/`.
  - Target documentation baseline: `docs/PROJECT.md`, `docs/MILESTONES.md`, `docs/COMPACT.md`.

---

## 1. State Evolution Map & Knowledge Graph

```mermaid
flowchart TD
    subgraph Chain["Interwoven Knowledge Graph Chain (Unbroken Sequence)"]
        D15["Predecessor: feature_20261025_031500_backup_restore_and_offensive_countermeasures.md<br/>(Milestone ONT-11: 5-Slot Hot Backup Engine & Offensive Countermeasures)"]
        D16["Current: feature_20261025_051500_autonomous_setup_updater_and_python314_migration.md<br/>(Milestone ONT-12: Autonomous Setup/Updater & Python 3.14 LTS Migration)"]
        R1["Chain Rollup: feature_rollup.md<br/>(Consolidated History Docs 1 to 15)"]
        D15 -->|"unbroken anchor chain"| D16
        D16 -.->|"rollup historical anchor"| R1
    end

    subgraph Pipeline["Full Mode Pipeline Lifecycle (Topos Integrity Protocol)"]
        A1["Archon (Stage 1)<br/>Strategic Plan Formulation & Topos DAG: COMPLETE ✅"]
        G1["Graphos G1 (Stage 2)<br/>Knowledge Graph Weave & Task 113 SYNTHESIZED: COMPLETE ✅"]
        O1["Ontos (Stage 3)<br/>Topos Structural & Interface Contract Audit (ONT-12): APPROVED ✅"]
        P1["Pragma (Stage 4)<br/>Implementation of TASK-01 to TASK-09: COMPLETE ✅"]
        DK1["Dokimos (Stage 5)<br/>Verification Multi-Gate (Gates 1 to 7): VERIFIED ✅"]
        G2["Graphos G2 (Stage 2)<br/>Documentation Sync & Baseline Compaction: COMPLETE (Current) 🔵"]
        H1["Hermon (Stage 6)<br/>Atomic Conventional Commit & Release: PENDING ⏳"]
    end

    D16 --> A1
    A1 --> G1
    G1 -->|"documented plan"| O1
    O1 -->|"APPROVED"| P1
    P1 --> DK1
    DK1 -->|"VERIFIED"| G2
    G2 -->|"ready for release"| H1
```

```mermaid
flowchart LR
    subgraph StateEvolution["State Evolution Map: Milestone ONT-12"]
        direction LR
        S0["Baseline Verified AEP<br/>(ONT-11 Backup Engine & Security Hardened) ✅"]
        S1["TASK-01: Python 3.14 LTS Migration<br/>(pyproject.toml py314 specification) ✅"]
        S2["TASK-02: Self-Provisioning uv Manager<br/>(~/.local/bin/uv auto-install & PATH) ✅"]
        S3["TASK-03: Hermetic Python 3.14 Venv<br/>(uv python install 3.14 & venv isolation) ✅"]
        S4["TASK-04: Golang Toolchain Self-Provisioning<br/>(sudo -n apt or ~/.local/share/go tarball) ✅"]
        S5["TASK-05: Static Pre-Compilation of Probes<br/>(socket-monitor & fd-rescuer static ELF) ✅"]
        S6["TASK-06: Bubblewrap Sandboxing Provisioning<br/>(bwrap detection & fail-soft fallback) ✅"]
        S7["TASK-07: Pueue Daemon Provisioning<br/>(musl binary auto-download & daemon start) ✅"]
        S8["TASK-08: Dual-Mode Bootstrapper & Updater<br/>(scripts/setup.sh --update & --check) ✅"]
        S9["TASK-09: Multi-Agent Hub & Auto-Plug<br/>(Skills symlinks & Connect-RPC hot-reload) ✅"]
        S10["Dokimos Multi-Gate Verification<br/>(Gates 1 to 7, Task 113 PROMOTED) ✅"]

        S0 --> S1 --> S3
        S0 --> S2 --> S3
        S0 --> S4 --> S5
        S0 --> S6
        S0 --> S7
        S3 --> S8
        S5 --> S8
        S6 --> S8
        S7 --> S8
        S8 --> S9
        S9 --> S10
    end
```

```mermaid
flowchart TD
    subgraph ToposDAG["Topos Integrity Protocol Task Dependency DAG (Milestone ONT-12)"]
        T1["TASK-01: Python 3.14 LTS Migration & pyproject.toml Configuration ✅"]
        T2["TASK-02: Self-Provisioning Astral uv Tooling Engine ✅"]
        T3["TASK-03: Python 3.14 Hermetic Virtual Environment & Dependency Isolation ✅"]
        T4["TASK-04: Automated Golang Toolchain Self-Provisioning & User-Space Fallback ✅"]
        T5["TASK-05: Static Pre-Compilation of Go Diagnostic Probes (socket-monitor, fd-rescuer) ✅"]
        T6["TASK-06: Bubblewrap Sandboxing Provisioning & Fail-Soft Detection ✅"]
        T7["TASK-07: Pueue Daemon Self-Provisioning & User-Space Service Activation ✅"]
        T8["TASK-08: Dual-Mode Bootstrapper & Updater CLI Engine (scripts/setup.sh) ✅"]
        T9["TASK-09: Multi-Agent Hub Linking, Git Hooks & Hot-Reload Sync ✅"]

        T1 --> T3
        T2 --> T3
        T4 --> T5
        T2 --> T8
        T3 --> T8
        T4 --> T8
        T5 --> T8
        T6 --> T8
        T7 --> T8
        T8 --> T9
    end
```

---

## 2. Operating Premises & Tool Reach (P0, P1, P2)

- **Premise P0 (Agents-for-Agents Delivery & Deterministic Execution)**:
  - The primary deliverable is an autonomously self-provisioning runtime and validated system state, requiring zero human intervention on deterministic engineering procedures.
  - Setup, dependency synchronization, environment upgrades, and system health checks are owned deterministically by the pipeline scripts without interactive operator prompts.
  - Fail-soft invariants guarantee that non-root, air-gapped, or degraded environments continue operating gracefully without crashing parent agents.

- **Premise P1 (Tool Reach, Blast Radius & Self-Provisioning Tooling Cascade)**:
  - **Tool Reach**: Extends beyond existing system binaries by establishing automated user-space self-provisioning for all required toolchains:
    - `uv`: High-performance Rust-based Python package and toolchain manager.
    - `Python 3.14`: Managed hermetically by `uv` independent of Ubuntu system Python releases.
    - `Golang`: Automated user-space fallback (`~/.local/share/go`) when root APT privileges are unavailable.
    - `Pueue`: User-space static musl binary execution for non-blocking asynchronous dispatch.
  - **Standard vs. Non-Conventional Execution Paths**:
    - Standard Path: System package manager (`apt-get`) via non-interactive passwordless sudo (`sudo -n apt-get install -y ...`).
    - Non-Conventional User-Space Path: Automated static binary and tarball extraction into `~/.local/bin` and `~/.local/share/` with dynamic PATH resolution, operating fully unprivileged.
    - Read-Only Audit Path (`--check`): Deterministic non-destructive inspection of versions, daemon processes, and symlink integrity returning structured machine-readable exit codes.
  - **Safety Boundary & Invariants**:
    - Under no circumstances may `setup.sh` or its subroutines trigger interactive sudo prompts (`sudo -n` is strictly required).
    - If root privileges are unavailable and a package cannot be downloaded in user-space, the system must degrade fail-soft (e.g. Bubblewrap degrading to unshare/host, semantic catalog degrading to hash-only).
    - User configuration files (`~/.bashrc`, `~/.zshenv`) must never accumulate duplicate entries across multiple runs (strict idempotency).

- **Premise P2 (Pipeline Mode & Budget Control)**:
  - Mode: **Full** (Archon Plan -> Graphos G1 Weave -> Ontos Audit -> Pragma Execution -> Dokimos Verification -> Graphos G2 Rollup -> Hermon Commit).
  - All 9 tasks (TASK-01 to TASK-09) operate under Topos DAG constraints with zero cyclic co-dependencies (validated by `topos_audit_dag` verdict `APPROVED`).

---

## 3. Strategic Context & State of the Art (SOTA) Comparative Matrix

Traditional deployment and setup scripts in open-source AI tooling suffer from severe fragility: they presume interactive root access (`sudo apt-get`), hardcode system Python versions that conflict with OS packages (PEP 668 externally-managed environments), pollute user dotfiles with redundant PATH exports, and lack integrated self-update or diagnostic mechanisms. When executed by an autonomous agent, these scripts hang on password prompts, break system packages, or fail silently without structured telemetry.

Milestone ONT-12 establishes an autonomous zero-dependency systems engineering bootstrapper that sets a new industry standard for agentic runtime environments:

| Dimension | Conventional AI Setup Scripts (e.g. AutoGPT, LangChain, Ollama) | AEP Autonomous Bootstrapper & Updater (Milestone ONT-12) |
| :--- | :--- | :--- |
| **Python Lifecycle & Isolation** | Relies on ambient system Python or Conda; fails under Ubuntu PEP 668; slow pip resolution. | Hermetic Python 3.14 LTS managed via Astral `uv` (`uv python install 3.14`); sub-second dependency resolution; zero OS package pollution. |
| **Privilege Model & Escalation** | Interactively prompts for `sudo`, hanging background agent processes indefinitely. | Fully non-interactive: probes `sudo -n`; utilizes root if available; seamlessly falls back to user-space static binaries if unprivileged. |
| **Go Toolchain Availability** | Assumes `go` is pre-installed; compilation fails if missing. | Dual-tier auto-provisioning: installs via `apt` if sudo is available; downloads and installs official Go tarball to `~/.local/share/go` if unprivileged. |
| **Background Queue Daemon** | Requires root systemd services or manual terminal execution of message brokers. | Automatic download of static musl `pueue`/`pueued` binaries to `~/.local/bin`; launches via `systemd --user` or detached daemon. |
| **Execution Modes** | Single-shot destructive install; re-running creates duplicate entries and overwrites configs. | Tri-mode engine: idempotent full setup, `--update`/`--upgrade` for all components, and `--check` for non-destructive health audits. |
| **Dotfile Hygiene** | Appends duplicate `export PATH=...` lines to `.bashrc` on every invocation. | Guarded idempotency blocks; single-source shell environment (`aep-env.sh`) sourced cleanly across bash, zsh, and POSIX sh. |
| **Agent Hub & MCP Integration** | Manual configuration of MCP JSON files per agent. | Automatic multi-agent symlinking (Omarchy SPEC-OM-3) and hot reload via Connect-RPC `RefreshMcpServers` and Codex socket proxy. |
| **Diagnostic Verification** | None; silent failures discoverable only at runtime. | Deterministic `--check` suite auditing binaries, versions, running daemons, and symlink targets with 0/1 exit codes. |

---

## 4. Mandate 1: Python 3.14 Production LTS Migration Architecture

### 4.1 Rationale for Python 3.14 Production LTS
Python 3.14 represents the premier modern LTS standard for high-performance Python systems engineering:
1. **Deferred Evaluation of Annotations (PEP 649)**: Annotations are evaluated lazily only when inspected via `annotationlib`, eliminating runtime overhead for heavy type hints and resolving forward reference circularities.
2. **Free-Threading & Concurrency Enhancements (PEP 703)**: Mature support for disabling the Global Interpreter Lock (GIL), enabling true CPU-bound parallelism for concurrent agent swarms without inter-process IPC overhead.
3. **Interpreter Performance & JIT Specialization**: Substantial performance improvements in bytecode specialization and C-API execution speed, reducing FastMCP stdio event loop processing times.
4. **Standard Library Modernization**: Enhanced asynchronous primitives, refined subprocess management, and strict type checking compliance.

### 4.2 Configuration Specification (`pyproject.toml`)
- Update `requires-python` constraint:
  ```toml
  [project]
  requires-python = ">=3.14"
  ```
- Modernize Ruff linter and formatter targets:
  ```toml
  [tool.ruff]
  target-version = "py314"
  line-length = 120
  ```
- Preserve existing zero-regression rule matrix: E, W, F, I, UP, S, BLE, PLW, FURB with explicit FastMCP fail-soft per-file ignores.

### 4.3 Hermetic Toolchain Management via Astral `uv`
To ensure absolute environment reproducibility across Ubuntu hosts without interfering with the host OS Python distribution:
1. `uv` installs and manages standalone, isolated Python 3.14 toolchains:
   ```bash
   uv python install 3.14
   ```
2. The AEP runtime virtual environment is created hermetically:
   ```bash
   uv venv --python 3.14 "$HOME/.local/share/agent-os/venv"
   ```
3. Runtime dependencies are synchronized into the hermetic venv:
   - `mcp` (Model Context Protocol FastMCP SDK)
   - `anyio>=4.0.0` (Asynchronous worker thread concurrency)
   - `pydantic>=2.0.0` (FastMCP schema validation and serialization)
   - `sqlite-vec` (C-extension vector similarity search)
   - `fastembed` (Local ONNX text embeddings)
   - `playwright` (Headless browser automation)

---

## 5. Mandate 2: Zero-Dependency Self-Provisioning Bootstrapper & Updater (`scripts/setup.sh`)

### 5.1 Dual-Mode CLI Engine Architecture
`scripts/setup.sh` is transformed into an autonomous, self-contained lifecycle manager supporting three operational invocations:

1. **Default Mode (`./scripts/setup.sh`)**:
   - Executes full idempotent provisioning: directories, Astral `uv`, Python 3.14 hermetic venv, Go toolchain, static diagnostic probes, Bubblewrap, Pueue daemon, Playwright Chromium, Omarchy skills hub, git hooks, and MCP seeding.
   - Guaranteed idempotent: re-running against an already-provisioned host completes in seconds without side effects.

2. **Updater Mode (`./scripts/setup.sh --update` or `./scripts/setup.sh --upgrade`)**:
   - Checks and pulls the latest versions of all self-provisioned components:
     - `uv self update`
     - Upgrades Python 3.14 venv dependencies via `uv pip install --upgrade`
     - Queries GitHub API for latest Pueue release and updates binary if newer
     - Re-compiles Go diagnostic probes (`socket-monitor`, `fd-rescuer`)
     - Updates Playwright browser binaries
     - Re-triggers `aep-sync.sh` hot reload

3. **Health Audit Mode (`./scripts/setup.sh --check`)**:
   - Read-only non-destructive inspection of system health:
     - Verifies presence and executable permissions of `uv`, `python3.14`, `go`, `bwrap`, `pueue`, `pueued`.
     - Verifies Python venv integrity and imports (`mcp`, `anyio`, `pydantic`, `sqlite-vec`, `fastembed`).
     - Verifies Pueue daemon responsiveness (`pueue status`).
     - Verifies Omarchy skills hub symlinks and pre-commit hook tracking.
     - Emits structured terminal report and exits with `0` (HEALTHY) or `1` (DEGRADED).

### 5.2 Complete Tooling Self-Provisioning Pipeline

#### 1. Astral `uv` Self-Provisioning:
- Check if `uv` is present in `PATH` or `~/.local/bin/uv`.
- If missing: automatically fetch and execute the official standalone installer (`curl -LsSf https://astral.sh/uv/install.sh | sh`) targeting `~/.local/bin/uv`.
- Ensure `~/.local/bin` is immediately active in the script's `PATH`.
- In update mode: execute `uv self update`.

#### 2. Golang Toolchain Self-Provisioning:
- Check if `go` is available.
- If missing:
  - Attempt non-interactive APT installation: `sudo -n apt-get update -y && sudo -n apt-get install -y golang-go` (suppressing password prompts).
  - If `sudo -n` fails (unprivileged environment): download official static Go linux-amd64 tarball from `https://go.dev/dl/`, extract into `~/.local/share/go`, and symlink `go` into `~/.local/bin/go`.
- Compile diagnostic probes statically:
  ```bash
  CGO_ENABLED=0 go build -ldflags="-s -w" -o "$HOME/.local/share/agent-os/bin/socket-monitor" "$PROJECT_ROOT/templates/tpl_socket_monitor.go"
  CGO_ENABLED=0 go build -ldflags="-s -w" -o "$HOME/.local/share/agent-os/bin/fd-rescuer" "$PROJECT_ROOT/templates/tpl_fd_rescuer.go"
  ```

#### 3. Bubblewrap (`bwrap`) Provisioning:
- Check if `bwrap` is available.
- If missing: attempt non-interactive install via `sudo -n apt-get install -y bubblewrap`.
- If unprivileged and missing: log clear notice and configure `sandbox_run` fail-soft mode.

#### 4. Pueue Daemon Self-Provisioning:
- Check if `pueued` and `pueue` binaries exist in `PATH` or `~/.local/bin`.
- If missing: query `https://api.github.com/repos/Nukesor/pueue/releases/latest` to resolve latest release tag, download pre-compiled `x86_64-unknown-linux-musl` static binaries, and install to `~/.local/bin`.
- Daemon activation: attempt `systemctl --user enable --now pueued`; fallback to detached daemon spawn `pueued -d` with `stdin=DEVNULL`, `stdout=DEVNULL`, `stderr=DEVNULL`, `close_fds=True`.

#### 5. Headless Chromium Provisioning:
- Execute `$VENV_DIR/bin/python -m playwright install chromium`.
- Verify presence of browser binary; fail-soft if dependencies missing (gracefully falls back to `DISPLAY_UNAVAILABLE`).

#### 6. Omarchy Universal Skills Hub & Git Hooks:
- Idempotently link skills directories:
  ```bash
  ln -sfn "$HOME/.agents/skills" "$HOME/.claude/skills/shared"
  ln -sfn "$HOME/.agents/skills" "$HOME/.gemini/skills/shared"
  ln -sfn "$HOME/.agents/skills" "$HOME/.codex/skills/shared"
  ```
- Track git pre-commit hook via repository configuration:
  ```bash
  git config core.hooksPath scripts/hooks
  chmod +x scripts/hooks/pre-commit
  ```

#### 7. Auto-Plug & Hot-Reload Integration:
- Delegate registration and live reloading to `scripts/aep-sync.sh`:
  - Registers FastMCP server with launcher `scripts/aep-mcp-launch.sh` across Claude Code (`~/.claude.json`), Antigravity (`~/.gemini/config/mcp_config.json`), and Codex (`~/.codex/config.json`).
  - Triggers Connect-RPC `RefreshMcpServers` to Antigravity without requiring IDE restart.
  - Sockets proxy signaling for Codex runtime.

---

## 6. Strategic Execution Plan Tasks (TASK-01 to TASK-09)

### TASK-01: Python 3.14 LTS Migration & pyproject.toml Configuration (COMPLETED ✅)
- **Module**: `pyproject.toml`
- **Scope**:
  - Update `requires-python = ">=3.14"`.
  - Update `[tool.ruff] target-version = "py314"`.
  - Verify syntax rules and per-file-ignores compatibility under Python 3.14.
- **Invariants**:
  - Zero syntax regressions.
  - Strict type hints adhere to PEP 585/604/649.
- **Blast Radius**: `pyproject.toml`.
- **Topos Classification**: Independent specification node.

### TASK-02: Self-Provisioning Astral `uv` Tooling Engine (COMPLETED ✅)
- **Module**: `scripts/setup.sh`
- **Scope**:
  - Implement `ensure_uv()` in `scripts/setup.sh`.
  - Detect `uv` in `PATH` and `~/.local/bin/uv`.
  - Download and install official standalone binary to `~/.local/bin/uv` if missing.
  - Support `uv self update` in `--update` mode.
  - Inject `~/.local/bin` into execution environment PATH.
- **Invariants**:
  - User-space installation without requiring root/sudo.
  - Idempotent invocation: does not re-download if `uv` is already operational.
- **Blast Radius**: `scripts/setup.sh`, `~/.local/bin/uv`.
- **Topos Classification**: Dependency for TASK-03 and TASK-08.

### TASK-03: Python 3.14 Hermetic Virtual Environment & Dependency Isolation (COMPLETED ✅)
- **Module**: `scripts/setup.sh`, `scripts/aep-mcp-launch.sh`
- **Scope**:
  - Implement `setup_python_env()` using `uv`.
  - Execute `uv python install 3.14` to fetch standalone Python 3.14 toolchain.
  - Create hermetic venv at `~/.local/share/agent-os/venv` via `uv venv --python 3.14`.
  - Install dependencies via `uv pip install`: `mcp`, `anyio>=4.0.0`, `pydantic>=2.0.0`, `sqlite-vec`, `fastembed`, `playwright`.
  - Pre-cache default embedding model `BAAI/bge-small-en-v1.5`.
  - Update `scripts/aep-mcp-launch.sh` to resolve `$VENV_DIR/bin/python` preferentially.
- **Invariants**:
  - Completely isolated from Ubuntu system Python packages.
  - Fail-soft fallback if network is restricted: catalog operates in hash-only mode.
- **Blast Radius**: `scripts/setup.sh`, `scripts/aep-mcp-launch.sh`, `~/.local/share/agent-os/venv`.
- **Topos Classification**: Depends on TASK-01 and TASK-02.

### TASK-04: Automated Golang Toolchain Self-Provisioning & User-Space Fallback (COMPLETED ✅)
- **Module**: `scripts/setup.sh`
- **Scope**:
  - Implement `ensure_golang()` in `scripts/setup.sh`.
  - Check `command -v go` and `~/.local/bin/go`.
  - If missing: probe `sudo -n apt-get update -y && sudo -n apt-get install -y golang-go`.
  - If unprivileged: query official Go downloads, fetch `go*.linux-amd64.tar.gz`, extract to `~/.local/share/go`, and create symlink `~/.local/bin/go`.
  - Export `GOROOT` and `PATH` accordingly.
- **Invariants**:
  - Zero interactive password prompts.
  - Fully functional Go compiler available in user-space.
- **Blast Radius**: `scripts/setup.sh`, `~/.local/share/go`, `~/.local/bin/go`.
- **Topos Classification**: Prerequisite for TASK-05.

### TASK-05: Static Pre-Compilation of Go Diagnostic Probes (COMPLETED ✅)
- **Module**: `scripts/setup.sh`, `templates/tpl_*.go`
- **Scope**:
  - Implement `compile_probes()` in `scripts/setup.sh`.
  - Statically compile `socket-monitor` and `fd-rescuer`:
    - `CGO_ENABLED=0 go build -ldflags="-s -w" -o ~/.local/share/agent-os/bin/socket-monitor ...`
    - `CGO_ENABLED=0 go build -ldflags="-s -w" -o ~/.local/share/agent-os/bin/fd-rescuer ...`
  - Verify ELF binary execution and version output.
- **Invariants**:
  - Pure static ELF binaries (`CGO_ENABLED=0`) with zero external dynamic library dependencies.
- **Blast Radius**: `~/.local/share/agent-os/bin/`.
- **Topos Classification**: Depends on TASK-04.

### TASK-06: Bubblewrap Sandboxing Provisioning & Fail-Soft Detection (COMPLETED ✅)
- **Module**: `scripts/setup.sh`, `server.py`
- **Scope**:
  - Implement `ensure_bubblewrap()` in `scripts/setup.sh`.
  - Detect `bwrap` executable.
  - Attempt non-interactive installation via `sudo -n apt-get install -y bubblewrap` if missing.
  - If unprivileged and missing: log warning and set status flag for fail-soft sandboxing.
- **Invariants**:
  - Missing `bwrap` does not crash setup; logs advisory status.
- **Blast Radius**: `scripts/setup.sh`.
- **Topos Classification**: Independent system provisioning task.

### TASK-07: Pueue Daemon Self-Provisioning & User-Space Service Activation (COMPLETED ✅)
- **Module**: `scripts/setup.sh`
- **Scope**:
  - Implement `ensure_pueue()` in `scripts/setup.sh`.
  - Detect `pueue` and `pueued`.
  - If missing: fetch latest static musl binaries from GitHub releases to `~/.local/bin/`.
  - Start daemon via `systemctl --user enable --now pueued` or detached `pueued -d`.
  - Verify queue response via `pueue status`.
- **Invariants**:
  - Background daemon runs unprivileged in user-space.
  - Detached process hygiene (`DEVNULL` stdio, `close_fds=True`).
- **Blast Radius**: `scripts/setup.sh`, `~/.local/bin/pueue*`.
- **Topos Classification**: Independent service provisioning task.

### TASK-08: Dual-Mode Bootstrapper & Updater CLI Engine (COMPLETED ✅)
- **Module**: `scripts/setup.sh`
- **Scope**:
  - Implement CLI argument parsing:
    - Default (no arguments): full idempotent setup.
    - `--update` / `--upgrade`: update all components and tools.
    - `--check`: read-only audit of system components, versions, daemons, and symlinks.
    - `--help`: usage documentation.
  - Implement structured health audit table with pass/warn/fail indicators and appropriate exit codes.
  - Implement idempotent execution guards preventing duplicate configuration lines or symlinks.
- **Invariants**:
  - Multiple executions produce identical, idempotent states.
  - `--check` is strictly read-only and causes zero filesystem mutations.
- **Blast Radius**: `scripts/setup.sh`.
- **Topos Classification**: Coordinates TASK-02 through TASK-07; prerequisite for TASK-09.

### TASK-09: Multi-Agent Hub Linking, Git Hooks & Hot-Reload Sync (COMPLETED ✅)
- **Module**: `scripts/setup.sh`, `scripts/aep-sync.sh`
- **Scope**:
  - Implement `setup_agent_links()` and `setup_git_hooks()` in `scripts/setup.sh`.
  - Link `~/.agents/skills` to Claude, Gemini, and Codex using `ln -sfn`.
  - Configure `git config core.hooksPath scripts/hooks`.
  - Delegate MCP seeding to `scripts/aep-sync.sh`.
  - Trigger Connect-RPC `RefreshMcpServers` for Antigravity and Unix socket proxy for Codex.
- **Invariants**:
  - Seamless agent integration across all supported harnesses without manual restart.
- **Blast Radius**: `scripts/setup.sh`, agent configuration files, git configuration.
- **Topos Classification**: Depends on TASK-08; final step in provisioning chain.

---

## 7. Dokimos Multi-Gate Verification Matrix (Gates 1 to 7)

| Gate # | Name | Verification Scope | Target Artifacts | Acceptance Criteria | Status |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **Gate 1** | **Python 3.14 LTS & Hermetic Venv Validation** | Verify `pyproject.toml` configuration (`requires-python = ">=3.14"`, `target-version = "py314"`). Verify hermetic venv creates and runs Python 3.14 with `mcp`, `anyio`, `pydantic`, `sqlite-vec`. | `pyproject.toml`, `$VENV_DIR` | Python 3.14 binary active; all core modules importable without errors; zero host package contamination. | **PASS ✅** |
| **Gate 2** | **Astral `uv` Autonomous Provisioning & Upgrade** | Test `ensure_uv()` from clean state (simulating missing `uv`). Verify auto-download to `~/.local/bin/uv`. Test `uv self update` in `--update` mode. | `scripts/setup.sh`, `~/.local/bin/uv` | `uv` installs cleanly in user-space; path resolves; self-update succeeds without sudo. | **PASS ✅** |
| **Gate 3** | **Golang Self-Provisioning & Static Probe Compilation** | Verify Go auto-installation (APT or user-space static tarball fallback). Compile `socket-monitor` and `fd-rescuer` via `CGO_ENABLED=0`. | `scripts/setup.sh`, `~/.local/share/agent-os/bin/` | Go compiler functional; binaries are pure static ELF executables; execute with exit code 0. | **PASS ✅** |
| **Gate 4** | **Pueue Daemon & Bubblewrap Provisioning** | Verify Pueue musl binary download and daemon auto-launch. Verify `pueue status` returns valid queue. Verify `bwrap` detection. | `scripts/setup.sh`, `~/.local/bin/pueue*` | Pueue daemon active and responsive; jobs can be queued; bwrap detected or gracefully degraded. | **PASS ✅** |
| **Gate 5** | **Dual-Mode Engine & Health Audit (`--check`)** | Execute `setup.sh --check`. Verify non-destructive inspection of all components. Verify exit code 0 on healthy system and 1 on broken component. | `scripts/setup.sh` | Read-only check audits all 7 subsystem areas; produces structured summary; zero file mutations. | **PASS ✅** |
| **Gate 6** | **Idempotency & Dotfile Hygiene** | Execute `setup.sh` 3 consecutive times. Inspect `.bashrc`, `.zshenv`, and symlinks for duplicate lines or broken pointers. | User dotfiles, symlinks | 0 duplicate lines in config files; symlinks remain canonical and intact; execution time < 3s on repeat runs. | **PASS ✅** |
| **Gate 7** | **Multi-Agent Hub & Auto-Plug Hot-Reload** | Verify Omarchy skills hub symlinks across Claude, Gemini, Codex. Verify `aep-sync.sh` registers MCP and Connect-RPC reloads servers. | `scripts/setup.sh`, `scripts/aep-sync.sh` | 3 agent skill hubs linked; git pre-commit hook active; FastMCP 15 tools verified; hot reload signaled cleanly. | **PASS ✅** |

---

## 8. Ontos Structural & Contract Pre-Audit Checklist (ONT-12)

- [x] **Topos Task DAG Validated**: `topos_audit_dag` executed with verdict `APPROVED` (Grafo coherente: Cero co-dependencias detectadas; TASK-01 to TASK-09 form a strict directional DAG).
- [x] **Unbroken Knowledge Graph Sequence**: Predecessor anchor `feature_20261025_031500_backup_restore_and_offensive_countermeasures.md` linked.
- [x] **Rollup History Consolidated**: Rollup document `feature_rollup.md` (Docs 1-16) referenced.
- [x] **Kanban State Synchronized**: Task 113 transitioned from `BACKLOG` to `SYNTHESIZED` in `/home/ancruz/.local/share/agent-os/artifacts.db`.
- [x] **Dependency Direction Validated**: TASK-01 (pyproject) and TASK-02 (uv) precede TASK-03 (venv); TASK-04 (Go) precedes TASK-05 (probes); TASK-08 orchestrates provisioning; TASK-09 finalizes seeding.
- [x] **Zero-Dependency User-Space Autonomy**: Complete user-space fallbacks codified for `uv`, `go`, and `pueue`, eliminating interactive sudo blockers.
- [x] **Idempotency Invariants Established**: Multiple executions guaranteed to produce identical clean states without duplicate config entries.
- [x] **Tri-Mode Operational Interface**: Default setup, `--update`/`--upgrade`, and `--check` formally specified with input/output contracts.
- [x] **Dokimos Verification Gates Defined**: 7-Gate verification matrix specified with rigorous pass/fail criteria.

---

## 9. Ontos Structural Audit & Pre-Execution Baseline

- Ontos Stage 3 audit completed: **APPROVED**.
- Mandatory directives DIR-ONT-01 through DIR-ONT-04 established and verified.


---

## 10. Dokimos Verification Summary & Quality Gate Certification

Dokimos conducted full multi-gate verification (Gates 1 through 7) under the Topos Integrity Protocol, certifying Milestone ONT-12 as **VERIFIED**:

- **Execution Report**: [`execution_report_20261025_053000_autonomous_setup_updater_and_python314_migration.md`](execution_report_20261025_053000_autonomous_setup_updater_and_python314_migration.md)
- **Verification Report**: [`verification_report_20261025_054000_autonomous_setup_updater_and_python314_migration.md`](verification_report_20261025_054000_autonomous_setup_updater_and_python314_migration.md)
- **Verdict**: **`VERIFIED`** (All 7 Mandatory Gates Passed — Zero Defect / Zero Regression)
- **Kanban Promotion**: `PROMOTED` in `/home/ancruz/.local/share/agent-os/artifacts.db`
  - Promotion Score: `0.9250` (exceeds the 0.75 TRUST threshold)
  - Verdict: `TRUST`
  - Confidence: `1.00`
  - Ponderation Dimensions: `{"quality": 1.0, "reliability": 1.0, "experience": 0.5, "recency": 1.0}`
  - Attempts: 3
- **Gates Validated**:
  1. Gate 1 (FastMCP Parity): 15 FastMCP tools and 18 capability definitions verified intact. `./scripts/aep-sync.sh --check` passed cleanly (exit code 0).
  2. Gate 2 (Read-Only Health Check): `./scripts/setup.sh --check` returned exit code 0 (`HEALTHY`) with zero side-effects and zero filesystem mutations (DIR-ONT-01 verified).
  3. Gate 3 (Setup Idempotency Suite): `tests/test_setup_idempotency.sh` 6/6 tests passed; repeat runs completed in <2s with zero duplicate exports in dotfiles.
  4. Gate 4 (Python 3.14 Hermetic Venv): Hermetic venv detected at `Python 3.14.7` (workspace) and `Python 3.14.4` (shared); `requires-python = ">=3.14"` and `target-version = "py314"` verified.
  5. Gate 5 (Go Probes Execution): `socket-monitor` and `fd-rescuer` verified as pure static 64-bit ELF executables; CLI and RAM execution (`artifact_execute_in_ram`) emitted structured JSON telemetry in <4ms.
  6. Gate 6 (Static Analysis & Security): Ruff linter passed with 0 errors / 0 warnings on Python 3.14; Semgrep evaluated 1,352 rules across 68 files with 0 findings.
  7. Gate 7 (Promotion Gate & Blast Radius): 12 modified files strictly adhere to authorized blast radius; Task 113 advanced to `PROMOTED`.

---

## 11. Graphos G2 State Transition & Routing Directive

- **Pipeline Stage**: `Stage 2 (G2) — Post-Dokimos Verification Weave & Knowledge Graph Rollup`
- **Active Intent / Milestone**: `Milestone ONT-12 (Autonomous Zero-Dependency Setup & Updater, Python 3.14 Production LTS Migration & Complete Tooling Self-Provisioning)`
- **Kanban Task State**: Task 113 `PROMOTED` (Score: `0.9250`, Verdict: `TRUST`, Confidence: `1.00`).
- **Knowledge Graph Anchor**: Sequence chain unbroken (`D15 -> D16`), rollup history updated in `docs/pipeline/feature_rollup.md`.
- **Baseline Maintenance**: `README.md`, `docs/MILESTONES.md`, `docs/PROJECT.md`, and `docs/COMPACT.md` fully synchronized.
- **Routing Decision**: Graphos certifies that all documentation, state evolution maps, and milestone records are synchronized. Routing directive emitted to **Hermon (Stage 6)** for atomic conventional release and commit.
