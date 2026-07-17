from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from optcg_material.geometry import CANONICAL_HEIGHT, CANONICAL_WIDTH
from optcg_material.models import Language, RightsStatus
from optcg_material.provenance import hash_file
from optcg_material.reference_bundle import (
    CompressionLevel,
    EditingLikelihood,
    LightingUsefulness,
    MediaForm,
    MediaResolution,
    Protection,
    ReferenceSourceRecord,
    RetrievalStatus,
    add_media,
    add_source,
    alignment_success_from_diagnostics,
    init_bundle,
    load_bundle_manifest,
)
from optcg_material.reference_normalize import (
    APPEARANCE_PRESERVATION_NOTE,
    NormalizationStatus,
    load_normalization_record,
    normalize_source,
)

FIXED_VARIANT = "OP05-119 SEC Manga Rare (EN)"


def synthetic_card(width: int = 718, height: int = 1000) -> np.ndarray:
    """Same synthetic fixture style as tests/test_geometry.py."""
    card = np.full((height, width, 3), 225, dtype=np.uint8)
    cv2.rectangle(card, (4, 4), (width - 5, height - 5), (20, 20, 20), 12)
    cv2.rectangle(card, (45, 70), (width - 45, 650), (80, 120, 180), -1)
    cv2.circle(card, (width // 2, 360), 170, (230, 200, 70), 14)
    cv2.putText(
        card,
        "OPTCG MATERIAL",
        (70, 760),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.35,
        (10, 10, 10),
        3,
        cv2.LINE_AA,
    )
    for offset in range(0, 130, 22):
        cv2.line(card, (70, 820 + offset), (640, 820 + offset), (35, 35, 35), 3)
    return card


def different_card(width: int = 718, height: int = 1000) -> np.ndarray:
    """A card with a border but almost no interior features to match against."""
    card = np.full((height, width, 3), 210, dtype=np.uint8)
    cv2.rectangle(card, (4, 4), (width - 5, height - 5), (20, 20, 20), 12)
    return card


def perspective_scene(card: np.ndarray, *, brightness: float = 1.0) -> np.ndarray:
    if brightness != 1.0:
        card = np.clip(card.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    canvas = np.full((2400, 1800, 3), 30, dtype=np.uint8)
    source = np.float32([[0, 0], [717, 0], [717, 999], [0, 999]])
    destination = np.float32([[360, 220], [1430, 330], [1320, 2150], [260, 2020]])
    matrix = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(card, matrix, (canvas.shape[1], canvas.shape[0]))
    mask = cv2.warpPerspective(
        np.full(card.shape[:2], 255, dtype=np.uint8),
        matrix,
        (canvas.shape[1], canvas.shape[0]),
    )
    canvas[mask > 0] = warped[mask > 0]
    return canvas


def write_png(path: Path, image: np.ndarray) -> Path:
    success, encoded = cv2.imencode(".png", image)
    assert success
    encoded.tofile(path)
    return path


def make_bundle(tmp_path: Path) -> Path:
    bundle_root = tmp_path / "bundle"
    init_bundle(
        bundle_root,
        bundle_id="op05-119-en-manga-001",
        card_id="op05-119",
        set_code="OP05",
        language=Language.EN,
        exact_print_variant=FIXED_VARIANT,
        region_release="EN-2023",
        rights_status=RightsStatus.RESTRICTED_RESEARCH,
    )
    return bundle_root


def make_source(
    source_id: str,
    *,
    protection: Protection = Protection.RAW,
    media_form: MediaForm = MediaForm.STILL,
) -> ReferenceSourceRecord:
    return ReferenceSourceRecord(
        source_id=source_id,
        source_url=f"https://example.com/listings/{source_id}",
        source_type="ebay-listing",
        retrieval_date="2026-07-16T12:00:00Z",
        card_id="op05-119",
        language=Language.EN,
        exact_print_variant=FIXED_VARIANT,
        region_release="EN-2023",
        protection=protection,
        media_form=media_form,
        resolution=MediaResolution(width=1800, height=2400),
        useful_angles=3,
        macro_available=False,
        lighting_usefulness=LightingUsefulness.MEDIUM,
        compression_level=CompressionLevel.LOW,
        editing_likelihood=EditingLikelihood.LOW,
        variant_confidence=0.95,
        proxy_counterfeit_risk="low",
        rights_status=RightsStatus.RESTRICTED_RESEARCH,
        retrieval_status=RetrievalStatus.RETRIEVED,
    )


def reference_image_path(tmp_path: Path) -> Path:
    reference = cv2.resize(
        synthetic_card(),
        (CANONICAL_WIDTH, CANONICAL_HEIGHT),
        interpolation=cv2.INTER_CUBIC,
    )
    return write_png(tmp_path / "clean-reference.png", reference)


def ingest_scene(
    tmp_path: Path,
    bundle_root: Path,
    source_id: str,
    scene: np.ndarray,
    *,
    protection: Protection = Protection.RAW,
) -> Path:
    add_source(bundle_root, make_source(source_id, protection=protection))
    media = write_png(tmp_path / f"{source_id}.png", scene)
    _, destination, _ = add_media(bundle_root, source_id, media)
    return destination


def test_normalization_preserves_original_and_writes_alongside(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    original = ingest_scene(tmp_path, bundle_root, "ebay-001", perspective_scene(synthetic_card()))
    reference = reference_image_path(tmp_path)
    hash_before = hash_file(original)

    record = normalize_source(bundle_root, "ebay-001", reference_path=reference)

    assert record.status is NormalizationStatus.ACCEPTED, record.reasons
    # Original retained byte-identical, alongside the new outputs.
    assert original.is_file()
    assert hash_file(original) == hash_before == record.original_blake3
    assert record.original_hash_verified

    rectified = bundle_root / record.rectified_path
    registered = bundle_root / record.registered_path
    assert rectified.is_file() and registered.is_file()
    assert rectified != original and registered != original
    assert hash_file(rectified) == record.rectified_blake3
    assert hash_file(registered) == record.registered_blake3

    stored = load_normalization_record(bundle_root, "ebay-001")
    assert stored.status is NormalizationStatus.ACCEPTED
    assert alignment_success_from_diagnostics(bundle_root, "ebay-001") == 1.0

    # Manifest untouched by normalization: media hash still verified.
    manifest = load_bundle_manifest(bundle_root)
    assert manifest.sources[0].private_media_hash == hash_before


def test_weak_alignment_is_rejected_with_diagnostic(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    ingest_scene(tmp_path, bundle_root, "ebay-002", perspective_scene(different_card()))
    reference = reference_image_path(tmp_path)

    record = normalize_source(bundle_root, "ebay-002", reference_path=reference)

    assert record.status is NormalizationStatus.REJECTED
    assert record.reasons, "rejection must carry a diagnostic reason"
    assert record.registered_path is None and record.rectified_path is None
    assert not (bundle_root / "registered" / "ebay-002").exists()

    stored = load_normalization_record(bundle_root, "ebay-002")
    assert stored.status is NormalizationStatus.REJECTED
    assert alignment_success_from_diagnostics(bundle_root, "ebay-002") == 0.0


def test_sleeve_interference_is_flagged_with_regions(tmp_path: Path) -> None:
    card = synthetic_card()
    # Simulate a sleeve reflection: a bright, desaturated glare band.
    cv2.rectangle(card, (60, 150), (660, 240), (255, 255, 255), -1)
    bundle_root = make_bundle(tmp_path)
    ingest_scene(
        tmp_path,
        bundle_root,
        "ebay-003",
        perspective_scene(card),
        protection=Protection.SLEEVED,
    )
    reference = reference_image_path(tmp_path)

    record = normalize_source(bundle_root, "ebay-003", reference_path=reference)

    assert record.status is NormalizationStatus.ACCEPTED, record.reasons
    interference = record.interference
    assert interference is not None
    assert interference.flagged
    assert interference.protection_flagged
    assert interference.regions, "the glare band should produce at least one region"
    assert interference.heuristic_confidence == "low"
    assert any("human review" in note for note in interference.notes)
    mask_path = bundle_root / interference.mask_path
    assert mask_path.is_file()
    assert hash_file(mask_path) == interference.mask_blake3


def test_raw_protection_still_records_honest_uncertainty_note(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    ingest_scene(tmp_path, bundle_root, "ebay-004", perspective_scene(synthetic_card()))
    reference = reference_image_path(tmp_path)

    record = normalize_source(bundle_root, "ebay-004", reference_path=reference)

    assert record.status is NormalizationStatus.ACCEPTED, record.reasons
    assert record.interference is not None
    assert not record.interference.protection_flagged
    assert record.interference.notes, "heuristic limits must always be disclosed"


def test_exposure_metadata_recorded_without_equalization(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    bright = perspective_scene(synthetic_card(), brightness=1.0)
    dark = perspective_scene(synthetic_card(), brightness=0.55)
    ingest_scene(tmp_path, bundle_root, "ebay-005", bright)
    ingest_scene(tmp_path, bundle_root, "ebay-006", dark)
    reference = reference_image_path(tmp_path)

    record_bright = normalize_source(bundle_root, "ebay-005", reference_path=reference)
    record_dark = normalize_source(bundle_root, "ebay-006", reference_path=reference)

    assert record_bright.status is NormalizationStatus.ACCEPTED, record_bright.reasons
    assert record_dark.status is NormalizationStatus.ACCEPTED, record_dark.reasons

    assert record_bright.exposure is not None and record_dark.exposure is not None
    assert record_bright.exposure.note == APPEARANCE_PRESERVATION_NOTE

    # Metadata observes the exposure difference...
    luminance_gap = (
        record_bright.exposure.mean_luminance - record_dark.exposure.mean_luminance
    )
    assert luminance_gap > 0.15

    # ...and the pixels keep it: no global normalization erased the difference.
    bright_out = cv2.imread(str(bundle_root / record_bright.registered_path))
    dark_out = cv2.imread(str(bundle_root / record_dark.registered_path))
    assert float(bright_out.mean()) - float(dark_out.mean()) > 0.15 * 255 * 0.5


def test_video_media_is_skipped_not_silently_passed(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    add_source(bundle_root, make_source("video-001", media_form=MediaForm.VIDEO))
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not-a-real-video-payload")
    add_media(bundle_root, "video-001", media)
    reference = reference_image_path(tmp_path)

    record = normalize_source(bundle_root, "video-001", reference_path=reference)

    assert record.status is NormalizationStatus.SKIPPED
    assert any("human" in reason for reason in record.reasons)
    assert alignment_success_from_diagnostics(bundle_root, "video-001") == 0.0


def test_tampered_original_is_refused(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    original = ingest_scene(
        tmp_path, bundle_root, "ebay-007", perspective_scene(synthetic_card())
    )
    reference = reference_image_path(tmp_path)

    original.write_bytes(b"tampered-after-ingestion")
    record = normalize_source(bundle_root, "ebay-007", reference_path=reference)

    assert record.status is NormalizationStatus.REJECTED
    assert any("immutable" in reason or "tampered" in reason for reason in record.reasons)


def test_diagnostic_record_is_valid_json_with_hashes(tmp_path: Path) -> None:
    bundle_root = make_bundle(tmp_path)
    ingest_scene(tmp_path, bundle_root, "ebay-008", perspective_scene(synthetic_card()))
    reference = reference_image_path(tmp_path)

    normalize_source(bundle_root, "ebay-008", reference_path=reference)
    payload = json.loads(
        (bundle_root / "diagnostics" / "normalize" / "ebay-008.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["status"] == "accepted"
    for key in ("original_blake3", "reference_blake3", "rectified_blake3", "registered_blake3"):
        assert len(payload[key]) == 64
    assert payload["registration"]["inliers"] >= 14
