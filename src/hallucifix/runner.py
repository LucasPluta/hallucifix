"""Test runner that captures structured failure information."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestFailure:
    """Structured representation of a test failure."""

    test_name: str
    file_path: str
    line_number: int | None
    error_type: str
    error_message: str
    traceback: str
    stdout: str = ""
    stderr: str = ""


@dataclass
class TestResult:
    """Result of a test run."""

    passed: bool
    total: int = 0
    failed: int = 0
    errors: int = 0
    failures: list[TestFailure] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    raw_output: str = ""


def run_pytest(
    test_path: str,
    *,
    python_exe: str | None = None,
    extra_args: list[str] | None = None,
    timeout: float = 120.0,
    cwd: str | None = None,
) -> TestResult:
    """Run pytest and return structured results.

    Uses --tb=long and --json-report for detailed failure info.
    """
    python = python_exe or sys.executable
    json_report_file = tempfile.mktemp(suffix=".json")

    cmd = [
        python, "-m", "pytest",
        test_path,
        "-v",
        "--tb=long",
        f"--json-report",
        f"--json-report-file={json_report_file}",
    ]
    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return TestResult(
            passed=False,
            raw_output="Test execution timed out",
            failures=[TestFailure(
                test_name=test_path,
                file_path=test_path,
                line_number=None,
                error_type="TimeoutError",
                error_message=f"Test timed out after {timeout}s",
                traceback="",
            )],
        )

    # Try to parse JSON report
    failures = []
    json_report = None
    json_path = Path(json_report_file)
    if json_path.exists():
        try:
            with open(json_path) as f:
                json_report = json.load(f)
            json_path.unlink()
        except (json.JSONDecodeError, OSError):
            pass

    if json_report:
        summary = json_report.get("summary", {})
        tests = json_report.get("tests", [])

        for test in tests:
            if test.get("outcome") in ("failed", "error"):
                call_info = test.get("call", {})
                longrepr = call_info.get("longrepr", "")
                crash = call_info.get("crash", {})

                failures.append(TestFailure(
                    test_name=test.get("nodeid", "unknown"),
                    file_path=crash.get("path", test.get("nodeid", "").split("::")[0]),
                    line_number=crash.get("lineno"),
                    error_type=call_info.get("crash", {}).get("message", "AssertionError"),
                    error_message=crash.get("message", ""),
                    traceback=longrepr if isinstance(longrepr, str) else str(longrepr),
                    stdout=test.get("setup", {}).get("stdout", "") + call_info.get("stdout", ""),
                    stderr=test.get("setup", {}).get("stderr", "") + call_info.get("stderr", ""),
                ))

        return TestResult(
            passed=summary.get("failed", 0) == 0 and summary.get("error", 0) == 0,
            total=summary.get("total", 0),
            failed=summary.get("failed", 0),
            errors=summary.get("error", 0),
            failures=failures,
            stdout=result.stdout,
            stderr=result.stderr,
            duration=json_report.get("duration", 0.0),
            raw_output=result.stdout + result.stderr,
        )

    # Fallback: parse from exit code and raw output
    return TestResult(
        passed=result.returncode == 0,
        failures=_parse_failures_from_output(result.stdout + result.stderr) if result.returncode != 0 else [],
        stdout=result.stdout,
        stderr=result.stderr,
        raw_output=result.stdout + result.stderr,
    )


def _parse_failures_from_output(output: str) -> list[TestFailure]:
    """Best-effort parse of pytest output when json-report is unavailable."""
    failures = []
    lines = output.split("\n")
    current_test = None
    current_tb = []
    in_failure = False

    for line in lines:
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            if current_test and current_tb:
                failures.append(TestFailure(
                    test_name=current_test,
                    file_path=current_test.split("::")[0] if "::" in current_test else "",
                    line_number=None,
                    error_type="AssertionError",
                    error_message=current_tb[-1] if current_tb else "",
                    traceback="\n".join(current_tb),
                ))
            current_test = line.split(" ", 1)[1].strip() if " " in line else line
            current_tb = []
            in_failure = True
        elif line.startswith("___ ") or line.startswith("=== "):
            in_failure = not in_failure
        elif in_failure:
            current_tb.append(line)

    if current_test:
        failures.append(TestFailure(
            test_name=current_test,
            file_path=current_test.split("::")[0] if "::" in current_test else "",
            line_number=None,
            error_type="AssertionError",
            error_message=current_tb[-1] if current_tb else "",
            traceback="\n".join(current_tb),
        ))

    return failures
