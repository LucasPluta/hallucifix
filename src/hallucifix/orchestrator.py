"""Main orchestration loop: test → fail → LLM fix → retest."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from hallucifix.config import HallucifixConfig
from hallucifix.debugger import DebugSession, attach
from hallucifix.llm import FixAttempt, build_prompt, request_explanation, request_fix
from hallucifix.log_tailer import LogTailer
from hallucifix.patcher import apply_patch
from hallucifix.report import (
    FixReport,
    build_report_markdown,
    generate_git_patch,
    write_report,
)
from hallucifix.test_runner import TestResult, run_pytest

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Outcome of a full hallucifix session."""

    success: bool
    iterations: int
    fix_attempts: list[FixAttempt] = field(default_factory=list)
    final_test: TestResult | None = None
    report: FixReport | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FILE_LINE_RE = re.compile(r'File "([^"]+)", line \d+')


def _candidate_source_files(traceback_text: str, project_root: str) -> list[str]:
    """Return relative paths of source files that might contain the bug.

    First tries files mentioned in the traceback; falls back to scanning
    *project_root* for non-test ``.py`` files.
    """
    root = Path(project_root).resolve()

    # --- pass 1: files referenced in the traceback ---
    candidates: list[str] = []
    for m in _FILE_LINE_RE.finditer(traceback_text):
        fpath = Path(m.group(1)).resolve()
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            continue
        if "site-packages" in str(fpath):
            continue
        if fpath.name.startswith("test_") or fpath.name.startswith("conftest"):
            continue
        if rel not in candidates:
            candidates.append(rel)

    if candidates:
        return candidates

    # --- pass 2: scan project root ---
    for py_file in sorted(root.rglob("*.py")):
        if "site-packages" in str(py_file):
            continue
        if py_file.name.startswith("test_") or py_file.name.startswith("conftest"):
            continue
        if py_file.name == "__init__.py":
            continue
        rel = str(py_file.relative_to(root))
        if rel not in candidates:
            candidates.append(rel)

    return candidates


class Orchestrator:
    """Drives the test → fix → retest loop."""

    def __init__(self, config: HallucifixConfig) -> None:
        self.config = config
        self._tailers: dict[str, LogTailer] = {}
        self._sessions: list[DebugSession] = []
        self._fix_attempts: list[FixAttempt] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> RunResult:
        self._attach_debuggers()
        self._start_tailers()

        for iteration in range(1, self.config.max_fix_iterations + 1):
            log.info("━━━ Iteration %d / %d ━━━", iteration, self.config.max_fix_iterations)
            print(f"\n{'━' * 50}")
            print(f"  Iteration {iteration} / {self.config.max_fix_iterations}")
            print(f"{'━' * 50}")

            result = run_pytest(
                self.config.test_path,
                extra_args=self.config.extra_pytest_args,
                timeout=self.config.timeout,
            )

            if result.passed:
                log.info("Tests passed! 🎉")
                print("\n  ✅ Tests PASSED")
                run_result = RunResult(
                    success=True,
                    iterations=iteration,
                    fix_attempts=self._fix_attempts,
                    final_test=result,
                )
                run_result.report = self._generate_report(result)
                return run_result

            # Collect diagnostics ------------------------------------------------
            process_logs = self._collect_logs()
            combined_output = result.stdout + "\n" + result.stderr

            # Show a short failure summary on console
            failed_lines = [
                l for l in result.stdout.splitlines()
                if l.startswith("FAILED ") or "assert " in l
            ]
            if failed_lines:
                print("  Tests FAILED:")
                for fl in failed_lines[:5]:
                    print(f"    {fl.strip()}")

            candidates = _candidate_source_files(combined_output, self.config.project_root)

            if not candidates:
                log.error("No candidate source files found to fix.")
                print("  ❌ No candidate source files found.")
                return RunResult(
                    success=False,
                    iterations=iteration,
                    fix_attempts=self._fix_attempts,
                    final_test=result,
                )

            root = Path(self.config.project_root).resolve()
            source_files = {
                rel: (root / rel).read_text() for rel in candidates
            }

            print(f"  Asking LLM ({self.config.model}) for a fix...")

            prompt = build_prompt(
                traceback=combined_output,
                test_stdout=result.stdout,
                test_stderr=result.stderr,
                process_logs=process_logs,
                source_files=source_files,
                previous_attempts=self._fix_attempts,
            )

            # Ask LLM for a fix ---------------------------------------------------
            fix = request_fix(
                prompt,
                model=self.config.model,
                base_url=self.config.base_url,
                iteration=iteration,
            )

            if fix.patch is None:
                log.error("LLM did not return a valid patch on iteration %d.", iteration)
                print("  ⚠️  LLM did not return a valid patch – retrying...")
                self._fix_attempts.append(fix)
                continue

            # Apply the patch ------------------------------------------------------
            try:
                diff = apply_patch(fix.patch, project_root=self.config.project_root)
                fix.patch_diff = diff
                print(f"  Proposed fix (file: {fix.patch.get('file', '?')}):")
                for line in diff.splitlines():
                    if line.startswith("- ") or line.startswith("+ "):
                        print(f"    {line}")
            except (FileNotFoundError, ValueError) as exc:
                log.error("Patch could not be applied: %s", exc)
                print(f"  ⚠️  Patch could not be applied: {exc}")
                self._fix_attempts.append(fix)
                continue

            self._fix_attempts.append(fix)

        # Exhausted iterations – run one last test
        final = run_pytest(
            self.config.test_path,
            extra_args=self.config.extra_pytest_args,
            timeout=self.config.timeout,
        )
        run_result = RunResult(
            success=final.passed,
            iterations=self.config.max_fix_iterations,
            fix_attempts=self._fix_attempts,
            final_test=final,
        )
        if final.passed:
            run_result.report = self._generate_report(final)
        return run_result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _attach_debuggers(self) -> None:
        for proc in self.config.processes:
            session = attach(proc)
            if session is not None:
                self._sessions.append(session)

    def _close_debuggers(self) -> None:
        for session in self._sessions:
            session.close()
        self._sessions.clear()

    def _start_tailers(self) -> None:
        for proc in self.config.processes:
            if proc.log_file:
                tailer = LogTailer(proc.log_file)
                tailer.start()
                self._tailers[proc.name] = tailer

    def _collect_logs(self) -> dict[str, str]:
        return {name: tailer.collect() for name, tailer in self._tailers.items()}

    def _generate_report(self, final_test: TestResult) -> FixReport:
        """Build a git patch + markdown explanation after a successful fix."""
        print("  Generating fix report...")

        git_patch = generate_git_patch(self.config.project_root)

        # Build per-iteration summaries
        fix_summaries = []
        for attempt in self._fix_attempts:
            fix_summaries.append({
                "file": attempt.patch.get("file", "unknown") if attempt.patch else "unknown",
                "diff": attempt.patch_diff,
            })

        # Collect source context for edited files
        root = Path(self.config.project_root).resolve()
        source_files: dict[str, str] = {}
        seen_files: set[str] = set()
        for summary in fix_summaries:
            rel = summary["file"]
            if rel in seen_files or rel == "unknown":
                continue
            seen_files.add(rel)
            fpath = root / rel
            if fpath.is_file():
                try:
                    source_files[rel] = fpath.read_text()
                except OSError:
                    log.debug("Could not read source file %s", fpath)

        # Ask LLM to explain the fix
        test_output = final_test.stdout if final_test else ""
        try:
            explanation = request_explanation(
                applied_diffs=fix_summaries,
                test_stdout=test_output,
                source_files=source_files or None,
                model=self.config.model,
                base_url=self.config.base_url,
            )
        except Exception:
            log.warning("Failed to generate LLM explanation", exc_info=True)
            explanation = "_Explanation could not be generated._"

        markdown = build_report_markdown(
            test_path=self.config.test_path,
            iterations=len(self._fix_attempts),
            model=self.config.model,
            fix_summaries=fix_summaries,
            explanation=explanation,
        )

        report = FixReport(git_patch=git_patch, markdown=markdown)
        write_report(report, output_dir=self.config.project_root)
        return report
