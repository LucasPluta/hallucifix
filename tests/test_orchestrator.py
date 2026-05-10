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

    mock_msg = MagicMock()
    mock_msg.content = fix_payload
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("hallucifix.llm.OpenAI", return_value=mock_client):
        result = Orchestrator(config).run()

    assert result.success
    assert result.iterations == 2  # iteration 1 fails, applies fix, iteration 2 passes
    assert len(result.fix_attempts) == 1
    assert "return a + b" in buggy.read_text()
