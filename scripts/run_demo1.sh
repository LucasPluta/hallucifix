#!/usr/bin/env bash
# Demo 1 (Easy): Square calculator — single arithmetic bug (n*(n+1) instead of n²)
exec "$(dirname "$0")/_run_demo.sh" demos/demo1 demos/demo_templates/worker1.py \
    "Easy: n*(n+1) instead of n*n in compute_square"
