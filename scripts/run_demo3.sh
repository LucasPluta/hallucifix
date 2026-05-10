#!/usr/bin/env bash
# Demo 3 (Hard): Temperature converter — two bugs (div by 4 not 5 + appending wrong var)
exec "$(dirname "$0")/_run_demo.sh" demos/demo3 demos/demo_templates/worker3.py \
    "Hard: TWO bugs — div/4 not div/5 + append(c) not append(f)"
