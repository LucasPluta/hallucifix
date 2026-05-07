"""Integration test that exercises both the API server and worker.

This test will FAIL because:
1. The API server has a bug: it multiplies price by 0.1 instead of 1.0
2. The worker has a bug: it reads item['cost'] instead of item['price']

hallucifix should detect these failures and fix the source code.
"""

import json
import time
import urllib.request

API_BASE = "http://127.0.0.1:8100"


def _post_json(path: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _get_json(path: str) -> dict | list:
    req = urllib.request.Request(f"{API_BASE}{path}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


class TestItemPipeline:
    """Tests the full item creation → processing pipeline."""

    def test_create_item_preserves_price(self):
        """Creating an item should store the correct price."""
        item = _post_json("/items", {"id": "test1", "name": "Widget", "price": 29.99})

        assert item["name"] == "Widget"
        # BUG TRIGGER: API multiplies price by 0.1, so this will be 2.999 instead of 29.99
        assert item["price"] == 29.99, f"Expected price 29.99, got {item['price']}"

    def test_worker_processes_item_with_correct_price(self):
        """Worker should process items and apply a 10% discount to the price."""
        # Create an item via the API
        created = _post_json("/items", {"id": "test2", "name": "Gadget", "price": 100.0})

        # The worker imports process_item from worker module - test it directly
        import sys
        sys.path.insert(0, "demo")
        from worker import process_item

        # Simulate what the worker does: process the item as returned by the API
        result = process_item(created)

        # Worker should have read price=100.0 (but bug reads 'cost' which doesn't exist → 0)
        # Then applied 10% discount: 100.0 * 0.9 = 90.0
        assert result["original_price"] == 100.0, (
            f"Expected original_price=100.0, got {result['original_price']}"
        )
        assert result["final_price"] == 90.0, (
            f"Expected final_price=90.0, got {result['final_price']}"
        )

    def test_health_check(self):
        """Sanity check that the API is running."""
        result = _get_json("/health")
        assert result == {"status": "ok"}
