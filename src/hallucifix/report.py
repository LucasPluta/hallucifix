"""Generate git-format patches and markdown fix reports."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class FixReport:
    """Artefacts produced at the end of a successful hallucifix run."""

    git_patch: str
    markdown: str
    patch_path: str | None = None
    markdown_path: str | None = None


def generate_git_patch(project_root: str) -> str:
    """Create a ``git diff`` patch of all unstaged changes in *project_root*.

    Falls back to a plain unified diff if the directory isn't a git repo.
    """
    root = Path(project_root).resolve()

    # Try git diff first (staged + unstaged vs HEAD)
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: git diff without HEAD (for fresh repos with no commits)
    try:
        result = subprocess.run(
            ["git", "diff"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return "# No git diff available (directory may not be a git repository)\n"


def build_report_markdown(
    test_path: str,
    iterations: int,
    model: str,
    fix_summaries: list[dict],
    explanation: str,
) -> str:
    """Assemble a Markdown document describing the fix."""
    lines: list[str] = [
        "# Hallucifix Fix Report",
        "",
        "## Summary",
        "",
        f"- **Test**: `{test_path}`",
        f"- **Model**: `{model}`",
        f"- **Iterations to fix**: {iterations}",
        "",
        "## Explanation",
        "",
        explanation,
        "",
    ]

    if fix_summaries:
        lines.append("## Changes Applied")
        lines.append("")
        for i, summary in enumerate(fix_summaries, 1):
            lines.append(f"### Iteration {i}")
            lines.append("")
            lines.append(f"**File**: `{summary.get('file', 'unknown')}`")
            lines.append("")
            if summary.get("diff"):
                lines.append("```diff")
                lines.append(summary["diff"])
                lines.append("```")
                lines.append("")

    return "\n".join(lines)


def write_report(
    report: FixReport,
    output_dir: str = ".",
) -> FixReport:
    """Write the patch and markdown files to *output_dir*."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    patch_path = out / "hallucifix.patch"
    patch_path.write_text(report.git_patch)
    report.patch_path = str(patch_path)

    md_path = out / "hallucifix-report.md"
    md_path.write_text(report.markdown)
    report.markdown_path = str(md_path)

    log.info("Wrote patch to %s", patch_path)
    log.info("Wrote report to %s", md_path)
    return report
