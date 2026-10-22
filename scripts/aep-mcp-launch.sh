#!/usr/bin/env bash
# =============================================================================
# aep-mcp-launch.sh — Launcher estable del servidor FastMCP (AUTO-PLUG)
#
# Los clientes de IA registran ESTE script como comando del MCP, no `python server.py`.
# Resuelve el intérprete correcto en tiempo de arranque: el venv semántico si existe y
# tiene sqlite-vec, si no el python del sistema (modo solo-hash). Así, cambiar/recrear el
# venv NO obliga a re-registrar el MCP en cada cliente — el launcher se auto-ajusta.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER="$PROJECT_ROOT/server.py"
VENV_PY="$HOME/.local/share/agent-os/venv/bin/python"

# Preferir el venv si puede importar sqlite_vec (tier semántico); si no, python3 (fail-soft).
if [[ -x "$VENV_PY" ]] && "$VENV_PY" -c "import sqlite_vec" >/dev/null 2>&1; then
    AEP_PYTHON="$VENV_PY"
else
    AEP_PYTHON="$(command -v python3)"
fi

export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
# Asegurar que las herramientas de usuario (pueue, aep-ctl, sondas Go) resuelvan en PATH.
export PATH="$HOME/.local/bin:$HOME/.local/share/agent-os/bin:$PATH"
cd "$PROJECT_ROOT"
exec "$AEP_PYTHON" "$SERVER"
