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
#   ./scripts/aep-sync.sh               # valida + re-registra una vez (Claude, agy, Codex, Gemini)
#   ./scripts/aep-sync.sh --no-claude   # valida + re-registra omitiendo Claude Code
#   ./scripts/aep-sync.sh --check       # solo valida (CI/pre-commit), no toca registros
#   ./scripts/aep-sync.sh --watch       # vigila cambios y re-sincroniza automáticamente
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
    if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]] && "$PROJECT_ROOT/.venv/bin/python" -c "import sqlite_vec" >/dev/null 2>&1; then
        echo "$PROJECT_ROOT/.venv/bin/python"
    elif [[ -x "$VENV_PY" ]] && "$VENV_PY" -c "import sqlite_vec" >/dev/null 2>&1; then
        echo "$VENV_PY"
    else
        command -v python3
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
        if [[ "${AEP_PLUG_CLAUDE:-1}" == "1" ]]; then
            if claude mcp add --scope user "$SERVER_NAME" -- "$LAUNCHER" >/dev/null 2>&1; then
                ok "Claude Code re-registrado"
                n=$((n+1))
            else
                warn "Claude: fallo al registrar"
            fi
        else
            log "Claude Code: omitido (AEP_PLUG_CLAUDE=0 o --no-claude)"
        fi
    fi
    if command -v agy >/dev/null 2>&1; then
        agy mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
        if agy mcp add "$SERVER_NAME" "$LAUNCHER" >/dev/null 2>&1; then
            # Hot-reload en vivo para sesiones activas de Antigravity (language_server Connect-RPC):
            # descubre el PID/CSRF token del language_server y dispara RefreshMcpServers para
            # regenerar ~/.gemini/antigravity/mcp/agent-execution-plane/*.json sin reiniciar sesión.
            python3 - "$PROJECT_ROOT" <<'PY' >/dev/null 2>&1 || true
import re, subprocess, sys
from pathlib import Path
project_root = sys.argv[1] if len(sys.argv) > 1 else "."
ps = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
ss = subprocess.check_output(["ss", "-tulnp"], text=True)
for line in ps.splitlines():
    if "language_server" in line and "--csrf_token" in line:
        pid = line.split()[0]
        m = re.search(r"--csrf_token\s+(\S+)", line)
        tok = m.group(1) if m else ""
        for port in re.findall(r"127\.0\.0\.1:(\d+).*?pid=" + pid + r",", ss):
            for scheme in ("https", "http"):
                subprocess.run(
                    ["curl", "-sk", "--max-time", "5", "-X", "POST",
                     f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RefreshMcpServers",
                     "-H", "Content-Type: application/json",
                     "-H", "Connect-Protocol-Version: 1",
                     "-H", f"x-codeium-csrf-token: {tok}", "-d", "{}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
try:
    sys.path.insert(0, project_root)
    import server
    registered = set(server.mcp._tool_manager._tools.keys())
    mcp_dir = Path.home() / ".gemini" / "antigravity" / "mcp" / "agent-execution-plane"
    if mcp_dir.exists():
        for json_file in mcp_dir.glob("*.json"):
            if json_file.stem not in registered:
                json_file.unlink(missing_ok=True)
except Exception:
    pass
PY
            ok "Antigravity (agy) re-registrado + hot-reload (RefreshMcpServers)"
            n=$((n+1))
        else
            warn "agy: fallo al registrar"
        fi
    fi
    if command -v codex >/dev/null 2>&1; then
        codex mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
        if codex mcp add "$SERVER_NAME" -- "$LAUNCHER" >/dev/null 2>&1; then
            local codex_sock="${CODEX_HOME:-$HOME/.codex}/app-server-control/app-server-control.sock"
            if [[ -S "$codex_sock" ]]; then
                timeout 3 python3 - "$codex_sock" <<'PY' >/dev/null 2>&1 || true
import json, subprocess, sys
sock = sys.argv[1]
proc = subprocess.Popen(
    ["codex", "app-server", "proxy", "--sock", sock],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
)
try:
    for msg in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "aep-sync", "version": "1.0.0"}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "config/mcpServer/reload", "params": None},
    ):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
finally:
    proc.terminate()
PY
                ok "Codex (ChatGPT) re-registrado + hot-reload (config/mcpServer/reload)"
            else
                ok "Codex (ChatGPT) re-registrado (~/.codex/config.toml)"
            fi
            n=$((n+1))
        else
            warn "codex: fallo al registrar"
        fi
    fi
    if command -v gemini >/dev/null 2>&1; then
        gemini mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
        if gemini mcp add "$SERVER_NAME" "$LAUNCHER" >/dev/null 2>&1; then
            ok "Gemini CLI re-registrado"
            n=$((n+1))
        else
            warn "gemini: fallo al registrar"
        fi
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
    --check)       validate ;;
    --watch)       watch_mode ;;
    --with-claude) AEP_PLUG_CLAUDE=1 sync_once ;;
    --no-claude)   AEP_PLUG_CLAUDE=0 sync_once ;;
    "")            sync_once ;;
    *)             err "Uso: aep-sync.sh [--check|--watch|--with-claude|--no-claude]"; exit 2 ;;
esac
