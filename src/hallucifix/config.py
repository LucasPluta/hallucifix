"""Configuration models for hallucifix."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProcessConfig:
    """Configuration for a single monitored process."""

    name: str
    debugpy_port: int
    log_file: str = ""

    @classmethod
    def from_cli_string(cls, spec: str) -> ProcessConfig:
        """Parse ``name:port:logfile`` CLI shorthand."""
        parts = spec.split(":")
        if len(parts) < 2:
            raise ValueError(
                f"Process spec must be 'name:port[:logfile]', got {spec!r}"
            )
        name = parts[0]
        port = int(parts[1])
        log_file = parts[2] if len(parts) > 2 else ""
        return cls(name=name, debugpy_port=port, log_file=log_file)


@dataclass
class HallucifixConfig:
    """Top-level configuration."""

    test_path: str
    processes: list[ProcessConfig] = field(default_factory=list)
    project_root: str = "."
    max_fix_iterations: int = 5
    model: str = "gpt-4o"
    timeout: int = 120
    base_url: str | None = None
    extra_pytest_args: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str | Path) -> HallucifixConfig:
        """Load config from a JSON file."""
        raw = json.loads(Path(path).read_text())
        processes = [
            ProcessConfig(**p) for p in raw.pop("processes", [])
        ]
        # Normalise key names (JSON uses max_iterations, dataclass uses max_fix_iterations)
        if "max_iterations" in raw:
            raw["max_fix_iterations"] = raw.pop("max_iterations")
        return cls(processes=processes, **raw)
