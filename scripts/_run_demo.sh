#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  _run_demo.sh – shared E2E demo runner for hallucifix
#
#  Usage (not called directly — use run_demo1/2/3.sh):
#    ./_run_demo.sh <demo_dir> <template_file> <description>
#
#  Required env vars:
#    OPENAI_API_KEY   – your OpenAI (or compatible) API key
#
#  Optional env vars:
#    MODEL            – LLM model name  (default: gpt-4o)
#    OPENAI_BASE_URL  – custom API base  (for Azure / local)
#    MAX_ITERATIONS   – fix attempts     (default: 5)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DEMO_DIR="$1"
TEMPLATE="$2"
DESCRIPTION="$3"
DEMO_NAME="$(basename "$DEMO_DIR")"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Pre-flight checks ──────────────────────────────────────────
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: OPENAI_API_KEY is not set."
    echo "  export OPENAI_API_KEY=sk-..."
    exit 1
fi

# ── Virtualenv & install ───────────────────────────────────────
if [[ ! -d .venv ]]; then
    echo "=== Creating virtual environment ==="
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -e ".[dev]" --quiet 2>/dev/null

# ── Reset the buggy worker from template ───────────────────────
cp "$TEMPLATE" "$DEMO_DIR/worker.py"

# ── Clean up old logs ──────────────────────────────────────────
rm -f "/tmp/hallucifix_${DEMO_NAME}_server.log" "/tmp/hallucifix_${DEMO_NAME}_worker.log"
touch "/tmp/hallucifix_${DEMO_NAME}_server.log" "/tmp/hallucifix_${DEMO_NAME}_worker.log"

# ── Kill any leftover processes on port 9100 ───────────────────
lsof -ti:9100 2>/dev/null | xargs kill 2>/dev/null || true
sleep 0.5

# ── Suppress debugpy warnings ─────────────────────────────────
export PYDEVD_DISABLE_FILE_VALIDATION=1

# ── Start the server ──────────────────────────────────────────
echo "=== Starting server (port 9100) ==="
python "$DEMO_DIR/server.py" &
SERVER_PID=$!

cleanup() {
    echo ""
    echo "=== Cleaning up ==="
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ── Wait for server ────────────────────────────────────────────
echo "=== Waiting for server ==="
for i in $(seq 1 20); do
    if curl -sf http://127.0.0.1:9100/health >/dev/null 2>&1; then
        echo "Server is up."
        break
    fi
    if [[ $i -eq 20 ]]; then
        echo "ERROR: server did not start in time."
        exit 1
    fi
    sleep 0.3
done

# ── Banner ─────────────────────────────────────────────────────
MODEL="${MODEL:-gpt-4o}"
MAX_ITER="${MAX_ITERATIONS:-5}"

echo ""
echo "┌──────────────────────────────────────────────────────────┐"
echo "│  hallucifix E2E · ${DEMO_NAME}                                │"
echo "├──────────────────────────────────────────────────────────┤"
printf "│  %-57s│\n" "$DESCRIPTION"
echo "│                                                          │"
printf "│  model: %-49s│\n" "$MODEL"
printf "│  max iterations: %-40s│\n" "$MAX_ITER"
echo "└──────────────────────────────────────────────────────────┘"
echo ""

# ── Run hallucifix ─────────────────────────────────────────────
EXTRA_ARGS=()
if [[ -n "${OPENAI_BASE_URL:-}" ]]; then
    EXTRA_ARGS+=(--base-url "$OPENAI_BASE_URL")
fi

hallucifix "$DEMO_DIR/test_demo.py" \
    -p "server:5678:/tmp/hallucifix_${DEMO_NAME}_server.log" \
    --project-root "$DEMO_DIR" \
    --max-iterations "$MAX_ITER" \
    --model "$MODEL" \
    "${EXTRA_ARGS[@]}" \
    -v

EXIT_CODE=$?

# ── Show result ────────────────────────────────────────────────
echo ""
echo "=== Final state of $DEMO_DIR/worker.py ==="
cat "$DEMO_DIR/worker.py"

exit $EXIT_CODE
