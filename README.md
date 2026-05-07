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
