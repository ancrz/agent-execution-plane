# shellcheck shell=sh
# =============================================================================
# aep-env.sh — Entorno de herencia universal para subprocesos de agentes de IA.
#
# AGNÓSTICO DE SHELL: escrito en sintaxis POSIX para funcionar igual en bash, zsh y sh.
# NO depende de Oh My Zsh ni de ningún framework. Se instala haciendo que cada rc del
# usuario (~/.bashrc, ~/.zshenv, ~/.profile) lo haga `source`, vía scripts/install-shell-env.sh.
#
# Objetivo: que cualquier subproceso que lance un agente herede un entorno no-bloqueante
# (sin pagers interactivos, sin prompts) y los wrappers estructurados del stack AEP.
# =============================================================================

# --- Variables anti-bloqueo (resuelven el "entorno hostil" para la IA) ---
export PAGER="cat"
export SYSTEMD_PAGER="cat"
export GIT_PAGER="cat"
export DEBIAN_FRONTEND="noninteractive"

# --- PATH de usuario: sondas Go, binarios (pueue), venv, aep-ctl ---
case ":${PATH}:" in
    *":${HOME}/.local/share/agent-os/bin:"*) : ;;
    *) PATH="${HOME}/.local/share/agent-os/bin:${HOME}/.local/bin:${PATH}" ;;
esac
export PATH

# Raíz del proyecto AEP (resuelta en instalación; sobreescribible).
export AEP_HOME="${AEP_HOME:-${HOME}/Documents/workspaces/agent-execution-plane}"

# --- Wrappers de ejecución estructurada y asíncrona (degradan si falta el binario) ---
# jrun: formatea salida de utilidades POSIX como JSON (requiere jc).
jrun() { if command -v jc >/dev/null 2>&1; then jc --pretty "$@"; else "$@"; fi; }

# bg_exec / bg_stat: encolado asíncrono vía Pueue (Camino B).
bg_exec() { if command -v pueue >/dev/null 2>&1; then pueue add --print-task-id -- "$@"; else echo "pueue no instalado" >&2; return 127; fi; }
bg_stat() { if command -v pueue >/dev/null 2>&1; then pueue status --json; else echo "pueue no instalado" >&2; return 127; fi; }

# sys_json: telemetría de host en JSON (nu si existe; si no, aep-ctl).
sys_json() {
    if command -v nu >/dev/null 2>&1; then
        nu -c "sys host | merge (sys mem) | to json"
    elif command -v aep-ctl >/dev/null 2>&1; then
        aep-ctl storage usage --json
    else
        echo '{"error":"nu/aep-ctl no disponibles"}'
    fi
}

# aep: atajo al plano de control unificado desde la shell.
aep() { if [ -x "${AEP_HOME}/scripts/aep-ctl" ]; then "${AEP_HOME}/scripts/aep-ctl" "$@"; else echo "aep-ctl no encontrado en ${AEP_HOME}" >&2; return 127; fi; }
