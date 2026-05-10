#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Create venv if it doesn't exist
if [[ ! -d .venv ]]; then
    echo "=== Creating virtual environment ==="
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "=== Installing hallucifix in editable mode ==="
pip install -e ".[dev]" --quiet

echo ""
echo "=== Running tests ==="
python -m pytest tests/ -v --tb=short

echo ""
echo "✅ All tests passed."
