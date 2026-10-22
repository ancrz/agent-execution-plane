#!/usr/bin/env bash
# =============================================================================
# setup.sh — AEP Installer & Multi-Agent MCP Seeder
# Configura el plano de ejecución no-bloqueante para Ubuntu (Zsh/Oh My Zsh)
# y registra el servidor FastMCP en Claude Code, Antigravity (agy) y Codex.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colores y logs
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
NC="\033[0m"

log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo "=========================================================="
echo "  Agent Execution Plane (AEP) — Setup & MCP Seeding"
echo "=========================================================="

# 1. Directorios base
log_step "Preparando directorios locales..."
mkdir -p "$HOME/.local/bin"
mkdir -p "$HOME/.local/share/agent-os/bin"
mkdir -p "$HOME/.agents/skills"
mkdir -p "$HOME/.claude/skills"
mkdir -p "$HOME/.gemini/skills"

# Symlinks Omarchy pattern
ln -sfn "$HOME/.agents/skills" "$HOME/.claude/skills/shared"
ln -sfn "$HOME/.agents/skills" "$HOME/.gemini/skills/shared"
log_success "Estructura de directorios y Hub de Skills configurados."

# 2. Inicialización de base de datos y pre-compilación de plantillas
log_step "Inicializando catálogo de artefactos (SQLite) y pre-compilando sondas Go..."
cd "$PROJECT_ROOT"
python3 -c "
from engine.catalog import ArtifactCatalog
from pathlib import Path
cat = ArtifactCatalog()
tpl_socket = Path('templates/tpl_socket_monitor.go').read_text()
cue_socket = 'package schema\nname: \"socket-monitor\"\ncategory: \"network\"'
cat.register_artifact('socket-monitor', 'inspect_tcp_sockets', 'network', cue_socket, tpl_socket)

tpl_fd = Path('templates/tpl_fd_rescuer.go').read_text()
cue_fd = 'package schema\nname: \"fd-rescuer\"\ncategory: \"process\"'
cat.register_artifact('fd-rescuer', 'inspect_process_fds', 'process', cue_fd, tpl_fd)
print('Catálogo SQLite listo.')
"

# Pre-compilar los binarios en ~/.local/share/agent-os/bin
CGO_ENABLED=0 go build -ldflags="-s -w" -o "$HOME/.local/share/agent-os/bin/socket-monitor" "$PROJECT_ROOT/templates/tpl_socket_monitor.go"
CGO_ENABLED=0 go build -ldflags="-s -w" -o "$HOME/.local/share/agent-os/bin/fd-rescuer" "$PROJECT_ROOT/templates/tpl_fd_rescuer.go"
log_success "Sondas Go pre-compiladas estáticamente en ~/.local/share/agent-os/bin/"

# 3. Activación de demonio asíncrono Pueue
log_step "Verificando demonio Pueue..."
if command -v pueued &> /dev/null; then
    systemctl --user enable --now pueued 2>/dev/null || pueued -d 2>/dev/null || true
    log_success "Pueue daemon activo."
else
    log_warn "pueued no está instalado en el sistema. Puedes instalarlo con: sudo apt install pueue"
fi

# 4. Inyección no-destructiva en ~/.zshenv (Herencia universal para IA sin romper Oh My Zsh)
log_step "Configurando herencia de shell no-bloqueante en ~/.zshenv..."
ZSHENV="$HOME/.zshenv"
TOUCHED_ZSHENV=false

if [[ ! -f "$ZSHENV" ]] || ! grep -q "AEP_UNIVERSAL_INHERITANCE" "$ZSHENV"; then
    cat >> "$ZSHENV" <<'EOF'

# --- AEP_UNIVERSAL_INHERITANCE (Agent Execution Plane) ---
export PATH="$HOME/.local/share/agent-os/bin:$HOME/.local/bin:$PATH"
export PAGER="cat"
export SYSTEMD_PAGER="cat"
export GIT_PAGER="cat"
export DEBIAN_FRONTEND="noninteractive"

# Wrappers de ejecución estructurada y asíncrona
jrun() { jc --pretty "$@"; }
bg_exec() { pueue add --print-task-id -- "$@"; }
bg_stat() { pueue status --json; }
sys_json() { nu -c "sys host | merge (sys mem) | to json"; }
# --- END AEP_UNIVERSAL_INHERITANCE ---
EOF
    TOUCHED_ZSHENV=true
    log_success "Directivas anti-bloqueo y wrappers agregados a ~/.zshenv"
else
    log_success "Directivas AEP ya presentes en ~/.zshenv (sin duplicados)."
fi

# 5. Seeding del Servidor FastMCP en múltiples agentes (Claude, agy, Codex)
log_step "Seeding del Servidor FastMCP en los agentes..."

MCP_SERVER_SCRIPT="$PROJECT_ROOT/server.py"
chmod +x "$MCP_SERVER_SCRIPT"

# 5.1. Claude Code
if command -v claude &> /dev/null; then
    log_step "Registrando en Claude Code..."
    claude mcp remove --scope user agent-execution-plane 2>/dev/null || true
    claude mcp add --scope user agent-execution-plane -- python3 "$MCP_SERVER_SCRIPT" 2>/dev/null || true
    log_success "Registrado en Claude Code."
fi

# 5.2. Antigravity CLI (agy)
if command -v agy &> /dev/null; then
    log_step "Registrando en Antigravity (agy)..."
    agy mcp remove agent-execution-plane 2>/dev/null || true
    agy mcp add agent-execution-plane python3 "$MCP_SERVER_SCRIPT" 2>/dev/null || true
    log_success "Registrado en Antigravity (agy)."
fi

# 5.3. Codex
if command -v codex &> /dev/null; then
    log_step "Registrando en ChatGPT Codex..."
    codex mcp remove agent-execution-plane 2>/dev/null || true
    codex mcp add agent-execution-plane -- python3 "$MCP_SERVER_SCRIPT" 2>/dev/null || true
    log_success "Registrado en Codex."
fi

echo "=========================================================="
echo "  Instalación y Seeding de AEP Completados con Éxito"
echo "=========================================================="
