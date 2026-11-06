#!/usr/bin/env bash
# ==============================================================================
# scripts/aep-agy-probe.sh — Antigravity Headless Acceptance Probe Harness (ONT-38b)
#
# Runs canonical probe battery T1..T8 against the active AEP MCP server via agy -p,
# extracts response JSON, persists findings to ~/.local/share/agent-os/probes/,
# prints a single-line summary, and evaluates the acceptance threshold.
# ==============================================================================
set -euo pipefail

MODEL="${AEP_PROBE_MODEL:-gemini-3.8-flash-high}"
EXPECT_PASS="${AEP_PROBE_EXPECT:-8}"
DRY_RUN=0

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --model M        Override model for agy probe (default: \${AEP_PROBE_MODEL:-gemini-3.8-flash-high})
  --expect N       Required minimum passed probes to exit 0 (default: \${AEP_PROBE_EXPECT:-8})
  --dry-run        Print probe prompt without invoking agy
  -h, --help       Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            if [[ $# -lt 2 ]]; then
                echo "Error: --model requires an argument" >&2
                exit 1
            fi
            MODEL="$2"
            shift 2
            ;;
        --expect)
            if [[ $# -lt 2 ]]; then
                echo "Error: --expect requires an argument" >&2
                exit 1
            fi
            EXPECT_PASS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

PROMPT=$(cat <<'EOF'
Eres el consumidor de verificación del MCP agent-execution-plane. NO modifiques archivos.
Ejecuta, en orden, y para cada uno reporta {id, pass:bool, tok:int, nota}:
T1 discover(action="capabilities", verbosity="terse", session_id="agy-test") -> stale==false
T2 discover(action="schema", verbosity="summary") -> t.tok < 3000            (D-01)
T3 discover(action="playbook", select_fields=["nope"]) -> contiene unresolved_fields (D-03a)
T4 discover(use_case="monitor open tcp sockets", select_fields=["suggested_capability.0.capability"])
   -> suggested_capability es lista y confidence=="HIGH"                     (D-03b, D-07)
T5 artifact_catalog(action="query", intent="monitorear sockets TCP abiertos", category="network")
   -> execution_count > 0                                                    (D-06)
T6 aep_ctl(domain="ipc", action="status", verbosity="summary") -> sin clave mux.pool (D-05)
T7 playbook_run(action="list", verbosity="summary") -> sin clave envelope     (D-02)
T8 discover(action="capabilities") -> capabilities.crash_forensics.ready==true (D-08)
Responde SOLO un JSON {"commit":..., "results":[...], "passed":N, "failed":M}.
EOF
)

if [[ "$DRY_RUN" -eq 1 ]]; then
    printf "%s\n" "$PROMPT"
    exit 0
fi

if ! command -v agy >/dev/null 2>&1; then
    echo "ERROR: 'agy' CLI command not found in PATH" >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: 'jq' command not found in PATH" >&2
    exit 1
fi

raw_output=$(agy -p "$PROMPT" --model "$MODEL" --output-format json --mode plan --print-timeout 300s)

# Extract response JSON payload (handling possible outer JSON wrapper or markdown codeblocks)
extracted_json=$(printf "%s" "$raw_output" | jq -r '.response // empty | gsub("^```(json)?\n|```$"; "") | if type == "string" then (fromjson? // .) else . end')

if [[ -z "$extracted_json" || "$extracted_json" == "null" ]]; then
    echo "ERROR: Failed to extract valid JSON response from agy output" >&2
    echo "Raw output was: $raw_output" >&2
    exit 1
fi

PROBE_DIR="${HOME}/.local/share/agent-os/probes"
mkdir -p "$PROBE_DIR"

UTC_TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
OUTPUT_PATH="${PROBE_DIR}/${UTC_TIMESTAMP}_${GIT_COMMIT}.json"

printf "%s\n" "$extracted_json" > "$OUTPUT_PATH"

PASSED=$(printf "%s" "$extracted_json" | jq -r '.passed // 0')
FAILED=$(printf "%s" "$extracted_json" | jq -r '.failed // 0')

echo "AEP agy probe summary: commit=${GIT_COMMIT} passed=${PASSED} failed=${FAILED} expect>=${EXPECT_PASS} file=${OUTPUT_PATH}"

if [[ "$PASSED" -ge "$EXPECT_PASS" ]]; then
    exit 0
else
    exit 1
fi
