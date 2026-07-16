#!/usr/bin/env python3
"""Validate a promotion ledger against the approval state machine.

Replays every event through the coded transition rules: chain integrity,
one-state-at-a-time promotion, human-only review transitions, required
session references, input hashes, metrics, reviewers, and rights status.

Run inside the project environment:
  uv run python scripts/agent-gates/check-profile-promotion.py <ledger.jsonl> [...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from optcg_material.promotion import (  # noqa: E402
    PromotionError,
    load_promotion_ledger,
    validate_transition,
)

BLOCK_EXIT_CODE = 2


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check-profile-promotion.py <promotion-ledger.jsonl> [...]", file=sys.stderr)
        return BLOCK_EXIT_CODE

    failures: list[str] = []
    for raw in argv:
        ledger_path = Path(raw)
        try:
            events = load_promotion_ledger(ledger_path)
            for index, event in enumerate(events):
                validate_transition(events[:index], event)
            print(f"check-profile-promotion: {ledger_path}: {len(events)} events valid")
        except (PromotionError, OSError) as exc:
            failures.append(f"{ledger_path}: {exc}")

    for failure in failures:
        print(f"check-profile-promotion: BLOCKED: {failure}", file=sys.stderr)
    return BLOCK_EXIT_CODE if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
