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
    COVERAGE_AXES,
    COVERAGE_ROUTE_COMPOSITE_FLOOR,
    DEFAULT_SCORE_WEIGHTS,
    TIER_B_MINIMUM_COMPOSITE,
    AcquisitionTask,
    BlockReason,
    BundleCoverageRecord,
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
    compute_bundle_coverage,
    compute_bundle_tier,
    compute_manifest_digest,
    coverage_bundle,
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


# --- bundle coverage ------------------------------------------------------------------


def make_single_angle_source(
    source_id: str,
    *,
    seller: str | None = "seller-x",
    review_notes: str | None = None,
    variant_confidence: float = 0.9,
    proxy_risk: ProxyRisk = ProxyRisk.LOW,
    editing: EditingLikelihood = EditingLikelihood.LOW,
    media_form: MediaForm = MediaForm.STILL,
    macro: bool = False,
) -> ReferenceSourceRecord:
    """A well-registered but individually weak source (single-angle penalty).

    With accepted registration (alignment 1.0) the per-source composite is
    ~0.4953 — below the tier-B per-source floor of 0.50 — reproducing the
    0.499 scenario from the first Lane A execution.
    """
    base = make_source(
        source_id,
        variant_confidence=variant_confidence,
        protection=Protection.SLEEVED,
        proxy_risk=proxy_risk,
        compression=CompressionLevel.HIGH,
        editing=editing,
        useful_angles=1,
        macro=macro,
        lighting=LightingUsefulness.MEDIUM,
        resolution=MediaResolution(width=1000, height=1400),
    )
    data = base.model_dump()
    data["seller_uploader"] = seller
    data["review_notes"] = review_notes
    data["media_form"] = media_form
    return ReferenceSourceRecord.model_validate(data)


def write_normalize_diagnostics(
    bundle_root: Path,
    source_id: str,
    *,
    status: str = "accepted",
    interference_flagged: bool = False,
    pose_label: str | None = None,
) -> None:
    payload: dict = {"status": status, "interference": {"flagged": interference_flagged}}
    if pose_label is not None:
        payload["pose"] = {"angle_label": pose_label}
    directory = bundle_root / "diagnostics" / "normalize"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{source_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def add_registered_source(
    tmp_path: Path,
    bundle_root: Path,
    source: ReferenceSourceRecord,
    *,
    interference_flagged: bool = False,
    pose_label: str | None = None,
) -> None:
    add_source(bundle_root, source)
    media = write_media(tmp_path, f"{source.source_id}.png", f"media-{source.source_id}".encode())
    add_media(bundle_root, source.source_id, media)
    write_normalize_diagnostics(
        bundle_root,
        source.source_id,
        interference_flagged=interference_flagged,
        pose_label=pose_label,
    )


def test_coverage_record_has_seven_axes_and_is_persisted(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_registered_source(
        tmp_path,
        bundle_root,
        make_single_angle_source("ebay-001", review_notes="ANGLE: face-on", macro=True),
    )
    record = coverage_bundle(bundle_root, computed_at=FIXED_TIME)

    assert set(record.axes) == set(COVERAGE_AXES)
    for axis in record.axes.values():
        assert 0.0 <= axis.score <= 1.0
        assert axis.rationale
    assert 0.0 <= record.composite <= 1.0

    coverage_path = bundle_root / "review" / "bundle-coverage.json"
    assert coverage_path.is_file()
    reparsed = BundleCoverageRecord.model_validate_json(
        coverage_path.read_text(encoding="utf-8")
    )
    assert reparsed == record


def test_coverage_is_deterministic_and_reads_temporal_and_macro_axes(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_registered_source(
        tmp_path,
        bundle_root,
        make_single_angle_source(
            "ebay-001", review_notes="ANGLE: face-on", media_form=MediaForm.VIDEO, macro=True
        ),
    )
    first = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    second = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.axes["temporal_sequence"].score == 1.0
    assert first.axes["macro_coverage"].score == 1.0


def test_provenance_unknown_sources_collapse_to_one_family(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    for index, seller in enumerate(("alice", "bob", "carol"), start=1):
        add_registered_source(
            tmp_path,
            bundle_root,
            make_single_angle_source(
                f"ebay-00{index}",
                seller=seller,
                review_notes=f"ANGLE: view-{index}; PROVENANCE UNKNOWN — attribution unverified",
            ),
        )
    record = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    assert record.independent_family_count == 1
    assert record.axes["independent_sources"].score == pytest.approx(1 / 3, abs=1e-3)


def test_distinct_sellers_count_as_independent_families(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    for index, seller in enumerate(("alice", "bob", "carol"), start=1):
        add_registered_source(
            tmp_path,
            bundle_root,
            make_single_angle_source(
                f"ebay-00{index}", seller=seller, review_notes=f"ANGLE: view-{index}"
            ),
        )
    record = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    assert record.independent_family_count == 3
    assert record.axes["independent_sources"].score == 1.0


def test_unlabeled_angles_collapse_and_pose_metadata_wins(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    # Two unlabeled sources collapse into ONE angle bucket (fail closed) ...
    add_registered_source(tmp_path, bundle_root, make_single_angle_source("ebay-001"))
    add_registered_source(tmp_path, bundle_root, make_single_angle_source("ebay-002"))
    record = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    assert record.distinct_angle_count == 1
    # ... while pose metadata in the diagnostics takes precedence over notes.
    add_registered_source(
        tmp_path,
        bundle_root,
        make_single_angle_source("ebay-003", review_notes="ANGLE: face-on"),
        pose_label="tilt-left-30",
    )
    record = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    assert record.distinct_angle_count == 2  # unlabeled bucket + pose label


def test_coverage_with_no_accepted_sources_is_zero_and_route_unsatisfied(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_single_angle_source("ebay-001"))  # no media, no diagnostics
    record = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    assert record.accepted_source_ids == []
    assert record.composite == 0.0
    assert record.multi_angle_route.satisfied is False


def test_multi_angle_bundle_reaches_reviewed_b_eligibility(tmp_path: Path) -> None:
    """The 0.499 scenario: three registered single-angle sources at variant
    confidence 0.9 reach the reviewed-B eligibility path while each source
    alone stays below the per-source tier-B floor."""
    bundle_root = make_bundle(tmp_path)
    for index, angle in enumerate(("face-on", "tilt-left", "tilt-right"), start=1):
        add_registered_source(
            tmp_path,
            bundle_root,
            make_single_angle_source(f"ebay-00{index}", review_notes=f"ANGLE: {angle}"),
        )

    coverage = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    assert coverage.distinct_angle_count == 3
    assert coverage.composite >= COVERAGE_ROUTE_COMPOSITE_FLOOR
    assert coverage.multi_angle_route.satisfied is True

    unreviewed = tier_bundle(bundle_root)
    for score in unreviewed.source_scores:
        assert score.tier is SourceTier.C
        assert score.composite_score < TIER_B_MINIMUM_COMPOSITE
    assert unreviewed.tier is SourceTier.B  # multi-angle route, never tier A
    assert unreviewed.eligible_for_profile is False  # human review still required

    reviewed = tier_bundle(bundle_root, human_reviewed_tier_b=True, reviewer="Eric Yun")
    assert reviewed.tier is SourceTier.B
    assert reviewed.eligible_for_profile is True

    # The persisted tier record still conforms to the frozen schema exactly.
    tier_payload = json.loads(
        (bundle_root / "review" / "bundle-tier.json").read_text(encoding="utf-8")
    )
    validator = load_schema("reference-source-quality.schema.json")
    validator.validate(
        {"source_score": tier_payload["source_scores"][0], "bundle_tier": tier_payload}
    )
    coverage_payload = json.loads(
        (bundle_root / "review" / "bundle-coverage.json").read_text(encoding="utf-8")
    )
    assert coverage_payload["multi_angle_route"]["satisfied"] is True


def test_weak_source_contributes_nothing_to_the_coverage_route(tmp_path: Path) -> None:
    """A high-proxy-risk source is never upgraded by bundle diversity and its
    angle does not count toward the multi-angle route."""
    bundle_root = make_bundle(tmp_path)
    add_registered_source(
        tmp_path, bundle_root, make_single_angle_source("ebay-001", review_notes="ANGLE: face-on")
    )
    add_registered_source(
        tmp_path, bundle_root, make_single_angle_source("ebay-002", review_notes="ANGLE: tilt-left")
    )
    # The third distinct angle exists ONLY on a weak (high proxy risk) source.
    add_registered_source(
        tmp_path,
        bundle_root,
        make_single_angle_source(
            "ebay-003", review_notes="ANGLE: tilt-right", proxy_risk=ProxyRisk.HIGH
        ),
    )

    coverage = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    assert "ebay-003" not in coverage.multi_angle_route.qualifying_source_ids
    assert coverage.multi_angle_route.distinct_angles == 2
    assert coverage.multi_angle_route.satisfied is False

    record = tier_bundle(bundle_root, human_reviewed_tier_b=True, reviewer="Eric Yun")
    weak = next(score for score in record.source_scores if score.source_id == "ebay-003")
    assert weak.tier is SourceTier.C  # the individual source is not upgraded
    assert record.tier is SourceTier.C  # and the bundle is not promoted through it
    assert record.eligible_for_profile is False


def test_coverage_from_a_different_bundle_is_refused() -> None:
    scores = [score_with_tier("c-one", SourceTier.C)]
    foreign = BundleCoverageRecord(
        bundle_id="another-bundle",
        computed_at=FIXED_TIME,
        accepted_source_ids=[],
        independent_family_count=0,
        distinct_angle_count=0,
        axes={
            name: {"score": 0.0, "rationale": "empty"}
            for name in COVERAGE_AXES
        },
        weights=dict.fromkeys(COVERAGE_AXES, 1 / 7),
        composite=0.0,
        multi_angle_route={
            "qualifying_source_ids": [],
            "distinct_angles": 0,
            "minimum_variant_confidence": 0.0,
            "composite_floor": COVERAGE_ROUTE_COMPOSITE_FLOOR,
            "satisfied": False,
            "rationale": "empty",
        },
    )
    with pytest.raises(BundleError, match="belongs to bundle"):
        compute_bundle_tier("bundle-x", scores, coverage=foreign)


def test_coverage_cli_verb_writes_record(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_registered_source(
        tmp_path, bundle_root, make_single_angle_source("ebay-001", review_notes="ANGLE: face-on")
    )
    result = runner.invoke(app, ["coverage", str(bundle_root)])
    assert result.exit_code == 0, result.output
    assert "coverage composite" in result.output
    assert (bundle_root / "review" / "bundle-coverage.json").is_file()

    result = runner.invoke(app, ["coverage", str(bundle_root), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload["axes"]) == set(COVERAGE_AXES)


def test_single_family_route_is_flagged_for_the_reviewer(tmp_path: Path) -> None:
    """PR #15 independent-review finding 1: a route satisfied entirely by one
    provenance family must say so explicitly in the record and rationale."""
    bundle_root = make_bundle(tmp_path)
    for index, angle in enumerate(("face-on", "tilt-left", "tilt-right"), start=1):
        add_registered_source(
            tmp_path,
            bundle_root,
            make_single_angle_source(f"ebay-00{index}", review_notes=f"ANGLE: {angle}"),
        )
    coverage = compute_bundle_coverage(bundle_root, computed_at=FIXED_TIME)
    route = coverage.multi_angle_route
    assert route.satisfied is True
    assert route.qualifying_family_count == 1
    assert route.single_family is True
    assert "SINGLE-FAMILY ROUTE" in route.rationale
