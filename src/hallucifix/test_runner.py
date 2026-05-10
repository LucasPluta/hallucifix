"""Run pytest and capture results."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Outcome of a single pytest invocation."""

    passed: bool
    return_code: int
    stdout: str
    stderr: str


def run_pytest(
    test_path: str,
    extra_args: list[str] | None = None,
    timeout: int = 120,
) -> TestResult:
    """Execute pytest in a subprocess and return the result."""
    cmd = ["python", "-m", "pytest", test_path, "-v", "--tb=long"]
    if extra_args:
        cmd.extend(extra_args)

    log.info("Running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return TestResult(
            passed=False,
            return_code=-1,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        )

    return TestResult(
        passed=proc.returncode == 0,
        return_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
