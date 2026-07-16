from __future__ import annotations

from pathlib import Path

import pytest

from optcg_material.models import RightsStatus
from optcg_material.promotion import (
    ActorType,
    FamilyCardEvidence,
    ProfileState,
    PromotionAction,
    PromotionError,
    PromotionEvent,
    append_promotion,
    current_revision_state,
    load_promotion_ledger,
    new_event_id,
    validate_family_proposal,
)

HASH = "a" * 64


def event(**overrides) -> PromotionEvent:
    payload = {
        "event_id": new_event_id(),
        "sequence": 0,
        "profile_id": "op05-119-luffy",
        "revision": 1,
        "action": PromotionAction.PROMOTE,
        "to_state": ProfileState.HYPOTHESIS,
        "actor": "pipeline-agent",
        "actor_type": ActorType.AGENT,
    }
    payload.update(overrides)
    return PromotionEvent(**payload)


def open_revision(ledger: Path, revision: int = 1) -> None:
    append_promotion(
        ledger,
        event(
            action=PromotionAction.OPEN_REVISION,
            revision=revision,
            to_state=ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
            source_session="op05-119-luffy-en-001",
            input_hashes=[HASH],
            fingerprint={"captures": HASH, "renderer": "three-r185"},
        ),
    )


def promote(ledger: Path, from_state: ProfileState, to_state: ProfileState, **overrides) -> None:
    defaults = {
        "action": PromotionAction.PROMOTE,
        "from_state": from_state,
        "to_state": to_state,
        "source_session": "op05-119-luffy-en-001",
        "input_hashes": [HASH],
        "evidence_packet": "review/evidence/packet.json",
        "actor": "GenkiStuff reviewer",
        "actor_type": ActorType.HUMAN,
        "technical_reviewer": "GenkiStuff reviewer",
    }
    defaults.update(overrides)
    append_promotion(ledger, event(**defaults))


def test_first_event_must_open_revision(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    with pytest.raises(PromotionError, match="open-revision"):
        append_promotion(ledger, event())


def test_promotion_advances_one_state_at_a_time(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    with pytest.raises(PromotionError, match="one state at a time"):
        promote(
            ledger,
            ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
            ProfileState.MASKS_REVIEWED,
        )
    promote(ledger, ProfileState.AUTHENTICATED_CAPTURE_INGESTED, ProfileState.QUALITY_APPROVED)
    state = current_revision_state(load_promotion_ledger(ledger), "op05-119-luffy")
    assert state is not None and state.state is ProfileState.QUALITY_APPROVED


def test_agent_cannot_perform_human_only_transition(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    with pytest.raises(PromotionError, match="human-only"):
        promote(
            ledger,
            ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
            ProfileState.QUALITY_APPROVED,
            actor="pipeline-agent",
            actor_type=ActorType.AGENT,
        )


def test_review_states_require_evidence_and_reviewer(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    with pytest.raises(PromotionError, match="evidence packet"):
        promote(
            ledger,
            ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
            ProfileState.QUALITY_APPROVED,
            evidence_packet=None,
        )
    with pytest.raises(PromotionError, match="technical_reviewer"):
        promote(
            ledger,
            ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
            ProfileState.QUALITY_APPROVED,
            technical_reviewer=None,
        )


def test_production_requires_rights_reviewer_and_rights_status(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    ladder = [
        ProfileState.QUALITY_APPROVED,
        ProfileState.REGISTRATION_APPROVED,
        ProfileState.MASKS_PROPOSED,
        ProfileState.MASKS_REVIEWED,
        ProfileState.MATERIAL_MAPS_PROPOSED,
        ProfileState.MATERIAL_MAPS_REVIEWED,
        ProfileState.PROFILE_FITTED,
        ProfileState.RENDER_REVIEWED,
        ProfileState.CAPTURE_VALIDATED,
    ]
    previous = ProfileState.AUTHENTICATED_CAPTURE_INGESTED
    for state in ladder:
        promote(
            ledger,
            previous,
            state,
            metrics={"linear_rgb_error": 0.03},
            rights_status=RightsStatus.OWNED_CAPTURE,
        )
        previous = state

    with pytest.raises(PromotionError, match="rights_reviewer"):
        promote(
            ledger,
            ProfileState.CAPTURE_VALIDATED,
            ProfileState.PRODUCTION_VALIDATED,
            metrics={"linear_rgb_error": 0.03},
            rights_status=RightsStatus.OWNED_CAPTURE,
        )

    promote(
        ledger,
        ProfileState.CAPTURE_VALIDATED,
        ProfileState.PRODUCTION_VALIDATED,
        metrics={"linear_rgb_error": 0.03},
        rights_status=RightsStatus.OWNED_CAPTURE,
        rights_reviewer="GenkiStuff rights reviewer",
    )
    state = current_revision_state(load_promotion_ledger(ledger), "op05-119-luffy")
    assert state is not None and state.state is ProfileState.PRODUCTION_VALIDATED


def test_fingerprint_change_requires_new_revision(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    with pytest.raises(PromotionError, match="new revision"):
        promote(
            ledger,
            ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
            ProfileState.QUALITY_APPROVED,
            fingerprint={"captures": "b" * 64},
        )
    append_promotion(
        ledger,
        event(
            action=PromotionAction.OPEN_REVISION,
            revision=2,
            to_state=ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
            source_session="op05-119-luffy-en-002",
            input_hashes=["b" * 64],
            fingerprint={"captures": "b" * 64},
        ),
    )
    state = current_revision_state(load_promotion_ledger(ledger), "op05-119-luffy")
    assert state is not None and state.revision == 2


def test_demotion_requires_reason_and_moves_backward(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    promote(ledger, ProfileState.AUTHENTICATED_CAPTURE_INGESTED, ProfileState.QUALITY_APPROVED)

    with pytest.raises(ValueError, match="failed gate"):
        event(action=PromotionAction.DEMOTE, to_state=ProfileState.HYPOTHESIS)

    append_promotion(
        ledger,
        event(
            action=PromotionAction.DEMOTE,
            from_state=ProfileState.QUALITY_APPROVED,
            to_state=ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
            reason="registration diagnostics show frame swim; earlier gate failed",
            actor_type=ActorType.CI,
            actor="quality-gate",
        ),
    )
    state = current_revision_state(load_promotion_ledger(ledger), "op05-119-luffy")
    assert state is not None and state.state is ProfileState.AUTHENTICATED_CAPTURE_INGESTED


def test_tampered_promotion_ledger_detected(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    text = ledger.read_text(encoding="utf-8").replace("op05-119-luffy-en-001", "op05-119-luffy-en-999")
    ledger.write_text(text, encoding="utf-8")
    with pytest.raises(PromotionError, match="digest mismatch"):
        load_promotion_ledger(ledger)


def test_family_requires_two_validated_cards() -> None:
    one_card = [
        FamilyCardEvidence(
            profile_id="op05-119-luffy",
            source_session="op05-119-luffy-en-001",
            state=ProfileState.CAPTURE_VALIDATED,
            card_id="OP05-119",
        )
    ]
    with pytest.raises(PromotionError, match="at least two"):
        validate_family_proposal("sr-textured", one_card)

    two_cards = [
        *one_card,
        FamilyCardEvidence(
            profile_id="op05-060-law",
            source_session="op05-060-law-en-001",
            state=ProfileState.PRODUCTION_VALIDATED,
            card_id="OP05-060",
        ),
    ]
    validate_family_proposal("sr-textured", two_cards)
