"""AI-powered fix loop: analyze failures, generate patches, apply and retry."""

from __future__ import annotations

import difflib
import json
import os
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runner import TestFailure, TestResult


@dataclass
class FixAttempt:
    """A single attempt to fix a failure."""

    iteration: int
    failure: TestFailure
    analysis: str
    file_path: str
    original_code: str
    fixed_code: str
    patch_diff: str
    test_result: TestResult | None = None
    success: bool = False


@dataclass
class FixSession:
    """Complete session of attempting to fix failures."""

    test_path: str
    max_iterations: int
    attempts: list[FixAttempt] = field(default_factory=list)
    resolved: bool = False


SYSTEM_PROMPT = """\
You are an expert Python debugging assistant. You are given:
1. A failing test with its full traceback
2. Logs from two running processes that the test interacts with
3. The source code of the file where the failure occurred

Your job is to analyze the failure and produce a MINIMAL fix to make the test pass.

Rules:
- Only modify the source file that contains the bug (not the test)
- Make the smallest change possible
- Do not add unnecessary comments or docstrings
- Do not refactor unrelated code
- Return your fix as a JSON object with the exact format specified
"""

USER_PROMPT_TEMPLATE = """\
## Failing Test
**Test:** {test_name}
**File:** {file_path}:{line_number}
**Error:** {error_type}: {error_message}

### Traceback
```
{traceback}
```

### Test stdout
```
{test_stdout}
```

## Process Logs During Test
{process_logs}

## Source File: {source_file}
```python
{source_code}
```

## Previous Fix Attempts (if any)
{previous_attempts}

---

Analyze the failure and provide a fix. Respond with ONLY a JSON object:
{{
  "analysis": "Brief explanation of root cause",
  "file_path": "path/to/file.py",
  "search": "exact lines to find in the file (include enough context to be unique)",
  "replace": "the replacement lines that fix the bug"
}}
"""


class AIFixer:
    """Uses an LLM to analyze failures and generate fixes."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        max_iterations: int = 5,
        project_root: str | None = None,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.max_iterations = max_iterations
        self.project_root = Path(project_root) if project_root else Path.cwd()

    def analyze_and_fix(
        self,
        failure: TestFailure,
        process_logs: str,
        previous_attempts: list[FixAttempt] | None = None,
    ) -> dict[str, str] | None:
        """Send failure context to the LLM and get a fix suggestion."""
        source_code = self._read_source(failure.file_path)
        if source_code is None:
            return None

        prev_text = ""
        if previous_attempts:
            parts = []
            for att in previous_attempts:
                parts.append(
                    f"Attempt {att.iteration}: {att.analysis}\n"
                    f"Diff:\n{att.patch_diff}\n"
                    f"Result: {'passed' if att.success else 'still failing'}"
                )
            prev_text = "\n\n".join(parts)
        else:
            prev_text = "None"

        user_prompt = USER_PROMPT_TEMPLATE.format(
            test_name=failure.test_name,
            file_path=failure.file_path,
            line_number=failure.line_number or "?",
            error_type=failure.error_type,
            error_message=failure.error_message,
            traceback=failure.traceback,
            test_stdout=failure.stdout or "(none)",
            process_logs=process_logs,
            source_file=failure.file_path,
            source_code=source_code,
            previous_attempts=prev_text,
        )

        response = self._call_llm(user_prompt)
        if response is None:
            return None

        return self._parse_fix_response(response)

    def apply_fix(self, fix: dict[str, str]) -> FixAttempt | None:
        """Apply a fix to the source file. Returns the attempt or None on error."""
        file_path = self.project_root / fix["file_path"]
        if not file_path.exists():
            return None

        original = file_path.read_text()
        search = fix["search"]
        replace = fix["replace"]

        if search not in original:
            # Try with normalized whitespace
            search_normalized = _normalize_indent(search)
            lines = original.split("\n")
            # Sliding window match
            search_lines = search_normalized.split("\n")
            match_start = None
            for i in range(len(lines) - len(search_lines) + 1):
                window = "\n".join(lines[i : i + len(search_lines)])
                if _normalize_indent(window) == search_normalized:
                    match_start = i
                    break

            if match_start is None:
                return None

            # Replace in place
            new_lines = lines[:match_start] + replace.split("\n") + lines[match_start + len(search_lines):]
            fixed = "\n".join(new_lines)
        else:
            fixed = original.replace(search, replace, 1)

        # Write the fix
        file_path.write_text(fixed)

        # Generate diff
        diff = "\n".join(difflib.unified_diff(
            original.splitlines(),
            fixed.splitlines(),
            fromfile=f"a/{fix['file_path']}",
            tofile=f"b/{fix['file_path']}",
            lineterm="",
        ))

        return FixAttempt(
            iteration=0,
            failure=TestFailure(
                test_name="", file_path=fix["file_path"],
                line_number=None, error_type="", error_message="", traceback=""
            ),
            analysis=fix.get("analysis", ""),
            file_path=fix["file_path"],
            original_code=original,
            fixed_code=fixed,
            patch_diff=diff,
        )

    def revert_fix(self, attempt: FixAttempt) -> None:
        """Revert a fix by writing back the original code."""
        file_path = self.project_root / attempt.file_path
        file_path.write_text(attempt.original_code)

    def _read_source(self, file_path: str) -> str | None:
        """Read the source file."""
        full_path = self.project_root / file_path
        if full_path.exists():
            return full_path.read_text()
        # Try as absolute path
        p = Path(file_path)
        if p.exists():
            return p.read_text()
        return None

    def _call_llm(self, user_prompt: str) -> str | None:
        """Call the LLM API (OpenAI-compatible)."""
        try:
            import httpx
        except ImportError:
            import urllib.request
            return self._call_llm_urllib(user_prompt)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
        }

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[hallucifix] LLM call failed: {e}")
            return None

    def _call_llm_urllib(self, user_prompt: str) -> str | None:
        """Fallback LLM call using urllib (no extra deps)."""
        import urllib.request

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
        }).encode()

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[hallucifix] LLM call failed: {e}")
            return None

    def _parse_fix_response(self, response: str) -> dict[str, str] | None:
        """Extract JSON fix from LLM response."""
        # Try to find JSON block in response
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            response = json_match.group(1)
        else:
            # Try to find raw JSON object
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                response = json_match.group(0)

        try:
            fix = json.loads(response)
            required_keys = {"analysis", "file_path", "search", "replace"}
            if not required_keys.issubset(fix.keys()):
                print(f"[hallucifix] LLM response missing keys: {required_keys - fix.keys()}")
                return None
            return fix
        except json.JSONDecodeError as e:
            print(f"[hallucifix] Failed to parse LLM response as JSON: {e}")
            return None


def _normalize_indent(text: str) -> str:
    """Normalize indentation for fuzzy matching."""
    return textwrap.dedent(text).strip()
