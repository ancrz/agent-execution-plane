#!/usr/bin/env bash
# =============================================================================
# test_setup_idempotency.sh — Automated Idempotency & Setup Verification
# Tests setup.sh --check, idempotency across multiple runs, Python 3.14 venv,
# Go diagnostic probes, and FastMCP auto-plug validation.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

GREEN="\033[0;32m"
RED="\033[0;31m"
BLUE="\033[0;34m"
NC="\033[0m"

TESTS_PASSED=0
TESTS_FAILED=0

assert_ok() {
    local desc="$1"
    shift
    echo -e "${BLUE}[TEST]${NC} $desc..."
    if "$@"; then
        echo -e "${GREEN}[PASS]${NC} $desc"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${RED}[FAIL]${NC} $desc"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

echo "=========================================================="
echo "  Running AEP Setup Idempotency & Verification Suite"
echo "=========================================================="

cd "$PROJECT_ROOT"

# Test 1: setup.sh --check returns 0 on healthy environment
assert_ok "setup.sh --check execution and exit code 0" ./scripts/setup.sh --check

# Test 2: setup.sh runs successfully
assert_ok "setup.sh full provisioning run #1" ./scripts/setup.sh

# Test 3: Sequential run of setup.sh is idempotent and succeeds without error
assert_ok "setup.sh full provisioning run #2 (idempotency verification)" ./scripts/setup.sh

# Test 4: Verify Python version in .venv is Python 3.14.*
test_python_version() {
    local py_bin="$PROJECT_ROOT/.venv/bin/python"
    [[ -x "$py_bin" ]] || return 1
    local ver
    ver="$("$py_bin" --version)"
    echo "Detected: $ver"
    [[ "$ver" =~ ^Python\ 3\.14 ]]
}
assert_ok "Hermetic virtual environment uses Python 3.14.*" test_python_version

# Test 5: Verify Go diagnostic probes execute cleanly
test_go_probes() {
    local probe_dir="$HOME/.local/share/agent-os/bin"
    [[ -x "$probe_dir/socket-monitor" ]] || return 1
    [[ -x "$probe_dir/fd-rescuer" ]] || return 1
    [[ -x "$probe_dir/landlock-guard" ]] || return 1
    
    local sm_out
    sm_out="$("$probe_dir/socket-monitor")"
    echo "$sm_out" | grep -q "total_sockets" || return 1
    
    local fd_out
    fd_out="$("$probe_dir/fd-rescuer" $$)"
    echo "$fd_out" | grep -q "total_fd" || return 1

    local lg_out
    lg_out="$("$probe_dir/landlock-guard")"
    echo "$lg_out" | grep -q "landlock-guard" || return 1
    return 0
}
assert_ok "Go diagnostic probes execute cleanly (socket-monitor, fd-rescuer, landlock-guard)" test_go_probes

# Test 6: Verify aep-sync.sh --check passes cleanly
assert_ok "aep-sync.sh --check FastMCP validation" ./scripts/aep-sync.sh --check

echo "=========================================================="
echo "  Test Summary: $TESTS_PASSED passed, $TESTS_FAILED failed"
echo "=========================================================="

if [[ $TESTS_FAILED -eq 0 ]]; then
    echo -e "${GREEN}ALL IDEMPOTENCY AND PROVISIONING TESTS PASSED.${NC}"
    exit 0
else
    echo -e "${RED}SOME TESTS FAILED.${NC}"
    exit 1
fi
