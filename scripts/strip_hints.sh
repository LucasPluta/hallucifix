#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  strip_hints.sh – Remove bug-hinting comments from demo files
#
#  Usage:
#    ./scripts/strip_hints.sh <file>
#    ./scripts/strip_hints.sh demos/demo4/worker.py
#
#  Strips:
#    - Lines that are pure comments containing bug hint keywords
#      (BUG, FIXME, HACK, ← BUG, should be, race, mismatch, etc.)
#    - Inline trailing comments containing those keywords
#    - The file-level docstring block marked with ⚠️
#
#  The script edits the file IN PLACE (overwrites the original).
# ─────────────────────────────────────────────────────────────
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <file>" >&2
    exit 1
fi

FILE="$1"
if [[ ! -f "$FILE" ]]; then
    echo "ERROR: $FILE not found." >&2
    exit 1
fi

TMP=$(mktemp)

python3 -c "
import re, sys

with open(sys.argv[1]) as f:
    text = f.read()

# ── 1. Remove the file-level docstring block with ⚠️ ──────────
# Match a triple-quoted docstring at the very start of the file
text = re.sub(
    r'\A\s*\"\"\".*?⚠️.*?\"\"\"\\n*',
    '',
    text,
    flags=re.DOTALL,
)

# ── 2. Hint keywords (case-insensitive) ───────────────────────
HINT = re.compile(
    r'BUG|FIXME|HACK|← BUG|should be |race.*(window|condition)|'
    r'mismatch|cumulative|double-register|without.*(lock|a lock)|'
    r'widens the race|check-then-act|read-modify-write|'
    r'loses? updates?|integer.*instead|instead of.*string|'
    r'instead of.*delay|instead of.*done|catastrophic|'
    r'collide|collision|one increment is lost|sleeps.*instead|'
    r'concurrent.*(registr|decrement|reading)|'
    r'simultaneously.*same value|yields? to other threads|'
    r'creating a race|zero rows|always report|matches\s*nothing|'
    r'is lost\b|SQLite stores status',
    re.IGNORECASE,
)

lines = text.splitlines(keepends=True)

# ── 3. Process docstrings: strip hint lines, clean up ─────────
out = []
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.lstrip()

    # Detect start of a multi-line docstring
    if '\"\"\"' in stripped:
        quote_count = stripped.count('\"\"\"')
        if quote_count == 1:
            # Multi-line docstring: collect entire block
            block = [line]
            j = i + 1
            while j < len(lines):
                block.append(lines[j])
                if '\"\"\"' in lines[j]:
                    break
                j += 1

            # Filter hint lines from the docstring body (keep first/last)
            cleaned = [block[0]]
            for bline in block[1:-1]:
                if not HINT.search(bline):
                    cleaned.append(bline)
            # Remove trailing blank lines before closing quotes
            while len(cleaned) > 1 and cleaned[-1].strip() == '':
                cleaned.pop()
            cleaned.append(block[-1])

            # If the docstring body is now empty, collapse it
            indent = len(block[0]) - len(block[0].lstrip())
            body_lines = [l for l in cleaned[1:-1] if l.strip()]
            if not body_lines:
                # Check if the first line has content after \"\"\"
                first_content = cleaned[0].strip().replace('\"\"\"', '').strip()
                if first_content:
                    out.append(' ' * indent + '\"\"\"' + first_content + '\"\"\"' + '\\n')
                else:
                    # Drop empty docstring entirely
                    pass
            else:
                out.extend(cleaned)

            i = j + 1
            continue
        else:
            # Single-line docstring
            if HINT.search(stripped):
                i += 1
                continue

    # Pure comment line with hints → drop
    if stripped.startswith('#') and HINT.search(stripped):
        i += 1
        continue

    # Inline trailing comment with hints → strip comment
    m = re.match(r'^(.*\S)\s+#\s*(.*)', line)
    if m and HINT.search(m.group(2)):
        out.append(m.group(1).rstrip() + '\\n')
        i += 1
        continue

    out.append(line)
    i += 1

# ── 4. Collapse runs of blank lines (max 2) ──────────────────
result = []
blank_count = 0
for line in out:
    if line.strip() == '':
        blank_count += 1
        if blank_count <= 2:
            result.append(line)
    else:
        blank_count = 0
        result.append(line)

with open(sys.argv[1], 'w') as f:
    f.writelines(result)
" "$FILE"

echo "Stripped bug hints from $FILE"
