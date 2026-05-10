"""Demo 4 server: job queue HTTP API (port 9100).

Provides:
  POST /enqueue   body={"value": N}      → {"job_id": int}
  GET  /status                            → {"counts": {status: n}}
  GET  /results                           → {"results": [...]}
  GET  /health                            → {"status": "ok"}

This server is CORRECT — the bugs are in worker.py.
"""

import json
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

LOG_FILE = "/tmp/hallucifix_demo4_server.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [server] %(message)s",
)
log = logging.getLogger("server")

# Import models
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import models  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json({"status": "ok"})
        elif self.path == "/status":
            counts = models.count_by_status()
            self._json({"counts": counts})
        elif self.path == "/results":
            results = models.get_all_results()
            self._json({"results": results})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/enqueue":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            value = body.get("value", 0)
            payload = json.dumps({"op": "transform", "value": value})
            job_id = models.enqueue_job(payload)
            self._json({"job_id": job_id})
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    models.init_db()
    server = HTTPServer(("127.0.0.1", port), Handler)
    log.info("Server starting on port %d", port)
    print(f"Server listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()
