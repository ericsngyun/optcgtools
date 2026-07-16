from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from optcg_material.models import RightsStatus
from optcg_material.promotion import (
    ActorType,
    FamilyCardEvidence,
    Lane,
    ProfileState,
    PromotionAction,
    PromotionError,
    PromotionEvent,
    ReferenceFamilyCardEvidence,
    ReferenceState,
    append_promotion,
    current_revision_state,
    load_promotion_ledger,
    new_event_id,
    validate_family_proposal,
    validate_reference_family_proposal,
)

HASH = "a" * 64
HASH_B = "b" * 64


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


# ---------------------------------------------------------------------------
# Lane A (reference) — ADR-0002
# ---------------------------------------------------------------------------


def reference_open_revision(ledger: Path, revision: int = 1, *, profile_id: str = "op05-119-luffy") -> None:
    append_promotion(
        ledger,
        event(
            profile_id=profile_id,
            action=PromotionAction.OPEN_REVISION,
            revision=revision,
            lane=Lane.REFERENCE,
            to_state=ReferenceState.HYPOTHESIS,
            fingerprint={"reference_bundle": "seed"},
        ),
    )


def reference_promote(
    ledger: Path,
    from_state: ReferenceState,
    to_state: ReferenceState,
    *,
    profile_id: str = "op05-119-luffy",
    **overrides,
) -> None:
    defaults = {
        "profile_id": profile_id,
        "action": PromotionAction.PROMOTE,
        "lane": Lane.REFERENCE,
        "from_state": from_state,
        "to_state": to_state,
        "actor": "GenkiStuff reviewer",
        "actor_type": ActorType.HUMAN,
        "technical_reviewer": "GenkiStuff reviewer",
    }
    defaults.update(overrides)
    append_promotion(ledger, event(**defaults))


def test_reference_lane_happy_path(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    reference_open_revision(ledger)

    reference_promote(
        ledger,
        ReferenceState.HYPOTHESIS,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
    )
    reference_promote(
        ledger,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
    )
    reference_promote(
        ledger,
        ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
        ReferenceState.REFERENCE_ASSETS_PROPOSED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
        source_quality_tier="A",
        evidence_packet="review/evidence/reference-assets.json",
        rights_status=RightsStatus.LICENSED,
    )
    reference_promote(
        ledger,
        ReferenceState.REFERENCE_ASSETS_PROPOSED,
        ReferenceState.REFERENCE_PROFILE_FITTED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
        source_quality_tier="A",
        evidence_packet="review/evidence/reference-assets.json",
        rights_status=RightsStatus.LICENSED,
        metrics={"cross_reference_consistency_score": 0.82},
    )
    reference_promote(
        ledger,
        ReferenceState.REFERENCE_PROFILE_FITTED,
        ReferenceState.ADVERSARIAL_REVIEW_PASSED,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
        source_quality_tier="A",
        evidence_packet="review/evidence/reference-assets.json",
        rights_status=RightsStatus.LICENSED,
        metrics={"cross_reference_consistency_score": 0.82},
    )
    reference_promote(
        ledger,
        ReferenceState.ADVERSARIAL_REVIEW_PASSED,
        ReferenceState.PRODUCTION_REFERENCE_DERIVED,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
        source_quality_tier="A",
        evidence_packet="review/evidence/reference-assets.json",
        rights_status=RightsStatus.LICENSED,
        metrics={"cross_reference_consistency_score": 0.82},
        rights_reviewer="GenkiStuff rights reviewer",
    )

    state = current_revision_state(load_promotion_ledger(ledger), "op05-119-luffy")
    assert state is not None
    assert state.lane is Lane.REFERENCE
    assert state.state is ReferenceState.PRODUCTION_REFERENCE_DERIVED


def test_reference_lane_entry_must_be_hypothesis(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    with pytest.raises(PromotionError, match="hypothesis"):
        append_promotion(
            ledger,
            event(
                action=PromotionAction.OPEN_REVISION,
                lane=Lane.REFERENCE,
                to_state=ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
            ),
        )


@pytest.mark.parametrize(
    "target",
    [
        ReferenceState.EXACT_VARIANT_VERIFIED,
        ReferenceState.ADVERSARIAL_REVIEW_PASSED,
        ReferenceState.PRODUCTION_REFERENCE_DERIVED,
    ],
)
def test_agent_cannot_perform_reference_human_only_transition(
    tmp_path: Path, target: ReferenceState
) -> None:
    ledger = tmp_path / "promotions.jsonl"
    reference_open_revision(ledger)
    ladder = list(ReferenceState)
    previous = ReferenceState.HYPOTHESIS
    for state in ladder[1:]:
        if state is target:
            with pytest.raises(PromotionError, match="human-only"):
                reference_promote(
                    ledger,
                    previous,
                    state,
                    actor="pipeline-agent",
                    actor_type=ActorType.AGENT,
                    technical_reviewer=None,
                    reference_bundle_id="op05-119-luffy-en-bundle-001",
                    input_hashes=[HASH],
                    source_quality_tier="A",
                    evidence_packet="review/evidence/reference-assets.json",
                    rights_status=RightsStatus.LICENSED,
                    metrics={"cross_reference_consistency_score": 0.5},
                )
            return
        reference_promote(
            ledger,
            previous,
            state,
            actor="pipeline-agent" if state not in (
                ReferenceState.EXACT_VARIANT_VERIFIED,
                ReferenceState.ADVERSARIAL_REVIEW_PASSED,
                ReferenceState.PRODUCTION_REFERENCE_DERIVED,
            ) else "GenkiStuff reviewer",
            actor_type=ActorType.AGENT if state not in (
                ReferenceState.EXACT_VARIANT_VERIFIED,
                ReferenceState.ADVERSARIAL_REVIEW_PASSED,
                ReferenceState.PRODUCTION_REFERENCE_DERIVED,
            ) else ActorType.HUMAN,
            technical_reviewer=None if state not in (
                ReferenceState.EXACT_VARIANT_VERIFIED,
                ReferenceState.ADVERSARIAL_REVIEW_PASSED,
                ReferenceState.PRODUCTION_REFERENCE_DERIVED,
            ) else "GenkiStuff reviewer",
            reference_bundle_id="op05-119-luffy-en-bundle-001",
            input_hashes=[HASH],
            source_quality_tier="A",
            evidence_packet="review/evidence/reference-assets.json",
            rights_status=RightsStatus.LICENSED,
            metrics={"cross_reference_consistency_score": 0.5},
            rights_reviewer=(
                "GenkiStuff rights reviewer" if state is ReferenceState.PRODUCTION_REFERENCE_DERIVED else None
            ),
        )
        previous = state


def test_reference_tier_c_always_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    reference_open_revision(ledger)
    reference_promote(
        ledger,
        ReferenceState.HYPOTHESIS,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
    )
    reference_promote(
        ledger,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
    )
    with pytest.raises(PromotionError, match="never eligible"):
        reference_promote(
            ledger,
            ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
            ReferenceState.REFERENCE_ASSETS_PROPOSED,
            actor="pipeline-agent",
            actor_type=ActorType.AGENT,
            technical_reviewer=None,
            reference_bundle_id="op05-119-luffy-en-bundle-001",
            input_hashes=[HASH],
            source_quality_tier="C",
            evidence_packet="review/evidence/reference-assets.json",
            rights_status=RightsStatus.LICENSED,
        )


def test_reference_thresholds_require_bundle_hashes_evidence_metrics(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    reference_open_revision(ledger)

    with pytest.raises(PromotionError, match="reference_bundle_id"):
        reference_promote(
            ledger,
            ReferenceState.HYPOTHESIS,
            ReferenceState.EXACT_VARIANT_VERIFIED,
            reference_bundle_id=None,
        )

    reference_promote(
        ledger,
        ReferenceState.HYPOTHESIS,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
    )

    with pytest.raises(PromotionError, match="input content hashes"):
        reference_promote(
            ledger,
            ReferenceState.EXACT_VARIANT_VERIFIED,
            ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
            actor="pipeline-agent",
            actor_type=ActorType.AGENT,
            technical_reviewer=None,
            reference_bundle_id="op05-119-luffy-en-bundle-001",
            input_hashes=[],
        )

    reference_promote(
        ledger,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
    )

    with pytest.raises(PromotionError, match="evidence packet"):
        reference_promote(
            ledger,
            ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
            ReferenceState.REFERENCE_ASSETS_PROPOSED,
            actor="pipeline-agent",
            actor_type=ActorType.AGENT,
            technical_reviewer=None,
            reference_bundle_id="op05-119-luffy-en-bundle-001",
            input_hashes=[HASH],
            source_quality_tier="A",
            evidence_packet=None,
            rights_status=RightsStatus.LICENSED,
        )

    with pytest.raises(PromotionError, match="rights_status"):
        reference_promote(
            ledger,
            ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
            ReferenceState.REFERENCE_ASSETS_PROPOSED,
            actor="pipeline-agent",
            actor_type=ActorType.AGENT,
            technical_reviewer=None,
            reference_bundle_id="op05-119-luffy-en-bundle-001",
            input_hashes=[HASH],
            source_quality_tier="A",
            evidence_packet="review/evidence/reference-assets.json",
            rights_status=RightsStatus.UNKNOWN,
        )

    reference_promote(
        ledger,
        ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
        ReferenceState.REFERENCE_ASSETS_PROPOSED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
        source_quality_tier="A",
        evidence_packet="review/evidence/reference-assets.json",
        rights_status=RightsStatus.LICENSED,
    )

    with pytest.raises(PromotionError, match="quantitative metrics"):
        reference_promote(
            ledger,
            ReferenceState.REFERENCE_ASSETS_PROPOSED,
            ReferenceState.REFERENCE_PROFILE_FITTED,
            actor="pipeline-agent",
            actor_type=ActorType.AGENT,
            technical_reviewer=None,
            reference_bundle_id="op05-119-luffy-en-bundle-001",
            input_hashes=[HASH],
            source_quality_tier="A",
            evidence_packet="review/evidence/reference-assets.json",
            rights_status=RightsStatus.LICENSED,
            metrics={},
        )


def test_reference_production_requires_rights_reviewer(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    reference_open_revision(ledger)
    reference_promote(
        ledger,
        ReferenceState.HYPOTHESIS,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
    )
    reference_promote(
        ledger,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
    )
    reference_promote(
        ledger,
        ReferenceState.PUBLIC_REFERENCE_SUPPORTED,
        ReferenceState.REFERENCE_ASSETS_PROPOSED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
        source_quality_tier="A",
        evidence_packet="review/evidence/reference-assets.json",
        rights_status=RightsStatus.LICENSED,
    )
    reference_promote(
        ledger,
        ReferenceState.REFERENCE_ASSETS_PROPOSED,
        ReferenceState.REFERENCE_PROFILE_FITTED,
        actor="pipeline-agent",
        actor_type=ActorType.AGENT,
        technical_reviewer=None,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
        source_quality_tier="A",
        evidence_packet="review/evidence/reference-assets.json",
        rights_status=RightsStatus.LICENSED,
        metrics={"cross_reference_consistency_score": 0.82},
    )
    reference_promote(
        ledger,
        ReferenceState.REFERENCE_PROFILE_FITTED,
        ReferenceState.ADVERSARIAL_REVIEW_PASSED,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
        input_hashes=[HASH],
        source_quality_tier="A",
        evidence_packet="review/evidence/reference-assets.json",
        rights_status=RightsStatus.LICENSED,
        metrics={"cross_reference_consistency_score": 0.82},
    )
    with pytest.raises(PromotionError, match="rights_reviewer"):
        reference_promote(
            ledger,
            ReferenceState.ADVERSARIAL_REVIEW_PASSED,
            ReferenceState.PRODUCTION_REFERENCE_DERIVED,
            reference_bundle_id="op05-119-luffy-en-bundle-001",
            input_hashes=[HASH],
            source_quality_tier="A",
            evidence_packet="review/evidence/reference-assets.json",
            rights_status=RightsStatus.LICENSED,
            metrics={"cross_reference_consistency_score": 0.82},
        )


def test_reference_revision_must_enter_at_hypothesis(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    with pytest.raises(PromotionError, match="hypothesis"):
        append_promotion(
            ledger,
            event(
                action=PromotionAction.OPEN_REVISION,
                lane=Lane.REFERENCE,
                to_state=ReferenceState.REFERENCE_ASSETS_PROPOSED,
            ),
        )


def test_lane_mismatch_mid_revision_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    reference_open_revision(ledger)
    with pytest.raises(PromotionError, match="lane"):
        append_promotion(
            ledger,
            event(
                action=PromotionAction.PROMOTE,
                from_state=ProfileState.HYPOTHESIS,
                to_state=ProfileState.PUBLIC_REFERENCE_SUPPORTED,
                actor="pipeline-agent",
                actor_type=ActorType.AGENT,
            ),
        )


def test_cross_lane_demotion_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    reference_open_revision(ledger)
    reference_promote(
        ledger,
        ReferenceState.HYPOTHESIS,
        ReferenceState.EXACT_VARIANT_VERIFIED,
        reference_bundle_id="op05-119-luffy-en-bundle-001",
    )
    with pytest.raises(PromotionError, match="lane"):
        append_promotion(
            ledger,
            event(
                action=PromotionAction.DEMOTE,
                from_state=ProfileState.PUBLIC_REFERENCE_SUPPORTED,
                to_state=ProfileState.HYPOTHESIS,
                actor="quality-gate",
                actor_type=ActorType.CI,
                reason="cross-lane demotion attempt",
            ),
        )


def test_reference_event_rejects_schema_1_0_0(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"1\.1\.0"):
        event(
            action=PromotionAction.OPEN_REVISION,
            lane=Lane.REFERENCE,
            to_state=ReferenceState.HYPOTHESIS,
            schema_version="1.0.0",
        )


def test_reference_family_requires_two_cards_and_two_bundles() -> None:
    below_threshold = ReferenceState.REFERENCE_PROFILE_FITTED
    at_threshold = ReferenceState.ADVERSARIAL_REVIEW_PASSED

    one_card_two_bundles = [
        ReferenceFamilyCardEvidence(
            profile_id="op05-119-luffy",
            reference_bundle_id="bundle-one",
            state=at_threshold,
            card_id="OP05-119",
        ),
        ReferenceFamilyCardEvidence(
            profile_id="op05-119-luffy",
            reference_bundle_id="bundle-two",
            state=at_threshold,
            card_id="OP05-119",
        ),
    ]
    with pytest.raises(PromotionError, match="at least two distinct card_ids"):
        validate_reference_family_proposal("sr-textured", one_card_two_bundles)

    two_cards_one_bundle = [
        ReferenceFamilyCardEvidence(
            profile_id="op05-119-luffy",
            reference_bundle_id="bundle-shared",
            state=at_threshold,
            card_id="OP05-119",
        ),
        ReferenceFamilyCardEvidence(
            profile_id="op05-060-law",
            reference_bundle_id="bundle-shared",
            state=at_threshold,
            card_id="OP05-060",
        ),
    ]
    with pytest.raises(PromotionError, match="at least two distinct card_ids"):
        validate_reference_family_proposal("sr-textured", two_cards_one_bundle)

    two_cards_two_bundles_below_threshold = [
        ReferenceFamilyCardEvidence(
            profile_id="op05-119-luffy",
            reference_bundle_id="bundle-one",
            state=below_threshold,
            card_id="OP05-119",
        ),
        ReferenceFamilyCardEvidence(
            profile_id="op05-060-law",
            reference_bundle_id="bundle-two",
            state=below_threshold,
            card_id="OP05-060",
        ),
    ]
    with pytest.raises(PromotionError, match="at least two distinct card_ids"):
        validate_reference_family_proposal("sr-textured", two_cards_two_bundles_below_threshold)

    two_cards_two_bundles_at_threshold = [
        ReferenceFamilyCardEvidence(
            profile_id="op05-119-luffy",
            reference_bundle_id="bundle-one",
            state=at_threshold,
            card_id="OP05-119",
        ),
        ReferenceFamilyCardEvidence(
            profile_id="op05-060-law",
            reference_bundle_id="bundle-two",
            state=at_threshold,
            card_id="OP05-060",
        ),
    ]
    validate_reference_family_proposal("sr-textured", two_cards_two_bundles_at_threshold)


# ---------------------------------------------------------------------------
# Digest-compat regression: schema 1.0.0 physical events must stay byte-
# identical to the pre-two-lane serialization and digest.
# ---------------------------------------------------------------------------


def test_physical_event_with_new_fields_none_excludes_new_keys(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_event = event(
        schema_version="1.0.0",
        action=PromotionAction.OPEN_REVISION,
        revision=1,
        to_state=ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
        source_session="op05-119-luffy-en-001",
        input_hashes=[HASH],
        fingerprint={"captures": HASH, "renderer": "three-r185"},
    )
    appended = append_promotion(ledger, open_event)

    payload = appended.model_dump(mode="json", exclude_none=True)
    new_keys = {
        "lane",
        "reference_bundle_id",
        "source_quality_tier",
        "adversarial_review",
        "linked_reference_revision",
    }
    assert new_keys.isdisjoint(payload.keys())

    # The digest is computed over exactly that payload (minus event_digest
    # itself), independent of whether the new optional fields exist at all.
    expected_payload = dict(payload)
    expected_payload.pop("event_digest", None)
    from optcg_material.semantic import canonical_digest

    assert appended.event_digest == canonical_digest(expected_payload)

    # A ledger written this way still round-trips and verifies cleanly.
    events = load_promotion_ledger(ledger)
    assert len(events) == 1
    assert events[0].event_digest == appended.event_digest
    assert events[0].effective_lane is Lane.PHYSICAL


def test_golden_digest_pin_for_schema_1_0_0_physical_event() -> None:
    """Pins the exact serialized form and content digest of a schema-1.0.0
    physical event to a literal constant. Any change to PromotionEvent that
    alters either value breaks replay of every historical physical ledger —
    this test must never be updated without an explicit ledger-migration plan."""
    event = PromotionEvent(
        schema_version="1.0.0",
        event_id="pro-golden000000000000000000000000",
        sequence=0,
        profile_id="op05-119-luffy",
        revision=1,
        action=PromotionAction.OPEN_REVISION,
        to_state="authenticated-capture-ingested",
        actor="capture-operator",
        actor_type=ActorType.AGENT,
        source_session="op05-119-luffy-en-001",
        input_hashes=["a" * 64],
        fingerprint={"captures": "a" * 64},
        created_at=datetime(2026, 7, 16, 0, 0, 0, tzinfo=UTC),
    )
    assert (
        event.content_digest()
        == "39dc789bbef4dd2a37ebc6a47e26e6eb8cea2986b4d0b56dc72a9c5107b15086"
    )
    serialized = event.model_dump_json(exclude_none=True)
    for new_field in (
        "lane",
        "reference_bundle_id",
        "source_quality_tier",
        "adversarial_review",
        "linked_reference_revision",
    ):
        assert f'"{new_field}"' not in serialized
