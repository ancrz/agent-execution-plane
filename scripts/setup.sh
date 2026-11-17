#!/usr/bin/env bash
# =============================================================================
# setup.sh — AEP Autonomous Zero-Dependency Setup & Tooling Provisioner
# Dual-mode bootstrapper, updater, and read-only health auditor.
# Supports: Ubuntu / Linux (POSIX sh / bash / zsh)
# =============================================================================
# shellcheck disable=SC2034  # los *_SHA256_* se resuelven por expansión indirecta ${!VAR}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="$HOME/.local/bin:$HOME/.local/share/go/bin:$HOME/.local/share/agent-os/bin:$PATH"

# -----------------------------------------------------------------------------
# Versiones fijadas y checksums SHA-256 (integridad de la cadena de suministro).
# Para actualizar: cambia versión + hashes juntos, tomando los hashes de la fuente oficial indicada.
# -----------------------------------------------------------------------------
# uv 0.13.7 — hashes: assets oficiales `uv-<arch>-unknown-linux-gnu.tar.gz.sha256` del release
#   https://github.com/astral-sh/uv/releases/tag/0.13.7
UV_VERSION="0.13.7"
UV_SHA256_x86_64="c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83"
UV_SHA256_aarch64="71279f8d3c67241e807b9d8db872d1bf541579fb9f08b7d1eb1682196d1e57dc"
# Go 1.27.4 — PIN DE CAÍDA (ONT-59/T5): solo se usa con AEP_GO_CHANNEL=pinned o si go.dev no es alcanzable.
#   Con el canal `stable` (por defecto) la versión y su sha256 se resuelven en https://go.dev/dl/?mode=json.
#   hashes: https://go.dev/dl/?mode=json (campo sha256 de cada archive linux), verificados el 2026-11-14.
GO_VERSION="1.27.4"
GO_SHA256_amd64="7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840"
GO_SHA256_arm64="3392582988a273a87ab5043ee1b2c9c17a2c3c00580bf9326c47a2e0aaaeac92"
# golangci-lint v2.15.0 (go.mod go 1.26.0; binario compilado con Go 1.27.0, compatible con Go 1.26.10) — hashes:
#   golangci-lint-2.15.0-checksums.txt (asset oficial del release)
#   https://github.com/golangci/golangci-lint/releases/tag/v2.15.0
GL_VERSION="2.15.0"
GL_SHA256_amd64="9b7fe6a6bf6334b98decf8d86b11415ea7889afdabdd1959fdce23af2a9ebcea"
GL_SHA256_arm64="b4d8f17068b35ee6060cc2f69a16fb48740d706fbba81661c318649c114a6998"
# pueue v4.0.4 — el release NO publica checksums: sha256 calculado localmente sobre los assets
#   https://github.com/Nukesor/pueue/releases/tag/v4.0.4 (musl) el 2026-11-07 (TOFU, fijado desde esa fecha).
PUEUE_VERSION="v4.0.4"
PUEUE_SHA256_x86_64_pueue="c1b10d7e4e62211075ddd0e1dc3e8cbfc5a43d662cb3be7402a28504e23fcb51"
PUEUE_SHA256_x86_64_pueued="5afeff6adbafb909e8d54e2caff158e6966c2adffa2c09e60fd631cc51b60390"
PUEUE_SHA256_aarch64_pueue="759bf5100a51024997111c6913aaf3330a0cdfd893ff552dcf429ae9b5e01e09"
PUEUE_SHA256_aarch64_pueued="332c5ef74270b64aeaf04894c8c04826f3422eb7d50dbd1a8e0706d74a42f653"

# -----------------------------------------------------------------------------
# Color Codes & Terminal Logging
# -----------------------------------------------------------------------------
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERR]${NC} $1"; }

show_help() {
    cat << 'HELP'
Usage: ./scripts/setup.sh [OPTIONS]

Options:
  --tier                Output strictly the detected chmod octal string (7rwx, 6rw-, 5r-x, 4r--).
  --predict, --plan     Display predictive privilege degradation plan without mutating system.
  --check               Execute 100% read-only health audit calibrated to current privilege tier
                        (NO file modifications, exits 0 if healthy, 1 if degraded).
  --update, --upgrade   Update self-provisioned toolchains, venv dependencies,
                        and recompile probes.
  --help, -h            Show this help message.

Default (no flags):
  Full idempotent provisioning of uv, Python 3.14 hermetic venv, Go toolchain (channel AEP_GO_CHANNEL=stable|pinned),
  static probes, Pueue daemon, Playwright, Omarchy skill hubs, and MCP seeding.
HELP
}

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# STEP 0: Predictive Privilege Probing & Chmod Octal Detection (ONT-33)
# -----------------------------------------------------------------------------
detect_tier() {
    if [[ -n "${AEP_FORCE_TIER:-}" ]]; then
        echo "$AEP_FORCE_TIER"
        return 0
    fi
    if [[ -n "${AEP_CHMOD_TIER:-}" ]]; then
        echo "$AEP_CHMOD_TIER"
        return 0
    fi

    local PY_CMD=""
    if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
        PY_CMD="$PROJECT_ROOT/.venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PY_CMD="python3"
    fi

    if [[ -n "$PY_CMD" ]]; then
        local DETECTED
        DETECTED=$(PYTHONPATH="$PROJECT_ROOT" "$PY_CMD" -m engine.privilege --tier 2>/dev/null || echo "")
        if [[ "$DETECTED" =~ ^(7rwx|6rw-|5r-x|4r--)$ ]]; then
            echo "$DETECTED"
            return 0
        fi
    fi

    if [[ $EUID -eq 0 ]]; then
        echo "7rwx"
        return 0
    fi

    if command -v sudo &>/dev/null; then
        if timeout 3 sudo -n true 2>/dev/null; then
            echo "7rwx"
            return 0
        fi
    fi

    if [[ -w "$PROJECT_ROOT" ]] && [[ -w "${HOME:-/tmp}" ]]; then
        echo "6rw-"
        return 0
    fi

    if [[ -x "/proc/self/exe" ]] || command -v sh &>/dev/null; then
        echo "5r-x"
        return 0
    fi

    echo "4r--"
}

run_predict() {
    local TIER
    TIER="$(detect_tier)"
    echo "=========================================================="
    echo "  AEP Predictive Privilege Probing & Degradation Matrix"
    echo "=========================================================="
    echo "Detected Chmod Tier: $TIER"
    case "$TIER" in
        7rwx)
            echo "Operational Authority: Root / Passwordless Sudo (Full System & Kernel Scope)"
            echo "Package Provisioner: System Package Manager (apt-get) + User-Space Fallbacks"
            echo "Sandboxing Posture: Full Bubblewrap Namespace Jail (--cap-drop ALL)"
            echo "Service Control: Systemd System Unit Mutation (systemctl)"
            echo "Observability: Full eBPF Tracing (CAP_BPF)"
            ;;
        6rw-)
            echo "Operational Authority: Standard Host User (Read-Write Workspace & RAM Exec)"
            echo "Package Provisioner: Autonomous User-Space Hermetic Binaries (~/.local/bin)"
            echo "Sandboxing Posture: User Namespace Bubblewrap Jail"
            echo "Service Control: Systemd User Unit Scope (systemctl --user)"
            echo "Observability: In-RAM /proc/net Socket Table Telemetry"
            ;;
        5r-x)
            echo "Operational Authority: Restricted Container / CI Runner (Read-Only Workspace)"
            echo "Package Provisioner: In-Memory / Ephemeral Staging (No Host Disk Mutation)"
            echo "Sandboxing Posture: Read-Only Mounted Sandbox Bind"
            echo "Service Control: Read-Only Service Status Inspection"
            echo "Observability: Pure In-Memory Socket Telemetry"
            ;;
        4r--)
            echo "Operational Authority: Auditor / Observer (Strict Read-Only Inspection)"
            echo "Package Provisioner: Disabled (Auditor Mode)"
            echo "Sandboxing Posture: Execution Disabled / Dry-Run Mock"
            echo "Service Control: Static Service Report Only"
            echo "Observability: Cached Telemetry & Ledger Audit Only"
            ;;
    esac
    echo "----------------------------------------------------------"
    echo "FastMCP 17-Tool Degradation Posture:"
    echo "  - topos_audit_dag: ACTIVE (Pure In-RAM DAG Verification)"
    echo "  - discover: ACTIVE (Reflects $TIER & Capabilities)"
    echo "  - autoevol: ACTIVE ($( [[ "$TIER" == "7rwx" || "$TIER" == "6rw-" ]] && echo "Thread Graph + Generation Persistence" || echo "Thread Graph Read-Only, No Persistence" ))"
    echo "  - aep_ctl: ACTIVE (9 Domains Fail-Soft Degradation)"
    echo "  - default_primitives: $( [[ "$TIER" == "4r--" ]] && echo "DISABLED (Auditor Mode: PERMISSION_DENIED)" || echo "ACTIVE (In-RAM System Probes)" )"
    echo "  - artifact_execute_in_ram: $( [[ "$TIER" == "4r--" ]] && echo "DISABLED (Auditor Mode)" || echo "ACTIVE (memfd_create)" )"
    echo "  - sandbox_run: $( [[ "$TIER" == "4r--" ]] && echo "DISABLED / DRY-RUN" || echo "ACTIVE (Fail-Soft)" )"
    echo "  - kernel_trace: $( [[ "$TIER" == "7rwx" ]] && echo "ACTIVE (eBPF)" || echo "DEGRADED (In-RAM /proc/net Telemetry)" )"
    echo "=========================================================="
    return 0
}

# DIR-ONT-01: Flag Short-Circuit for --check (100% Read-Only)
# -----------------------------------------------------------------------------
MODE="setup"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier)
            detect_tier
            exit 0
            ;;
        --predict|--plan)
            run_predict
            exit 0
            ;;
        --check)
            MODE="check"
            shift
            ;;
        --update|--upgrade)
            MODE="update"
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown flag: $1" >&2
            show_help
            exit 2
            ;;
    esac
done

# -----------------------------------------------------------------------------
# ONT-59/T5: canal de Go. `stable` (defecto) | `pinned`. Lo decide el montaje, no una descarga implícita en un build:
# setup.sh deja el resultado en toolchain.env y AEP (engine/go_toolchain.py) lo lee (AEP_GO_BIN, ruta absoluta).
# -----------------------------------------------------------------------------
# Política de Go: solo se parchean las dos últimas mayores (hoy 1.27 y 1.26). Mantener igual a
# GO_SUPPORTED_MIN de engine/go_toolchain.py y actualizar al salir Go 1.28.
GO_SUPPORTED_MIN="1.26"
AEP_DATA_DIR="${AEP_DATA_HOME:-$HOME/.local/share/agent-os}"
TOOLCHAIN_ENV="$AEP_DATA_DIR/toolchain.env"

toolchain_env_get() {
    [[ -f "$TOOLCHAIN_ENV" ]] || return 0
    sed -n "s/^$1=//p" "$TOOLCHAIN_ENV" | tail -n1 | tr -d "'\""
}
go_channel() {
    case "${AEP_GO_CHANNEL:-$(toolchain_env_get AEP_GO_CHANNEL)}" in
        pinned) echo "pinned" ;;
        *) echo "stable" ;;
    esac
}
# ver_ge A B: A >= B (orden de versión)
ver_ge() { [[ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" == "$2" ]]; }
go_semver() { GOTOOLCHAIN=local "$1" env GOVERSION 2>/dev/null | sed 's/^go//' || true; }
# Go en uso: AEP_GO_BIN (env o toolchain.env) si es ejecutable; si no, el primero del PATH.
go_current_bin() {
    local c="${AEP_GO_BIN:-$(toolchain_env_get AEP_GO_BIN)}"
    if [[ -n "$c" && -x "$c" ]]; then echo "$c"; else command -v go 2>/dev/null || true; fi
}

# ONT-67/T8: ajustes de memoria. Los valores por defecto viven en el código de AEP (un fresh start los hereda);
# setup.sh solo persiste en toolchain.env lo que el usuario fija (AEP_EMBED_IDLE_S) y --update no lo pisa.
toolchain_env_set() {
    local key="$1" val="$2" tmp="$TOOLCHAIN_ENV.tmp.$$"
    mkdir -p "$AEP_DATA_DIR"
    { [[ -f "$TOOLCHAIN_ENV" ]] && grep -v "^$key=" "$TOOLCHAIN_ENV"; echo "$key=$val"; } > "$tmp" && mv "$tmp" "$TOOLCHAIN_ENV"
}
# Valor del usuario para AEP_EMBED_IDLE_S (entorno > toolchain.env); vacío si no lo fijó o no es un número >= 0.
embed_idle_user_value() {
    local v="${AEP_EMBED_IDLE_S:-$(toolchain_env_get AEP_EMBED_IDLE_S)}"
    [[ "$v" =~ ^[0-9]+([.][0-9]+)?$ ]] && echo "$v" || true
}
# Memoria del host (solo lectura). Las rutas son sobreescribibles para tests.
# Imprime una línea "[PASS|WARN|FAIL] Memory: ..." y, si hay aviso, líneas "       -> recomendación".
# Código de salida: 1 si FAIL (la ejecución en RAM de AEP no funciona), 0 en otro caso.
memory_check() {
    local vmdir="${AEP_PROC_VM_DIR:-/proc/sys/vm}" mmdir="${AEP_SYS_MM_DIR:-/sys/kernel/mm}"
    local meminfo="${AEP_PROC_MEMINFO:-/proc/meminfo}"
    local noexec thp ksm swap_total swap_free swap_pct="n/a" level="PASS" idle notes=()
    noexec="$(tr -d '[:space:]' < "$vmdir/memfd_noexec" 2>/dev/null || true)"
    thp="$(sed -n 's/.*\[\(.*\)\].*/\1/p' "$mmdir/transparent_hugepage/enabled" 2>/dev/null | head -n1 || true)"
    ksm="$(tr -d '[:space:]' < "$mmdir/ksm/run" 2>/dev/null || true)"
    swap_total="$(awk '/^SwapTotal:/ {print $2}' "$meminfo" 2>/dev/null || true)"
    swap_free="$(awk '/^SwapFree:/ {print $2}' "$meminfo" 2>/dev/null || true)"
    if [[ "${swap_total:-0}" =~ ^[0-9]+$ && "${swap_total:-0}" -gt 0 && "${swap_free:-0}" =~ ^[0-9]+$ ]]; then
        swap_pct=$(( (swap_total - swap_free) * 100 / swap_total ))
    fi
    idle="$(embed_idle_user_value)"
    if [[ "$noexec" == "2" ]]; then
        level="FAIL"
        notes+=("vm.memfd_noexec=2: artifact_execute_in_ram cannot run (AEP answers error_class=memfd_noexec_enforced and points to sandbox_run). Set vm.memfd_noexec=0 or 1 yourself if you want in-RAM execution; setup.sh never changes sysctl.")
    elif [[ "$noexec" == "1" ]]; then
        level="WARN"
        notes+=("vm.memfd_noexec=1: memfds are non-executable by default; AEP asks for MFD_EXEC explicitly so it still works on kernels >= 6.3.")
    fi
    if [[ "$swap_pct" =~ ^[0-9]+$ && "$swap_pct" -gt 90 ]]; then
        [[ "$level" == "PASS" ]] && level="WARN"
        notes+=("swap ${swap_pct}% used: consider zram (e.g. zram-generator) as a manual step; setup.sh never changes swap, zram, KSM or THP.")
    fi
    echo -e "[$level] Memory: memfd_noexec=${noexec:-n/a} THP=${thp:-n/a} KSM=${ksm:-n/a} swap_used=${swap_pct}%" \
        "| AEP embed_idle=${idle:-600}s sqlite_mmap=256MiB sqlite_cache=64MiB/conn sandbox_out=zstd"
    local n
    for n in "${notes[@]}"; do echo "       -> $n"; done
    [[ "$level" != "FAIL" ]]
}

# Cuenta los clientes MCP (CLIs) presentes en PATH donde aep-sync.sh puede registrar el servidor.
count_mcp_clients() {
    local n=0 c
    for c in claude agy codex gemini; do
        command -v "$c" &>/dev/null && n=$((n + 1))
    done
    echo "$n"
}

run_check() {
    local DEGRADED=0
    local DETECTED_TIER
    DETECTED_TIER="$(detect_tier)"
    echo "=========================================================="
    echo "  AEP System Health & Read-Only Audit (--check)"
    echo "  Detected Privilege Tier: $DETECTED_TIER"
    echo "=========================================================="

    # 1. uv package manager
    local UV_BIN
    UV_BIN="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
    if [[ -x "$UV_BIN" ]]; then
        local UV_VER
        UV_VER="$("$UV_BIN" --version 2>/dev/null || echo "present")"
        echo -e "[PASS] Astral uv: $UV_VER ($UV_BIN)"
    else
        echo -e "[FAIL] Astral uv: MISSING"
        DEGRADED=1
    fi

    # 2. Python 3.14 hermetic virtual environment
    local VENV_PY=""
    if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
        VENV_PY="$PROJECT_ROOT/.venv/bin/python"
    elif [[ -x "$HOME/.local/share/agent-os/venv/bin/python" ]]; then
        VENV_PY="$HOME/.local/share/agent-os/venv/bin/python"
    fi

    if [[ -n "$VENV_PY" ]]; then
        local PY_VER
        PY_VER="$("$VENV_PY" --version 2>/dev/null || echo "")"
        if [[ "$PY_VER" =~ ^Python\ 3\.14 ]]; then
            echo -e "[PASS] Python Runtime: $PY_VER ($VENV_PY)"
            if "$VENV_PY" -c "import mcp, anyio, pydantic, sqlite_vec, fastembed" 2>/dev/null; then
                echo -e "[PASS] Python Venv Packages: mcp, anyio, pydantic, sqlite_vec, fastembed verified"
            else
                echo -e "[FAIL] Python Venv Packages: required dependencies missing in $VENV_PY"
                DEGRADED=1
            fi
        else
            echo -e "[FAIL] Python Runtime: $PY_VER (Requires Python 3.14.*)"
            DEGRADED=1
        fi
    else
        echo -e "[FAIL] Python Venv: MISSING hermetic virtual environment"
        DEGRADED=1
    fi

    # 3. Golang Toolchain
    local GO_BIN
    GO_BIN="$(go_current_bin)"
    [[ -n "$GO_BIN" ]] || GO_BIN="$HOME/.local/bin/go"
    if [[ -x "$GO_BIN" ]]; then
        local GO_VER GO_SEMVER GO_SUP="sí" GO_LATEST="unknown"
        GO_VER="$(GOTOOLCHAIN=local "$GO_BIN" version 2>/dev/null || echo "present")"
        GO_SEMVER="$(go_semver "$GO_BIN")"
        ver_ge "${GO_SEMVER:-0}" "$GO_SUPPORTED_MIN" || GO_SUP="no"
        if command -v curl &>/dev/null && command -v python3 &>/dev/null; then  # solo lectura de red, fail-soft, 4 s
            GO_LATEST="$(curl -fsS --max-time 4 'https://go.dev/dl/?mode=json' 2>/dev/null \
                | python3 -c 'import json,sys
print(next((r["version"][2:] for r in json.load(sys.stdin) if r.get("stable")), "unknown"))' 2>/dev/null || true)"
            [[ -n "$GO_LATEST" ]] || GO_LATEST="unknown"
        fi
        local GO_LINE GO_CH
        GO_CH="$(go_channel)"
        GO_LINE="Golang: $GO_VER ($GO_BIN) channel=$GO_CH supported=$GO_SUP latest_stable=$GO_LATEST"
        if [[ "$GO_SUP" == "sí" ]]; then
            echo -e "[PASS] $GO_LINE"
        else
            echo -e "[WARN] $GO_LINE (fuera de soporte; mínimo $GO_SUPPORTED_MIN: ejecuta setup.sh --update)"
        fi
    else
        echo -e "[FAIL] Golang: MISSING"
        DEGRADED=1
    fi

    # 3.1. golangci-lint Static Analyzer
    local LINT_BIN
    LINT_BIN="$(command -v golangci-lint 2>/dev/null || echo "$HOME/.local/bin/golangci-lint")"
    if [[ -x "$LINT_BIN" ]]; then
        local LINT_VER
        LINT_VER="$("$LINT_BIN" --version 2>/dev/null || echo "present")"
        echo -e "[PASS] golangci-lint: $LINT_VER ($LINT_BIN)"
    else
        echo -e "[WARN] golangci-lint: not installed (artifact_lint_and_build will fallback to go vet)"
    fi

    # 4. Go Static Diagnostic Probes
    local PROBE_DIR="$HOME/.local/share/agent-os/bin"
    if [[ -x "$PROBE_DIR/socket-monitor" ]] && [[ -x "$PROBE_DIR/fd-rescuer" ]]; then
        echo -e "[PASS] Static Go Probes: socket-monitor and fd-rescuer present in $PROBE_DIR"
    else
        echo -e "[FAIL] Static Go Probes: missing or not executable in $PROBE_DIR"
        DEGRADED=1
    fi

    # 5. Bubblewrap Sandboxing (fail-soft)
    if command -v bwrap &>/dev/null; then
        local BWRAP_VER
        BWRAP_VER="$(bwrap --version 2>/dev/null || echo "present")"
        echo -e "[PASS] Bubblewrap: $BWRAP_VER"
    else
        echo -e "[WARN] Bubblewrap: not installed (fail-soft mode active)"
    fi

    # 6. Pueue Asynchronous Queue Daemon
    local PUEUE_BIN
    PUEUE_BIN="$(command -v pueue 2>/dev/null || echo "$HOME/.local/bin/pueue")"
    if [[ -x "$PUEUE_BIN" ]]; then
        # ONT-62: the daemon can be momentarily busy; probe up to 3 times (5 s each, 1 s apart) before declaring failure.
        local PUEUE_TRY PUEUE_ERR="" PUEUE_OK=0
        for PUEUE_TRY in 1 2 3; do
            if PUEUE_ERR="$(timeout 5 "$PUEUE_BIN" status 2>&1 >/dev/null)"; then
                PUEUE_OK=1
                break
            fi
            [[ $PUEUE_TRY -lt 3 ]] && sleep 1
        done
        if [[ $PUEUE_OK -eq 1 ]]; then
            echo -e "[PASS] Pueue Daemon: ACTIVE and responsive ($PUEUE_BIN)"
        else
            echo -e "[FAIL] Pueue Daemon: binary present but daemon NOT responding after 3 attempts (${PUEUE_ERR:0:200})"
            DEGRADED=1
        fi
    else
        echo -e "[FAIL] Pueue: MISSING pueue binary"
        DEGRADED=1
    fi

    # 7. Omarchy Skills Hub & Git Hooks
    local SKILLS_OK=1
    for client in claude gemini codex; do
        if [[ ! -L "$HOME/.$client/skills/shared" ]]; then
            SKILLS_OK=0
        fi
    done
    if [[ $SKILLS_OK -eq 1 ]]; then
        echo -e "[PASS] Omarchy Skills Hub: shared symlinks verified for claude, gemini, codex"
    else
        echo -e "[WARN] Omarchy Skills Hub: shared skills symlinks partial or missing"
    fi

    local HOOKS_PATH
    HOOKS_PATH="$(git -C "$PROJECT_ROOT" config core.hooksPath 2>/dev/null || echo "")"
    # ONT-62: core.hooksPath may be relative (to the repo) or an absolute path to the same dir; compare resolved paths.
    local HOOKS_RESOLVED="" HOOKS_EXPECTED
    HOOKS_EXPECTED="$(realpath -m "$PROJECT_ROOT/scripts/hooks")"
    if [[ -n "$HOOKS_PATH" ]]; then
        if [[ "$HOOKS_PATH" == /* ]]; then
            HOOKS_RESOLVED="$(realpath -m "$HOOKS_PATH")"
        else
            HOOKS_RESOLVED="$(realpath -m "$PROJECT_ROOT/$HOOKS_PATH")"
        fi
    fi
    if [[ -n "$HOOKS_RESOLVED" && "$HOOKS_RESOLVED" == "$HOOKS_EXPECTED" ]]; then
        echo -e "[PASS] Git Pre-commit Hook: tracked (core.hooksPath=$HOOKS_PATH)"
    else
        echo -e "[WARN] Git Pre-commit Hook: not tracked (current: '$HOOKS_PATH')"
    fi

    # 8. SQLite Catalog & Storage Integrity
    # ONT-61/G67: AEP_DATA_HOME relocates the catalog (default unchanged); the venv and probes stay HOME-installed.
    local DB_PATH="${AEP_CATALOG_DB:-$AEP_DATA_DIR/artifacts.db}"
    if [[ -x "$VENV_PY" ]] && [[ -f "$DB_PATH" ]]; then
        local DB_CHK_OUT
        DB_CHK_OUT=$(PYTHONPATH="$PROJECT_ROOT" "$VENV_PY" - "$DB_PATH" <<'PY' 2>/dev/null || echo "FAILED"
import sqlite3
import sys
from pathlib import Path
from engine.backup import verify_database_integrity

db_path = Path(sys.argv[1]).resolve()
ok, status, _ = verify_database_integrity(db_path=db_path, auto_seed_canary=False)
if not ok:
    print(f"FAIL:{status}")
    sys.exit(1)

conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
try:
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='artifacts'")
    if cur.fetchone()[0] == 0:
        print("FAIL:ARTIFACTS_TABLE_MISSING")
        sys.exit(1)
finally:
    conn.close()

print("HEALTHY")
PY
)
        if [[ "$DB_CHK_OUT" == "HEALTHY" ]]; then
            echo -e "[PASS] SQLite Catalog & Integrity: Healthy ($DB_PATH)"
        else
            echo -e "[FAIL] SQLite Catalog & Integrity: check failed ($DB_CHK_OUT) ($DB_PATH)"
            DEGRADED=1
        fi
    elif [[ -x "$VENV_PY" ]] && [[ ! -f "$DB_PATH" ]]; then
        echo -e "[FAIL] SQLite Catalog & Integrity: missing database file ($DB_PATH)"
        DEGRADED=1
    else
        echo -e "[FAIL] SQLite Catalog & Integrity: Python runtime unavailable"
        DEGRADED=1
    fi

    # 9. MCP Ecosystem Sync & Server Importability
    if bash "$PROJECT_ROOT/scripts/aep-sync.sh" --check >/dev/null 2>&1; then
        echo -e "[PASS] MCP Ecosystem Sync: Server compile & import verification passed"
    else
        echo -e "[FAIL] MCP Ecosystem Sync: aep-sync.sh --check failed"
        DEGRADED=1
    fi

    # 10. Clientes MCP: un servidor válido sin ningún cliente donde registrarlo no es un éxito completo.
    local MCP_CLIENTS
    MCP_CLIENTS="$(count_mcp_clients)"
    if [[ "$MCP_CLIENTS" -eq 0 ]]; then
        echo -e "[WARN] MCP Clients: 0 clientes MCP detectados (claude, agy, codex, gemini); el servidor es válido pero NO está registrado en ningún agente"
    else
        echo -e "[PASS] MCP Clients: $MCP_CLIENTS cliente(s) MCP detectado(s) en PATH"
    fi

    # 11. Memoria (ONT-67/T8): solo lectura; FAIL si el kernel impide la ejecución en RAM de AEP.
    memory_check || DEGRADED=1

    echo "=========================================================="
    if [[ $DEGRADED -eq 0 ]]; then
        echo -e "${GREEN}[RESULT] System Health Status: HEALTHY (Exit 0)${NC}"
        return 0
    else
        echo -e "${RED}[RESULT] System Health Status: DEGRADED (Exit 1)${NC}"
        return 1
    fi
}

if [[ "$MODE" == "check" ]]; then
    run_check
    exit $?
fi

# -----------------------------------------------------------------------------
# DIR-ONT-02: Atomic Download Trap & Temporary Staging
# -----------------------------------------------------------------------------
TMP_DIR="$(mktemp -d -t aep_setup_XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

# download <url> <dest>: fail-closed fetch (-f: HTTP errors are failures) that rejects empty files.
download() {
    curl -fsSL --retry 3 --connect-timeout 15 -o "$2" "$1" && [[ -s "$2" ]]
}

# download_verified <url> <dest> <sha256>: descarga y exige coincidencia SHA-256 (fail-closed: borra si no coincide).
# Códigos de retorno: 0 = ok, 1 = fallo de descarga (red/release), 2 = checksum no coincide (artefacto alterado o pin obsoleto).
# DL_FAIL_REASON queda en "download" | "checksum" para que el llamador pueda informar la causa exacta.
DL_FAIL_REASON=""
download_verified() {
    DL_FAIL_REASON=""
    if ! download "$1" "$2"; then
        DL_FAIL_REASON="download"
        log_warn "Descarga fallida para $(basename "$2") (red o release no disponible)."
        rm -f "$2"
        return 1
    fi
    if [[ -z "${3:-}" ]] || ! echo "$3  $2" | sha256sum -c --status 2>/dev/null; then
        DL_FAIL_REASON="checksum"
        log_err "SHA-256 no coincide para $(basename "$2"); descarga descartada."
        rm -f "$2"
        return 2
    fi
}

# Arquitectura: mapea `uname -m` a los nombres de cada proyecto. Arquitectura no soportada => ARCH_OK=0 y
# cada herramienta binaria degrada con aviso (no se aborta a mitad de la instalación).
case "$(uname -m)" in
    x86_64|amd64)  ARCH_OK=1; GO_ARCH="amd64"; UV_ARCH="x86_64";  PUEUE_ARCH="x86_64" ;;
    aarch64|arm64) ARCH_OK=1; GO_ARCH="arm64"; UV_ARCH="aarch64"; PUEUE_ARCH="aarch64" ;;
    *)             ARCH_OK=0; GO_ARCH="";      UV_ARCH="";        PUEUE_ARCH=""
                   log_warn "Arquitectura $(uname -m) no soportada para binarios precompilados (Go, golangci-lint, pueue): se degradará." ;;
esac

# -----------------------------------------------------------------------------
# DIR-ONT-03: Subshell PATH Injection
# -----------------------------------------------------------------------------
export PATH="$HOME/.local/bin:$HOME/.local/share/go/bin:$HOME/.local/share/agent-os/bin:$PATH"

SETUP_TIER="$(detect_tier)"
echo "=========================================================="
echo "  Agent Execution Plane (AEP) — Setup & Tooling Provisioner"
echo "  Mode: $MODE | Detected Chmod Tier: $SETUP_TIER"
echo "=========================================================="
log_step "Paso 0: Sondeo predictivo de privilegios completado (Tier: $SETUP_TIER)."

# -----------------------------------------------------------------------------
# 1. Base Directories & Omarchy Skills Hub
# -----------------------------------------------------------------------------
log_step "Preparando directorios base y enlaces de agentes..."
mkdir -p "$HOME/.local/bin"
mkdir -p "$HOME/.local/share/agent-os/bin"
mkdir -p "$HOME/.agents/skills"
mkdir -p "$HOME/.claude/skills"
mkdir -p "$HOME/.gemini/skills"
mkdir -p "$HOME/.codex/skills"

# Idempotent Omarchy Hub Symlinks (SPEC-OM-3)
ln -sfn "$HOME/.agents/skills" "$HOME/.claude/skills/shared"
ln -sfn "$HOME/.agents/skills" "$HOME/.gemini/skills/shared"
ln -sfn "$HOME/.agents/skills" "$HOME/.codex/skills/shared"
log_success "Hub de Skills multi-agente configurado."

# Pre-commit hook tracked
git -C "$PROJECT_ROOT" config core.hooksPath scripts/hooks 2>/dev/null     && chmod +x "$PROJECT_ROOT/scripts/hooks/pre-commit" 2>/dev/null     && log_success "Hook pre-commit instalado (core.hooksPath=scripts/hooks)." || true

# -----------------------------------------------------------------------------
# 2. Astral uv Toolchain Provisioning
# -----------------------------------------------------------------------------
log_step "Verificando gestor Astral uv..."
uv_needs_install() {
    command -v uv &>/dev/null || [[ -x "$HOME/.local/bin/uv" ]] || return 0
    [[ "$MODE" == "update" ]] && [[ "$(uv --version 2>/dev/null)" != "uv $UV_VERSION"* ]] && return 0
    return 1
}
if uv_needs_install; then
    if [[ $ARCH_OK -ne 1 ]]; then
        log_err "uv no tiene binario para $(uname -m) en este script; instala uv manualmente y reejecuta."
        exit 1
    fi
    log_step "Instalando uv $UV_VERSION fijado (SHA-256 verificado)..."
    UV_TAR="uv-${UV_ARCH}-unknown-linux-gnu"
    UV_SHA_VAR="UV_SHA256_${UV_ARCH}"
    if download_verified "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_TAR}.tar.gz" "$TMP_DIR/uv.tar.gz" "${!UV_SHA_VAR}" \
        && tar -C "$TMP_DIR" -xzf "$TMP_DIR/uv.tar.gz" && [[ -x "$TMP_DIR/$UV_TAR/uv" ]]; then
        install -m 0755 "$TMP_DIR/$UV_TAR/uv" "$HOME/.local/bin/uv"
        [[ -x "$TMP_DIR/$UV_TAR/uvx" ]] && install -m 0755 "$TMP_DIR/$UV_TAR/uvx" "$HOME/.local/bin/uvx"
        export PATH="$HOME/.local/bin:$PATH"
    elif command -v uv &>/dev/null; then
        log_warn "No se pudo instalar uv $UV_VERSION; se conserva el uv existente."
    else
        log_err "uv no disponible y la descarga verificada falló; no se puede continuar."
        exit 1
    fi
fi
log_success "uv operativo: $(uv --version 2>/dev/null || echo 'ok')"

# -----------------------------------------------------------------------------
# 3. Python 3.14 Hermetic Virtual Environment (DIR-ONT-04)
# -----------------------------------------------------------------------------
log_step "Provisionando entorno hermético Python 3.14..."
uv python install 3.14

VENV_DIR="$PROJECT_ROOT/.venv"
# ONT-62/G71: never recreate an existing venv implicitly. uv >= 0.13 rejects `uv venv` over an existing dir without
# --clear, and recreating the venv that the live plane runs from would break the server. `uv sync --frozen` below
# updates the packages in place.
venv_mm() { "$VENV_DIR/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true; }
if [[ ! -e "$VENV_DIR" ]]; then
    log_step "Creando venv hermético en $VENV_DIR con Python 3.14..."
    # DIR-ONT-04: STRICTLY omit --system-site-packages
    uv venv --python 3.14 "$VENV_DIR"
else
    VENV_CUR="$(venv_mm)"
    if [[ "$VENV_CUR" == "3.14" ]]; then
        log_step "Reutilizando venv existente (Python $VENV_CUR); uv sync lo actualiza in situ."
    elif [[ "${AEP_RECREATE_VENV:-}" == "1" ]]; then
        log_warn "venv existente con Python '${VENV_CUR:-desconocido}': recreando (AEP_RECREATE_VENV=1)."
        uv venv --clear --python 3.14 "$VENV_DIR"
    else
        log_warn "venv existente con Python '${VENV_CUR:-desconocido}' (se esperaba 3.14): NO se recrea. Usa AEP_RECREATE_VENV=1 para forzarlo."
    fi
fi

# Instalar dependencias del proyecto en modo editable con extras dev
log_step "Sincronizando dependencias en el venv hermético..."
# Reproducible install from uv.lock (sqlite-vec, fastembed, playwright are declared in pyproject + locked).
# --frozen: never re-resolve; the lock is the source of truth.
(cd "$PROJECT_ROOT" && UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv sync --frozen --extra dev)

# Sincronizar symlink canónico para ~/.local/share/agent-os/venv
mkdir -p "$HOME/.local/share/agent-os"
VENV_LINK="$HOME/.local/share/agent-os/venv"
if [[ -d "$VENV_LINK" && ! -L "$VENV_LINK" ]]; then
    # ONT-62: a real directory (possibly the user's own venv): `ln -sfn` would create a link INSIDE it. Never delete it.
    log_warn "$VENV_LINK es un directorio real, no un symlink: no se enlaza (no se borra). Apunta tus clientes a $VENV_DIR."
else
    ln -sfn "$VENV_DIR" "$VENV_LINK"
fi

# ONT-41: last-known-good store (private, 0700). AEP_DATA_HOME overrides the data home (same as aep_lkg.lkg_home()).
AEP_LKG_DIR="${AEP_DATA_HOME:-$HOME/.local/share/agent-os}/lkg"
mkdir -p "$AEP_LKG_DIR" && chmod 700 "$AEP_LKG_DIR"

# Pre-cache de modelo semántico BAAI/bge-small-en-v1.5
if "$VENV_DIR/bin/python" -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')" &>/dev/null; then
    log_success "Entorno semántico listo (modelo bge-small-en-v1.5 cacheado)."
else
    log_warn "Modelo semántico bge-small-en-v1.5 se descargará en primer uso."
fi

# Chromium headless para visual_inspect (fail-soft): descargar el binario NO basta, hay que comprobar que arranca.
if "$VENV_DIR/bin/python" -m playwright install chromium &>/dev/null; then
    if "$VENV_DIR/bin/python" - <<'PY' &>/dev/null
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    p.chromium.launch(headless=True, args=["--no-sandbox"]).close()
PY
    then
        log_success "Chromium headless provisionado y verificado (visual_inspect)."
    else
        log_warn "Chromium descargado pero NO arranca (faltan librerías del sistema). Ejecuta como root: $VENV_DIR/bin/python -m playwright install-deps chromium. Hasta entonces visual_inspect devuelve DISPLAY_UNAVAILABLE."
    fi
else
    log_warn "Chromium no se pudo descargar; visual_inspect degrada a DISPLAY_UNAVAILABLE."
fi

# -----------------------------------------------------------------------------
# 4. Golang Toolchain & Static Diagnostic Probes
# -----------------------------------------------------------------------------
log_step "Verificando compilador Golang..."
GO_CHANNEL="$(go_channel)"
GO_CUR="$(go_current_bin)"
GO_CUR_VER=""
[[ -z "$GO_CUR" ]] || GO_CUR_VER="$(go_semver "$GO_CUR")"
GO_SHA_VAR="GO_SHA256_${GO_ARCH}"
GO_TARGET_VER="$GO_VERSION"
GO_TARGET_SHA="${!GO_SHA_VAR:-}"
GO_RESOLVED="pinned"

# resolve_go_stable: primer release `stable: true` de go.dev y el sha256 de su archive linux (mismo JSON oficial, HTTPS).
resolve_go_stable() {
    command -v python3 &>/dev/null || return 1
    download "https://go.dev/dl/?mode=json" "$TMP_DIR/godl.json" || return 1
    local out
    out="$(python3 - "$TMP_DIR/godl.json" "$GO_ARCH" <<'PY'
import json, sys
try:
    for rel in json.load(open(sys.argv[1])):
        if rel.get("stable"):
            for f in rel["files"]:
                if f.get("os") == "linux" and f.get("arch") == sys.argv[2] and f.get("kind") == "archive":
                    print(rel["version"].removeprefix("go"), f["sha256"])
                    raise SystemExit(0)
            break
except Exception:
    pass
raise SystemExit(1)
PY
)" || return 1
    read -r GO_TARGET_VER GO_TARGET_SHA <<<"$out"
    [[ "$GO_TARGET_VER" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ && "$GO_TARGET_SHA" =~ ^[0-9a-f]{64}$ ]]
}

GO_NEEDS_INSTALL=0
if [[ -z "$GO_CUR_VER" ]]; then
    log_step "Golang ausente; se instalará la versión del canal $GO_CHANNEL..."
    GO_NEEDS_INSTALL=1
elif ! ver_ge "$GO_CUR_VER" "$GO_SUPPORTED_MIN"; then
    log_warn "Go $GO_CUR_VER ($GO_CUR) está fuera de soporte (mínimo $GO_SUPPORTED_MIN); se instalará el gestionado por AEP sin tocar el existente."
    GO_NEEDS_INSTALL=1
elif [[ "$MODE" == "update" ]]; then
    GO_NEEDS_INSTALL=1  # se decide tras resolver el objetivo
fi

if [[ $GO_NEEDS_INSTALL -eq 1 ]]; then
    if [[ "$GO_CHANNEL" == "stable" ]]; then
        if resolve_go_stable; then
            GO_RESOLVED="stable"
        else
            GO_RESOLVED="pinned-fallback"
            GO_TARGET_VER="$GO_VERSION"
            GO_TARGET_SHA="${!GO_SHA_VAR:-}"
            log_warn "No se pudo resolver el Go estable desde go.dev; se usa el pin go${GO_VERSION} (AEP_GO_CHANNEL_RESOLVED=pinned-fallback)."
        fi
    fi
    if [[ -n "$GO_CUR_VER" ]] && ver_ge "$GO_CUR_VER" "$GO_SUPPORTED_MIN" && ver_ge "$GO_CUR_VER" "$GO_TARGET_VER"; then
        log_success "Go $GO_CUR_VER ya es >= $GO_TARGET_VER; sin cambios."
        GO_NEEDS_INSTALL=0
    fi
fi

if [[ $GO_NEEDS_INSTALL -eq 1 ]]; then
    log_step "Instalando Go $GO_TARGET_VER (canal $GO_CHANNEL) en espacio de usuario desde tarball oficial..."
    GO_TARBALL="go${GO_TARGET_VER}.linux-${GO_ARCH}.tar.gz"
    # Descarga -> valida -> extrae en tmp -> comprueba versión -> solo entonces reemplaza el gestionado
    # (nunca se borra la instalación previa antes de validar la nueva; el Go ajeno del sistema no se toca).
    if [[ $ARCH_OK -eq 1 ]] && download_verified "https://go.dev/dl/$GO_TARBALL" "$TMP_DIR/$GO_TARBALL" "$GO_TARGET_SHA" \
        && mkdir -p "$TMP_DIR/go_extract" \
        && tar -C "$TMP_DIR/go_extract" -xzf "$TMP_DIR/$GO_TARBALL" \
        && [[ -x "$TMP_DIR/go_extract/go/bin/go" ]] \
        && [[ "$(go_semver "$TMP_DIR/go_extract/go/bin/go")" == "$GO_TARGET_VER" ]]; then
        mkdir -p "$HOME/.local/share" "$HOME/.local/bin"
        if [[ -e "$HOME/.local/share/go" ]]; then mv "$HOME/.local/share/go" "$HOME/.local/share/go.prev.$$"; fi
        mv "$TMP_DIR/go_extract/go" "$HOME/.local/share/go"
        rm -rf "$HOME/.local/share/go.prev.$$"
        [[ -n "$GO_CUR" ]] || ln -sfn "$HOME/.local/share/go/bin/go" "$HOME/.local/bin/go"  # sin shadowing de un Go ajeno
        export PATH="$HOME/.local/share/go/bin:$HOME/.local/bin:$PATH"
        GO_CUR="$HOME/.local/share/go/bin/go"
    else
        log_warn "Descarga/validación de Go falló; se conserva la instalación previa (si existe)."
    fi
fi

# ONT-67/T8: capturar ANTES del reescrito de toolchain.env (que lo descarta) para no pisar ajustes del usuario.
KEEP_EMBED_IDLE="$(embed_idle_user_value)"
if [[ -n "$GO_CUR" && -x "$GO_CUR" ]]; then
    mkdir -p "$AEP_DATA_DIR"
    {
        echo "# Generado por scripts/setup.sh (ONT-59/T5). AEP_GO_CHANNEL=stable|pinned; editar y re-ejecutar setup.sh para aplicar."
        echo "AEP_GO_CHANNEL=$GO_CHANNEL"
        echo "AEP_GO_CHANNEL_RESOLVED=$GO_RESOLVED"
        echo "AEP_GO_VERSION=$(go_semver "$GO_CUR")"
        echo "AEP_GO_BIN=$GO_CUR"
        echo "AEP_GO_RESOLVED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$TOOLCHAIN_ENV.tmp.$$" && mv "$TOOLCHAIN_ENV.tmp.$$" "$TOOLCHAIN_ENV"
fi

# ONT-67/T8: AEP_EMBED_IDLE_S solo se escribe si el usuario la fijó (entorno o toolchain.env); sin valor no se toca nada.
if [[ -n "$KEEP_EMBED_IDLE" ]]; then
    toolchain_env_set AEP_EMBED_IDLE_S "$KEEP_EMBED_IDLE"
fi

if [[ -n "$GO_CUR" && -x "$GO_CUR" ]]; then
    GO_CMD="$GO_CUR"
    export AEP_GO_BIN="$GO_CMD" GOTOOLCHAIN=local  # el toolchain lo decide el montaje, no una descarga implícita
    log_success "Golang disponible: $($GO_CMD version 2>/dev/null) ($GO_CMD) channel=$GO_CHANNEL ($GO_RESOLVED)"

    log_step "Compilando sondas Go estáticas (socket-monitor, fd-rescuer)..."
    mkdir -p "$HOME/.local/share/agent-os/bin"

    SOCK_SRC=""
    if [[ -f "$PROJECT_ROOT/diagnostic/go/socket-monitor/main.go" ]]; then
        SOCK_SRC="$PROJECT_ROOT/diagnostic/go/socket-monitor/main.go"
    else
        SOCK_SRC="$PROJECT_ROOT/templates/tpl_socket_monitor.go"
    fi

    FD_SRC=""
    if [[ -f "$PROJECT_ROOT/diagnostic/go/fd-rescuer/main.go" ]]; then
        FD_SRC="$PROJECT_ROOT/diagnostic/go/fd-rescuer/main.go"
    else
        FD_SRC="$PROJECT_ROOT/templates/tpl_fd_rescuer.go"
    fi

    CGO_ENABLED=0 "$GO_CMD" build -ldflags="-s -w" -o "$HOME/.local/share/agent-os/bin/socket-monitor" "$SOCK_SRC"
    CGO_ENABLED=0 "$GO_CMD" build -ldflags="-s -w" -o "$HOME/.local/share/agent-os/bin/fd-rescuer" "$FD_SRC"
    chmod +x "$HOME/.local/share/agent-os/bin/socket-monitor" "$HOME/.local/share/agent-os/bin/fd-rescuer"
    log_success "Sondas Go pre-compiladas estáticamente en ~/.local/share/agent-os/bin/"

    # 4.1. golangci-lint Provisioning (Idempotent user-space linter)
    log_step "Verificando linter estático golangci-lint..."
    if ! command -v golangci-lint &>/dev/null && [[ ! -x "$HOME/.local/bin/golangci-lint" ]]; then
        log_step "golangci-lint ausente; instalando binario oficial en ~/.local/bin..."
        GL_DIR="golangci-lint-${GL_VERSION}-linux-${GO_ARCH}"
        GL_SHA_VAR="GL_SHA256_${GO_ARCH}"
        if [[ $ARCH_OK -eq 1 ]] && download_verified "https://github.com/golangci/golangci-lint/releases/download/v${GL_VERSION}/$GL_DIR.tar.gz" "$TMP_DIR/golangci-lint.tar.gz" "${!GL_SHA_VAR:-}" \
            && tar -C "$TMP_DIR" -xzf "$TMP_DIR/golangci-lint.tar.gz" \
            && [[ -x "$TMP_DIR/$GL_DIR/golangci-lint" ]]; then
            mv "$TMP_DIR/$GL_DIR/golangci-lint" "$HOME/.local/bin/golangci-lint"
        else
            log_warn "No se pudo auto-instalar golangci-lint; artifact_lint_and_build usará go vet."
        fi
    fi
    if command -v golangci-lint &>/dev/null || [[ -x "$HOME/.local/bin/golangci-lint" ]]; then
        LINT_CMD="$(command -v golangci-lint || echo "$HOME/.local/bin/golangci-lint")"
        log_success "golangci-lint disponible: $($LINT_CMD --version 2>/dev/null || echo 'ok')"
    fi
else
    log_warn "Golang no disponible; sondas Go y golangci-lint omitidos."
fi

# -----------------------------------------------------------------------------
# 5. Bubblewrap Sandboxing (Fail-Soft)
# -----------------------------------------------------------------------------
log_step "Verificando Bubblewrap (bwrap)..."
if ! command -v bwrap &>/dev/null; then
    if [[ "$SETUP_TIER" == "7rwx" ]] && timeout 3 sudo -n true 2>/dev/null; then
        sudo -n apt-get update -qq && sudo -n apt-get install -y -qq bubblewrap 2>/dev/null || true
    fi
fi
if command -v bwrap &>/dev/null; then
    log_success "Bubblewrap disponible ($(bwrap --version 2>/dev/null || echo 'ok'))."
else
    log_warn "Bubblewrap no disponible; sandbox_run operará en modo fail-soft degradado."
fi

# -----------------------------------------------------------------------------
# 6. Pueue Asynchronous Queue Daemon
# -----------------------------------------------------------------------------
log_step "Verificando demonio Pueue..."
if [[ "$MODE" == "update" ]] || ! command -v pueued &>/dev/null || [[ ! -x "$HOME/.local/bin/pueued" ]]; then
    log_step "Descargando binarios estáticos musl de Pueue a ~/.local/bin..."
    TAG="$PUEUE_VERSION"
    PQ_OK=$ARCH_OK
    PQ_REASON=""
    for b in pueue pueued; do
        [[ $ARCH_OK -eq 1 ]] || break
        PQ_SHA_VAR="PUEUE_SHA256_${PUEUE_ARCH}_${b}"
        download_verified "https://github.com/Nukesor/pueue/releases/download/$TAG/${b}-${PUEUE_ARCH}-unknown-linux-musl" "$TMP_DIR/$b" "${!PQ_SHA_VAR:-}" || { PQ_OK=0; PQ_REASON="$DL_FAIL_REASON"; break; }
    done
    if [[ $PQ_OK -eq 1 ]]; then
        for b in pueue pueued; do
            chmod +x "$TMP_DIR/$b"
            mv "$TMP_DIR/$b" "$HOME/.local/bin/$b"
        done
        log_success "Pueue $TAG instalado en ~/.local/bin."
    else
        if [[ "$PQ_REASON" == "checksum" ]]; then
            log_warn "Pueue no instalado: checksum no coincide con el SHA-256 fijado (binario alterado o pin obsoleto); se omite."
        elif [[ -n "$PQ_REASON" ]]; then
            log_warn "No se pudo descargar Pueue (red o release no disponible); se omite."
        else
            log_warn "Pueue no instalado (arquitectura no soportada); se omite."
        fi
    fi
fi

if command -v pueued &>/dev/null || [[ -x "$HOME/.local/bin/pueued" ]]; then
    PUEUE_CLI="$(command -v pueue 2>/dev/null || echo "$HOME/.local/bin/pueue")"
    PUEUED_BIN="$(command -v pueued 2>/dev/null || echo "$HOME/.local/bin/pueued")"
    if ! "$PUEUE_CLI" status &>/dev/null; then
        systemctl --user enable --now pueued 2>/dev/null || "$PUEUED_BIN" -d 2>/dev/null || true
    fi
    log_success "Pueue daemon activo."
else
    log_warn "pueued no disponible; tareas asíncronas degradarán a fail-soft."
fi

# -----------------------------------------------------------------------------
# 7. Shell Environment Inheritance (Agnostic)
# -----------------------------------------------------------------------------
log_step "Configurando herencia de shell agnóstica..."
bash "$PROJECT_ROOT/scripts/install-shell-env.sh" 2>/dev/null || log_warn "Configuración de entorno shell omitida."

# -----------------------------------------------------------------------------
# 8. Artifact Catalog DB Initialization
# -----------------------------------------------------------------------------
log_step "Inicializando catálogo de artefactos (SQLite)..."
PYTHONPATH="$PROJECT_ROOT" "$VENV_DIR/bin/python" - "$PROJECT_ROOT" <<'PY' 2>/dev/null || log_warn "Init de catálogo omitido (posible lock activo)."
import sys
from pathlib import Path
from engine.backup import verify_database_integrity
from engine.catalog import ArtifactCatalog

project_root = Path(sys.argv[1]).resolve()
cat = ArtifactCatalog()
probe_dir = Path.home() / ".local" / "share" / "agent-os" / "bin"
socket_bin = (probe_dir / "socket-monitor").read_bytes() if (probe_dir / "socket-monitor").is_file() else None
fd_bin = (probe_dir / "fd-rescuer").read_bytes() if (probe_dir / "fd-rescuer").is_file() else None

tpl_socket = (project_root / "templates" / "tpl_socket_monitor.go").read_text(encoding="utf-8")
cue_socket = 'package schema\nname: "socket-monitor"\ncategory: "network"'
for name in ("socket-monitor", "socket_monitor"):
    cat.register_artifact(
        name,
        "inspect_tcp_sockets",
        "network",
        cue_socket,
        tpl_socket,
        binary_blob=socket_bin,
        intent_description="list and inspect listening TCP sockets and open network ports on the host",
        source_template="socket-monitor",
    )

tpl_fd = (project_root / "templates" / "tpl_fd_rescuer.go").read_text(encoding="utf-8")
cue_fd = 'package schema\nname: "fd-rescuer"\ncategory: "process"'
for name in ("fd-rescuer", "fd_rescuer"):
    cat.register_artifact(
        name,
        "inspect_process_fds",
        "process",
        cue_fd,
        tpl_fd,
        binary_blob=fd_bin,
        intent_description="inspect the open file descriptors of a process to diagnose hung or deadlocked threads",
        source_template="fd-rescuer",
    )
# Siembra el canario anti-envenenamiento: `setup.sh --check` lo verifica con auto_seed_canary=False.
ok, status, _ = verify_database_integrity(db_path=cat.db_path, auto_seed_canary=True)
if not ok:
    print(f"Integridad del catálogo: {status}", file=sys.stderr)
    sys.exit(1)
print(f"Catálogo SQLite listo (vec_available={cat._vec_available}, integridad={status}).")
PY

# -----------------------------------------------------------------------------
# 9. MCP Seeding & Hot-Reload Delegation (aep-sync.sh)
# -----------------------------------------------------------------------------
log_step "Ejecutando auto-plug y sincronización MCP multi-agente..."
chmod +x "$PROJECT_ROOT/scripts/aep-mcp-launch.sh" "$PROJECT_ROOT/scripts/aep-sync.sh" "$PROJECT_ROOT/scripts/aep-ctl" 2>/dev/null || true
SYNC_LOG="$TMP_DIR/aep-sync.out"
SYNC_RC=0
bash "$PROJECT_ROOT/scripts/aep-sync.sh" 2>&1 | tee "$SYNC_LOG" || SYNC_RC=$?
if [[ $SYNC_RC -ne 0 ]]; then
    log_warn "Auto-plug MCP finalizó con advertencias; revisa aep-sync.sh --check."
fi
# aep-sync.sh imprime "Auto-plug completado en N cliente(s)"; N=0 => nada quedó registrado.
REGISTERED="$(sed -n 's/.*Auto-plug completado en \([0-9]\+\) cliente.*/\1/p' "$SYNC_LOG" | tail -1)"

echo "=========================================================="
if [[ "$SYNC_RC" -ne 0 ]]; then
    echo "  Instalación completada CON ADVERTENCIAS: el registro MCP falló (ver arriba)"
elif [[ "${REGISTERED:-0}" -eq 0 ]]; then
    echo "  Instalación completada, pero 0 clientes MCP registrados"
    echo "  (instala claude, agy, codex o gemini y reejecuta ./scripts/aep-sync.sh)"
else
    echo "  Instalación y Seeding de AEP Completados con Éxito ($REGISTERED cliente(s) MCP registrado(s))"
fi
echo "=========================================================="
