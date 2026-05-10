"""Tests for hallucifix.log_tailer."""

import tempfile
from pathlib import Path

from hallucifix.log_tailer import LogTailer


def test_tailer_collects_new_content():
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("old stuff\n")
        f.flush()

        tailer = LogTailer(f.name)
        tailer.start()  # should skip existing content

        f.write("new line 1\n")
        f.write("new line 2\n")
        f.flush()

    content = tailer.collect()
    assert "new line 1" in content
    assert "new line 2" in content
    assert "old stuff" not in content


def test_tailer_missing_file():
    tailer = LogTailer("/tmp/nonexistent_hallucifix_test.log")
    tailer.start()
    assert tailer.collect() == ""
