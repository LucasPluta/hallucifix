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
    url = f"{SERVER_URL}/multiply?a={n}&b={n}"
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
