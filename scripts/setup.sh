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
mkdir -p "$HOME/.codex/skills"

# Symlinks Omarchy pattern (SPEC-OM-3: Universal Multi-Agent Skills Hub)
ln -sfn "$HOME/.agents/skills" "$HOME/.claude/skills/shared"
ln -sfn "$HOME/.agents/skills" "$HOME/.gemini/skills/shared"
ln -sfn "$HOME/.agents/skills" "$HOME/.codex/skills/shared"
log_success "Estructura de directorios y Hub de Skills configurados."

# 1.5. Provisionamiento del entorno semántico (venv aislado + sqlite-vec + fastembed)
# FAIL-SOFT: si algo falla, el catálogo opera en modo solo-hash sin romperse.
log_step "Provisionando entorno semántico (venv + sqlite-vec + fastembed)..."
VENV_DIR="$HOME/.local/share/agent-os/venv"
AEP_PYTHON="python3"  # fallback: python del sistema (catálogo en modo solo-hash)
if command -v uv &> /dev/null; then
    if uv venv --system-site-packages --python "$(command -v python3)" "$VENV_DIR" &> /dev/null; then
        if VIRTUAL_ENV="$VENV_DIR" uv pip install -q sqlite-vec fastembed playwright &> /dev/null; then
            AEP_PYTHON="$VENV_DIR/bin/python"
            if "$AEP_PYTHON" -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')" &> /dev/null; then
                log_success "Entorno semántico listo (modelo bge-small-en-v1.5 cacheado, 384-dim)."
            else
                log_warn "Paquetes instalados pero el modelo se descargará en el primer uso (requiere internet)."
            fi
            # Chromium headless para SPEC-OM-5 visual_inspect (opcional; no bloquea).
            "$AEP_PYTHON" -m playwright install chromium &> /dev/null \
                && log_success "Chromium headless provisionado (visual_inspect)." \
                || log_warn "Chromium no se pudo provisionar; visual_inspect degrada a DISPLAY_UNAVAILABLE."
        else
            log_warn "sqlite-vec/fastembed no se pudieron instalar; catálogo en modo solo-hash."
        fi
    else
        log_warn "No se pudo crear el venv; catálogo en modo solo-hash."
    fi
else
    log_warn "uv no está instalado (https://astral.sh/uv). Catálogo en modo solo-hash."
fi

# 2. Inicialización de base de datos y pre-compilación de plantillas
log_step "Inicializando catálogo de artefactos (SQLite) y pre-compilando sondas Go..."
cd "$PROJECT_ROOT"
PYTHONPATH="$PROJECT_ROOT" "$AEP_PYTHON" -c "
from engine.catalog import ArtifactCatalog
from pathlib import Path
cat = ArtifactCatalog()
tpl_socket = Path('templates/tpl_socket_monitor.go').read_text()
cue_socket = 'package schema\nname: \"socket-monitor\"\ncategory: \"network\"'
cat.register_artifact('socket-monitor', 'inspect_tcp_sockets', 'network', cue_socket, tpl_socket,
    intent_description='list and inspect listening TCP sockets and open network ports on the host')

tpl_fd = Path('templates/tpl_fd_rescuer.go').read_text()
cue_fd = 'package schema\nname: \"fd-rescuer\"\ncategory: \"process\"'
cat.register_artifact('fd-rescuer', 'inspect_process_fds', 'process', cue_fd, tpl_fd,
    intent_description='inspect the open file descriptors of a process to diagnose hung or deadlocked threads')
print('Catalogo SQLite listo (vec_available=%s).' % cat._vec_available)
" || log_warn "Init del catálogo falló (¿DB bloqueada por un server activo?). Reintenta tras cerrar el MCP."

# Pre-compilar los binarios en ~/.local/share/agent-os/bin
CGO_ENABLED=0 go build -ldflags="-s -w" -o "$HOME/.local/share/agent-os/bin/socket-monitor" "$PROJECT_ROOT/templates/tpl_socket_monitor.go"
CGO_ENABLED=0 go build -ldflags="-s -w" -o "$HOME/.local/share/agent-os/bin/fd-rescuer" "$PROJECT_ROOT/templates/tpl_fd_rescuer.go"
log_success "Sondas Go pre-compiladas estáticamente en ~/.local/share/agent-os/bin/"

# 3. Activación de demonio asíncrono Pueue (auto-descarga user-space, sin sudo)
log_step "Verificando demonio Pueue..."
if ! command -v pueued &> /dev/null && [[ ! -x "$HOME/.local/bin/pueued" ]]; then
    log_step "pueued ausente; descargando binario estático musl a ~/.local/bin..."
    TAG=$(curl -sSL https://api.github.com/repos/Nukesor/pueue/releases/latest 2>/dev/null | grep -m1 '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
    if [[ -n "${TAG:-}" ]]; then
        for b in pueue pueued; do
            curl -sSL -o "$HOME/.local/bin/$b" \
                "https://github.com/Nukesor/pueue/releases/download/$TAG/${b}-x86_64-unknown-linux-musl" \
                && chmod +x "$HOME/.local/bin/$b"
        done
        log_success "Pueue $TAG instalado en ~/.local/bin (sin sudo)."
    else
        log_warn "No se pudo resolver la release de Pueue (¿sin red?). Camino B async en modo degradado."
    fi
fi
if command -v pueued &> /dev/null || [[ -x "$HOME/.local/bin/pueued" ]]; then
    PUEUED_BIN="$(command -v pueued || echo "$HOME/.local/bin/pueued")"
    systemctl --user enable --now pueued 2>/dev/null || "$PUEUED_BIN" -d 2>/dev/null || true
    log_success "Pueue daemon activo."
else
    log_warn "pueued no disponible; async_job_dispatch degradará con error estructurado (fail-soft)."
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
chmod +x "$PROJECT_ROOT/scripts/aep-ctl" 2>/dev/null || true

# Ingesta curada opcional de man-pages (SPEC-OM-4). ~30s; no bloquea el seeding.
if [[ "$AEP_PYTHON" != "python3" ]]; then
    log_step "Vectorizando man-pages del sistema (SPEC-OM-4, opcional)..."
    PYTHONPATH="$PROJECT_ROOT" "$AEP_PYTHON" -c "
from engine.docs_vectorizer import ManPagesVectorizer
r = ManPagesVectorizer().ingest_curated()
ok = sum(1 for v in r['results'].values() if v == 'OK')
print('man-pages indexadas:', ok, '/', len(r['results']))
" 2>/dev/null || log_warn "Ingesta de man-pages omitida (no crítico)."
fi

# Registro delegado al script de autogestión atómica (una sola fuente de verdad).
# aep-sync.sh valida y SOLO si pasa re-registra el MCP en Claude/agy/Codex apuntando
# al launcher estable (aep-mcp-launch.sh), que resuelve el intérprete por sí mismo.
bash "$PROJECT_ROOT/scripts/aep-sync.sh" || log_warn "Auto-plug del MCP falló; revisa scripts/aep-sync.sh --check."

echo "=========================================================="
echo "  Instalación y Seeding de AEP Completados con Éxito"
echo "=========================================================="
