"""Demo 3 worker: batch temperature converter via the arithmetic server.

Converts a list of Celsius temperatures to Fahrenheit using the formula:
    F = C * 9/5 + 32

Delegates arithmetic to the remote server:
    1. multiply(C, 9)
    2. divide(result, 5)
    3. add 32 → but we don't have /add, so: subtract(step2, -32)

⚠️  THIS FILE CONTAINS TWO INTENTIONAL BUGS ⚠️
  Bug 1: divides by 4 instead of 5
  Bug 2: in batch conversion, appends from the wrong list (input instead of output)
"""

import json
import logging
import urllib.request

SERVER_URL = "http://127.0.0.1:9100"
LOG_FILE = "/tmp/hallucifix_demo3_worker.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("worker")


def _remote_call(op: str, a: float, b: float) -> float:
    url = f"{SERVER_URL}/{op}?a={a}&b={b}"
    log.info("Requesting: %s", url)
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    return data["result"]


def celsius_to_fahrenheit(c: float) -> float:
    """Convert a single Celsius value to Fahrenheit via remote arithmetic."""
    step1 = _remote_call("multiply", c, 9)
    # BUG 1: should divide by 5, not 4
    step2 = _remote_call("divide", step1, 4)
    result = _remote_call("subtract", step2, -32)
    log.info("celsius_to_fahrenheit(%s) = %s", c, result)
    return result


def batch_convert(temps: list[float]) -> list[float]:
    """Convert a list of Celsius temperatures to Fahrenheit."""
    results = []
    for c in temps:
        f = celsius_to_fahrenheit(c)
        # BUG 2: appends the input (c) instead of the output (f)
        results.append(c)
    return results
