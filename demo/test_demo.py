"""Integration tests that exercise the demo server + worker.

The server must already be running (port 9100).
The worker's compute_square function is imported directly so that
hallucifix patches to worker.py take effect on the next pytest run
without needing to restart the worker process.
"""

import importlib
import json
import sys
import urllib.request
from pathlib import Path

# Ensure the demo directory is on sys.path so we can import worker
_demo_dir = str(Path(__file__).resolve().parent)
if _demo_dir not in sys.path:
    sys.path.insert(0, _demo_dir)

import worker  # noqa: E402  (our demo module)


def _reload_worker():
    """Re-import worker.py so disk-level patches are picked up."""
    importlib.reload(worker)


def test_square_of_5():
    """5² should be 25."""
    _reload_worker()
    assert worker.compute_square(5) == 25


def test_square_of_3():
    """3² should be 9."""
    _reload_worker()
    assert worker.compute_square(3) == 9


def test_square_of_0():
    """0² should be 0."""
    _reload_worker()
    assert worker.compute_square(0) == 0
