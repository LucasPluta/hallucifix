"""LLM client – ask an OpenAI-compatible API for a code fix."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from openai import OpenAI

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert Python debugger.  You will be given:
  • a pytest traceback and test output
  • log output from running processes
  • the source code of one or more candidate files
  • (optionally) previous fix attempts that did not work

Return ONLY a JSON object with a list of search/replace edits:
{
  "file": "<path to the file you are fixing – must match one of the given paths>",
  "edits": [
    {"search": "<exact text to find>", "replace": "<replacement text>"}
  ]
}

Rules:
- Pick the ONE file that contains the bug.
- The "search" string MUST appear verbatim in that source file.
- Make the MINIMAL change that fixes the failing test.
- Do NOT add unrelated refactors or style changes.
- Return valid JSON only – no markdown fences, no commentary.
"""


@dataclass
class FixAttempt:
    """Record of a single LLM-generated fix."""

    iteration: int
    prompt_text: str
    raw_response: str
    patch: dict | None
    patch_diff: str = ""


def build_prompt(
    traceback: str,
    test_stdout: str,
    test_stderr: str,
    process_logs: dict[str, str],
    source_files: dict[str, str],
    previous_attempts: list[FixAttempt],
) -> str:
    """Assemble the user-message sent to the LLM.

    *source_files* maps relative file paths to their source code.
    """
    parts: list[str] = []
    parts.append("## Test traceback\n```\n" + traceback + "\n```\n")
    if test_stdout.strip():
        parts.append("## Test stdout\n```\n" + test_stdout + "\n```\n")
    if test_stderr.strip():
        parts.append("## Test stderr\n```\n" + test_stderr + "\n```\n")
    for name, logs in process_logs.items():
        if logs.strip():
            parts.append(f"## Logs from {name}\n```\n{logs}\n```\n")
    for fpath, code in source_files.items():
        parts.append(f"## Source file: {fpath}\n```python\n{code}\n```\n")
    if previous_attempts:
        parts.append("## Previous fix attempts (did NOT work):\n")
        for att in previous_attempts:
            parts.append(f"### Attempt {att.iteration}\n```json\n{att.raw_response}\n```\n")
    return "\n".join(parts)


def request_fix(
    prompt_text: str,
    model: str = "gpt-4o",
    base_url: str | None = None,
    iteration: int = 1,
) -> FixAttempt:
    """Call the LLM and return a FixAttempt."""
    kwargs: dict = {"model": model}
    if base_url:
        client = OpenAI(base_url=base_url)
    else:
        client = OpenAI()

    log.info("Requesting fix from %s (iteration %d)", model, iteration)
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
        ],
        temperature=0.2,
        **kwargs,
    )
    raw = response.choices[0].message.content or ""

    # Strip markdown fences the LLM sometimes wraps around JSON
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or just ```)
        first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_newline + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -3]
    cleaned = cleaned.strip()

    try:
        patch = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("LLM returned non-JSON response:\n%s", raw[:500])
        patch = None

    return FixAttempt(
        iteration=iteration,
        prompt_text=prompt_text,
        raw_response=raw,
        patch=patch,
    )
