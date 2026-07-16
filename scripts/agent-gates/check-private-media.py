#!/usr/bin/env python3
"""Block private card media, marketplace imagery, raw camera files, video
captures, model checkpoints, and oversized rasters from entering the public
repository.

Usage:
  check-private-media.py --staged        # staged additions/changes
  check-private-media.py --scan          # every tracked file
  check-private-media.py PATH [PATH...]  # explicit paths (hooks)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_common import (  # noqa: E402
    normalize,
    private_media_violation,
    repo_root,
    report,
    staged_files,
    tracked_files,
)


def main(argv: list[str]) -> int:
    root = repo_root()
    targets: list[str] = []
    if "--staged" in argv:
        targets = [path for status, path in staged_files() if status != "D"]
    elif "--scan" in argv:
        targets = tracked_files()
    else:
        targets = [normalize(arg, root) for arg in argv if not arg.startswith("--")]

    violations: list[str] = []
    for path in targets:
        absolute = root / path
        size = absolute.stat().st_size if absolute.is_file() else None
        violation = private_media_violation(path, size)
        if violation:
            violations.append(violation)
    return report(violations, "check-private-media")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
