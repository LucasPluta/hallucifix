"""Tests for hallucifix.report."""

from hallucifix.report import FixReport, build_report_markdown, write_report


def test_build_report_markdown():
    md = build_report_markdown(
        test_path="tests/test_app.py",
        iterations=1,
        model="gpt-4o",
        fix_summaries=[{"file": "app.py", "diff": "- x\n+ y"}],
        explanation="Changed x to y because it was wrong.",
    )
    assert "# Hallucifix Fix Report" in md
    assert "`tests/test_app.py`" in md
    assert "`gpt-4o`" in md
    assert "Changed x to y" in md
    assert "```diff" in md


def test_write_report(tmp_path):
    report = FixReport(
        git_patch="diff --git a/app.py b/app.py\n",
        markdown="# Report\n",
    )
    write_report(report, output_dir=str(tmp_path))

    assert report.patch_path is not None
    assert report.markdown_path is not None
    assert (tmp_path / "hallucifix.patch").read_text() == "diff --git a/app.py b/app.py\n"
    assert (tmp_path / "hallucifix-report.md").read_text() == "# Report\n"
