"""Per-image normalization for Lane A reference media (ADR-0002 Phase 1).

Pipeline per accepted media file:

1. Verify the original file still matches its manifest BLAKE3 hash; the
   original is never modified or overwritten.
2. Detect the card boundary and rectify to canonical card coordinates
   (``geometry.py`` public API, imported read-only).
3. Register printed features against a clean English reference image.
   Weak alignment is *rejected* with a diagnostic record — never accepted.
4. Flag sleeve/slab/toploader interference regions with conservative,
   explicitly low-confidence heuristics (uncertainty is recorded, never
   silently passed).
5. Record conservative exposure / white-balance *metadata only*.

Geometry is normalized; appearance is not. There is deliberately no global
color, brightness, or white-balance equalization step: per-source foil
appearance differences are real evidence and must survive normalization.
Outputs are written alongside originals; both are retained and hashed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .geometry import (
    CANONICAL_HEIGHT,
    CANONICAL_WIDTH,
    GeometryError,
    detect_card_quad,
    register_residual,
    warp_card,
    write_image,
)
from .provenance import hash_file
from .quality import read_image
from .reference_bundle import (
    NORMALIZE_DIAGNOSTICS_DIRECTORY,
    BundleError,
    MediaForm,
    Protection,
    ReferenceSourceRecord,
    RetrievalStatus,
    load_bundle_manifest,
    media_directory,
)

NORMALIZATION_SCHEMA_VERSION = "1.0.0"

HASH_PATTERN = r"^[0-9a-f]{64}$"

PROTECTED_PROTECTIONS = (Protection.SLEEVED, Protection.TOPLOADER, Protection.SLABBED)

APPEARANCE_PRESERVATION_NOTE = (
    "metadata only: pixel values are never exposure- or white-balance-equalized "
    "across sources; per-source foil appearance differences are preserved"
)

INTERFERENCE_HEURISTIC_NOTE = (
    "conservative low-confidence heuristic: bright low-saturation regions may be "
    "sleeve/slab/toploader reflections or genuine foil specular highlights; "
    "human review is required to distinguish them"
)


class NormalizeError(RuntimeError):
    """Raised when normalization cannot proceed safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class NormalizationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_matches: int = Field(default=24, ge=4)
    minimum_inliers: int = Field(default=14, ge=4)
    minimum_inlier_ratio: float = Field(default=0.45, ge=0, le=1)
    maximum_median_reprojection_error: float = Field(default=3.0, gt=0)
    glare_value_threshold: int = Field(default=245, ge=1, le=255)
    glare_saturation_threshold: int = Field(default=40, ge=0, le=255)
    glare_minimum_region_ratio: float = Field(default=0.0005, ge=0, le=1)
    glare_flag_ratio: float = Field(default=0.002, ge=0, le=1)


class NormalizationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class InterferenceRegion(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    area_ratio: float = Field(ge=0, le=1)


class InterferenceReport(StrictModel):
    declared_protection: Protection
    protection_flagged: bool
    heuristic_glare_ratio: float = Field(ge=0, le=1)
    regions: list[InterferenceRegion] = Field(default_factory=list)
    mask_path: str | None = None
    mask_blake3: str | None = Field(default=None, pattern=HASH_PATTERN)
    flagged: bool
    heuristic_confidence: str = "low"
    notes: list[str] = Field(default_factory=list)


class ExposureMetadata(StrictModel):
    """Conservative exposure / white-balance observation — never a correction."""

    mean_luminance: float = Field(ge=0, le=1)
    channel_means_bgr: list[float]
    gray_world_gains_bgr: list[float]
    dark_clip_ratio: float = Field(ge=0, le=1)
    bright_clip_ratio: float = Field(ge=0, le=1)
    note: str = APPEARANCE_PRESERVATION_NOTE


class RegistrationMetrics(StrictModel):
    matches: int = Field(ge=0)
    inliers: int = Field(ge=0)
    inlier_ratio: float = Field(ge=0, le=1)
    median_reprojection_error: float = Field(ge=0)


class DetectionMetrics(StrictModel):
    score: float
    area_ratio: float
    aspect_ratio: float
    rectangularity: float


class NormalizationRecord(StrictModel):
    schema_version: str = NORMALIZATION_SCHEMA_VERSION
    bundle_id: str
    source_id: str
    status: NormalizationStatus
    reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    original_path: str
    original_blake3: str = Field(pattern=HASH_PATTERN)
    original_hash_verified: bool
    reference_path: str
    reference_blake3: str = Field(pattern=HASH_PATTERN)
    rectified_path: str | None = None
    rectified_blake3: str | None = Field(default=None, pattern=HASH_PATTERN)
    registered_path: str | None = None
    registered_blake3: str | None = Field(default=None, pattern=HASH_PATTERN)
    detection: DetectionMetrics | None = None
    registration: RegistrationMetrics | None = None
    interference: InterferenceReport | None = None
    exposure: ExposureMetadata | None = None
    thresholds: NormalizationThresholds


def _relative_or_absolute(path: Path, bundle_root: Path) -> str:
    try:
        return path.resolve().relative_to(bundle_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _write_record(bundle_root: Path, record: NormalizationRecord) -> Path:
    directory = bundle_root / NORMALIZE_DIAGNOSTICS_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{record.source_id}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        record.model_dump_json(indent=2, exclude_none=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def compute_exposure_metadata(image: np.ndarray) -> ExposureMetadata:
    """Observe exposure and illuminant balance without altering any pixels."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    channel_means = [float(image[:, :, index].mean()) / 255.0 for index in range(3)]
    overall = float(np.mean(channel_means))
    gains = [
        round(overall / mean, 4) if mean > 1e-6 else 0.0
        for mean in channel_means
    ]
    return ExposureMetadata(
        mean_luminance=float(gray.mean()),
        channel_means_bgr=[round(value, 4) for value in channel_means],
        gray_world_gains_bgr=gains,
        dark_clip_ratio=float(np.mean(gray <= (4.0 / 255.0))),
        bright_clip_ratio=float(np.mean(gray >= (251.0 / 255.0))),
    )


def detect_interference(
    image: np.ndarray,
    *,
    declared_protection: Protection,
    thresholds: NormalizationThresholds,
) -> tuple[InterferenceReport, np.ndarray | None]:
    """Conservative sleeve/slab/toploader interference flagging.

    The heuristic marks bright, low-saturation pixels (plastic reflections
    read as near-white glare). It is deliberately labeled low-confidence:
    foil specular highlights can trigger it, and matte sleeves can evade it,
    so declared protection always forces a flag regardless of pixels found.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    glare = (
        (value >= thresholds.glare_value_threshold)
        & (saturation <= thresholds.glare_saturation_threshold)
    ).astype(np.uint8) * 255
    glare = cv2.morphologyEx(
        glare, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    )

    image_area = float(image.shape[0] * image.shape[1])
    count, _, stats, _ = cv2.connectedComponentsWithStats(glare, connectivity=8)
    regions: list[InterferenceRegion] = []
    for label in range(1, count):
        area_ratio = float(stats[label, cv2.CC_STAT_AREA]) / image_area
        if area_ratio < thresholds.glare_minimum_region_ratio:
            continue
        regions.append(
            InterferenceRegion(
                x=int(stats[label, cv2.CC_STAT_LEFT]),
                y=int(stats[label, cv2.CC_STAT_TOP]),
                width=int(stats[label, cv2.CC_STAT_WIDTH]),
                height=int(stats[label, cv2.CC_STAT_HEIGHT]),
                area_ratio=round(area_ratio, 6),
            )
        )
    regions.sort(key=lambda region: region.area_ratio, reverse=True)

    glare_ratio = float(np.mean(glare > 0))
    protection_flagged = declared_protection in PROTECTED_PROTECTIONS
    notes = [INTERFERENCE_HEURISTIC_NOTE]
    if protection_flagged:
        notes.append(
            f"declared protection '{declared_protection.value}': the whole frame is "
            "treated as potentially interfered even where the heuristic found nothing"
        )
    if declared_protection is Protection.UNKNOWN:
        notes.append(
            "protection is unknown: interference cannot be ruled out; treat regions "
            "and unflagged areas alike with caution"
        )

    flagged = (
        protection_flagged
        or declared_protection is Protection.UNKNOWN
        or glare_ratio >= thresholds.glare_flag_ratio
        or bool(regions)
    )
    report = InterferenceReport(
        declared_protection=declared_protection,
        protection_flagged=protection_flagged,
        heuristic_glare_ratio=round(glare_ratio, 6),
        regions=regions,
        flagged=flagged,
        notes=notes,
    )
    mask = glare if (regions or glare_ratio > 0) else None
    return report, mask


def _locate_media_file(bundle_root: Path, record: ReferenceSourceRecord) -> Path:
    """Locate the ingested file structurally; hash verification happens separately.

    This deliberately does not require a hash match: a tampered original must
    surface as a rejected diagnostic record, not as a missing file.
    """
    directory = media_directory(bundle_root, record.source_id)
    candidates = sorted(path for path in directory.glob("*") if path.is_file())
    if not candidates:
        raise BundleError(f"no ingested media file found for source {record.source_id}")
    if len(candidates) > 1:
        for candidate in candidates:
            if hash_file(candidate) == record.private_media_hash:
                return candidate
        raise BundleError(
            f"multiple media files for source {record.source_id} and none matches "
            "the recorded hash"
        )
    return candidates[0]


def load_reference_image(reference_path: Path) -> np.ndarray:
    """Load the clean English reference at canonical card dimensions."""
    if not reference_path.is_file():
        raise NormalizeError(f"reference image does not exist: {reference_path}")
    reference = read_image(reference_path)
    if reference.shape[:2] != (CANONICAL_HEIGHT, CANONICAL_WIDTH):
        reference = cv2.resize(
            reference,
            (CANONICAL_WIDTH, CANONICAL_HEIGHT),
            interpolation=cv2.INTER_LANCZOS4,
        )
    return reference


def normalize_source(
    bundle_root: Path,
    source_id: str,
    *,
    reference_path: Path,
    thresholds: NormalizationThresholds | None = None,
    manual_quad: list[list[float]] | None = None,
) -> NormalizationRecord:
    limits = thresholds or NormalizationThresholds()
    manifest = load_bundle_manifest(bundle_root)
    record = next(
        (item for item in manifest.sources if item.source_id == source_id), None
    )
    if record is None:
        raise BundleError(f"unknown source: {source_id}")
    if record.retrieval_status is not RetrievalStatus.RETRIEVED:
        raise BundleError(f"source {source_id} has not been retrieved; nothing to normalize")
    if record.private_media_hash is None:
        raise BundleError(f"source {source_id} has no ingested media")

    original = _locate_media_file(bundle_root, record)
    original_digest = hash_file(original)
    reference_digest = hash_file(reference_path)
    base = NormalizationRecord(
        bundle_id=manifest.bundle_id,
        source_id=source_id,
        status=NormalizationStatus.REJECTED,
        original_path=_relative_or_absolute(original, bundle_root),
        original_blake3=original_digest,
        original_hash_verified=original_digest == record.private_media_hash,
        reference_path=str(reference_path.resolve()),
        reference_blake3=reference_digest,
        thresholds=limits,
    )

    if not base.original_hash_verified:
        base.reasons = [
            "original media hash no longer matches the manifest; ingested files are "
            "immutable — refusing to normalize tampered input"
        ]
        _write_record(bundle_root, base)
        return base

    if record.media_form is MediaForm.VIDEO:
        base.status = NormalizationStatus.SKIPPED
        base.reasons = [
            "video normalization is not automated; frame selection from video is a "
            "human curation step, after which frames are ingested as still sources"
        ]
        _write_record(bundle_root, base)
        return base

    reference = load_reference_image(reference_path)

    try:
        image = read_image(original)
        if manual_quad is None:
            candidate = detect_card_quad(image)
            quad = candidate.points
            base.detection = DetectionMetrics(
                score=float(candidate.score),
                area_ratio=float(candidate.area_ratio),
                aspect_ratio=float(candidate.aspect_ratio),
                rectangularity=float(candidate.rectangularity),
            )
        else:
            quad = np.asarray(manual_quad, dtype=np.float32)
            if quad.shape != (4, 2):
                raise GeometryError("manual quad must contain four [x, y] points")
        rectified, _ = warp_card(image, quad)
    except (GeometryError, ValueError) as exc:
        base.reasons = [f"rectification failed: {exc}"]
        _write_record(bundle_root, base)
        return base

    try:
        registration = register_residual(
            rectified,
            reference,
            minimum_matches=limits.minimum_matches,
            minimum_inliers=limits.minimum_inliers,
        )
    except GeometryError as exc:
        base.reasons = [f"registration to the clean reference failed: {exc}"]
        _write_record(bundle_root, base)
        return base

    metrics = RegistrationMetrics(
        matches=registration.matches,
        inliers=registration.inliers,
        inlier_ratio=float(registration.inlier_ratio),
        median_reprojection_error=float(registration.reprojection_error),
    )
    base.registration = metrics

    weak_reasons: list[str] = []
    if metrics.inlier_ratio < limits.minimum_inlier_ratio:
        weak_reasons.append(
            f"weak alignment: inlier ratio {metrics.inlier_ratio:.3f} < "
            f"{limits.minimum_inlier_ratio:.3f}"
        )
    if metrics.median_reprojection_error > limits.maximum_median_reprojection_error:
        weak_reasons.append(
            "weak alignment: median reprojection error "
            f"{metrics.median_reprojection_error:.2f}px > "
            f"{limits.maximum_median_reprojection_error:.2f}px"
        )
    if weak_reasons:
        base.reasons = weak_reasons
        _write_record(bundle_root, base)
        return base

    # Geometry only from here on: exposure is observed, never corrected.
    base.exposure = compute_exposure_metadata(rectified)
    interference, mask = detect_interference(
        rectified,
        declared_protection=record.protection,
        thresholds=limits,
    )
    if mask is not None:
        mask_path = (
            bundle_root / NORMALIZE_DIAGNOSTICS_DIRECTORY / f"{source_id}-interference.png"
        )
        write_image(mask_path, mask)
        interference.mask_path = _relative_or_absolute(mask_path, bundle_root)
        interference.mask_blake3 = hash_file(mask_path)
    base.interference = interference

    stem = original.stem
    rectified_path = bundle_root / "normalized" / source_id / f"{stem}-rectified.png"
    registered_path = bundle_root / "registered" / source_id / f"{stem}-registered.png"
    write_image(rectified_path, rectified)
    write_image(registered_path, registration.image)

    base.rectified_path = _relative_or_absolute(rectified_path, bundle_root)
    base.rectified_blake3 = hash_file(rectified_path)
    base.registered_path = _relative_or_absolute(registered_path, bundle_root)
    base.registered_blake3 = hash_file(registered_path)

    # The original must be byte-identical after the run (written alongside, never over).
    base.original_hash_verified = hash_file(original) == record.private_media_hash
    if not base.original_hash_verified:
        base.status = NormalizationStatus.REJECTED
        base.reasons = ["original media changed during normalization; run rejected"]
        _write_record(bundle_root, base)
        return base

    base.status = NormalizationStatus.ACCEPTED
    _write_record(bundle_root, base)
    return base


def normalize_bundle(
    bundle_root: Path,
    *,
    reference_path: Path,
    thresholds: NormalizationThresholds | None = None,
    source_ids: list[str] | None = None,
    manual_quads: dict[str, list[list[float]]] | None = None,
) -> list[NormalizationRecord]:
    manifest = load_bundle_manifest(bundle_root)
    selected = source_ids or [
        record.source_id
        for record in manifest.sources
        if record.retrieval_status is RetrievalStatus.RETRIEVED
        and record.private_media_hash is not None
    ]
    if not selected:
        raise BundleError("no retrieved sources with ingested media to normalize")
    quads = manual_quads or {}
    return [
        normalize_source(
            bundle_root,
            source_id,
            reference_path=reference_path,
            thresholds=thresholds,
            manual_quad=quads.get(source_id),
        )
        for source_id in selected
    ]


def load_normalization_record(bundle_root: Path, source_id: str) -> NormalizationRecord:
    path = bundle_root / NORMALIZE_DIAGNOSTICS_DIRECTORY / f"{source_id}.json"
    if not path.is_file():
        raise NormalizeError(f"no normalization record for source: {source_id}")
    return NormalizationRecord.model_validate_json(path.read_text(encoding="utf-8"))


def summarize_records(records: list[NormalizationRecord]) -> dict[str, int]:
    summary = {status.value: 0 for status in NormalizationStatus}
    for record in records:
        summary[record.status.value] += 1
    return summary


__all__ = [
    "APPEARANCE_PRESERVATION_NOTE",
    "DetectionMetrics",
    "ExposureMetadata",
    "InterferenceRegion",
    "InterferenceReport",
    "NormalizationRecord",
    "NormalizationStatus",
    "NormalizationThresholds",
    "NormalizeError",
    "RegistrationMetrics",
    "compute_exposure_metadata",
    "detect_interference",
    "load_normalization_record",
    "load_reference_image",
    "normalize_bundle",
    "normalize_source",
    "summarize_records",
]
