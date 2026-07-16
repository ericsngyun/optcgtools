"""Profile promotion state machine.

Implements the approval ladder from AGENTS.md / docs/agent-ops/approval-state-machine.md
as code: append-only, hash-chained promotion events with enforced transition rules,
human-only review transitions, per-revision input fingerprints, and the two-card
rule for finish-family proposals.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import RightsStatus
from .semantic import canonical_digest

PROMOTION_SCHEMA_VERSION = "1.0.0"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]{1,95}$"


class PromotionError(RuntimeError):
    """Raised when a promotion event violates the approval state machine."""


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
    from_state: ProfileState | None = None
    to_state: ProfileState
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previous_event_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None
    event_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None

    @field_validator("actor")
    @classmethod
    def actor_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("actor must be named")
        return value

    @model_validator(mode="after")
    def demotion_requires_reason(self) -> PromotionEvent:
        if self.action is PromotionAction.DEMOTE and not (self.reason and self.reason.strip()):
            raise ValueError("demotions must state the failed gate or superseding evidence")
        return self

    def content_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        payload.pop("event_digest", None)
        return canonical_digest(payload)


class RevisionState(StrictModel):
    profile_id: str
    revision: int
    state: ProfileState
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


def verify_promotion_ledger(events: list[PromotionEvent]) -> None:
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


def current_revision_state(
    events: list[PromotionEvent], profile_id: str
) -> RevisionState | None:
    state: RevisionState | None = None
    fingerprint: dict[str, str] = {}
    for event in events:
        if event.profile_id != profile_id:
            continue
        if state is None or event.revision != state.revision:
            fingerprint = dict(event.fingerprint)
        else:
            fingerprint.update(event.fingerprint)
        state = RevisionState(
            profile_id=profile_id,
            revision=event.revision,
            state=event.to_state,
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
        if candidate.to_state not in REVISION_ENTRY_STATES:
            raise PromotionError(
                "a new revision must start from hypothesis, public-reference-supported, "
                "or authenticated-capture-ingested"
            )
    else:
        if latest is None:
            raise PromotionError("first event for a profile must be an open-revision event")
        if candidate.revision != latest.revision:
            raise PromotionError(
                "promotion events must stay on the active revision; "
                "open a new revision to change inputs"
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
        current_rank = STATE_RANK[latest.state] if latest else -1
        if STATE_RANK[candidate.to_state] != current_rank + 1:
            raise PromotionError(
                f"promotion must advance one state at a time; "
                f"'{latest.state if latest else 'none'}' cannot jump to '{candidate.to_state}'"
            )
    elif candidate.action is PromotionAction.DEMOTE:
        if latest is None or STATE_RANK[candidate.to_state] >= STATE_RANK[latest.state]:
            raise PromotionError("demotion must move to a strictly earlier state")

    _validate_requirements(candidate)


def _validate_requirements(candidate: PromotionEvent) -> None:
    target = candidate.to_state
    rank = STATE_RANK[target]

    if candidate.action is not PromotionAction.DEMOTE:
        if target in HUMAN_ONLY_TARGETS and candidate.actor_type is not ActorType.HUMAN:
            raise PromotionError(
                f"transition to '{target}' is human-only; actor_type is "
                f"'{candidate.actor_type}'"
            )

        if rank >= STATE_RANK[HASHES_REQUIRED_FROM]:
            if not candidate.source_session:
                raise PromotionError(f"'{target}' requires a source_session reference")
            if not candidate.input_hashes:
                raise PromotionError(f"'{target}' requires input content hashes")

        if rank >= STATE_RANK[EVIDENCE_REQUIRED_FROM] and not candidate.evidence_packet:
            raise PromotionError(f"'{target}' requires an evidence packet reference")

        if rank >= STATE_RANK[METRICS_REQUIRED_FROM] and not candidate.metrics:
            raise PromotionError(f"'{target}' requires quantitative metrics")

        if target in HUMAN_ONLY_TARGETS and not candidate.technical_reviewer:
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
