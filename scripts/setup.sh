#!/usr/bin/env bash
# =============================================================================
# setup.sh — AEP Autonomous Zero-Dependency Setup & Tooling Provisioner
# Dual-mode bootstrapper, updater, and read-only health auditor.
# Supports: Ubuntu / Linux (POSIX sh / bash / zsh)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="$HOME/.local/bin:$HOME/.local/share/go/bin:$HOME/.local/share/agent-os/bin:$PATH"

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
  --check               Execute 100% read-only health audit of all components
                        (NO file modifications, exits 0 if healthy, 1 if degraded).
  --update, --upgrade   Update self-provisioned toolchains, venv dependencies,
                        and recompile probes.
  --help, -h            Show this help message.

Default (no flags):
  Full idempotent provisioning of uv, Python 3.14 hermetic venv, Go toolchain,
  static probes, Pueue daemon, Playwright, Omarchy skill hubs, and MCP seeding.
HELP
}

# -----------------------------------------------------------------------------
# DIR-ONT-01: Flag Short-Circuit for --check (100% Read-Only)
# -----------------------------------------------------------------------------
MODE="setup"
while [[ $# -gt 0 ]]; do
    case "$1" in
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

run_check() {
    local DEGRADED=0
    echo "=========================================================="
    echo "  AEP System Health & Read-Only Audit (--check)"
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
    GO_BIN="$(command -v go 2>/dev/null || echo "$HOME/.local/bin/go")"
    if [[ -x "$GO_BIN" ]]; then
        local GO_VER
        GO_VER="$("$GO_BIN" version 2>/dev/null || echo "present")"
        echo -e "[PASS] Golang: $GO_VER ($GO_BIN)"
    else
        echo -e "[FAIL] Golang: MISSING"
        DEGRADED=1
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
        if "$PUEUE_BIN" status &>/dev/null; then
            echo -e "[PASS] Pueue Daemon: ACTIVE and responsive ($PUEUE_BIN)"
        else
            echo -e "[FAIL] Pueue Daemon: binary present but daemon NOT responding"
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
    if [[ "$HOOKS_PATH" == "scripts/hooks" ]]; then
        echo -e "[PASS] Git Pre-commit Hook: tracked (core.hooksPath=scripts/hooks)"
    else
        echo -e "[WARN] Git Pre-commit Hook: not tracked (current: '$HOOKS_PATH')"
    fi

    # 8. SQLite Catalog & Storage Integrity
    local DB_PATH="${AEP_CATALOG_DB:-$HOME/.local/share/agent-os/artifacts.db}"
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

# -----------------------------------------------------------------------------
# DIR-ONT-03: Subshell PATH Injection
# -----------------------------------------------------------------------------
export PATH="$HOME/.local/bin:$HOME/.local/share/go/bin:$HOME/.local/share/agent-os/bin:$PATH"

echo "=========================================================="
echo "  Agent Execution Plane (AEP) — Setup & Tooling Provisioner"
echo "  Mode: $MODE"
echo "=========================================================="

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
if ! command -v uv &>/dev/null && [[ ! -x "$HOME/.local/bin/uv" ]]; then
    log_step "uv ausente; descargando instalador oficial de Astral..."
    curl -LsSf https://astral.sh/uv/install.sh | env CARGO_DIST_FORCE_INSTALL_DIR="$HOME/.local/bin" sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if [[ "$MODE" == "update" ]]; then
    log_step "Actualizando uv..."
    uv self update 2>/dev/null || true
fi
log_success "uv operativo: $(uv --version 2>/dev/null || echo 'ok')"

# -----------------------------------------------------------------------------
# 3. Python 3.14 Hermetic Virtual Environment (DIR-ONT-04)
# -----------------------------------------------------------------------------
log_step "Provisionando entorno hermético Python 3.14..."
uv python install 3.14

VENV_DIR="$PROJECT_ROOT/.venv"
if [[ "$MODE" == "update" ]] || [[ ! -d "$VENV_DIR" ]]; then
    log_step "Creando venv hermético en $VENV_DIR con Python 3.14..."
    # DIR-ONT-04: STRICTLY omit --system-site-packages
    uv venv --python 3.14 "$VENV_DIR"
fi

# Instalar dependencias del proyecto en modo editable con extras dev
log_step "Sincronizando dependencias en el venv hermético..."
VIRTUAL_ENV="$VENV_DIR" uv pip install -e ".[dev]"
VIRTUAL_ENV="$VENV_DIR" uv pip install -q sqlite-vec fastembed playwright

# Sincronizar symlink canónico para ~/.local/share/agent-os/venv
mkdir -p "$HOME/.local/share/agent-os"
ln -sfn "$VENV_DIR" "$HOME/.local/share/agent-os/venv"

# Pre-cache de modelo semántico BAAI/bge-small-en-v1.5
if "$VENV_DIR/bin/python" -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')" &>/dev/null; then
    log_success "Entorno semántico listo (modelo bge-small-en-v1.5 cacheado)."
else
    log_warn "Modelo semántico bge-small-en-v1.5 se descargará en primer uso."
fi

# Chromium headless para visual_inspect (fail-soft)
"$VENV_DIR/bin/python" -m playwright install chromium &>/dev/null     && log_success "Chromium headless provisionado (visual_inspect)."     || log_warn "Chromium no se pudo provisionar; visual_inspect degrada a DISPLAY_UNAVAILABLE."

# -----------------------------------------------------------------------------
# 4. Golang Toolchain & Static Diagnostic Probes
# -----------------------------------------------------------------------------
log_step "Verificando compilador Golang..."
if ! command -v go &>/dev/null && [[ ! -x "$HOME/.local/bin/go" ]]; then
    log_step "Golang ausente; intentando instalación..."
    if sudo -n true 2>/dev/null; then
        log_step "Instalando golang-go vía apt-get (sudo no-interactivo)..."
        sudo -n apt-get update -qq && sudo -n apt-get install -y -qq golang-go 2>/dev/null || true
    fi

    if ! command -v go &>/dev/null; then
        log_step "Instalando Golang en espacio de usuario desde tarball oficial..."
        GO_VERSION="1.22.5"
        GO_TARBALL="go${GO_VERSION}.linux-amd64.tar.gz"
        curl -sSL -o "$TMP_DIR/$GO_TARBALL" "https://go.dev/dl/$GO_TARBALL"
        mkdir -p "$HOME/.local/share"
        rm -rf "$HOME/.local/share/go"
        tar -C "$HOME/.local/share" -xzf "$TMP_DIR/$GO_TARBALL"
        ln -sfn "$HOME/.local/share/go/bin/go" "$HOME/.local/bin/go"
        export PATH="$HOME/.local/share/go/bin:$HOME/.local/bin:$PATH"
    fi
fi

if command -v go &>/dev/null || [[ -x "$HOME/.local/bin/go" ]]; then
    GO_CMD="$(command -v go || echo "$HOME/.local/bin/go")"
    log_success "Golang disponible: $($GO_CMD version 2>/dev/null)"

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
else
    log_warn "Golang no disponible; sondas Go omitidas."
fi

# -----------------------------------------------------------------------------
# 5. Bubblewrap Sandboxing (Fail-Soft)
# -----------------------------------------------------------------------------
log_step "Verificando Bubblewrap (bwrap)..."
if ! command -v bwrap &>/dev/null; then
    if sudo -n true 2>/dev/null; then
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
    TAG=$(curl -sSL https://api.github.com/repos/Nukesor/pueue/releases/latest 2>/dev/null | grep -m1 '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/' || echo "")
    if [[ -n "${TAG:-}" ]]; then
        for b in pueue pueued; do
            curl -sSL -o "$TMP_DIR/$b" "https://github.com/Nukesor/pueue/releases/download/$TAG/${b}-x86_64-unknown-linux-musl"
            chmod +x "$TMP_DIR/$b"
            mv "$TMP_DIR/$b" "$HOME/.local/bin/$b"
        done
        log_success "Pueue $TAG instalado en ~/.local/bin."
    else
        log_warn "No se pudo consultar GitHub API para Pueue (posible limitación de red)."
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
print(f"Catálogo SQLite listo (vec_available={cat._vec_available}).")
PY

# -----------------------------------------------------------------------------
# 9. MCP Seeding & Hot-Reload Delegation (aep-sync.sh)
# -----------------------------------------------------------------------------
log_step "Ejecutando auto-plug y sincronización MCP multi-agente..."
chmod +x "$PROJECT_ROOT/scripts/aep-mcp-launch.sh" "$PROJECT_ROOT/scripts/aep-sync.sh" "$PROJECT_ROOT/scripts/aep-ctl" 2>/dev/null || true
bash "$PROJECT_ROOT/scripts/aep-sync.sh" || log_warn "Auto-plug MCP finalizó con advertencias; revisa aep-sync.sh --check."

echo "=========================================================="
echo "  Instalación y Seeding de AEP Completados con Éxito"
echo "=========================================================="
