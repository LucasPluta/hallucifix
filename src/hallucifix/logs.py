"""Log collection from running processes via multiple strategies."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO


@dataclass
class LogCollector:
    """Collects logs from multiple sources during a test run."""

    process_names: list[str] = field(default_factory=list)
    log_files: list[Path] = field(default_factory=list)
    _captured: dict[str, list[str]] = field(default_factory=dict)
    _watchers: list[threading.Thread] = field(default_factory=list)
    _stop_event: threading.Event = field(default_factory=threading.Event)

    def add_log_file(self, name: str, path: Path) -> None:
        """Register a log file to watch."""
        self.process_names.append(name)
        self.log_files.append(path)
        self._captured[name] = []

    def start(self) -> None:
        """Start tailing all registered log files."""
        self._stop_event.clear()
        for name, path in zip(self.process_names, self.log_files):
            t = threading.Thread(
                target=self._tail_file, args=(name, path), daemon=True
            )
            t.start()
            self._watchers.append(t)

    def stop(self) -> None:
        """Stop all log watchers."""
        self._stop_event.set()
        for t in self._watchers:
            t.join(timeout=2.0)
        self._watchers.clear()

    def get_logs(self, name: str) -> list[str]:
        """Get captured logs for a named process."""
        return self._captured.get(name, [])

    def get_all_logs(self) -> dict[str, list[str]]:
        """Get all captured logs."""
        return dict(self._captured)

    def get_combined_log_text(self, max_lines: int = 500) -> str:
        """Get a combined text representation of all logs, truncated."""
        parts = []
        for name, lines in self._captured.items():
            tail = lines[-max_lines:] if len(lines) > max_lines else lines
            parts.append(f"=== {name} (last {len(tail)} lines) ===\n")
            parts.append("\n".join(tail))
            parts.append("\n")
        return "\n".join(parts)

    def _tail_file(self, name: str, path: Path) -> None:
        """Tail a log file, collecting new lines."""
        # Wait for file to exist
        for _ in range(50):
            if path.exists():
                break
            time.sleep(0.1)

        if not path.exists():
            self._captured[name].append(f"[hallucifix] Log file not found: {path}")
            return

        with open(path, "r") as f:
            # Seek to end to only get new content
            f.seek(0, 2)
            while not self._stop_event.is_set():
                line = f.readline()
                if line:
                    self._captured[name].append(line.rstrip("\n"))
                else:
                    time.sleep(0.05)


@dataclass
class StdoutCollector:
    """Collect stdout/stderr from subprocess handles."""

    _captured: dict[str, list[str]] = field(default_factory=dict)
    _threads: list[threading.Thread] = field(default_factory=list)
    _stop_event: threading.Event = field(default_factory=threading.Event)

    def attach_stream(self, name: str, stream: IO[str]) -> None:
        """Start collecting from a stream in a background thread."""
        self._captured[name] = []
        t = threading.Thread(
            target=self._read_stream, args=(name, stream), daemon=True
        )
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=2.0)

    def get_output(self, name: str) -> list[str]:
        return self._captured.get(name, [])

    def get_combined_output(self, max_lines: int = 500) -> str:
        parts = []
        for name, lines in self._captured.items():
            tail = lines[-max_lines:] if len(lines) > max_lines else lines
            parts.append(f"=== {name} (last {len(tail)} lines) ===\n")
            parts.append("\n".join(tail))
            parts.append("\n")
        return "\n".join(parts)

    def _read_stream(self, name: str, stream: IO[str]) -> None:
        try:
            for line in stream:
                if self._stop_event.is_set():
                    break
                self._captured[name].append(line.rstrip("\n"))
        except (ValueError, OSError):
            pass


def collect_process_logs_via_procfs(pid: int) -> str | None:
    """Try to read recent output from /proc/{pid}/fd/1 (Linux only)."""
    stdout_path = f"/proc/{pid}/fd/1"
    if os.path.exists(stdout_path):
        try:
            result = subprocess.run(
                ["tail", "-n", "200", stdout_path],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout
        except (subprocess.TimeoutExpired, PermissionError):
            pass
    return None
