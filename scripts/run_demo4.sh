#!/usr/bin/env bash
# Demo 4 (Expert): Concurrent job queue — race condition + schema mismatch + retry timing bug
exec "$(dirname "$0")/_run_demo.sh" demos/demo4 demos/demo_templates/worker4.py \
    "Expert: race condition + schema mismatch + I/O retry bug" "$@"
