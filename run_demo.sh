#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# hallucifix demo runner
#
# Starts two buggy processes, runs hallucifix to detect and fix test failures.
# Usage: ./run_demo.sh [--no-fix]
#        --no-fix: just run the test without hallucifix (to see it fail)
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Config
API_PORT=8100
API_PID=""
WORKER_PID=""
LOG_DIR="/tmp"

cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"
    [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null && echo "  Stopped API server (PID $API_PID)"
    [[ -n "$WORKER_PID" ]] && kill "$WORKER_PID" 2>/dev/null && echo "  Stopped worker (PID $WORKER_PID)"
    rm -f "$LOG_DIR/api-server.log" "$LOG_DIR/worker.log"
}
trap cleanup EXIT

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║            hallucifix demo                               ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# --- Check prerequisites ---
echo -e "${YELLOW}[1/5] Checking prerequisites...${NC}"

# Find python (prefer python3)
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo -e "${RED}Error: python not found${NC}"
    exit 1
fi

# Install hallucifix + deps if needed
if ! $PYTHON -c "import hallucifix" 2>/dev/null; then
    echo "  Installing hallucifix..."
    $PYTHON -m pip install -e "$PROJECT_ROOT" --quiet --break-system-packages 2>/dev/null || \
        $PYTHON -m pip install -e "$PROJECT_ROOT" --quiet
fi

# Ensure pytest-json-report is available
if ! $PYTHON -c "import pytest_jsonreport" 2>/dev/null; then
    $PYTHON -m pip install pytest-json-report --quiet --break-system-packages 2>/dev/null || \
        $PYTHON -m pip install pytest-json-report --quiet
fi

echo -e "  ${GREEN}✓ All prerequisites met${NC}"

# --- Clear old logs ---
echo -e "${YELLOW}[2/5] Clearing old logs...${NC}"
> "$LOG_DIR/api-server.log"
> "$LOG_DIR/worker.log"
echo -e "  ${GREEN}✓ Logs cleared${NC}"

# --- Start API server ---
echo -e "${YELLOW}[3/5] Starting API server on port $API_PORT...${NC}"
$PYTHON "$PROJECT_ROOT/demo/api_server.py" "$API_PORT" &
API_PID=$!
sleep 1

# Verify it's running
if ! kill -0 "$API_PID" 2>/dev/null; then
    echo -e "${RED}Error: API server failed to start${NC}"
    exit 1
fi

# Wait for it to be ready
for i in {1..10}; do
    if curl -s "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done
echo -e "  ${GREEN}✓ API server running (PID $API_PID)${NC}"

# --- Start worker ---
echo -e "${YELLOW}[4/5] Starting worker process...${NC}"
$PYTHON "$PROJECT_ROOT/demo/worker.py" &
WORKER_PID=$!
sleep 1

if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    echo -e "${RED}Error: Worker failed to start${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓ Worker running (PID $WORKER_PID)${NC}"

# --- Run hallucifix or just the test ---
echo -e "${YELLOW}[5/5] Running test...${NC}"
echo ""

if [[ "${1:-}" == "--no-fix" ]]; then
    echo -e "${BLUE}Mode: test-only (no AI fixing)${NC}"
    echo "Running: pytest demo/test_integration.py -v"
    echo ""
    $PYTHON -m pytest "$PROJECT_ROOT/demo/test_integration.py" -v --tb=short || true
    echo ""
    echo -e "${RED}Tests failed as expected (bugs are present).${NC}"
    echo -e "Run without --no-fix to let hallucifix attempt AI-powered fixes."
else
    echo -e "${BLUE}Mode: hallucifix AI fix loop${NC}"
    echo ""

    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
        echo -e "${YELLOW}WARNING: OPENAI_API_KEY is not set.${NC}"
        echo -e "  Set it to enable AI-powered fixing:"
        echo -e "  export OPENAI_API_KEY='sk-...'"
        echo ""
        echo -e "  Running test to show failures (fix loop will fail without API key):"
        echo ""
    fi

    hallucifix "$PROJECT_ROOT/demo/test_integration.py" \
        -p "api-server:5678:$LOG_DIR/api-server.log" \
        -p "worker:5679:$LOG_DIR/worker.log" \
        --max-iterations 5 \
        --project-root "$PROJECT_ROOT" \
        --model "${HALLUCIFIX_MODEL:-gpt-4o}"

    EXIT_CODE=$?
    echo ""
    if [[ $EXIT_CODE -eq 0 ]]; then
        echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║  SUCCESS: hallucifix fixed the bugs!                     ║${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
        echo ""
        echo "Check the diffs:"
        echo "  git diff demo/"
    else
        echo -e "${RED}╔══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║  FAILED: Could not fix within max iterations            ║${NC}"
        echo -e "${RED}╚══════════════════════════════════════════════════════════╝${NC}"
    fi
fi

echo ""
echo -e "${YELLOW}Logs available at:${NC}"
echo "  API server: $LOG_DIR/api-server.log"
echo "  Worker:     $LOG_DIR/worker.log"
