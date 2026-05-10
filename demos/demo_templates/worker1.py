"""Demo 1 worker: square calculator via the multiply server.

⚠️  THIS FILE CONTAINS AN INTENTIONAL BUG ⚠️
Passes n+1 instead of n as the second factor → n*(n+1) instead of n².
"""

import json
import logging
import urllib.request

SERVER_URL = "http://127.0.0.1:9100"
LOG_FILE = "/tmp/hallucifix_demo1_worker.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("worker")


def compute_square(n: int) -> int:
    """Return n² by delegating to the multiply server."""
    # BUG: passes n+1 instead of n as the second factor
    url = f"{SERVER_URL}/multiply?a={n}&b={n + 1}"
    log.info("Requesting: %s", url)
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    log.info("Got result: %s", data)
    return data["result"]
