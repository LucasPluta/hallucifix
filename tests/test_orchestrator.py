"""End-to-end integration test for the orchestrator (mocked LLM, no real processes)."""

import json
import textwrap
from unittest.mock import MagicMock, patch

from hallucifix.config import HallucifixConfig
from hallucifix.orchestrator import Orchestrator


def test_orchestrator_fixes_bug(tmp_path):
    """Simulate a full loop: buggy file → LLM returns fix → test passes."""

    # ── Create a buggy source file ──────────────────────────────────────
    buggy = tmp_path / "app.py"
    buggy.write_text(textwrap.dedent("""\
        def add(a, b):
            return a - b  # BUG: should be a + b
    """))

    # ── Create a test that imports and exercises the buggy function ──────
    test_file = tmp_path / "test_app.py"
    test_file.write_text(textwrap.dedent(f"""\
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(r"{tmp_path}")))
        from app import add

        def test_add():
            assert add(2, 3) == 5
    """))

    # ── Configure hallucifix ────────────────────────────────────────────
    config = HallucifixConfig(
        test_path=str(test_file),
        processes=[],  # no real processes to attach to
        project_root=str(tmp_path),
        max_fix_iterations=3,
        model="gpt-test",
    )

    # ── Mock the LLM to return the correct fix ──────────────────────────
    fix_payload = json.dumps({
        "file": "app.py",
        "edits": [
            {"search": "return a - b  # BUG: should be a + b", "replace": "return a + b"}
        ],
    })

    # First call → fix JSON, second call → explanation text
    fix_msg = MagicMock()
    fix_msg.content = fix_payload
    fix_choice = MagicMock()
    fix_choice.message = fix_msg
    fix_response = MagicMock()
    fix_response.choices = [fix_choice]

    explain_msg = MagicMock()
    explain_msg.content = "The bug was using subtraction instead of addition."
    explain_choice = MagicMock()
    explain_choice.message = explain_msg
    explain_response = MagicMock()
    explain_response.choices = [explain_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [fix_response, explain_response]

    with patch("hallucifix.llm.OpenAI", return_value=mock_client):
        result = Orchestrator(config).run()

    assert result.success
    assert result.iterations == 2  # iteration 1 fails, applies fix, iteration 2 passes
    assert len(result.fix_attempts) == 1
    assert "return a + b" in buggy.read_text()

    # Verify report was generated
    assert result.report is not None
    assert "subtraction" in result.report.markdown
    assert result.report.patch_path is not None
