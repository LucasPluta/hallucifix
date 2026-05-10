"""Tests for demo 1: square calculator."""

import importlib
import sys
from pathlib import Path

_demo_dir = str(Path(__file__).resolve().parent)
if _demo_dir not in sys.path:
    sys.path.insert(0, _demo_dir)

import worker  # noqa: E402


def _reload():
    importlib.reload(worker)


def test_square_of_5():
    _reload()
    assert worker.compute_square(5) == 25


def test_square_of_3():
    _reload()
    assert worker.compute_square(3) == 9


def test_square_of_0():
    _reload()
    assert worker.compute_square(0) == 0
