from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from typer.testing import CliRunner

from optcg_material.models import Language, RightsStatus
from optcg_material.provenance import hash_file
from optcg_material.reference_bundle import (
    DEFAULT_SCORE_WEIGHTS,
    AcquisitionTask,
    BlockReason,
    BundleError,
    BundleTierRecord,
    CompressionLevel,
    EditingLikelihood,
    LightingUsefulness,
    MediaForm,
    MediaResolution,
    Protection,
    ProxyRisk,
    ReferenceSourceRecord,
    RetrievalStatus,
    SourceQualityScore,
    SourceTier,
    add_media,
    add_source,
    compute_bundle_tier,
    compute_manifest_digest,
    init_bundle,
    list_acquisition_tasks,
    load_bundle_manifest,
    record_variant_verification,
    score_source,
    tier_bundle,
    validate_bundle,
)
from optcg_material.reference_bundle_cli import app

SCHEMA_DIRECTORY = Path(__file__).resolve().parents[1] / "docs" / "agent-ops"
FIXED_TIME = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)

runner = CliRunner()


def load_schema(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIRECTORY / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def make_source(
    source_id: str = "ebay-001",
    *,
    retrieval_status: RetrievalStatus = RetrievalStatus.RETRIEVED,
    language: Language = Language.EN,
    variant_confidence: float = 0.95,
    protection: Protection = Protection.RAW,
    proxy_risk: ProxyRisk = ProxyRisk.LOW,
    compression: CompressionLevel = CompressionLevel.LOW,
    editing: EditingLikelihood = EditingLikelihood.LOW,
    useful_angles: int = 6,
    macro: bool = True,
    lighting: LightingUsefulness = LightingUsefulness.HIGH,
    resolution: MediaResolution | None = None,
    private_media_hash: str | None = None,
) -> ReferenceSourceRecord:
    return ReferenceSourceRecord(
        source_id=source_id,
        source_url=f"https://example.com/listings/{source_id}",
        source_type="ebay-listing",
        retrieval_date=FIXED_TIME,
        card_id="op05-119",
        language=language,
        exact_print_variant="OP05-119 SEC Manga Rare (EN)",
        region_release="EN-2023",
        protection=protection,
        media_form=MediaForm.STILL,
        resolution=resolution or MediaResolution(width=1600, height=2200),
        useful_angles=useful_angles,
        macro_available=macro,
        lighting_usefulness=lighting,
        compression_level=compression,
        editing_likelihood=editing,
        variant_confidence=variant_confidence,
        proxy_counterfeit_risk=proxy_risk,
        rights_status=RightsStatus.RESTRICTED_RESEARCH,
        private_media_hash=private_media_hash,
        retrieval_status=retrieval_status,
    )


def make_bundle(tmp_path: Path) -> Path:
    bundle_root = tmp_path / "bundle"
    init_bundle(
        bundle_root,
        bundle_id="op05-119-en-manga-001",
        card_id="op05-119",
        set_code="OP05",
        language=Language.EN,
        exact_print_variant="OP05-119 SEC Manga Rare (EN)",
        region_release="EN-2023",
        rights_status=RightsStatus.RESTRICTED_RESEARCH,
    )
    return bundle_root


def write_media(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


# --- manifest round-trip and integrity ------------------------------------------


def test_manifest_round_trips_against_frozen_schema(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_source("ebay-001"))
    media = write_media(tmp_path, "photo.png", b"synthetic-media-bytes-001")
    add_media(bundle_root, "ebay-001", media)
    record_variant_verification(
        bundle_root,
        verifier="Eric Yun",
        method="set-symbol and copyright-line comparison",
        confidence=0.9,
    )

    manifest = load_bundle_manifest(bundle_root)
    validator = load_schema("reference-bundle.schema.json")
    validator.validate(manifest.model_dump(mode="json", exclude_none=True))

    reparsed = load_bundle_manifest(bundle_root)
    assert reparsed == manifest


def test_manifest_digest_detects_tampering(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_source("ebay-001"))
    media = write_media(tmp_path, "photo.png", b"synthetic-media-bytes-002")
    add_media(bundle_root, "ebay-001", media)

    result = validate_bundle(bundle_root)
    assert result["valid"], result["errors"]

    manifest_path = bundle_root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["notes"] = "tampered after sealing"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_bundle(bundle_root)
    assert not result["valid"]
    assert any("digest mismatch" in error for error in result["errors"])


def test_manifest_digest_is_canonical(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_source("ebay-001"))
    manifest = load_bundle_manifest(bundle_root)
    assert manifest.manifest_digest == compute_manifest_digest(manifest)


def test_empty_bundle_fails_validation(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    result = validate_bundle(bundle_root)
    assert not result["valid"]
    assert any("no sources" in error for error in result["errors"])


# --- media ingestion --------------------------------------------------------------


def test_media_is_hash_recorded_and_immutable(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_source("ebay-001"))
    media = write_media(tmp_path, "photo.png", b"synthetic-media-bytes-003")

    record, destination, digest = add_media(bundle_root, "ebay-001", media)
    assert record.private_media_hash == digest
    assert hash_file(destination) == digest
    assert load_bundle_manifest(bundle_root).sources[0].private_media_hash == digest

    replacement = write_media(tmp_path, "other.png", b"different-bytes")
    with pytest.raises(BundleError, match="immutable"):
        add_media(bundle_root, "ebay-001", replacement)


def test_duplicate_media_content_is_rejected(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_source("ebay-001"))
    add_source(bundle_root, make_source("ebay-002"))
    media = write_media(tmp_path, "photo.png", b"synthetic-media-bytes-004")
    add_media(bundle_root, "ebay-001", media)
    with pytest.raises(BundleError, match="duplicate media content"):
        add_media(bundle_root, "ebay-002", media)


def test_add_media_to_blocked_source_is_refused(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_source("tcg-001", retrieval_status=RetrievalStatus.BLOCKED))
    media = write_media(tmp_path, "photo.png", b"synthetic-media-bytes-005")
    with pytest.raises(BundleError, match="blocked"):
        add_media(bundle_root, "tcg-001", media)


def test_init_bundle_refuses_git_repositories(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(BundleError, match="git repository"):
        init_bundle(
            tmp_path / "bundle",
            bundle_id="op05-119-en-manga-001",
            card_id="op05-119",
            set_code="OP05",
            language=Language.EN,
            exact_print_variant="OP05-119 SEC Manga Rare (EN)",
            region_release="EN-2023",
        )


# --- acquisition tasks (blocked retrievals) ---------------------------------------


def test_blocked_retrieval_creates_acquisition_task_retaining_url(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    source = make_source("tcg-002", retrieval_status=RetrievalStatus.BLOCKED)
    _, task = add_source(bundle_root, source, blocked_reason=BlockReason.ANTI_BOT)

    assert task is not None
    assert task.source_url == source.source_url
    assert task.reason_blocked is BlockReason.ANTI_BOT
    assert task.status.value == "open"

    stored = list_acquisition_tasks(bundle_root)
    assert [item.task_id for item in stored] == [task.task_id]

    validator = load_schema("acquisition-task.schema.json")
    validator.validate(task.model_dump(mode="json", exclude_none=True))

    result = validate_bundle(bundle_root)
    assert result["valid"], result["errors"]


def test_acquisition_task_model_has_no_bypass_fields() -> None:
    fields = set(AcquisitionTask.model_fields)
    assert fields == {
        "task_id",
        "bundle_id",
        "source_url",
        "reason_blocked",
        "detected_at",
        "requested_media",
        "status",
        "assignee",
        "resolution_notes",
    }


def test_retrieved_source_does_not_create_task(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    _, task = add_source(bundle_root, make_source("ebay-003"))
    assert task is None
    assert list_acquisition_tasks(bundle_root) == []


# --- deterministic scoring ---------------------------------------------------------


def test_scoring_is_deterministic() -> None:
    source = make_source(private_media_hash="a" * 64)
    first = score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    second = score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.weights == DEFAULT_SCORE_WEIGHTS


def test_score_round_trips_against_frozen_schema() -> None:
    source = make_source(private_media_hash="a" * 64)
    score = score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    tier = compute_bundle_tier("op05-119-en-manga-001", [score, score])
    validator = load_schema("reference-source-quality.schema.json")
    validator.validate(
        {
            "source_score": score.model_dump(mode="json", exclude_none=True),
            "bundle_tier": tier.model_dump(mode="json", exclude_none=True),
        }
    )


def test_strong_clean_source_scores_tier_a() -> None:
    source = make_source(private_media_hash="a" * 64)
    score = score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    assert score.tier is SourceTier.A
    assert score.composite_score >= 0.75


def test_blocked_source_is_tier_c() -> None:
    source = make_source(retrieval_status=RetrievalStatus.BLOCKED)
    score = score_source(source, alignment_success=0.0, computed_at=FIXED_TIME)
    assert score.tier is SourceTier.C
    assert "blocked" in score.tier_rationale


def test_source_without_media_is_tier_c() -> None:
    source = make_source()
    score = score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    assert score.tier is SourceTier.C
    assert "no ingested media" in score.tier_rationale


def test_high_proxy_risk_never_reaches_tier_b() -> None:
    source = make_source(private_media_hash="a" * 64, proxy_risk=ProxyRisk.HIGH)
    score = score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    assert score.tier is SourceTier.C


def test_medium_quality_source_scores_tier_b() -> None:
    source = make_source(
        private_media_hash="a" * 64,
        variant_confidence=0.7,
        protection=Protection.SLEEVED,
        compression=CompressionLevel.MEDIUM,
        lighting=LightingUsefulness.MEDIUM,
        useful_angles=2,
        macro=False,
    )
    score = score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    assert score.tier is SourceTier.B


# --- tier gating ---------------------------------------------------------------------


def score_with_tier(source_id: str, tier: SourceTier) -> SourceQualityScore:
    if tier is SourceTier.A:
        source = make_source(source_id, private_media_hash=source_id[0] * 64)
        return score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    if tier is SourceTier.B:
        source = make_source(
            source_id,
            private_media_hash=source_id[0] * 64,
            variant_confidence=0.7,
            protection=Protection.SLEEVED,
            compression=CompressionLevel.MEDIUM,
            lighting=LightingUsefulness.MEDIUM,
            useful_angles=2,
            macro=False,
        )
        return score_source(source, alignment_success=1.0, computed_at=FIXED_TIME)
    source = make_source(source_id, retrieval_status=RetrievalStatus.BLOCKED)
    return score_source(source, alignment_success=0.0, computed_at=FIXED_TIME)


def test_two_tier_a_sources_make_bundle_a_and_eligible() -> None:
    scores = [score_with_tier("a-one", SourceTier.A), score_with_tier("b-two", SourceTier.A)]
    record = compute_bundle_tier("bundle-a", scores)
    assert record.tier is SourceTier.A
    assert record.eligible_for_profile is True


def test_single_tier_a_source_is_only_tier_b() -> None:
    record = compute_bundle_tier("bundle-b", [score_with_tier("a-one", SourceTier.A)])
    assert record.tier is SourceTier.B
    assert record.eligible_for_profile is False


def test_tier_b_requires_named_human_review_for_eligibility() -> None:
    scores = [score_with_tier("a-one", SourceTier.B), score_with_tier("b-two", SourceTier.B)]
    unreviewed = compute_bundle_tier("bundle-c", scores)
    assert unreviewed.tier is SourceTier.B
    assert unreviewed.eligible_for_profile is False

    reviewed = compute_bundle_tier(
        "bundle-c", scores, human_reviewed_tier_b=True, reviewer="Eric Yun"
    )
    assert reviewed.eligible_for_profile is True


def test_tier_c_bundle_is_never_eligible() -> None:
    scores = [score_with_tier("c-one", SourceTier.C)]
    record = compute_bundle_tier(
        "bundle-d", scores, human_reviewed_tier_b=True, reviewer="Eric Yun"
    )
    assert record.tier is SourceTier.C
    assert record.eligible_for_profile is False


def test_tier_record_model_refuses_ineligible_claims() -> None:
    score = score_with_tier("c-one", SourceTier.C)
    with pytest.raises(ValidationError):
        BundleTierRecord(
            bundle_id="bundle-e",
            tier=SourceTier.C,
            source_scores=[score],
            human_reviewed_tier_b=False,
            eligible_for_profile=True,
        )
    b_score = score_with_tier("b-one", SourceTier.B)
    with pytest.raises(ValidationError):
        BundleTierRecord(
            bundle_id="bundle-e",
            tier=SourceTier.B,
            source_scores=[b_score],
            human_reviewed_tier_b=False,
            reviewer=None,
            eligible_for_profile=True,
        )


def test_tier_bundle_persists_record_and_manifest_tier(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_source("ebay-001"))
    media = write_media(tmp_path, "photo.png", b"synthetic-media-bytes-006")
    add_media(bundle_root, "ebay-001", media)

    record = tier_bundle(bundle_root)
    assert (bundle_root / "review" / "bundle-tier.json").is_file()
    manifest = load_bundle_manifest(bundle_root)
    assert manifest.tier is record.tier

    result = validate_bundle(bundle_root)
    assert result["valid"], result["errors"]


# --- source registration guards -----------------------------------------------------


def test_add_source_rejects_mismatched_card(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    source = make_source("ebay-001").model_copy(update={"card_id": "op06-001"})
    with pytest.raises(BundleError, match="card_id"):
        add_source(bundle_root, ReferenceSourceRecord.model_validate(source.model_dump()))


def test_blocked_source_cannot_carry_media_hash() -> None:
    with pytest.raises(ValidationError):
        make_source(
            "tcg-001",
            retrieval_status=RetrievalStatus.BLOCKED,
            private_media_hash="a" * 64,
        )


# --- CLI end-to-end -----------------------------------------------------------------


def test_cli_end_to_end(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    media_one = write_media(tmp_path, "one.png", b"cli-media-one")
    media_two = write_media(tmp_path, "two.png", b"cli-media-two")

    result = runner.invoke(
        app,
        [
            "init-bundle", str(bundle_root),
            "--bundle-id", "op05-119-en-manga-001",
            "--card-id", "op05-119",
            "--set-code", "OP05",
            "--exact-print-variant", "OP05-119 SEC Manga Rare (EN)",
            "--region-release", "EN-2023",
            "--rights-status", "restricted-research",
        ],
    )
    assert result.exit_code == 0, result.output

    common = [
        "--card-id", "op05-119",
        "--exact-print-variant", "OP05-119 SEC Manga Rare (EN)",
        "--region-release", "EN-2023",
        "--source-type", "ebay-listing",
        "--protection", "raw",
        "--media-form", "still",
        "--useful-angles", "6",
        "--macro",
        "--lighting", "high",
        "--compression", "low",
        "--editing-likelihood", "low",
        "--variant-confidence", "0.95",
        "--proxy-risk", "low",
        "--rights-status", "restricted-research",
        "--width", "1600",
        "--height", "2200",
    ]
    for source_id, url in (("ebay-001", "https://example.com/1"), ("ebay-002", "https://example.com/2")):
        result = runner.invoke(
            app,
            [
                "add-source", str(bundle_root),
                "--source-id", source_id,
                "--source-url", url,
                "--retrieval-status", "retrieved",
                *common,
            ],
        )
        assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "add-source", str(bundle_root),
            "--source-id", "tcg-001",
            "--source-url", "https://example.com/blocked",
            "--retrieval-status", "blocked",
            "--reason-blocked", "anti-bot",
            *common,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "acquisition" in result.output

    for source_id, media in (("ebay-001", media_one), ("ebay-002", media_two)):
        result = runner.invoke(app, ["add-media", str(bundle_root), source_id, str(media)])
        assert result.exit_code == 0, result.output
        assert "blake3" in result.output

    result = runner.invoke(app, ["acquisition-task", str(bundle_root), "--list"])
    assert result.exit_code == 0, result.output
    assert "1 open" in result.output

    result = runner.invoke(app, ["score", str(bundle_root)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["tier", str(bundle_root)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["validate", str(bundle_root)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output
