# hallucifix

Attach debuggers to running Python processes, run tests, and use AI to brute-force fix failures in a loop.

## How it works

```
┌─────────────────────────────────────────────────────────────┐
│                      hallucifix loop                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Attach debugpy to Process A (port 5678)                 │
│  2. Attach debugpy to Process B (port 5679)                 │
│  3. Start tailing log files from both processes             │
│  4. Run pytest                                              │
│  5. If test PASSES → done                                   │
│  6. If test FAILS:                                          │
│     a. Collect logs from both processes                     │
│     b. Collect test traceback + failure info                │
│     c. Send everything to LLM (GPT-4o / Claude / etc)      │
│     d. LLM returns a minimal code fix                       │
│     e. Apply the fix                                        │
│     f. Go to step 4                                         │
│  7. Repeat up to N iterations                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Installation

```bash
pip install -e .
```

## Prerequisites

Your target processes must have `debugpy` installed and be started with debugpy listening:

```python
# In your process startup code:
import debugpy
debugpy.listen(("127.0.0.1", 5678))  # Process A
# debugpy.listen(("127.0.0.1", 5679))  # Process B
```

Or inject at runtime if the process supports it.

## Usage

### CLI

```bash
# Basic: monitor two processes and run a test
hallucifix tests/test_integration.py \
  -p "api-server:5678:/tmp/api.log" \
  -p "worker:5679:/tmp/worker.log" \
  --max-iterations 5 \
  --model gpt-4o

# With config file
hallucifix tests/test_integration.py -c hallucifix.json

# Pass extra pytest args
hallucifix tests/test_integration.py -p "server:5678:" -- -x -k "test_specific"
```

### Config file (hallucifix.json)

```json
{
  "test_path": "tests/",
  "project_root": ".",
  "max_iterations": 5,
  "model": "gpt-4o",
  "timeout": 120,
  "processes": [
    {
      "name": "api-server",
      "debugpy_port": 5678,
      "log_file": "/tmp/api-server.log"
    },
    {
      "name": "worker",
      "debugpy_port": 5679,
      "log_file": "/tmp/worker.log"
    }
  ]
}
```

### Python API

```python
from hallucifix.orchestrator import Orchestrator, HallucifixConfig, ProcessConfig

config = HallucifixConfig(
    test_path="tests/test_integration.py",
    processes=[
        ProcessConfig(name="api", debugpy_port=5678, log_file="/tmp/api.log"),
        ProcessConfig(name="worker", debugpy_port=5679, log_file="/tmp/worker.log"),
    ],
    max_fix_iterations=5,
    model="gpt-4o",
)

orchestrator = Orchestrator(config)
result = orchestrator.run()

if result.success:
    print(f"Fixed in {result.iterations} iterations!")
    for attempt in result.fix_attempts:
        print(attempt.patch_diff)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | API key for LLM calls |
| `OPENAI_BASE_URL` | Custom API base URL (for Azure, local models, etc.) |

## How the AI fix works

On each failure, hallucifix sends the LLM:
- The full test traceback
- stdout/stderr from the test
- Logs collected from both monitored processes during the test run
- The source code of the file containing the bug
- Previous fix attempts (so it doesn't repeat itself)

The LLM returns a search/replace patch that hallucifix applies to the source, then re-runs the test.

## Supported LLM backends

Any OpenAI-compatible API works:
- OpenAI (GPT-4o, GPT-4-turbo)
- Anthropic via proxy
- Azure OpenAI
- Local models (ollama, vLLM, etc.) via `--base-url`

## Report generation & PR-ready output

When hallucifix successfully fixes a failing test, it produces two artefacts in the project root:

| File | Purpose |
|------|---------|
| `hallucifix.patch` | A `git diff HEAD` patch that can be applied with `git apply` |
| `hallucifix-report.md` | A Markdown explanation suitable for use as a PR body |

The report includes a summary (test path, model, iteration count), an LLM-generated explanation of the fix, and a per-iteration changelog with inline diffs.

### Explanation quality guidelines

<!--
@hallucifix-llm-context
The following principles govern how the explanation LLM call is constructed.
They are critical for producing useful, accurate PR descriptions.
Any agent or contributor modifying request_explanation(), EXPLAIN_SYSTEM_PROMPT,
or _generate_report() MUST adhere to these rules.
-->

The LLM-generated explanation must describe **only the actual code change** and its immediate motivation. The following principles apply:

1. **Scope the description to the diff.** The explanation should cover what was wrong in the original code, what was changed, and why the new code is correct. It must not speculate about unrelated concerns (git state, CI configuration, repository setup, deployment, etc.).

2. **Provide source context proportional to complexity.** The edited source file(s) are passed alongside the diffs so the LLM can reference surrounding logic when explaining the root cause. Simple one-line fixes need minimal context; multi-file changes across interacting components need more.

3. **Start with the directly-edited files.** Only the files that were actually patched are included as source context by default. Do not eagerly expand to the entire codebase — additional files should only be pulled in when the edited file alone does not contain enough information to explain the fix.

4. **Use the applied search/replace diffs, not the git diff.** The search/replace edits are always available and precisely describe what changed. The git diff may be empty (fresh repo, unstaged changes) and should not be the primary input to the explanation call.

5. **Structure: Root cause → Fix → Testing.** Every explanation should cover these three points concisely (1–3 paragraphs). It should not reproduce the full diff or large blocks of source code.

### How it works internally

```
Fix succeeds
  │
  ├─ Read source file(s) that were patched (post-fix versions)
  ├─ Collect per-iteration search/replace diffs
  ├─ Send diffs + source context + test output to LLM
  │    → LLM returns a concise PR-body explanation
  ├─ Run `git diff HEAD` for a machine-applicable patch
  └─ Write hallucifix.patch + hallucifix-report.md
```

### Python API access

```python
result = orchestrator.run()

if result.success and result.report:
    print(result.report.markdown)       # PR-body text
    print(result.report.git_patch)      # git-apply-able patch
    print(result.report.patch_path)     # absolute path to .patch file
    print(result.report.markdown_path)  # absolute path to .md file
```
