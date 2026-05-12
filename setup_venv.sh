#!/usr/bin/env bash
set -euo pipefail

if [[ -d .venv ]]; then
    echo "Virtual environment .venv already exists."
else
    echo "Creating virtual environment .venv ..."
    python3 -m venv .venv
    echo "Done."
fi

echo "Activate with: source .venv/bin/activate"