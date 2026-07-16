"""Profile promotion state machine.

Implements the approval ladder from AGENTS.md / docs/agent-ops/approval-state-machine.md
as code: append-only, hash-chained promotion events with enforced transition rules,
human-only review transitions, per-revision input fingerprints, and the two-card
rule for finish-family proposals.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import RightsStatus
from .semantic import canonical_digest

PROMOTION_SCHEMA_VERSION = "1.1.0"
SUPPORTED_SCHEMA_VERSIONS = ("1.0.0", "1.1.0")
SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]{1,95}$"


class PromotionError(RuntimeError):
    """Raised when a promotion event violates the approval state machine."""


class Lane(StrEnum):
    """The two promotion lanes (ADR-0002). Lane B (`physical`) is the original,
    unmodified authenticated-capture ladder. Lane A (`reference`) is the new
    public-reference synthesis ladder; it never reaches a physical-validation
    state."""

    PHYSICAL = "physical"
    REFERENCE = "reference"


class ProfileState(StrEnum):
    HYPOTHESIS = "hypothesis"
    PUBLIC_REFERENCE_SUPPORTED = "public-reference-supported"
    AUTHENTICATED_CAPTURE_INGESTED = "authenticated-capture-ingested"
    QUALITY_APPROVED = "quality-approved"
    REGISTRATION_APPROVED = "registration-approved"
    MASKS_PROPOSED = "masks-proposed"
    MASKS_REVIEWED = "masks-reviewed"
    MATERIAL_MAPS_PROPOSED = "material-maps-proposed"
    MATERIAL_MAPS_REVIEWED = "material-maps-reviewed"
    PROFILE_FITTED = "profile-fitted"
    RENDER_REVIEWED = "render-reviewed"
    CAPTURE_VALIDATED = "capture-validated"
    PRODUCTION_VALIDATED = "production-validated"


STATE_ORDER: tuple[ProfileState, ...] = tuple(ProfileState)
STATE_RANK: dict[ProfileState, int] = {state: rank for rank, state in enumerate(STATE_ORDER)}

# Transitions only a named human reviewer may perform. Agents and CI may
# propose, ingest, and fit; they may never review, validate, or approve.
HUMAN_ONLY_TARGETS: frozenset[ProfileState] = frozenset(
    {
        ProfileState.QUALITY_APPROVED,
        ProfileState.REGISTRATION_APPROVED,
        ProfileState.MASKS_REVIEWED,
        ProfileState.MATERIAL_MAPS_REVIEWED,
        ProfileState.RENDER_REVIEWED,
        ProfileState.CAPTURE_VALIDATED,
        ProfileState.PRODUCTION_VALIDATED,
    }
)

# States a fresh revision may (re)start from.
REVISION_ENTRY_STATES: frozenset[ProfileState] = frozenset(
    {
        ProfileState.HYPOTHESIS,
        ProfileState.PUBLIC_REFERENCE_SUPPORTED,
        ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
    }
)

EVIDENCE_REQUIRED_FROM = ProfileState.QUALITY_APPROVED
HASHES_REQUIRED_FROM = ProfileState.AUTHENTICATED_CAPTURE_INGESTED
METRICS_REQUIRED_FROM = ProfileState.PROFILE_FITTED


class ReferenceState(StrEnum):
    """Lane A (`reference`) ladder: public-reference synthesis for cards without
    an authenticated physical capture. No member of this ladder is a
    physical-validation state; a reference-lane revision can never reach one."""

    HYPOTHESIS = "hypothesis"
    EXACT_VARIANT_VERIFIED = "exact-variant-verified"
    PUBLIC_REFERENCE_SUPPORTED = "public-reference-supported"
    REFERENCE_ASSETS_PROPOSED = "reference-assets-proposed"
    REFERENCE_PROFILE_FITTED = "reference-profile-fitted"
    ADVERSARIAL_REVIEW_PASSED = "adversarial-review-passed"
    INTERNAL_REFERENCE_PROTOTYPE = "internal-reference-prototype"
    PRODUCTION_REFERENCE_DERIVED = "production-reference-derived"


REFERENCE_STATE_ORDER: tuple[ReferenceState, ...] = tuple(ReferenceState)
REFERENCE_STATE_RANK: dict[ReferenceState, int] = {
    state: rank for rank, state in enumerate(REFERENCE_STATE_ORDER)
}

# Lane-indexed registries. Lane B (physical) registries are the original,
# byte-for-byte unchanged objects; Lane A (reference) registries are new. Keys
# and values are lane-local enum members (ProfileState for Lane.PHYSICAL,
# ReferenceState for Lane.REFERENCE); looked up only via `effective_lane`.
LANE_STATES: dict[Lane, tuple[Any, ...]] = {
    Lane.PHYSICAL: STATE_ORDER,
    Lane.REFERENCE: REFERENCE_STATE_ORDER,
}
LANE_RANK: dict[Lane, dict[Any, int]] = {
    Lane.PHYSICAL: STATE_RANK,
    Lane.REFERENCE: REFERENCE_STATE_RANK,
}
LANE_HUMAN_ONLY: dict[Lane, frozenset[Any]] = {
    Lane.PHYSICAL: HUMAN_ONLY_TARGETS,
    Lane.REFERENCE: frozenset(
        {
            ReferenceState.EXACT_VARIANT_VERIFIED,
            ReferenceState.ADVERSARIAL_REVIEW_PASSED,
            ReferenceState.INTERNAL_REFERENCE_PROTOTYPE,
            ReferenceState.PRODUCTION_REFERENCE_DERIVED,
        }
    ),
}
LANE_ENTRY_STATES: dict[Lane, frozenset[Any]] = {
    Lane.PHYSICAL: REVISION_ENTRY_STATES,
    # Every new reference bundle re-passes the human variant gate: a reference
    # revision may only enter at hypothesis.
    Lane.REFERENCE: frozenset({ReferenceState.HYPOTHESIS}),
}

REFERENCE_BUNDLE_REQUIRED_FROM = ReferenceState.EXACT_VARIANT_VERIFIED
REFERENCE_HASHES_REQUIRED_FROM = ReferenceState.PUBLIC_REFERENCE_SUPPORTED
REFERENCE_TIER_EVIDENCE_RIGHTS_REQUIRED_FROM = ReferenceState.REFERENCE_ASSETS_PROPOSED
REFERENCE_METRICS_REQUIRED_FROM = ReferenceState.REFERENCE_PROFILE_FITTED
# `internal-reference-prototype` is the first rank past the critic gate, so it
# (and everything after it) must carry the adversarial_review reference that
# earned adversarial-review-passed; evidence_packet is already required from
# REFERENCE_TIER_EVIDENCE_RIGHTS_REQUIRED_FROM, so this rank inherits it too.
REFERENCE_ADVERSARIAL_REVIEW_REQUIRED_FROM = ReferenceState.INTERNAL_REFERENCE_PROTOTYPE


class ActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    CI = "ci"


class PromotionAction(StrEnum):
    PROMOTE = "promote"
    DEMOTE = "demote"
    OPEN_REVISION = "open-revision"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PromotionEvent(StrictModel):
    schema_version: str = PROMOTION_SCHEMA_VERSION
    event_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{7,63}$")]
    sequence: int = Field(ge=0)
    profile_id: Annotated[str, Field(pattern=SLUG_PATTERN)]
    revision: int = Field(ge=1)
    action: PromotionAction
    from_state: ProfileState | ReferenceState | None = None
    to_state: ProfileState | ReferenceState
    actor: str = Field(min_length=1, max_length=160)
    actor_type: ActorType
    technical_reviewer: str | None = Field(default=None, max_length=160)
    rights_reviewer: str | None = Field(default=None, max_length=160)
    source_session: Annotated[str | None, Field(pattern=SLUG_PATTERN)] = None
    input_hashes: list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]] = Field(
        default_factory=list
    )
    fingerprint: dict[str, str] = Field(
        default_factory=dict,
        description="Identity of captures, checkpoints, extraction algorithms, and renderer version",
    )
    metrics: dict[str, float] = Field(default_factory=dict)
    rights_status: RightsStatus | None = None
    evidence_packet: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=4000)
    # Lane A (reference) fields. All default to None so exclude_none=True
    # reproduces historical schema-1.0.0 physical digests byte-for-byte.
    lane: Lane | None = None
    reference_bundle_id: Annotated[str | None, Field(pattern=SLUG_PATTERN)] = None
    source_quality_tier: Annotated[str | None, Field(pattern=r"^[ABC]$")] = None
    adversarial_review: str | None = Field(default=None, max_length=500)
    linked_reference_revision: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previous_event_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None
    event_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_state_fields(cls, data: Any) -> Any:
        """Resolve `from_state`/`to_state` against the correct lane-local enum
        before pydantic's field validation runs, since `hypothesis` and
        `public-reference-supported` are valid members of both ladders and a
        plain Union would otherwise always resolve to the physical enum."""
        if not isinstance(data, dict):
            return data
        lane_raw = data.get("lane")
        lane_value = lane_raw.value if isinstance(lane_raw, StrEnum) else lane_raw
        lane = Lane(lane_value) if lane_value else Lane.PHYSICAL
        state_enum = ProfileState if lane is Lane.PHYSICAL else ReferenceState
        for key in ("from_state", "to_state"):
            value = data.get(key)
            if value is None:
                continue
            raw_value = value.value if isinstance(value, StrEnum) else value
            try:
                data[key] = state_enum(raw_value)
            except ValueError as exc:
                raise ValueError(
                    f"'{raw_value}' is not a valid {lane.value}-lane state"
                ) from exc
        return data

    @field_validator("actor")
    @classmethod
    def actor_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("actor must be named")
        return value

    @field_validator("schema_version")
    @classmethod
    def schema_version_supported(cls, value: str) -> str:
        if value not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported promotion schema_version '{value}'")
        return value

    @model_validator(mode="after")
    def demotion_requires_reason(self) -> PromotionEvent:
        if self.action is PromotionAction.DEMOTE and not (self.reason and self.reason.strip()):
            raise ValueError("demotions must state the failed gate or superseding evidence")
        return self

    @model_validator(mode="after")
    def reference_lane_requires_current_schema(self) -> PromotionEvent:
        if self.effective_lane is Lane.REFERENCE and self.schema_version == "1.0.0":
            raise ValueError(
                "reference-lane events require promotion schema_version 1.1.0 or later"
            )
        return self

    @property
    def effective_lane(self) -> Lane:
        return self.lane or Lane.PHYSICAL

    def content_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        payload.pop("event_digest", None)
        return canonical_digest(payload)


class RevisionState(StrictModel):
    profile_id: str
    revision: int
    state: ProfileState | ReferenceState
    lane: Lane
    fingerprint: dict[str, str]
    head_digest: str | None


def new_event_id() -> str:
    return f"pro-{uuid.uuid4().hex}"


def load_promotion_ledger(path: Path, *, verify: bool = True) -> list[PromotionEvent]:
    if not path.is_file():
        return []
    events: list[PromotionEvent] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(PromotionEvent.model_validate_json(line))
        except ValueError as exc:
            raise PromotionError(f"invalid promotion event on line {line_number}: {exc}") from exc
    if verify:
        verify_promotion_ledger(events)
    return events


def verify_promotion_ledger(events: list[PromotionEvent], *, replay: bool = True) -> None:
    """Verify hash-chain integrity AND (by default) semantically replay every
    event through validate_transition. A valid-digest but semantically
    malformed ledger — lane laundering, human-only bypass, rank jumps — fails
    closed (independent-review finding, PR #15)."""
    previous_digest: str | None = None
    for index, event in enumerate(events):
        if event.sequence != index:
            raise PromotionError(f"promotion ledger sequence break at index {index}")
        if event.previous_event_digest != previous_digest:
            raise PromotionError(f"promotion ledger chain break at sequence {index}")
        if event.event_digest != event.content_digest():
            raise PromotionError(
                f"promotion event {event.event_id} digest mismatch: ledger was modified"
            )
        previous_digest = event.event_digest

    if replay:
        seen: list[PromotionEvent] = []
        for event in events:
            try:
                validate_transition(seen, event)
            except PromotionError as exc:
                raise PromotionError(
                    f"semantic replay failed at sequence {event.sequence} "
                    f"({event.event_id}): {exc}"
                ) from exc
            seen.append(event)


def current_revision_state(
    events: list[PromotionEvent], profile_id: str
) -> RevisionState | None:
    state: RevisionState | None = None
    fingerprint: dict[str, str] = {}
    lane = Lane.PHYSICAL
    for event in events:
        if event.profile_id != profile_id:
            continue
        if state is None or event.revision != state.revision:
            fingerprint = dict(event.fingerprint)
            # Lane is fixed at open-revision and is part of revision identity.
            lane = event.effective_lane
        else:
            fingerprint.update(event.fingerprint)
        state = RevisionState(
            profile_id=profile_id,
            revision=event.revision,
            state=event.to_state,
            lane=lane,
            fingerprint=fingerprint,
            head_digest=event.event_digest,
        )
    return state


def validate_transition(
    events: list[PromotionEvent],
    candidate: PromotionEvent,
) -> None:
    """Enforce the approval state machine before a candidate event is appended."""
    latest = current_revision_state(events, candidate.profile_id)

    if candidate.action is PromotionAction.OPEN_REVISION:
        expected_revision = 1 if latest is None else latest.revision + 1
        if candidate.revision != expected_revision:
            raise PromotionError(
                f"revision must be {expected_revision}, got {candidate.revision}"
            )
        if candidate.to_state not in LANE_ENTRY_STATES[candidate.effective_lane]:
            if candidate.effective_lane is Lane.PHYSICAL:
                raise PromotionError(
                    "a new revision must start from hypothesis, public-reference-supported, "
                    "or authenticated-capture-ingested"
                )
            raise PromotionError(
                "a new reference-lane revision must start from hypothesis; every new "
                "bundle re-passes the human variant gate"
            )
    else:
        if latest is None:
            raise PromotionError("first event for a profile must be an open-revision event")
        if candidate.revision != latest.revision:
            raise PromotionError(
                "promotion events must stay on the active revision; "
                "open a new revision to change inputs"
            )
        # Lane is fixed at open-revision and is part of revision identity; a
        # later event (including a demotion) may never switch lanes.
        if candidate.effective_lane is not latest.lane:
            raise PromotionError(
                f"event lane '{candidate.effective_lane}' does not match "
                f"revision lane '{latest.lane}'"
            )
        if candidate.from_state is not latest.state:
            raise PromotionError(
                f"from_state '{candidate.from_state}' does not match "
                f"current state '{latest.state}'"
            )
        # Changing any fingerprint component mid-revision is forbidden: a new
        # capture, checkpoint, algorithm, or renderer version is a new revision.
        for key, value in candidate.fingerprint.items():
            if key in latest.fingerprint and latest.fingerprint[key] != value:
                raise PromotionError(
                    f"fingerprint '{key}' changed within revision {candidate.revision}; "
                    "open a new revision instead"
                )

    if candidate.action is PromotionAction.PROMOTE:
        rank_map = LANE_RANK[candidate.effective_lane]
        current_rank = rank_map[latest.state] if latest else -1
        if rank_map[candidate.to_state] != current_rank + 1:
            raise PromotionError(
                f"promotion must advance one state at a time; "
                f"'{latest.state if latest else 'none'}' cannot jump to '{candidate.to_state}'"
            )
    elif candidate.action is PromotionAction.DEMOTE:
        rank_map = LANE_RANK[candidate.effective_lane]
        if latest is None or rank_map[candidate.to_state] >= rank_map[latest.state]:
            raise PromotionError("demotion must move to a strictly earlier state")

    _validate_requirements(candidate)


def _validate_requirements(candidate: PromotionEvent) -> None:
    lane = candidate.effective_lane
    target = candidate.to_state
    rank = LANE_RANK[lane][target]
    human_only = LANE_HUMAN_ONLY[lane]

    if candidate.action is not PromotionAction.DEMOTE:
        if target in human_only and candidate.actor_type is not ActorType.HUMAN:
            raise PromotionError(
                f"transition to '{target}' is human-only; actor_type is "
                f"'{candidate.actor_type}'"
            )

        if lane is Lane.PHYSICAL:
            if rank >= STATE_RANK[HASHES_REQUIRED_FROM]:
                if not candidate.source_session:
                    raise PromotionError(f"'{target}' requires a source_session reference")
                if not candidate.input_hashes:
                    raise PromotionError(f"'{target}' requires input content hashes")

            if rank >= STATE_RANK[EVIDENCE_REQUIRED_FROM] and not candidate.evidence_packet:
                raise PromotionError(f"'{target}' requires an evidence packet reference")

            if rank >= STATE_RANK[METRICS_REQUIRED_FROM] and not candidate.metrics:
                raise PromotionError(f"'{target}' requires quantitative metrics")

            if target in human_only and not candidate.technical_reviewer:
                raise PromotionError(f"'{target}' requires a named technical_reviewer")

            if target in (
                ProfileState.CAPTURE_VALIDATED,
                ProfileState.PRODUCTION_VALIDATED,
            ) and candidate.rights_status in (None, RightsStatus.UNKNOWN):
                raise PromotionError(f"'{target}' requires a resolved rights_status")

            if target is ProfileState.PRODUCTION_VALIDATED and not candidate.rights_reviewer:
                raise PromotionError(
                    "'production-validated' requires a named rights_reviewer in addition "
                    "to the technical_reviewer"
                )
        else:
            _validate_reference_requirements(candidate, rank=rank, human_only=human_only)


def _validate_reference_requirements(
    candidate: PromotionEvent, *, rank: int, human_only: frozenset[Any]
) -> None:
    """Lane A (reference) requirement thresholds. See ADR-0002. `reference_bundle_id`
    stands in for `source_session`: the reference lane has no source capture session."""
    target = candidate.to_state
    ref_rank = LANE_RANK[Lane.REFERENCE]

    # Tier C source quality is never eligible for promotion, at any rank.
    if candidate.source_quality_tier == "C":
        raise PromotionError(
            "source_quality_tier 'C' is never eligible for promotion; only 'A', or "
            "'B' with recorded human review, may reach reference-assets-proposed or later"
        )

    if rank >= ref_rank[REFERENCE_BUNDLE_REQUIRED_FROM] and not candidate.reference_bundle_id:
        raise PromotionError(f"'{target}' requires a reference_bundle_id")

    if rank >= ref_rank[REFERENCE_HASHES_REQUIRED_FROM]:
        if not candidate.input_hashes:
            raise PromotionError(f"'{target}' requires input content hashes")
        if not candidate.reference_bundle_id:
            raise PromotionError(
                f"'{target}' requires a reference_bundle_id in place of source_session"
            )

    if rank >= ref_rank[REFERENCE_TIER_EVIDENCE_RIGHTS_REQUIRED_FROM]:
        if candidate.source_quality_tier not in ("A", "B"):
            raise PromotionError(
                f"'{target}' requires source_quality_tier 'A', or 'B' with human review"
            )
        # Independent-review finding (PR #15): a bare self-declared "B" is not
        # auditable. Tier-B events must bind the bundle's fail-closed
        # BundleTierRecord into the ledger via a fingerprint digest so a
        # reviewer can recompute and confirm the recorded human review.
        # (Content verification happens in optcg-promote via
        # --bundle-tier-record; CI replays ledgers without bundle access.)
        if candidate.source_quality_tier == "B":
            tier_digest = candidate.fingerprint.get("bundle-tier-record", "")
            if not re.fullmatch(r"[0-9a-f]{64}", tier_digest):
                raise PromotionError(
                    f"'{target}' with source_quality_tier 'B' requires fingerprint "
                    "'bundle-tier-record' — the hex64 digest of the human-reviewed "
                    "BundleTierRecord produced by `optcg-reference tier`"
                )
        if not candidate.evidence_packet:
            raise PromotionError(f"'{target}' requires an evidence packet reference")
        if candidate.rights_status in (None, RightsStatus.UNKNOWN):
            raise PromotionError(f"'{target}' requires a resolved rights_status")

    if rank >= ref_rank[REFERENCE_METRICS_REQUIRED_FROM] and not candidate.metrics:
        raise PromotionError(f"'{target}' requires quantitative metrics")

    if (
        rank >= ref_rank[REFERENCE_ADVERSARIAL_REVIEW_REQUIRED_FROM]
        and not candidate.adversarial_review
    ):
        raise PromotionError(f"'{target}' requires an adversarial_review reference")

    if target in human_only and not candidate.technical_reviewer:
        raise PromotionError(f"'{target}' requires a named technical_reviewer")

    if target is ReferenceState.PRODUCTION_REFERENCE_DERIVED and not candidate.rights_reviewer:
        raise PromotionError(
            "'production-reference-derived' requires a named rights_reviewer in "
            "addition to the technical_reviewer"
        )


def append_promotion(ledger_path: Path, event: PromotionEvent) -> PromotionEvent:
    events = load_promotion_ledger(ledger_path)
    validate_transition(events, event)

    event.sequence = len(events)
    event.previous_event_digest = events[-1].event_digest if events else None
    event.event_digest = event.content_digest()

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json(exclude_none=True) + "\n")
        handle.flush()
    return event


class FamilyCardEvidence(StrictModel):
    profile_id: Annotated[str, Field(pattern=SLUG_PATTERN)]
    source_session: Annotated[str, Field(pattern=SLUG_PATTERN)]
    state: ProfileState
    card_id: str = Field(min_length=2, max_length=64)


def validate_family_proposal(family: str, cards: list[FamilyCardEvidence]) -> None:
    """One physical card cannot establish a reusable finish family."""
    validated = [
        card for card in cards if STATE_RANK[card.state] >= STATE_RANK[ProfileState.CAPTURE_VALIDATED]
    ]
    distinct_cards = {card.card_id for card in validated}
    distinct_sessions = {card.source_session for card in validated}
    if len(distinct_cards) < 2 or len(distinct_sessions) < 2:
        raise PromotionError(
            f"finish family '{family}' requires at least two distinct authenticated, "
            f"capture-validated cards; found {len(distinct_cards)}"
        )


class ReferenceFamilyCardEvidence(StrictModel):
    profile_id: Annotated[str, Field(pattern=SLUG_PATTERN)]
    reference_bundle_id: Annotated[str, Field(pattern=SLUG_PATTERN)]
    state: ReferenceState
    card_id: str = Field(min_length=2, max_length=64)


def validate_reference_family_proposal(
    family: str, cards: list[ReferenceFamilyCardEvidence]
) -> None:
    """Reference-lane finish families are never established by rarity or
    illustrator similarity alone: this requires at least two distinct card_ids
    AND two distinct reference_bundle_ids, each at reference-state rank
    >= adversarial-review-passed, with materially similar observed response.
    Every card retains its own foil/metallic/suppression/composition/art-texture
    masks regardless of shared family membership."""
    threshold_rank = LANE_RANK[Lane.REFERENCE][ReferenceState.ADVERSARIAL_REVIEW_PASSED]
    eligible = [
        card for card in cards if LANE_RANK[Lane.REFERENCE][card.state] >= threshold_rank
    ]
    distinct_cards = {card.card_id for card in eligible}
    distinct_bundles = {card.reference_bundle_id for card in eligible}
    if len(distinct_cards) < 2 or len(distinct_bundles) < 2:
        raise PromotionError(
            f"reference finish family '{family}' requires at least two distinct card_ids "
            "and two distinct reference_bundle_ids at adversarial-review-passed or later; "
            f"found {len(distinct_cards)} card(s) and {len(distinct_bundles)} bundle(s)"
        )
