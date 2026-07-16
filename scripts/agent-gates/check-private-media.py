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
from gate_common import (
    normalize,
    private_media_violation,
    repo_root,
    report,
    staged_files,
    tracked_files,
)

# Lane A (reference) private bundle roots (ADR-0002): the public repository
# holds only schemas, code, source URLs, hashes, and rights-permitted derived
# assets. The bundle's private media, normalization, and registration
# directories live outside the repo and must never be committed — treated
# the same way raw-captures/ is.
REFERENCE_BUNDLE_PRIVATE_PREFIXES = ("public-reference-bundles/",)
REFERENCE_BUNDLE_PRIVATE_SEGMENTS = frozenset(
    {
        "private-media",
        "normalized",
        "registered",
        # Full ADR-0002 bundle layout: diagnostics embed private card imagery
        # (e.g. interference overlays), so every bundle directory is blocked by
        # name, not only by the raster/video extension backstop.
        "appearance",
        "semantic",
        "diagnostics",
        "renders",
        "sources",
    }
)


def reference_bundle_private_root_violation(path: str) -> str | None:
    lowered = path.lower()
    for prefix in REFERENCE_BUNDLE_PRIVATE_PREFIXES:
        if lowered.startswith(prefix) or f"/{prefix}" in lowered:
            return (
                "private reference-bundle directory must never enter the repository: "
                f"{path}"
            )
    if set(Path(lowered).parts) & REFERENCE_BUNDLE_PRIVATE_SEGMENTS:
        return (
            "private reference-bundle directory must never enter the repository: "
            f"{path}"
        )
    return None


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
        violation = private_media_violation(path, size) or reference_bundle_private_root_violation(
            path
        )
        if violation:
            violations.append(violation)
    return report(violations, "check-private-media")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
