"""Tests for hallucifix.config."""

import json
import tempfile
from pathlib import Path

from hallucifix.config import HallucifixConfig, ProcessConfig


def test_process_config_from_cli_string():
    pc = ProcessConfig.from_cli_string("api:5678:/tmp/api.log")
    assert pc.name == "api"
    assert pc.debugpy_port == 5678
    assert pc.log_file == "/tmp/api.log"


def test_process_config_from_cli_string_no_logfile():
    pc = ProcessConfig.from_cli_string("worker:5679")
    assert pc.name == "worker"
    assert pc.debugpy_port == 5679
    assert pc.log_file == ""


def test_config_from_file():
    data = {
        "test_path": "tests/",
        "max_iterations": 3,
        "model": "gpt-4o",
        "processes": [
            {"name": "api", "debugpy_port": 5678, "log_file": "/tmp/a.log"},
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        f.flush()
        cfg = HallucifixConfig.from_file(f.name)

    assert cfg.test_path == "tests/"
    assert cfg.max_fix_iterations == 3
    assert len(cfg.processes) == 1
    assert cfg.processes[0].name == "api"
