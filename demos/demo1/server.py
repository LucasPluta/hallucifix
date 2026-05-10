"""Demo 1 server: multiplication service (port 9100).

Provides /multiply?a=X&b=Y → {"result": X*Y}
This server is correct — the bug is in the worker.
"""

import json
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

LOG_FILE = "/tmp/hallucifix_demo1_server.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("server")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/multiply":
            a = int(params["a"][0])
            b = int(params["b"][0])
            result = a * b
            log.info("multiply(%d, %d) = %d", a, b, result)
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    server = HTTPServer(("127.0.0.1", port), Handler)
    log.info("Server starting on port %d", port)
    print(f"Server listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()
