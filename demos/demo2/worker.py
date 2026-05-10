"""Demo 2 worker: Fibonacci via RPC to the addition server.

⚠️  THIS FILE CONTAINS AN INTENTIONAL BUG ⚠️
In the recurrence loop the worker calls add(b, b) instead of add(a, b),
doubling b each step instead of computing the real Fibonacci sequence.
"""

import json
import logging
import urllib.request

SERVER_URL = "http://127.0.0.1:9100"
LOG_FILE = "/tmp/hallucifix_demo2_worker.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("worker")


def _remote_add(x: int, y: int) -> int:
    """Call the add server and return the sum."""
    url = f"{SERVER_URL}/add?a={x}&b={y}"
    log.info("Requesting: %s", url)
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    return data["result"]


def fibonacci(n: int) -> int:
    """Return the n-th Fibonacci number (0-indexed)."""
    if n <= 0:
        return 0
    a, b = 0, 1
    for _ in range(n - 1):
        # BUG: should be _remote_add(a, b) — uses b,b instead
        next_val = _remote_add(a, b)
        a = b
        b = next_val
    log.info("fibonacci(%d) = %d", n, b)
    return b
