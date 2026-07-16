#!/usr/bin/env python3
"""Approved assets are append-only. Any modify/delete/rename under a path
containing an `approved` segment is blocked; new revisions are added, never
edited in place.

Usage:
  check-approved-assets.py --staged
  check-approved-assets.py --diff-stdin   # `git diff --name-status` lines on stdin
  check-approved-assets.py --status M PATH [PATH...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_common import (  # noqa: E402
    approved_asset_violation,
    normalize,
    repo_root,
    report,
    staged_files,
)


def main(argv: list[str]) -> int:
    entries: list[tuple[str, str]] = []
    if "--staged" in argv:
        entries = staged_files()
    elif "--diff-stdin" in argv:
        for line in sys.stdin.read().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                entries.append((parts[0][:1], parts[-1]))
    else:
        status = "M"
        paths: list[str] = []
        skip_next = False
        for index, arg in enumerate(argv):
            if skip_next:
                skip_next = False
                continue
            if arg == "--status":
                status = argv[index + 1]
                skip_next = True
            elif not arg.startswith("--"):
                paths.append(arg)
        root = repo_root()
        entries = [(status, normalize(path, root)) for path in paths]

    violations = [
        violation
        for status, path in entries
        if (violation := approved_asset_violation(status, path))
    ]
    return report(violations, "check-approved-assets")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
