"""Demo worker process - processes items from the API with a deliberate bug."""

import json
import logging
import sys
import time
import urllib.request

# Set up logging to file
logging.basicConfig(
    filename="/tmp/worker.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("worker")

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.DEBUG)
logger.addHandler(stdout_handler)


PROCESSED: list[dict] = []
API_BASE = "http://127.0.0.1:8100"


def fetch_items() -> list[dict]:
    """Fetch all items from the API."""
    try:
        req = urllib.request.Request(f"{API_BASE}/items")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.error(f"Failed to fetch items: {e}")
        return []


def process_item(item: dict) -> dict:
    """Process an item - apply discount and validate.

    BUG: The discount calculation uses wrong field name 'cost' instead of 'price'
    """
    logger.info(f"Processing item: {item['id']}")

    # BUG: references 'cost' which doesn't exist, should be 'price'
    original_price = item.get("cost", 0)
    discount = 0.1
    final_price = original_price * (1 - discount)

    result = {
        "id": item["id"],
        "name": item["name"],
        "original_price": original_price,
        "final_price": final_price,
        "discount_applied": discount,
        "processed": True,
    }
    PROCESSED.append(result)
    logger.info(f"Processed item {item['id']}: final_price={final_price}")
    return result


def get_processed() -> list[dict]:
    """Return all processed items."""
    return PROCESSED


def run_worker_loop():
    """Main worker loop - polls for new items."""
    logger.info("Worker starting polling loop")
    seen_ids: set[str] = set()

    while True:
        items = fetch_items()
        for item in items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                process_item(item)
        time.sleep(1)


def main():
    # Start debugpy if available
    try:
        import debugpy
        debugpy.listen(("127.0.0.1", 5679))
        logger.info("debugpy listening on 127.0.0.1:5679")
    except ImportError:
        logger.warning("debugpy not installed, skipping debug attach")

    logger.info("Worker process starting")
    print("Worker running", flush=True)
    run_worker_loop()


if __name__ == "__main__":
    main()
