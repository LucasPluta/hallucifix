#!/usr/bin/env bash
# Demo 2 (Medium): Fibonacci via RPC — wrong variable in recurrence (add(b,b) vs add(a,b))
exec "$(dirname "$0")/_run_demo.sh" demos/demo2 demos/demo_templates/worker2.py \
    "Medium: add(b,b) instead of add(a,b) in fibonacci"
