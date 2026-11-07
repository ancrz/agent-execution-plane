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
    local err_compile err_import
    err_compile="$(mktemp -t aep_sync_compile.XXXXXX)"
    err_import="$(mktemp -t aep_sync_import.XXXXXX)"
    trap 'rm -f "$err_compile" "$err_import"' RETURN
    if ! "$py" -m py_compile "$PROJECT_ROOT/server.py" "$PROJECT_ROOT/aep_front.py" "$PROJECT_ROOT/aep_backend.py" "$PROJECT_ROOT"/engine/*.py 2>"$err_compile"; then
        err "py_compile falló:"; cat "$err_compile"; return 1
    fi
    # Smoke de import: construye el server completo (registra las tools). Falla => no se enchufa.
    if ! PYTHONPATH="$PROJECT_ROOT" "$py" -c "import server; assert hasattr(server,'mcp'); assert len(server.mcp._tool_manager._tools) == 17, f'Expected 17 tools, got {len(server.mcp._tool_manager._tools)}'" 2>"$err_import"; then
        err "import de server falló:"; cat "$err_import"; return 1
    fi
    chmod +x "$LAUNCHER" "$SCRIPT_DIR/aep-ctl" "$PROJECT_ROOT/aep_front.py" "$PROJECT_ROOT/aep_backend.py" 2>/dev/null || true
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
            local agy_status
            agy_status="$(python3 - "$PROJECT_ROOT" <<'PY' 2>/dev/null || echo "STATUS:error"
import re, subprocess, sys
from pathlib import Path
project_root = sys.argv[1] if len(sys.argv) > 1 else "."
ps = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
ss = subprocess.check_output(["ss", "-tulnp"], text=True)
found_server = False
reload_ok = False
for line in ps.splitlines():
    if "language_server" in line and "--csrf_token" in line:
        found_server = True
        pid = line.split()[0]
        m = re.search(r"--csrf_token\s+(\S+)", line)
        tok = m.group(1) if m else ""
        for port in re.findall(r"127\.0\.0\.1:(\d+).*?pid=" + pid + r",", ss):
            for scheme in ("https", "http"):
                res = subprocess.run(
                    ["curl", "-sk", "--max-time", "5", "-w", "%{http_code}", "-o", "/dev/null", "-X", "POST",
                     f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RefreshMcpServers",
                     "-H", "Content-Type: application/json",
                     "-H", "Connect-Protocol-Version: 1",
                     "-H", f"x-codeium-csrf-token: {tok}", "-d", "{}"],
                    capture_output=True, text=True,
                )
                if res.stdout.strip() in ("200", "204"):
                    reload_ok = True
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

if reload_ok:
    print("STATUS:reload_ok")
elif found_server:
    print("STATUS:reload_failed")
else:
    print("STATUS:no_language_server")
PY
)"
            if echo "$agy_status" | grep -q "STATUS:reload_ok"; then
                ok "Antigravity (agy) re-registrado + hot-reload OK (RefreshMcpServers HTTP 200)"
            elif echo "$agy_status" | grep -q "STATUS:reload_failed"; then
                warn "Antigravity (agy) re-registrado, pero RefreshMcpServers falló (HTTP non-200)"
            else
                ok "Antigravity (agy) re-registrado (sin language_server activo; aplicará al iniciar agy)"
            fi
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

audit_running_instances() {
    log "Auditando instancias activas de AEP..."
    local head_commit; head_commit="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
    local head_ct; head_ct="$(git -C "$PROJECT_ROOT" log -1 --format=%ct 2>/dev/null || echo 0)"
    local head_time; head_time="$(date -d "@$head_ct" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "$head_ct")"
    local pids; pids="$(pgrep -f "python.*(server\.py|aep_front\.py|aep_backend\.py)" 2>/dev/null || true)"
    if [[ -z "$pids" ]]; then
        ok "No hay instancias de AEP en ejecución."
        return 0
    fi

    local current_pid=$$
    local found_count=0
    local stale_count=0
    # ONT-41 TC6: clasificacion por /dev/shm/aep_front_<pid>.json (pids muertos se limpian); sin archivo -> legacy/unknown.
    local state_lines; state_lines="$(python3 "$SCRIPT_DIR/aep_audit_state.py" "$PROJECT_ROOT" $pids 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.loads(sys.stdin.read() or "{}")
except ValueError:
    data = {}
for i in data.get("instances", []):
    print("%s\t%s\t%s" % (i["pid"], i["class"], i["detail"]))
' 2>/dev/null || true)"
    for pid in $pids; do
        if [[ "$pid" == "$current_pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
            continue
        fi
        local st_class; st_class="$(printf '%s\n' "$state_lines" | awk -F'\t' -v p="$pid" '$1==p {print $2; exit}')"
        local st_detail; st_detail="$(printf '%s\n' "$state_lines" | awk -F'\t' -v p="$pid" '$1==p {print $3; exit}')"
        if [[ -n "$st_class" && "$st_class" != "legacy/unknown" ]]; then
            found_count=$((found_count + 1))
            case "$st_class" in
                front_stale)   stale_count=$((stale_count + 1)); warn "PID $pid: front_stale -> $st_detail" ;;
                serving_lkg)   stale_count=$((stale_count + 1)); warn "PID $pid: serving_from=lkg -> $st_detail" ;;
                backend_stale) ok "PID $pid: backend_stale -> $st_detail" ;;
                *)             ok "PID $pid: $st_class ($st_detail)" ;;
            esac
            continue
        fi

        found_count=$((found_count + 1))
        local ppid; ppid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d " " || echo 0)"
        local parent_cmd; parent_cmd="$(ps -o comm= -p "$ppid" 2>/dev/null || ps -o args= -p "$ppid" 2>/dev/null || echo "unknown")"
        local pppid; pppid="$(ps -o ppid= -p "$ppid" 2>/dev/null | tr -d " " || echo 0)"
        local ancestors="$parent_cmd"
        if [[ "$pppid" -gt 1 ]]; then
            ancestors="$ancestors $(ps -o args= -p "$pppid" 2>/dev/null || true)"
        fi

        local harness="CLI/Other"
        local restart_hint="Reinicie el proceso o la sesión correspondiente."
        if echo "$ancestors" | grep -qi "claude"; then
            harness="Claude Code"
            restart_hint="Reinicie la sesión con 'claude' o salga y reanude con 'claude --resume'."
        elif echo "$ancestors" | grep -qi -E "agy|antigravity|language_server"; then
            harness="Antigravity"
            restart_hint="Reinicie la ventana/sesión de Antigravity o ejecute RefreshMcpServers."
        elif echo "$ancestors" | grep -qi "codex"; then
            harness="Codex"
            restart_hint="Envíe config/mcpServer/reload vía socket o reinicie Codex CLI."
        elif echo "$ancestors" | grep -qi "gemini"; then
            harness="Gemini CLI"
            restart_hint="Reinicie la sesión activa de Gemini CLI."
        fi

        local proc_mtime; proc_mtime="$(stat -c %Y "/proc/$pid" 2>/dev/null || echo 0)"
        local proc_time; proc_time="$(date -d "@$proc_mtime" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "$proc_mtime")"
        if [[ "$head_ct" -gt 0 && "$proc_mtime" -gt 0 && "$proc_mtime" -lt "$head_ct" ]]; then
            stale_count=$((stale_count + 1))
            warn "Instancia STALE detectada [legacy/unknown, D-24] (PID $pid, Harness: $harness, PPID $ppid):"
            echo -e "       ${YELLOW}Iniciada:${NC}       $proc_time (antes del HEAD $head_commit @ $head_time)"
            echo -e "       ${YELLOW}Estado:${NC}         Ejecutando bytecode desactualizado en memoria (GAP-RT-04)."
            echo -e "       ${YELLOW}Instrucciones:${NC}  $restart_hint"
            if [[ "${REAP_STALE:-0}" == "1" ]]; then
                if [[ "$ppid" -eq 1 ]]; then
                    echo -e "       ${GREEN}Reap:${NC}           Instancia huérfana (PPID=1) -> enviando SIGTERM."
                    kill -TERM "$pid" 2>/dev/null || true
                else
                    echo -e "       ${YELLOW}Seguridad:${NC}      No se mata automáticamente: PPID $ppid != 1 (preservando harness)."
                fi
            else
                echo -e "       ${YELLOW}Seguridad:${NC}      No se mata automáticamente para preservar contexto del harness (use --reap-stale para huérfanos)."
            fi
        else
            ok "Instancia AEP (PID $pid, Harness: $harness, PPID $ppid) al día con HEAD ($head_commit)."
        fi
    done
    if [[ "$found_count" -eq 0 ]]; then
        ok "No hay instancias secundarias de AEP en ejecución."
    elif [[ "$stale_count" -eq 0 ]]; then
        ok "Todas las instancias activas ($found_count) están sincronizadas con commit $head_commit."
    else
        warn "$stale_count instancia(s) obsoleta(s) encontrada(s). Siga las instrucciones de recarga por harness."
    fi
    return 0
}

print_fingerprint() {
    local py; py="$(resolve_py)"
    PYTHONPATH="$PROJECT_ROOT" "$py" -c "import engine.fingerprint as fp; print(fp.code_fingerprint('$PROJECT_ROOT'))"
}

sync_once() {
    if validate; then
        register
        audit_running_instances || true
    else
        err "Sync abortado: no se enchufa un server inválido."
        return 1
    fi
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

REAP_STALE=0
MODE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)             MODE="check"; shift ;;
        --audit)             MODE="audit"; shift ;;
        --watch)             MODE="watch"; shift ;;
        --reap-stale)        REAP_STALE=1; shift ;;
        --print-fingerprint) MODE="print_fingerprint"; shift ;;
        --with-claude)       AEP_PLUG_CLAUDE=1; shift ;;
        --no-claude)         AEP_PLUG_CLAUDE=0; shift ;;
        *)                   err "Uso: aep-sync.sh [--check|--audit|--reap-stale|--print-fingerprint|--watch|--with-claude|--no-claude]"; exit 2 ;;
    esac
done

case "$MODE" in
    check)               validate ;;
    audit)               audit_running_instances ;;
    watch)               watch_mode ;;
    print_fingerprint)   print_fingerprint ;;
    "")
        if [[ "$REAP_STALE" == "1" ]]; then
            audit_running_instances
        else
            sync_once
        fi
        ;;
esac
