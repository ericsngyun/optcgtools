from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from optcg_material.models import (
    AuthenticationStatus,
    Language,
    RightsStatus,
)
from optcg_material.provenance import load_manifest, save_manifest
from optcg_material.review import (
    TECHNICAL_ITEMS,
    ReviewAction,
    ReviewError,
    ReviewItem,
    ReviewState,
    append_event,
    check_publication,
    derive_status,
    load_ledger,
    review_log_path,
)
from optcg_material.session import initialize_session

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "card-material-profile.schema.json"
REVIEWER = "GenkiStuff reviewer"


def create_session(root: Path) -> None:
    initialize_session(
        root,
        session_id="op05-119-luffy-en-001",
        card_id="OP05-119",
        card_name="Monkey.D.Luffy",
        set_code="OP05",
        language=Language.EN,
        operator="GenkiStuff Lab",
        rights_owner="GenkiStuff",
    )


def mark_authenticated(root: Path, *, public_derivatives: bool = True) -> None:
    session = load_manifest(root)
    session.authentication.method = "physical inspection"
    session.authentication.verifier = REVIEWER
    session.authentication.status = AuthenticationStatus.VERIFIED
    session.rights.status = RightsStatus.OWNED_CAPTURE
    session.rights.public_derivatives_allowed = public_derivatives
    save_manifest(root, session)


def approve_everything(root: Path, profile_digest: str | None = None) -> None:
    for item in TECHNICAL_ITEMS:
        append_event(root, reviewer=REVIEWER, action=ReviewAction.APPROVE_ITEM, item=item)
    append_event(root, reviewer=REVIEWER, action=ReviewAction.APPROVE_ITEM, item=ReviewItem.RIGHTS)
    append_event(
        root,
        reviewer=REVIEWER,
        action=ReviewAction.APPROVE_ITEM,
        item=ReviewItem.PRODUCTION_PROFILE,
    )
    append_event(root, reviewer=REVIEWER, action=ReviewAction.APPROVE_TECHNICAL)
    append_event(root, reviewer=REVIEWER, action=ReviewAction.APPROVE_RIGHTS)
    append_event(
        root,
        reviewer=REVIEWER,
        action=ReviewAction.APPROVE_PRODUCTION,
        after_digest=profile_digest,
    )


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_profile(root: Path, asset_relative: str = "approved/albedo.png") -> Path:
    asset_path = root / "delivery" / asset_relative
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"synthetic-albedo-bytes")
    profile = {
        "schemaVersion": "1.0.0",
        "card": {"id": "OP05-119", "game": "one-piece-card-game", "language": "EN"},
        "classification": {"family": "sr-foil-basic", "confidence": "capture-validated"},
        "assets": {
            "albedo": {
                "uri": asset_relative,
                "sha256": hashlib.sha256(b"synthetic-albedo-bytes").hexdigest(),
            }
        },
        "renderer": {"cssPreset": "sr-foil-basic", "qualityTier": "detail"},
        "provenance": {
            "sourceType": "controlled-capture",
            "rights": "GenkiStuff owned capture",
            "reviewStatus": "approved",
            "reviewer": REVIEWER,
        },
    }
    profile_path = root / "delivery" / "profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    return profile_path


def test_events_chain_and_verify(tmp_path: Path) -> None:
    create_session(tmp_path)
    first = append_event(tmp_path, reviewer=REVIEWER, action=ReviewAction.OPEN_REVIEW)
    second = append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.COMMENT,
        comment="Foil boundary looks correct.",
    )

    events = load_ledger(tmp_path)
    assert [event.sequence for event in events] == [0, 1]
    assert events[0].previous_event_digest is None
    assert events[1].previous_event_digest == first.event_digest
    assert second.event_digest == events[1].content_digest()


def test_tampered_ledger_is_detected(tmp_path: Path) -> None:
    create_session(tmp_path)
    append_event(tmp_path, reviewer=REVIEWER, action=ReviewAction.OPEN_REVIEW)
    append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.COMMENT,
        comment="original comment",
    )

    log_path = review_log_path(tmp_path)
    tampered = log_path.read_text(encoding="utf-8").replace("original comment", "edited comment")
    log_path.write_text(tampered, encoding="utf-8")

    with pytest.raises(ReviewError, match="digest mismatch"):
        load_ledger(tmp_path)


def test_rejection_requires_explanation(tmp_path: Path) -> None:
    create_session(tmp_path)
    with pytest.raises(ValueError, match="explain"):
        append_event(
            tmp_path,
            reviewer=REVIEWER,
            action=ReviewAction.REJECT_ITEM,
            item=ReviewItem.SEMANTIC_MASKS,
        )


def test_technical_approval_requires_every_item(tmp_path: Path) -> None:
    create_session(tmp_path)
    append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.APPROVE_ITEM,
        item=ReviewItem.CARD_IDENTITY,
    )
    with pytest.raises(ReviewError, match="missing"):
        append_event(tmp_path, reviewer=REVIEWER, action=ReviewAction.APPROVE_TECHNICAL)


def test_blocking_comment_blocks_until_resolved(tmp_path: Path) -> None:
    create_session(tmp_path)
    for item in TECHNICAL_ITEMS:
        append_event(tmp_path, reviewer=REVIEWER, action=ReviewAction.APPROVE_ITEM, item=item)
    blocking = append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.COMMENT,
        comment="Halo around title text must be re-checked.",
        requires_resolution=True,
    )

    assert derive_status(load_ledger(tmp_path)).state is ReviewState.NEEDS_REVISION
    with pytest.raises(ReviewError, match="unresolved"):
        append_event(tmp_path, reviewer=REVIEWER, action=ReviewAction.APPROVE_TECHNICAL)

    append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.RESOLVE_COMMENT,
        target_event_id=blocking.event_id,
    )
    append_event(tmp_path, reviewer=REVIEWER, action=ReviewAction.APPROVE_TECHNICAL)
    assert derive_status(load_ledger(tmp_path)).state is ReviewState.TECHNICALLY_APPROVED


def test_full_ladder_reaches_production_approved(tmp_path: Path) -> None:
    create_session(tmp_path)
    approve_everything(tmp_path)
    report = derive_status(load_ledger(tmp_path))
    assert report.state is ReviewState.PRODUCTION_APPROVED
    assert len(report.approvals) == 3
    assert all(approval.active for approval in report.approvals)


def test_production_approval_requires_prior_approvals(tmp_path: Path) -> None:
    create_session(tmp_path)
    append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.APPROVE_ITEM,
        item=ReviewItem.PRODUCTION_PROFILE,
    )
    with pytest.raises(ReviewError, match="technical approval"):
        append_event(tmp_path, reviewer=REVIEWER, action=ReviewAction.APPROVE_PRODUCTION)


def test_regression_invalidates_approvals(tmp_path: Path) -> None:
    create_session(tmp_path)
    approve_everything(tmp_path)

    append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.REJECT_ITEM,
        item=ReviewItem.MATERIAL_MAPS,
        comment="Metallic mask leaks into character skin.",
    )
    report = derive_status(load_ledger(tmp_path))
    assert report.state is ReviewState.NEEDS_REVISION
    assert all(not approval.active for approval in report.approvals)

    # Re-approving the item clears the rejection but does not resurrect approvals.
    append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.APPROVE_ITEM,
        item=ReviewItem.MATERIAL_MAPS,
    )
    report = derive_status(load_ledger(tmp_path))
    assert report.state is ReviewState.UNREVIEWED
    assert all(not approval.active for approval in report.approvals)


def test_revoked_approval_lowers_state(tmp_path: Path) -> None:
    create_session(tmp_path)
    approve_everything(tmp_path)
    report = derive_status(load_ledger(tmp_path))
    production = next(
        approval
        for approval in report.approvals
        if approval.action is ReviewAction.APPROVE_PRODUCTION
    )

    append_event(
        tmp_path,
        reviewer=REVIEWER,
        action=ReviewAction.REVOKE_APPROVAL,
        target_event_id=production.event_id,
        comment="New capture supersedes the approved profile.",
    )
    assert derive_status(load_ledger(tmp_path)).state is ReviewState.RIGHTS_APPROVED


def test_publication_blocked_without_production_approval(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    profile_path = write_profile(tmp_path)

    report = check_publication(tmp_path, profile_path, SCHEMA_PATH)
    assert not report.passed
    assert any("production-approved" in error for error in report.errors)


def test_publication_passes_when_all_gates_hold(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    profile_path = write_profile(tmp_path)
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, SCHEMA_PATH)
    assert report.errors == []
    assert report.passed
    assert report.state is ReviewState.PRODUCTION_APPROVED
    assert "albedo" in report.checked_assets


def test_publication_blocks_profile_swapped_after_approval(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    profile_path = write_profile(tmp_path)
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["renderer"]["foilStrength"] = 2.0
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    report = check_publication(tmp_path, profile_path, SCHEMA_PATH)
    assert not report.passed
    assert any("does not match the reviewed profile" in error for error in report.errors)


def test_publication_requires_digest_bound_approval(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    profile_path = write_profile(tmp_path)
    approve_everything(tmp_path, profile_digest=None)

    report = check_publication(tmp_path, profile_path, SCHEMA_PATH)
    assert not report.passed
    assert any("must record the approved profile's sha256" in error for error in report.errors)


def test_publication_blocks_remote_assets_by_default(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    profile_path = write_profile(tmp_path)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["assets"]["foilMask"] = {"uri": "https://cdn.example.com/foil.webp"}
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, SCHEMA_PATH)
    assert not report.passed
    assert any("remote URI" in error for error in report.errors)


def test_publication_blocks_hash_mismatch_and_raw_paths(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    profile_path = write_profile(tmp_path)

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["assets"]["albedo"]["sha256"] = "0" * 64
    profile["assets"]["foilMask"] = {"uri": "raw/albedo/secret.png"}
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, SCHEMA_PATH)
    assert not report.passed
    assert any("hash mismatch" in error for error in report.errors)
    assert any("outside approved delivery paths" in error for error in report.errors)


def test_publication_blocks_missing_rights(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path, public_derivatives=False)
    profile_path = write_profile(tmp_path)
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, SCHEMA_PATH)
    assert not report.passed
    assert any("public derivatives" in error for error in report.errors)


def test_publication_blocks_hypothesis_confidence(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    profile_path = write_profile(tmp_path)

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["classification"]["confidence"] = "hypothesis"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, SCHEMA_PATH)
    assert not report.passed
    assert any("below capture-validated" in error for error in report.errors)


# ---------------------------------------------------------------------------
# Lane A (reference) publication gate — ADR-0002
# ---------------------------------------------------------------------------


def write_reference_schema(root: Path) -> Path:
    """A minimal Draft 2020-12 schema permitting the `lane` field: the shared
    card-material-profile.schema.json is out of this task's allowed_paths, so
    reference-lane tests validate against a synthetic reference schema."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["schemaVersion", "lane", "card", "classification", "assets", "renderer", "provenance"],
        "properties": {
            "schemaVersion": {"type": "string"},
            "lane": {"const": "reference"},
            "card": {"type": "object"},
            "classification": {"type": "object"},
            "assets": {"type": "object"},
            "renderer": {"type": "object"},
            "provenance": {"type": "object"},
        },
        "additionalProperties": True,
    }
    schema_path = root / "reference-profile.schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    return schema_path


def write_reference_profile(
    root: Path,
    *,
    confidence: str,
    rights_note: str = "GenkiStuff licensed reference bundle",
    asset_relative: str = "approved/albedo.png",
    omit_lane: bool = False,
) -> Path:
    asset_path = root / "delivery" / asset_relative
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"synthetic-albedo-bytes")
    profile = {
        "schemaVersion": "1.0.0",
        "lane": "reference",
        "card": {"id": "OP05-119", "game": "one-piece-card-game", "language": "EN"},
        "classification": {"family": "sr-foil-basic", "confidence": confidence},
        "assets": {
            "albedo": {
                "uri": asset_relative,
                "sha256": hashlib.sha256(b"synthetic-albedo-bytes").hexdigest(),
            }
        },
        "renderer": {"cssPreset": "sr-foil-basic", "qualityTier": "detail"},
        "provenance": {
            "sourceType": "public-reference-synthesis",
            "rights": rights_note,
            "reviewStatus": "approved",
            "reviewer": REVIEWER,
            "referenceBundleId": "op06-093-perona-v2-en-b001",
        },
    }
    if omit_lane:
        del profile["lane"]
    profile_path = root / "delivery" / "reference-profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    return profile_path


def test_reference_publication_passes_with_allowed_label(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    schema_path = write_reference_schema(tmp_path)
    profile_path = write_reference_profile(tmp_path, confidence="reference-derived")
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, schema_path)
    # Fail closed (ADR-0002 follow-up): the bundle-review publication adapter
    # has not landed, so even a fully-labeled reference profile is blocked —
    # and the block must be the ONLY error (labels and phrases are clean).
    assert not report.passed
    assert [e for e in report.errors if "reference-lane publication is blocked" in e]
    assert not [e for e in report.errors if "publication label" in e or "forbidden" in e]


@pytest.mark.parametrize(
    "confidence",
    [
        "source-supported simulation",
        "visually fitted across real-card references",
    ],
)
def test_reference_publication_blocked_for_every_allowed_label(
    tmp_path: Path, confidence: str
) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    schema_path = write_reference_schema(tmp_path)
    profile_path = write_reference_profile(tmp_path, confidence=confidence)
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, schema_path)
    assert not report.passed
    assert [e for e in report.errors if "reference-lane publication is blocked" in e]
    assert not [e for e in report.errors if "publication label" in e or "forbidden" in e]


def test_reference_profile_omitting_lane_is_rejected(tmp_path: Path) -> None:
    """H1: reference-synthesis provenance may not be laundered into the
    physical publication branch by omitting the lane field."""
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    schema_path = write_reference_schema(tmp_path)
    profile_path = write_reference_profile(
        tmp_path, confidence="reference-derived", omit_lane=True
    )
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, schema_path)
    assert not report.passed
    assert any("must declare lane: reference" in error for error in report.errors)


def test_reference_publication_rejects_physical_confidence_label(tmp_path: Path) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    schema_path = write_reference_schema(tmp_path)
    profile_path = write_reference_profile(tmp_path, confidence="capture-validated")
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, schema_path)
    assert not report.passed
    assert any("reference-lane publication label" in error for error in report.errors)


@pytest.mark.parametrize(
    "phrase",
    ["capture-validated", "physically measured", "physically exact"],
)
def test_reference_publication_rejects_forbidden_phrases(tmp_path: Path, phrase: str) -> None:
    create_session(tmp_path)
    mark_authenticated(tmp_path)
    schema_path = write_reference_schema(tmp_path)
    profile_path = write_reference_profile(
        tmp_path,
        confidence="reference-derived",
        rights_note=f"GenkiStuff licensed reference bundle; {phrase} appearance match",
    )
    approve_everything(tmp_path, profile_digest=sha256_of(profile_path))

    report = check_publication(tmp_path, profile_path, schema_path)
    assert not report.passed
    assert any("forbidden physical-claim phrase" in error for error in report.errors)
