#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  run_demo.sh – full E2E demo of hallucifix
#
#  Starts a math server + a buggy worker, then lets hallucifix
#  detect the test failure and ask an LLM to fix it.
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

cd "$(dirname "$0")"

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

# ── Make sure the worker has the bug (reset from git or template) ──
# Re-write the buggy line so the demo is repeatable.
cat > demo/worker.py <<'WORKER_EOF'
"""Demo worker – exposes /square by calling the math server's /multiply.

⚠️  THIS FILE CONTAINS AN INTENTIONAL BUG ⚠️
The worker asks the server to compute  n × (n + 1)  instead of  n × n.
hallucifix should detect the test failure and ask the LLM to fix it.
"""

import json
import logging
import sys
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

SERVER_URL = "http://127.0.0.1:9100"
LOG_FILE = "/tmp/hallucifix_demo_worker.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("worker")

# Optional debugpy
try:
    import os
    if os.environ.get("ENABLE_DEBUGPY"):
        import debugpy
        debugpy.listen(("127.0.0.1", 5679))
        log.info("debugpy listening on 5679")
except Exception:
    pass


def compute_square(n: int) -> int:
    """Return n² by delegating to the multiply server."""
    # BUG: passes n+1 instead of n as the second factor
    url = f"{SERVER_URL}/multiply?a={n}&b={n + 1}"
    log.info("Requesting: %s", url)
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    log.info("Got result: %s", data)
    return data["result"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/square":
            n = int(params["n"][0])
            result = compute_square(n)
            self._json({"result": result})
        elif parsed.path == "/health":
            self._json({"status": "ok"})
        else:
            self.send_error(404)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info(fmt, *args)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9101
    server = HTTPServer(("127.0.0.1", port), Handler)
    log.info("Worker starting on port %d", port)
    print(f"Worker listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()
WORKER_EOF

# ── Clean up old logs ──────────────────────────────────────────
rm -f /tmp/hallucifix_demo_server.log /tmp/hallucifix_demo_worker.log
touch /tmp/hallucifix_demo_server.log /tmp/hallucifix_demo_worker.log

# ── Kill any leftover demo processes on the same ports ─────────
lsof -ti:9100 2>/dev/null | xargs kill 2>/dev/null || true
sleep 0.5

# ── Suppress debugpy frozen-module warnings ────────────────────
export PYDEVD_DISABLE_FILE_VALIDATION=1

# ── Start the math server (the worker is imported directly by tests) ──
echo "=== Starting math server (port 9100) ==="
python demo/server.py &
SERVER_PID=$!

cleanup() {
    echo ""
    echo "=== Cleaning up background processes ==="
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ── Wait for the server to respond ─────────────────────────────
echo "=== Waiting for server to become ready ==="
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

# ── Show what's about to happen ────────────────────────────────
echo ""
echo "┌──────────────────────────────────────────────────────────┐"
echo "│                 hallucifix E2E demo                      │"
echo "├──────────────────────────────────────────────────────────┤"
echo "│  server.py  → correct multiply service (port 9100)      │"
echo "│  worker.py  → BUGGY compute_square function              │"
echo "│                                                          │"
echo "│  Bug: worker passes  n*(n+1) instead of n*n             │"
echo "│  hallucifix will run the tests, detect the failure,      │"
echo "│  send logs + traceback to the LLM, apply the fix,       │"
echo "│  and re-run until green.                                 │"
echo "└──────────────────────────────────────────────────────────┘"
echo ""

# ── Run hallucifix ─────────────────────────────────────────────
MODEL="${MODEL:-gpt-4o}"
MAX_ITER="${MAX_ITERATIONS:-5}"

EXTRA_ARGS=()
if [[ -n "${OPENAI_BASE_URL:-}" ]]; then
    EXTRA_ARGS+=(--base-url "$OPENAI_BASE_URL")
fi

echo "=== Running hallucifix (model=$MODEL, max_iterations=$MAX_ITER) ==="
echo ""

hallucifix demo/test_demo.py \
    -p "server:5678:/tmp/hallucifix_demo_server.log" \
    --project-root demo \
    --max-iterations "$MAX_ITER" \
    --model "$MODEL" \
    "${EXTRA_ARGS[@]}" \
    -v

EXIT_CODE=$?

# ── Show the fix that was applied ──────────────────────────────
echo ""
echo "=== Final state of demo/worker.py ==="
cat demo/worker.py

exit $EXIT_CODE
