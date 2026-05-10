"""Tests for demo 2: Fibonacci via RPC."""

import importlib
import sys
from pathlib import Path

_demo_dir = str(Path(__file__).resolve().parent)
if _demo_dir not in sys.path:
    sys.path.insert(0, _demo_dir)

import worker  # noqa: E402


def _reload():
    importlib.reload(worker)


def test_fib_0():
    _reload()
    assert worker.fibonacci(0) == 0


def test_fib_1():
    _reload()
    assert worker.fibonacci(1) == 1


def test_fib_6():
    """fib(6) = 8"""
    _reload()
    assert worker.fibonacci(6) == 8


def test_fib_10():
    """fib(10) = 55"""
    _reload()
    assert worker.fibonacci(10) == 55
