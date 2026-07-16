#!/usr/bin/env python3
"""Validate evidence packets: schema compliance plus the misleading-language
gate. Automated reports may not claim accuracy, validation, or approval
without the corresponding evidence state and a named reviewer.

Run inside the project environment:
  uv run python scripts/agent-gates/check-evidence-packet.py <packet.json> [...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import jsonschema

BLOCK_EXIT_CODE = 2
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs/agent-ops/evidence-packet.schema.json"

MISLEADING_WORDS = (
    "accurate",
    "accuracy",
    "validated",
    "validation",
    "matched",
    "matching",
    "faithful",
    "faithfully",
    "fidelity",
    "production-ready",
    "production-grade",
    "approved",
)
# Official state names and gate vocabulary may be referenced without making a claim.
STATE_NAME_TOKENS = (
    "capture-validated",
    "production-validated",
    "photo-validated",
    "quality-approved",
    "registration-approved",
    "technically-approved",
    "rights-approved",
    "production-approved",
    "approved-item",
    "approve-item",
    # Lane A (reference) ladder state names — ADR-0002.
    "hypothesis",
    "exact-variant-verified",
    "public-reference-supported",
    "reference-assets-proposed",
    "reference-profile-fitted",
    "adversarial-review-passed",
    "production-reference-derived",
)
TRUSTED_EVIDENCE_STATES = ("measured", "human-reviewed")
HUMAN_ONLY_STATES = {
    "quality-approved",
    "registration-approved",
    "masks-reviewed",
    "material-maps-reviewed",
    "render-reviewed",
    "capture-validated",
    "production-validated",
    # Lane A (reference) human-only ladder states.
    "exact-variant-verified",
    "adversarial-review-passed",
    "production-reference-derived",
}
# Lane A output must never claim physical measurement or capture validation
# (defense in depth, alongside review.py's publication gate).
FORBIDDEN_REFERENCE_PHRASES = (
    "capture-validated",
    "physically measured",
    "physically exact",
)
# The complete Lane A ladder: a reference-lane packet may only recommend a
# transition to one of these states.
REFERENCE_LADDER_STATES = frozenset(
    {
        "hypothesis",
        "exact-variant-verified",
        "public-reference-supported",
        "reference-assets-proposed",
        "reference-profile-fitted",
        "adversarial-review-passed",
        "production-reference-derived",
    }
)


def misleading_words_in(text: str) -> list[str]:
    lowered = text.lower()
    for token in STATE_NAME_TOKENS:
        lowered = lowered.replace(token, " ")
    return [
        word
        for word in MISLEADING_WORDS
        if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", lowered)
    ]


def check_packet(packet: dict) -> list[str]:
    errors: list[str] = []
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for issue in sorted(validator.iter_errors(packet), key=str):
        errors.append(f"schema violation: {issue.message}")
    if errors:
        return errors

    reviewer = (packet.get("reviewer") or "").strip()
    lane = packet.get("lane")

    for section in ("observations", "inferences"):
        for statement in packet.get(section, []):
            words = misleading_words_in(statement["statement"])
            if words and statement["evidence_state"] not in TRUSTED_EVIDENCE_STATES:
                errors.append(
                    f"{section} claim uses {words} but its evidence state is "
                    f"'{statement['evidence_state']}'; only measured or human-reviewed "
                    "statements may make that claim"
                )
            if words and not reviewer:
                errors.append(
                    f"{section} claim uses {words} without a named reviewer on the packet"
                )
            if lane == "reference" and statement["evidence_state"] == "measured":
                errors.append(
                    f"{section} claim has evidence_state 'measured'; reference-lane "
                    "packets never mark appearance/material claims as physically measured"
                )

    transition = packet.get("recommended_state_transition", {})
    justification = transition.get("justification", "")
    words = misleading_words_in(justification)
    if words and not reviewer:
        errors.append(
            f"state-transition justification uses {words} without a named reviewer"
        )

    to_state = transition.get("to_state")
    if to_state in HUMAN_ONLY_STATES and not packet.get("human_approval_required", True):
        errors.append(
            f"recommended transition to '{to_state}' is human-only; "
            "human_approval_required must be true"
        )

    free_text: list[tuple[str, str]] = []
    for section in ("subjective_judgments", "known_failures", "unresolved_questions"):
        free_text.extend((section, text) for text in packet.get(section, []))
    free_text.extend(
        ("visual_checks", check.get("description", "")) for check in packet.get("visual_checks", [])
    )
    for section, text in free_text:
        words = misleading_words_in(text)
        if words and not reviewer:
            errors.append(
                f"{section} may not claim {words} without a named reviewer: {text!r}"
            )

    if lane == "reference":
        scanned: list[tuple[str, str]] = []
        for section in ("observations", "inferences"):
            scanned.extend(
                (section, statement["statement"]) for statement in packet.get(section, [])
            )
        scanned.append(("recommended_state_transition.justification", justification))
        scanned.extend(free_text)
        for section, text in scanned:
            found = [phrase for phrase in FORBIDDEN_REFERENCE_PHRASES if phrase in text.lower()]
            if found:
                errors.append(
                    f"{section} uses forbidden reference-lane phrase(s) {found}: {text!r}"
                )

        recommended_state = transition.get("to_state")
        if recommended_state and recommended_state not in REFERENCE_LADDER_STATES:
            errors.append(
                f"reference-lane packet recommends transition to '{recommended_state}', "
                "which is not a reference-lane state"
            )

    return errors


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check-evidence-packet.py <packet.json> [...]", file=sys.stderr)
        return BLOCK_EXIT_CODE

    failed = False
    for raw in argv:
        path = Path(raw)
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"check-evidence-packet: BLOCKED: {path}: {exc}", file=sys.stderr)
            failed = True
            continue
        errors = check_packet(packet)
        if errors:
            failed = True
            for error in errors:
                print(f"check-evidence-packet: BLOCKED: {path}: {error}", file=sys.stderr)
        else:
            print(f"check-evidence-packet: {path}: valid")

    return BLOCK_EXIT_CODE if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
