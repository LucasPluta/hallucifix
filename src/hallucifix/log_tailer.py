"""Tail log files produced by monitored processes."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class LogTailer:
    """Incrementally read new content appended to a log file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._offset: int = 0

    def start(self) -> None:
        """Seek to the end of the file (ignore pre-existing content)."""
        if self.path.exists():
            self._offset = self.path.stat().st_size
        else:
            self._offset = 0

    def collect(self) -> str:
        """Return all text written since the last call to start/collect."""
        if not self.path.exists():
            return ""
        size = self.path.stat().st_size
        if size <= self._offset:
            return ""
        with self.path.open("r", errors="replace") as fh:
            fh.seek(self._offset)
            data = fh.read()
        self._offset = size
        return data
