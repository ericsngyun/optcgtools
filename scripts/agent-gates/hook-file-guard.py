#!/usr/bin/env python3
"""Claude Code PreToolUse hook for Write/Edit/NotebookEdit.

Reads the hook JSON payload on stdin, extracts the target file path, and
blocks (exit 2) when the write would add private media, mutate an approved
asset in place, or create a generated artifact inside the repository.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_common import (  # noqa: E402
    BLOCK_EXIT_CODE,
    approved_asset_violation,
    generated_artifact_violation,
    normalize,
    private_media_violation,
    repo_root,
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # never block on malformed hook input; CI re-checks everything

    tool_input = payload.get("tool_input", {}) or {}
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw_path:
        return 0

    root = repo_root()
    path = normalize(raw_path, root)
    absolute = Path(raw_path)
    if not absolute.is_absolute():
        absolute = root / path

    try:
        absolute.resolve().relative_to(root.resolve())
    except ValueError:
        return 0  # outside the repository (scratchpad, private storage): not this gate's job

    violations: list[str] = []
    size = absolute.stat().st_size if absolute.is_file() else None
    if (violation := private_media_violation(path, size)) is not None:
        violations.append(violation)
    if absolute.exists() and (violation := approved_asset_violation("M", path)) is not None:
        violations.append(violation)
    if (violation := generated_artifact_violation(path)) is not None:
        violations.append(violation)

    if violations:
        for violation in violations:
            print(f"agent-gate: {violation}", file=sys.stderr)
        return BLOCK_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
