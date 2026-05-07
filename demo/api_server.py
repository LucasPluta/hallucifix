"""Demo API server - a simple HTTP server with a deliberate bug."""

import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# Set up logging to file
logging.basicConfig(
    filename="/tmp/api-server.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("api-server")

# Also log to stdout
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.DEBUG)
logger.addHandler(stdout_handler)


# In-memory "database"
ITEMS: dict[str, dict] = {}


class APIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        logger.info(f"GET {self.path}")

        if self.path == "/items":
            self._respond(200, list(ITEMS.values()))
        elif self.path.startswith("/items/"):
            item_id = self.path.split("/items/")[1]
            item = ITEMS.get(item_id)
            if item:
                self._respond(200, item)
            else:
                self._respond(404, {"error": "not found"})
        elif self.path == "/health":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        logger.info(f"POST {self.path}")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if self.path == "/items":
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._respond(400, {"error": "invalid json"})
                return

            item_id = data.get("id", str(len(ITEMS) + 1))
            # BUG: price calculation is wrong - multiplies by 0.1 instead of 1.0
            price = data.get("price", 0) * 0.1
            item = {
                "id": item_id,
                "name": data.get("name", ""),
                "price": price,
                "in_stock": True,
            }
            ITEMS[item_id] = item
            logger.info(f"Created item: {item}")
            self._respond(201, item)
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, status: int, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        logger.debug(f"HTTP: {format % args}")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8100

    # Start debugpy if available
    try:
        import debugpy
        debugpy.listen(("127.0.0.1", 5678))
        logger.info(f"debugpy listening on 127.0.0.1:5678")
    except ImportError:
        logger.warning("debugpy not installed, skipping debug attach")

    server = HTTPServer(("127.0.0.1", port), APIHandler)
    logger.info(f"API server starting on port {port}")
    print(f"API server running on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
