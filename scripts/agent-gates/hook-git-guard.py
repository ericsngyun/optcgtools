#!/usr/bin/env python3
"""Claude Code PreToolUse hook for Bash.

When the command is a `git commit` (or `git push` with staged work pending),
run the staged agent gates first and block (exit 2) on any violation so
private media, approved-asset mutations, and generated artifacts never make
it into history.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_common import (  # noqa: E402
    BLOCK_EXIT_CODE,
    approved_asset_violation,
    generated_artifact_violation,
    private_media_violation,
    repo_root,
    staged_files,
)

COMMIT_PATTERN = re.compile(r"\bgit\b[^|;&]*\bcommit\b")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    command = (payload.get("tool_input", {}) or {}).get("command", "")
    if not COMMIT_PATTERN.search(command):
        return 0

    try:
        root = repo_root()
        entries = staged_files()
    except Exception:
        return 0  # not a git context; nothing to guard

    violations: list[str] = []
    for status, path in entries:
        if status != "D":
            absolute = root / path
            size = absolute.stat().st_size if absolute.is_file() else None
            if (violation := private_media_violation(path, size)) is not None:
                violations.append(violation)
            if (violation := generated_artifact_violation(path)) is not None:
                violations.append(violation)
        if (violation := approved_asset_violation(status, path)) is not None:
            violations.append(violation)

    if violations:
        for violation in violations:
            print(f"agent-gate (pre-commit): {violation}", file=sys.stderr)
        return BLOCK_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
