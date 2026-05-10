"""Tests for hallucifix.patcher."""

import tempfile
from pathlib import Path

import pytest

from hallucifix.patcher import apply_patch


def test_apply_patch_basic(tmp_path):
    src = tmp_path / "app.py"
    src.write_text("def greet():\n    return 'hello'\n")

    patch = {
        "file": "app.py",
        "edits": [{"search": "return 'hello'", "replace": "return 'hi'"}],
    }
    diff = apply_patch(patch, project_root=str(tmp_path))

    assert src.read_text() == "def greet():\n    return 'hi'\n"
    assert "- " in diff and "+ " in diff


def test_apply_patch_missing_search(tmp_path):
    src = tmp_path / "app.py"
    src.write_text("x = 1\n")

    patch = {
        "file": "app.py",
        "edits": [{"search": "NOPE", "replace": "YES"}],
    }
    with pytest.raises(ValueError, match="not found"):
        apply_patch(patch, project_root=str(tmp_path))
