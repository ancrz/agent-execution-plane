#!/usr/bin/env bash
# =============================================================================
# install-shell-env.sh — Instala la herencia de entorno AEP en shells NATIVAS.
#
# No asume Oh My Zsh. Hace que cada rc del usuario haga `source` del archivo único
# config/shell/aep-env.sh: ~/.bashrc (bash), ~/.zshenv (zsh) y ~/.profile (login POSIX).
# Idempotente (guardado por marcador). No modifica frameworks ni duplica.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/config/shell/aep-env.sh"

log()  { printf '[shell-env] %s\n' "$*"; }
warn() { printf '[shell-env][warn] %s\n' "$*" >&2; }

if [[ ! -f "${ENV_FILE}" ]]; then
    warn "No existe ${ENV_FILE}"; exit 1
fi

MARKER="# >>> AEP_SHELL_ENV >>>"
SOURCE_LINE="export AEP_HOME=\"${PROJECT_ROOT}\"; [ -f \"${ENV_FILE}\" ] && . \"${ENV_FILE}\"  ${MARKER}"

inject() {
    local rc="$1"
    # Crear ~/.profile si falta (fallback universal de login POSIX); el resto solo si existe.
    if [[ ! -e "${rc}" ]]; then
        if [[ "${rc}" == "${HOME}/.profile" ]]; then
            touch "${rc}"
        else
            return 0
        fi
    fi
    if grep -qF "${MARKER}" "${rc}" 2>/dev/null; then
        log "ya presente en ${rc} (sin duplicar)"
    else
        printf '\n%s\n' "${SOURCE_LINE}" >> "${rc}"
        log "inyectado en ${rc}"
    fi
}

# Aviso si existe el bloque inline antiguo del setup.sh previo (no lo tocamos, solo avisamos).
if grep -q "AEP_UNIVERSAL_INHERITANCE" "${HOME}/.zshenv" 2>/dev/null; then
    warn "~/.zshenv tiene el bloque inline antiguo (AEP_UNIVERSAL_INHERITANCE). Puedes borrarlo: ahora todo vive en config/shell/aep-env.sh."
fi

inject "${HOME}/.bashrc"
inject "${HOME}/.zshenv"
inject "${HOME}/.profile"

log "Listo. Shell detectada: ${SHELL:-desconocida}. Abre una shell nueva o ejecuta: . \"${ENV_FILE}\""
