#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from optcg_material.candidate import CandidateError, canonicalize_render


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Warp a perspective renderer screenshot into canonical card coordinates."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--quad-json", required=True)
    parser.add_argument("--width", type=int, default=1436)
    parser.add_argument("--height", type=int, default=2000)
    args = parser.parse_args()

    try:
        canonicalize_render(
            args.source,
            args.destination,
            args.quad_json,
            width=args.width,
            height=args.height,
        )
    except (CandidateError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
