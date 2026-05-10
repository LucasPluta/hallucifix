"""Tests for hallucifix.llm (mocked – no real API calls)."""

import json
from unittest.mock import MagicMock, patch

from hallucifix.llm import build_prompt, request_fix


def test_build_prompt_contains_sections():
    prompt = build_prompt(
        traceback="AssertionError: 1 != 2",
        test_stdout="FAILED test_x",
        test_stderr="",
        process_logs={"api": "INFO started"},
        source_files={"app.py": "x = 1\n"},
        previous_attempts=[],
    )
    assert "AssertionError" in prompt
    assert "app.py" in prompt
    assert "Logs from api" in prompt


@patch("hallucifix.llm.OpenAI")
def test_request_fix_parses_json(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    expected = {"file": "app.py", "edits": [{"search": "x=1", "replace": "x=2"}]}
    mock_msg = MagicMock()
    mock_msg.content = json.dumps(expected)
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    fix = request_fix("prompt text", model="gpt-test", iteration=1)

    assert fix.patch == expected
    assert fix.iteration == 1


@patch("hallucifix.llm.OpenAI")
def test_request_fix_handles_bad_json(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    mock_msg = MagicMock()
    mock_msg.content = "not json at all"
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    fix = request_fix("prompt text", model="gpt-test", iteration=2)
    assert fix.patch is None
