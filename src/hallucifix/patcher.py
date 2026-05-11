"""Apply search/replace patches returned by the LLM."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def apply_patch(patch: dict, project_root: str = ".") -> str:
    """Apply a patch dict ``{"file": ..., "edits": [{"search": ..., "replace": ...}]}``.

    Returns a unified-diff-style description of what changed.
    """
    file_path = Path(project_root) / patch["file"]
    if not file_path.exists():
        # The LLM sometimes returns a path that already includes the project_root
        # prefix (e.g. "demos/demo4/worker.py" when project_root is "demos/demo4"),
        # producing "demos/demo4/demos/demo4/worker.py". Strip the prefix and retry.
        try:
            rel = Path(patch["file"]).relative_to(Path(project_root))
            alt = Path(project_root) / rel
            if alt.exists():
                file_path = alt
                log.debug("Stripped redundant prefix: %s → %s", patch["file"], rel)
        except ValueError:
            pass
    if not file_path.exists():
        raise FileNotFoundError(f"Patch target not found: {file_path}")

    original = file_path.read_text()
    modified = original

    diff_lines: list[str] = [f"--- {patch['file']}", f"+++ {patch['file']}"]

    for edit in patch.get("edits", []):
        search = edit["search"]
        replace = edit["replace"]
        if search not in modified:
            log.warning("Search string not found in %s:\n%s", file_path, search[:200])
            raise ValueError(f"Search string not found in {file_path}")
        modified = modified.replace(search, replace, 1)
        diff_lines.append(f"@@ edit @@")
        for line in search.splitlines():
            diff_lines.append(f"- {line}")
        for line in replace.splitlines():
            diff_lines.append(f"+ {line}")

    file_path.write_text(modified)
    diff_text = "\n".join(diff_lines)
    log.debug("Patched %s:\n%s", file_path, diff_text)
    return diff_text
