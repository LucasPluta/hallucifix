"""Tests for demo 3: temperature converter."""

import importlib
import sys
from pathlib import Path

_demo_dir = str(Path(__file__).resolve().parent)
if _demo_dir not in sys.path:
    sys.path.insert(0, _demo_dir)

import worker  # noqa: E402


def _reload():
    importlib.reload(worker)


def test_boiling_point():
    """100°C → 212°F"""
    _reload()
    assert worker.celsius_to_fahrenheit(100) == 212.0


def test_freezing_point():
    """0°C → 32°F"""
    _reload()
    assert worker.celsius_to_fahrenheit(0) == 32.0


def test_body_temp():
    """37°C → 98.6°F"""
    _reload()
    result = worker.celsius_to_fahrenheit(37)
    assert abs(result - 98.6) < 0.01, f"Expected 98.6, got {result}"


def test_batch_convert():
    """Batch conversion of [0, 100] → [32.0, 212.0]"""
    _reload()
    result = worker.batch_convert([0, 100])
    assert result == [32.0, 212.0], f"Expected [32.0, 212.0], got {result}"
