"""Orchestrator: ties together attach, log collection, test running, and AI fixing."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .attacher import AttachedProcess, ProcessTarget, attach_via_dap
from .fixer import AIFixer, FixAttempt, FixSession, LLMConnectionError
from .logs import LogCollector
from .runner import TestResult, run_pytest


@dataclass
class ProcessConfig:
    """Configuration for a process to monitor."""

    name: str
    pid: int | None = None
    debugpy_port: int | None = None
    log_file: str | None = None


@dataclass
class HallucifixConfig:
    """Top-level configuration for a hallucifix session."""

    test_path: str
    processes: list[ProcessConfig] = field(default_factory=list)
    project_root: str | None = None
    max_fix_iterations: int = 5
    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str | None = None
    pytest_args: list[str] = field(default_factory=list)
    test_timeout: float = 120.0


@dataclass
class SessionResult:
    """Final result of a hallucifix session."""

    success: bool
    iterations: int
    fix_attempts: list[FixAttempt] = field(default_factory=list)
    final_test_result: TestResult | None = None
    process_logs: str = ""


class Orchestrator:
    """Main orchestrator that runs the debug-fix loop."""

    def __init__(self, config: HallucifixConfig):
        self.config = config
        self.project_root = Path(config.project_root) if config.project_root else Path.cwd()
        self.log_collector = LogCollector()
        self.attached_processes: list[AttachedProcess] = []
        self.fixer = AIFixer(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            max_iterations=config.max_fix_iterations,
            project_root=str(self.project_root),
        )

    def run(self) -> SessionResult:
        """Execute the full debug-fix loop.

        1. Attach debuggers to target processes
        2. Start log collection
        3. Run the test
        4. If test fails: collect logs, send to AI, apply fix, re-run
        5. Repeat until test passes or max iterations reached
        """
        print(f"[hallucifix] Starting session for test: {self.config.test_path}")
        print(f"[hallucifix] Max fix iterations: {self.config.max_fix_iterations}")
        print(f"[hallucifix] Model: {self.config.model}")

        # Step 1: Attach to processes
        self._attach_processes()

        # Step 2: Set up log collection
        self._setup_log_collection()
        self.log_collector.start()

        try:
            return self._fix_loop()
        finally:
            self.log_collector.stop()
            self._detach_processes()

    def _fix_loop(self) -> SessionResult:
        """The core fix loop."""
        attempts: list[FixAttempt] = []

        for iteration in range(1, self.config.max_fix_iterations + 1):
            print(f"\n[hallucifix] === Iteration {iteration}/{self.config.max_fix_iterations} ===")

            # Run the test
            print(f"[hallucifix] Running test: {self.config.test_path}")
            test_result = run_pytest(
                self.config.test_path,
                extra_args=self.config.pytest_args,
                timeout=self.config.test_timeout,
                cwd=str(self.project_root),
            )

            if test_result.passed:
                print(f"[hallucifix] Test PASSED on iteration {iteration}!")
                return SessionResult(
                    success=True,
                    iterations=iteration,
                    fix_attempts=attempts,
                    final_test_result=test_result,
                    process_logs=self.log_collector.get_combined_log_text(),
                )

            print(f"[hallucifix] Test FAILED ({test_result.failed} failures)")

            # Record the test result on the previous attempt so the LLM sees what happened
            if attempts and not attempts[-1].success:
                attempts[-1].test_result = test_result

            # If the previous iteration applied a fix that didn't work, show it
            if attempts and not attempts[-1].success:
                last = attempts[-1]
                print(f"[hallucifix]   Previous fix (iteration {last.iteration}) did NOT resolve the failure:")
                print(f"[hallucifix]   File: {last.file_path}")
                print(f"[hallucifix]   Analysis was: {last.analysis}")
                print(f"[hallucifix]   Diff that failed:")
                for line in last.patch_diff.split("\n"):
                    print(f"[hallucifix]     {line}")
                print()

            # Collect all context
            process_logs = self.log_collector.get_combined_log_text()

            # For each failure, try to fix
            for failure in test_result.failures:
                print(f"[hallucifix] Analyzing failure: {failure.test_name}")
                print(f"[hallucifix]   Error: {failure.error_type}: {failure.error_message}")

                # Ask AI for a fix
                try:
                    fix_suggestion = self.fixer.analyze_and_fix(
                        failure=failure,
                        process_logs=process_logs,
                        previous_attempts=attempts,
                    )
                except LLMConnectionError as e:
                    print(f"[hallucifix] FATAL: {e}")
                    print("[hallucifix] Cannot reach AI provider. Aborting.")
                    return SessionResult(
                        success=False,
                        iterations=iteration,
                        fix_attempts=attempts,
                        final_test_result=test_result,
                        process_logs=self.log_collector.get_combined_log_text(),
                    )

                if fix_suggestion is None:
                    print("[hallucifix]   AI could not produce a fix")
                    continue

                print(f"[hallucifix]   Analysis: {fix_suggestion['analysis']}")
                print(f"[hallucifix]   Fixing: {fix_suggestion['file_path']}")

                # Apply the fix
                attempt = self.fixer.apply_fix(fix_suggestion)
                if attempt is None:
                    print("[hallucifix]   Failed to apply fix (search pattern not found)")
                    continue

                attempt.iteration = iteration
                attempt.failure = failure
                attempts.append(attempt)

                print(f"[hallucifix]   Fix applied. Diff:")
                print(f"[hallucifix]   {'─' * 50}")
                for line in attempt.patch_diff.split("\n"):
                    print(f"[hallucifix]     {line}")
                print(f"[hallucifix]   {'─' * 50}")

                # Only fix one failure per iteration, then re-run
                break

        # Max iterations exhausted
        print(f"\n[hallucifix] Max iterations ({self.config.max_fix_iterations}) reached without resolution.")
        final_result = run_pytest(
            self.config.test_path,
            extra_args=self.config.pytest_args,
            timeout=self.config.test_timeout,
            cwd=str(self.project_root),
        )
        return SessionResult(
            success=final_result.passed,
            iterations=self.config.max_fix_iterations,
            fix_attempts=attempts,
            final_test_result=final_result,
            process_logs=self.log_collector.get_combined_log_text(),
        )

    def _attach_processes(self) -> None:
        """Attach debugpy to configured processes."""
        for proc_config in self.config.processes:
            if proc_config.debugpy_port:
                print(f"[hallucifix] Attaching to {proc_config.name} on port {proc_config.debugpy_port}...")
                sock = attach_via_dap("127.0.0.1", proc_config.debugpy_port)
                target = ProcessTarget(
                    pid=proc_config.pid or 0,
                    name=proc_config.name,
                    debugpy_port=proc_config.debugpy_port,
                    log_file=proc_config.log_file,
                )
                self.attached_processes.append(
                    AttachedProcess(target=target, connected=sock is not None)
                )
                if sock:
                    print(f"[hallucifix]   Connected to {proc_config.name}")
                else:
                    print(f"[hallucifix]   WARNING: Could not connect to {proc_config.name}")
            else:
                print(f"[hallucifix] Monitoring {proc_config.name} (no debugpy port, log-only)")

    def _setup_log_collection(self) -> None:
        """Set up log file watching for all configured processes."""
        for proc_config in self.config.processes:
            if proc_config.log_file:
                self.log_collector.add_log_file(
                    proc_config.name, Path(proc_config.log_file)
                )

    def _detach_processes(self) -> None:
        """Clean up debug connections."""
        self.attached_processes.clear()
