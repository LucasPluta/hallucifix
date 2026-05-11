"""LLM client – ask an OpenAI-compatible API for a code fix."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from openai import OpenAI

log = logging.getLogger(__name__)


# ── Gemini support ─────────────────────────────────────────────

def _use_gemini() -> bool:
    """Return True if GEMINI_API_KEY is set in the environment."""
    return bool(os.environ.get("GEMINI_API_KEY"))


def _gemini_chat(
    system: str,
    user: str,
    model: str,
    temperature: float,
) -> str:
    """Call the Google Gemini API via the native genai SDK."""
    from google import genai
    from google.genai import types

    api_key = os.environ["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)

    log.info("Using Gemini native client (model=%s)", model)
    response = client.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
        ),
    )
    return response.text or ""

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
    est_tokens = (len(SYSTEM_PROMPT) + len(prompt_text)) // 4
    log.info(
        "Requesting fix from %s (iteration %d) — ~%d estimated tokens",
        model, iteration, est_tokens,
    )

    if _use_gemini():
        raw = _gemini_chat(SYSTEM_PROMPT, prompt_text, model, temperature=0.2)
    else:
        kwargs: dict = {"model": model}
        if base_url:
            client = OpenAI(base_url=base_url)
        else:
            client = OpenAI()

        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_text},
                ],
                temperature=0.2,
                **kwargs,
            )
        except Exception as exc:
            msg = str(exc)
            limit_match = re.search(r"Max size:\s*([\d,]+)\s*tokens", msg)
            limit_str = limit_match.group(1) if limit_match else "unknown"
            log.error(
                "LLM request failed (~%d estimated tokens, limit: %s tokens): %s",
                est_tokens, limit_str, msg,
            )
            raise
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


EXPLAIN_SYSTEM_PROMPT = """\
You are a senior software engineer writing a pull-request description.
You will be given:
  • the search/replace diffs that were applied to fix failing tests
  • the source code of the edited file(s) (post-fix) for context
  • the test output that confirmed the fix

Use the source code to understand the surrounding logic and explain *why*
the original code was wrong. Focus on the actual code change — do not
speculate about git state, CI pipelines, repository setup, or anything
not visible in the provided materials.

Include:
1. **Root cause** – what was wrong in the original code and why,
   referencing the surrounding logic when it helps clarify.
2. **Fix** – what was changed (referencing the specific edit) and why
   the new code is correct.
3. **Testing** – the tests that were failing now pass.

Keep it to 1–3 short paragraphs. Do not reproduce the full diff or
large blocks of source code.
"""


def request_explanation(
    applied_diffs: list[dict],
    test_stdout: str,
    source_files: dict[str, str] | None = None,
    model: str = "gpt-4o",
    base_url: str | None = None,
) -> str:
    """Ask the LLM to explain a fix for use in a PR description.

    *applied_diffs* is a list of ``{"file": ..., "diff": ...}`` dicts
    describing the search/replace edits that were applied.

    *source_files* maps relative file paths to their (post-fix) source
    code, giving the LLM context to explain the surrounding logic.
    """
    diff_parts = []
    for d in applied_diffs:
        diff_parts.append(f"### {d['file']}\n```diff\n{d['diff']}\n```")
    diff_section = "\n\n".join(diff_parts) if diff_parts else "_No diffs available._"

    sections = ["## Applied code changes\n" + diff_section]

    if source_files:
        src_parts = []
        for fpath, code in source_files.items():
            src_parts.append(f"### {fpath}\n```python\n{code}\n```")
        sections.append("## Source context\n" + "\n\n".join(src_parts))

    sections.append("## Test output\n```\n" + test_stdout + "\n```")

    user_msg = "\n\n".join(sections)

    log.info("Requesting fix explanation from %s", model)

    if _use_gemini():
        return _gemini_chat(EXPLAIN_SYSTEM_PROMPT, user_msg, model, temperature=0.3)

    if base_url:
        client = OpenAI(base_url=base_url)
    else:
        client = OpenAI()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXPLAIN_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content or ""
