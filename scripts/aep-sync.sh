#!/usr/bin/env bash
# =============================================================================
# aep-sync.sh — Autogestión atómica del ecosistema MCP (AUTO-PLUG)
#
# Tras cambiar el servidor o el engine, este script:
#   1. VALIDA (py_compile + smoke de import que registra las tools).
#   2. Solo si la validación pasa, RE-REGISTRA el MCP en Claude/agy/Codex apuntando
#      al launcher estable (aep-mcp-launch.sh). Nunca "enchufa" un server roto (atómico).
#
# Uso:
#   ./scripts/aep-sync.sh           # valida + re-registra una vez
#   ./scripts/aep-sync.sh --check   # solo valida (CI/pre-commit), no toca registros
#   ./scripts/aep-sync.sh --watch   # vigila cambios y re-sincroniza automáticamente
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCHER="$SCRIPT_DIR/aep-mcp-launch.sh"
SERVER_NAME="agent-execution-plane"
VENV_PY="$HOME/.local/share/agent-os/venv/bin/python"

GREEN="\033[0;32m"; BLUE="\033[0;34m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
log()  { echo -e "${BLUE}[sync]${NC} $1"; }
ok()   { echo -e "${GREEN}[ok]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[fail]${NC} $1"; }

resolve_py() {
    if [[ -x "$VENV_PY" ]] && "$VENV_PY" -c "import sqlite_vec" >/dev/null 2>&1; then
        echo "$VENV_PY"
    else
        echo "$(command -v python3)"
    fi
}

validate() {
    local py; py="$(resolve_py)"
    log "Validando con $py"
    if ! "$py" -m py_compile "$PROJECT_ROOT/server.py" "$PROJECT_ROOT"/engine/*.py 2>/tmp/aep_sync_compile.err; then
        err "py_compile falló:"; cat /tmp/aep_sync_compile.err; return 1
    fi
    # Smoke de import: construye el server completo (registra las tools). Falla => no se enchufa.
    if ! PYTHONPATH="$PROJECT_ROOT" "$py" -c "import server; assert hasattr(server,'mcp')" 2>/tmp/aep_sync_import.err; then
        err "import de server falló:"; cat /tmp/aep_sync_import.err; return 1
    fi
    chmod +x "$LAUNCHER" "$SCRIPT_DIR/aep-ctl" 2>/dev/null || true
    ok "Validación superada (server importable, tools registradas)."
    return 0
}

register() {
    chmod +x "$LAUNCHER"
    local n=0
    if command -v claude >/dev/null 2>&1; then
        claude mcp remove --scope user "$SERVER_NAME" >/dev/null 2>&1 || true
        claude mcp add --scope user "$SERVER_NAME" -- "$LAUNCHER" >/dev/null 2>&1 && { ok "Claude Code re-registrado"; n=$((n+1)); } || warn "Claude: fallo al registrar"
    fi
    if command -v agy >/dev/null 2>&1; then
        agy mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
        agy mcp add "$SERVER_NAME" "$LAUNCHER" >/dev/null 2>&1 && { ok "Antigravity (agy) re-registrado"; n=$((n+1)); } || warn "agy: fallo al registrar"
    fi
    if command -v codex >/dev/null 2>&1; then
        codex mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
        codex mcp add "$SERVER_NAME" -- "$LAUNCHER" >/dev/null 2>&1 && { ok "Codex re-registrado"; n=$((n+1)); } || warn "codex: fallo al registrar"
    fi
    if command -v gemini >/dev/null 2>&1; then
        gemini mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
        gemini mcp add "$SERVER_NAME" "$LAUNCHER" >/dev/null 2>&1 && { ok "Gemini CLI re-registrado"; n=$((n+1)); } || warn "gemini: fallo al registrar"
    fi
    ok "Auto-plug completado en $n cliente(s). (Las sesiones activas aplican al reiniciar.)"
}

sync_once() {
    if validate; then register; else err "Sync abortado: no se enchufa un server inválido."; return 1; fi
}

watch_mode() {
    if ! command -v inotifywait >/dev/null 2>&1; then
        err "inotifywait no disponible (apt install inotify-tools). Usa --check en un hook."; exit 1
    fi
    log "Vigilando cambios en server.py, engine/, scripts/ (Ctrl-C para salir)..."
    sync_once || true
    while inotifywait -q -e close_write,move,create,delete \
            "$PROJECT_ROOT/server.py" "$PROJECT_ROOT/engine" "$SCRIPT_DIR" >/dev/null 2>&1; do
        sleep 0.4  # debounce
        echo "---"; log "Cambio detectado -> re-sincronizando"
        sync_once || warn "Validación falló; registros intactos."
    done
}

case "${1:-}" in
    --check) validate ;;
    --watch) watch_mode ;;
    "")      sync_once ;;
    *)       err "Uso: aep-sync.sh [--check|--watch]"; exit 2 ;;
esac
