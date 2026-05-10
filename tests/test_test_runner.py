"""Tests for hallucifix.test_runner."""

import textwrap
import tempfile
from pathlib import Path

from hallucifix.test_runner import run_pytest


def test_run_passing_test(tmp_path):
    t = tmp_path / "test_ok.py"
    t.write_text("def test_pass():\n    assert 1 + 1 == 2\n")
    result = run_pytest(str(t))
    assert result.passed
    assert result.return_code == 0


def test_run_failing_test(tmp_path):
    t = tmp_path / "test_fail.py"
    t.write_text("def test_fail():\n    assert 1 == 2\n")
    result = run_pytest(str(t))
    assert not result.passed
    assert result.return_code != 0
    assert "AssertionError" in result.stdout or "assert 1 == 2" in result.stdout
