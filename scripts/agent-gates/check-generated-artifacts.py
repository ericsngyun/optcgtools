#!/usr/bin/env python3
"""Block generated artifacts (build output, caches, reports, virtualenvs)
from being committed.

Usage:
  check-generated-artifacts.py --staged
  check-generated-artifacts.py PATH [PATH...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_common import (  # noqa: E402
    generated_artifact_violation,
    normalize,
    repo_root,
    report,
    staged_files,
)


def main(argv: list[str]) -> int:
    if "--staged" in argv:
        targets = [path for status, path in staged_files() if status != "D"]
    else:
        root = repo_root()
        targets = [normalize(arg, root) for arg in argv if not arg.startswith("--")]

    violations = [
        violation for path in targets if (violation := generated_artifact_violation(path))
    ]
    return report(violations, "check-generated-artifacts")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
