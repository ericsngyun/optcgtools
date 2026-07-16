"""Lane A (reference) bundle tooling — ADR-0002 Phase 1.

Implements the frozen interface contracts in:

- ``docs/agent-ops/reference-bundle.schema.json``
- ``docs/agent-ops/reference-source-quality.schema.json``
- ``docs/agent-ops/acquisition-task.schema.json``

The schemas are frozen; these models conform to them, never the reverse.

Policy notes (fail closed):

- A blocked retrieval (``retrieval_status: blocked``) becomes a human
  acquisition task that retains the source URL. There is intentionally no
  code path that automates around anti-bot controls: no HTTP client, no
  header or user-agent manipulation, and no scraping fallback exists in
  this module. Humans acquire blocked media.
- Every accepted media file is hashed with BLAKE3 and recorded in the
  bundle manifest before it is usable. The manifest schema records exactly
  one ``private_media_hash`` per source record, so this tooling ingests one
  media file per source; a multi-photo listing is recorded as sibling
  source records (e.g. ``ebay-123.img1``, ``ebay-123.img2``).
- Ingested media is immutable: a source's media hash can never be replaced.
- Bundle roots live outside any git repository (private storage); card
  imagery is never written into the repo.
- Tier C is never eligible for a profile. Tier B is eligible only when a
  named human reviewer has recorded the review; a model cannot self-approve.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from statistics import median
from typing import Any

from blake3 import blake3
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Language, RightsStatus
from .provenance import hash_file

BUNDLE_SCHEMA_VERSION = "1.0.0"
MANIFEST_FILENAME = "manifest.json"
URLS_FILENAME = "urls.json"
ACQUISITION_TASKS_DIRECTORY = "sources/acquisition-tasks"
SOURCE_SCORES_FILENAME = "diagnostics/source-scores.json"
BUNDLE_TIER_FILENAME = "review/bundle-tier.json"
BUNDLE_COVERAGE_FILENAME = "review/bundle-coverage.json"
NORMALIZE_DIAGNOSTICS_DIRECTORY = "diagnostics/normalize"

SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]{1,95}$"
HASH_PATTERN = r"^[0-9a-f]{64}$"
_SLUG_RE = re.compile(SLUG_PATTERN)

PLACEHOLDER_DIGEST = "0" * 64

# ADR-0002 private bundle layout.
BUNDLE_DIRECTORIES: tuple[str, ...] = (
    "sources/source-notes",
    ACQUISITION_TASKS_DIRECTORY,
    "private-media",
    "normalized",
    "registered",
    "appearance",
    "semantic",
    "profiles",
    "renders",
    "diagnostics",
    NORMALIZE_DIAGNOSTICS_DIRECTORY,
    "review",
)


class BundleError(RuntimeError):
    """Raised when a reference bundle cannot advance safely."""


class SourceType(StrEnum):
    EBAY_LISTING = "ebay-listing"
    MARKETPLACE_DATABASE = "marketplace-database"
    RETAILER = "retailer"
    OFFICIAL = "official"
    COLLECTOR_VIDEO = "collector-video"
    AUCTION_HOUSE = "auction-house"
    OTHER = "other"


class Protection(StrEnum):
    RAW = "raw"
    SLEEVED = "sleeved"
    TOPLOADER = "toploader"
    SLABBED = "slabbed"
    UNKNOWN = "unknown"


class MediaForm(StrEnum):
    STILL = "still"
    VIDEO = "video"


class LightingUsefulness(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class CompressionLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class EditingLikelihood(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ProxyRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RetrievalStatus(StrEnum):
    RETRIEVED = "retrieved"
    BLOCKED = "blocked"


class SourceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class BlockReason(StrEnum):
    ANTI_BOT = "anti-bot"
    PAYWALL = "paywall"
    LOGIN_REQUIRED = "login-required"
    GEOBLOCK = "geoblock"
    OTHER = "other"


class AcquisitionStatus(StrEnum):
    OPEN = "open"
    ACQUIRED = "acquired"
    ABANDONED = "abandoned"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class VariantVerification(StrictModel):
    """Human-only exact-print-variant verification; a model cannot record it."""

    verified: bool = False
    verifier: str | None = Field(default=None, min_length=1)
    method: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    notes: str | None = None

    @model_validator(mode="after")
    def verified_requires_named_human(self) -> VariantVerification:
        if self.verified and not self.verifier:
            raise ValueError("verified variant verification requires a named human verifier")
        return self


class TierOverride(StrictModel):
    reviewer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class MediaResolution(StrictModel):
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class ReferenceSourceRecord(StrictModel):
    source_id: str = Field(pattern=SLUG_PATTERN)
    source_url: str = Field(min_length=1)
    source_type: SourceType
    retrieval_date: datetime
    card_id: str = Field(min_length=2, max_length=64)
    language: Language
    exact_print_variant: str = Field(min_length=1)
    region_release: str = Field(min_length=1)
    seller_uploader: str | None = None
    protection: Protection
    media_form: MediaForm
    resolution: MediaResolution | None = None
    useful_angles: int = Field(ge=0)
    macro_available: bool
    lighting_usefulness: LightingUsefulness
    compression_level: CompressionLevel
    editing_likelihood: EditingLikelihood
    variant_confidence: float = Field(ge=0, le=1)
    proxy_counterfeit_risk: ProxyRisk
    rights_status: RightsStatus
    private_media_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    retrieval_status: RetrievalStatus
    review_notes: str | None = None

    @model_validator(mode="after")
    def blocked_sources_carry_no_media(self) -> ReferenceSourceRecord:
        if self.retrieval_status is RetrievalStatus.BLOCKED and self.private_media_hash:
            raise ValueError("a blocked retrieval cannot carry ingested media")
        return self


class ReferenceBundleManifest(StrictModel):
    schema_version: str = Field(default=BUNDLE_SCHEMA_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    bundle_id: str = Field(pattern=SLUG_PATTERN)
    card_id: str = Field(min_length=2, max_length=64)
    set_code: str = Field(min_length=2, max_length=16)
    language: Language
    exact_print_variant: str = Field(min_length=1)
    region_release: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    variant_verification: VariantVerification
    rights_status: RightsStatus
    rights_reviewer: str | None = Field(default=None, min_length=1)
    tier: SourceTier | None = None
    tier_override: TierOverride | None = None
    source_ids: list[str] = Field(default_factory=list)
    sources: list[ReferenceSourceRecord] = Field(default_factory=list)
    private_media_root: str
    manifest_digest: str = Field(default=PLACEHOLDER_DIGEST, pattern=HASH_PATTERN)
    notes: str | None = None

    @field_validator("source_ids")
    @classmethod
    def source_ids_must_be_slugs(cls, values: list[str]) -> list[str]:
        for value in values:
            if not _SLUG_RE.fullmatch(value):
                raise ValueError(f"source_id is not a lowercase slug: {value}")
        if len(values) != len(set(values)):
            raise ValueError("source_ids must be unique")
        return values

    @model_validator(mode="after")
    def sources_must_match_source_ids(self) -> ReferenceBundleManifest:
        record_ids = [record.source_id for record in self.sources]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("source records must be unique by source_id")
        known = set(self.source_ids)
        for record_id in record_ids:
            if record_id not in known:
                raise ValueError(f"source record {record_id} is missing from source_ids")
        hashes = [record.private_media_hash for record in self.sources if record.private_media_hash]
        if len(hashes) != len(set(hashes)):
            raise ValueError("duplicate media content is not allowed in one bundle")
        return self


class SourceQualityScore(StrictModel):
    source_id: str = Field(pattern=SLUG_PATTERN)
    exact_variant_match: float = Field(ge=0, le=1)
    english_confirmation: float = Field(ge=0, le=1)
    surface_visibility: float = Field(ge=0, le=1)
    angles_score: float = Field(ge=0, le=1)
    macro_score: float = Field(ge=0, le=1)
    lighting_diversity: float = Field(ge=0, le=1)
    resolution_score: float = Field(ge=0, le=1)
    compression_penalty: float = Field(ge=0, le=1)
    editing_risk_penalty: float = Field(ge=0, le=1)
    proxy_risk_penalty: float = Field(ge=0, le=1)
    alignment_success: float = Field(ge=0, le=1)
    weights: dict[str, float]
    composite_score: float = Field(ge=0, le=1)
    tier: SourceTier
    tier_rationale: str = Field(min_length=1)
    computed_at: datetime

    @field_validator("weights")
    @classmethod
    def weights_must_be_non_negative(cls, values: dict[str, float]) -> dict[str, float]:
        for name, weight in values.items():
            if weight < 0:
                raise ValueError(f"weight {name} must be non-negative")
        return values


class BundleTierRecord(StrictModel):
    bundle_id: str = Field(pattern=SLUG_PATTERN)
    tier: SourceTier
    source_scores: list[SourceQualityScore] = Field(min_length=1)
    human_reviewed_tier_b: bool
    reviewer: str | None = None
    eligible_for_profile: bool

    @model_validator(mode="after")
    def eligibility_is_fail_closed(self) -> BundleTierRecord:
        if self.tier is SourceTier.C and self.eligible_for_profile:
            raise ValueError("tier C is never eligible for a profile")
        if (
            self.tier is SourceTier.B
            and self.eligible_for_profile
            and (not self.human_reviewed_tier_b or not self.reviewer)
        ):
            raise ValueError(
                "tier B eligibility requires a recorded human review and a named reviewer"
            )
        if self.human_reviewed_tier_b and not self.reviewer:
            raise ValueError("a recorded tier-B review requires a named reviewer")
        return self


class AcquisitionTask(StrictModel):
    """A blocked retrieval handed to a human.

    This model intentionally carries no credential, header, cookie, or
    bypass fields — agents never automate around anti-bot controls.
    """

    task_id: str = Field(pattern=SLUG_PATTERN)
    bundle_id: str = Field(pattern=SLUG_PATTERN)
    source_url: str = Field(min_length=1)
    reason_blocked: BlockReason
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requested_media: str = Field(min_length=1)
    status: AcquisitionStatus = AcquisitionStatus.OPEN
    assignee: str | None = None
    resolution_notes: str | None = None


# --- canonical manifest digest ------------------------------------------------

def canonical_payload_digest(payload: dict[str, Any]) -> str:
    """BLAKE3 of the canonical JSON encoding (sorted keys, compact separators)."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return blake3(encoded).hexdigest()


def compute_manifest_digest(manifest: ReferenceBundleManifest) -> str:
    """Digest of the manifest content, excluding the digest field itself."""
    data = manifest.model_dump(mode="json", exclude_none=True)
    data.pop("manifest_digest", None)
    return canonical_payload_digest(data)


# --- persistence ----------------------------------------------------------------

def _write_json_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def ensure_outside_repository(bundle_root: Path) -> None:
    """Raw card imagery never enters a git working tree (private storage only)."""
    for parent in [bundle_root.resolve(), *bundle_root.resolve().parents]:
        if (parent / ".git").exists():
            raise BundleError(
                f"bundle root {bundle_root} is inside a git repository; "
                "reference bundles must live in private storage outside any repo"
            )


def load_bundle_manifest(bundle_root: Path) -> ReferenceBundleManifest:
    manifest_path = bundle_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise BundleError(f"missing bundle manifest: {manifest_path}")
    return ReferenceBundleManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )


def save_bundle_manifest(bundle_root: Path, manifest: ReferenceBundleManifest) -> Path:
    manifest.updated_at = datetime.now(UTC)
    manifest.manifest_digest = compute_manifest_digest(manifest)
    manifest_path = bundle_root / MANIFEST_FILENAME
    _write_json_atomic(
        manifest_path,
        manifest.model_dump_json(indent=2, exclude_none=True) + "\n",
    )
    return manifest_path


def _save_urls_index(bundle_root: Path, manifest: ReferenceBundleManifest) -> None:
    urls = {record.source_id: record.source_url for record in manifest.sources}
    _write_json_atomic(
        bundle_root / "sources" / URLS_FILENAME,
        json.dumps(urls, indent=2, sort_keys=True) + "\n",
    )


def init_bundle(
    bundle_root: Path,
    *,
    bundle_id: str,
    card_id: str,
    set_code: str,
    language: Language,
    exact_print_variant: str,
    region_release: str,
    rights_status: RightsStatus = RightsStatus.UNKNOWN,
    notes: str | None = None,
) -> ReferenceBundleManifest:
    ensure_outside_repository(bundle_root)
    if bundle_root.exists() and any(bundle_root.iterdir()):
        raise BundleError(f"bundle directory is not empty: {bundle_root}")

    for name in BUNDLE_DIRECTORIES:
        (bundle_root / name).mkdir(parents=True, exist_ok=True)

    manifest = ReferenceBundleManifest(
        bundle_id=bundle_id,
        card_id=card_id,
        set_code=set_code,
        language=language,
        exact_print_variant=exact_print_variant,
        region_release=region_release,
        variant_verification=VariantVerification(
            verified=False,
            method="pending-human-verification",
            confidence=0.0,
        ),
        rights_status=rights_status,
        private_media_root=str(bundle_root),
        notes=notes,
    )
    save_bundle_manifest(bundle_root, manifest)
    return manifest


def record_variant_verification(
    bundle_root: Path,
    *,
    verifier: str,
    method: str,
    confidence: float,
    notes: str | None = None,
) -> ReferenceBundleManifest:
    """Record the human-only exact-variant verification gate."""
    manifest = load_bundle_manifest(bundle_root)
    manifest.variant_verification = VariantVerification(
        verified=True,
        verifier=verifier,
        method=method,
        confidence=confidence,
        notes=notes,
    )
    save_bundle_manifest(bundle_root, manifest)
    return manifest


def _default_task_id(bundle_id: str, source_url: str) -> str:
    digest = blake3(source_url.encode()).hexdigest()[:16]
    return f"acq-{digest}-{bundle_id}"[:96]


def create_acquisition_task(
    bundle_root: Path,
    *,
    source_url: str,
    reason_blocked: BlockReason,
    requested_media: str,
    task_id: str | None = None,
    assignee: str | None = None,
) -> AcquisitionTask:
    manifest = load_bundle_manifest(bundle_root)
    task = AcquisitionTask(
        task_id=task_id or _default_task_id(manifest.bundle_id, source_url),
        bundle_id=manifest.bundle_id,
        source_url=source_url,
        reason_blocked=reason_blocked,
        requested_media=requested_media,
        assignee=assignee,
    )
    task_path = bundle_root / ACQUISITION_TASKS_DIRECTORY / f"{task.task_id}.json"
    if task_path.exists():
        raise BundleError(f"acquisition task already recorded: {task.task_id}")
    _write_json_atomic(task_path, task.model_dump_json(indent=2, exclude_none=True) + "\n")
    return task


def list_acquisition_tasks(bundle_root: Path) -> list[AcquisitionTask]:
    directory = bundle_root / ACQUISITION_TASKS_DIRECTORY
    if not directory.is_dir():
        return []
    return [
        AcquisitionTask.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]


def add_source(
    bundle_root: Path,
    record: ReferenceSourceRecord,
    *,
    blocked_reason: BlockReason = BlockReason.ANTI_BOT,
    requested_media: str | None = None,
) -> tuple[ReferenceSourceRecord, AcquisitionTask | None]:
    """Register a public source. A blocked retrieval becomes a human task.

    No retrieval is performed here; media enters only through
    :func:`add_media` from files a human already obtained lawfully.
    """
    manifest = load_bundle_manifest(bundle_root)
    if any(existing.source_id == record.source_id for existing in manifest.sources):
        raise BundleError(f"source already registered: {record.source_id}")
    if record.card_id != manifest.card_id:
        raise BundleError(
            f"source card_id {record.card_id} does not match bundle card_id {manifest.card_id}"
        )
    if record.language is not manifest.language:
        raise BundleError("source language does not match the bundle language")
    if record.exact_print_variant != manifest.exact_print_variant:
        raise BundleError("source exact_print_variant does not match the bundle variant")

    # source_ids first: assignment validation requires every record id to be listed.
    manifest.source_ids = [*manifest.source_ids, record.source_id]
    manifest.sources = [*manifest.sources, record]
    save_bundle_manifest(bundle_root, manifest)
    _save_urls_index(bundle_root, manifest)

    task: AcquisitionTask | None = None
    if record.retrieval_status is RetrievalStatus.BLOCKED:
        task = create_acquisition_task(
            bundle_root,
            source_url=record.source_url,
            reason_blocked=blocked_reason,
            requested_media=requested_media
            or f"card imagery for {manifest.card_id} ({manifest.exact_print_variant})",
        )
    return record, task


def media_directory(bundle_root: Path, source_id: str) -> Path:
    return bundle_root / "private-media" / source_id


def add_media(
    bundle_root: Path,
    source_id: str,
    media_path: Path,
) -> tuple[ReferenceSourceRecord, Path, str]:
    """Hash-record and copy one human-acquired media file for a source.

    The manifest schema stores exactly one media hash per source record, so
    each source accepts exactly one file; an already-ingested source is
    immutable and rejects replacement.
    """
    if not media_path.is_file():
        raise BundleError(f"media source does not exist: {media_path}")

    manifest = load_bundle_manifest(bundle_root)
    record = next((item for item in manifest.sources if item.source_id == source_id), None)
    if record is None:
        raise BundleError(f"unknown source: {source_id}")
    if record.retrieval_status is RetrievalStatus.BLOCKED:
        raise BundleError(
            f"source {source_id} is blocked; resolve its acquisition task "
            "(human retrieval) and re-register it as retrieved first"
        )
    if record.private_media_hash is not None:
        raise BundleError(
            f"source {source_id} already has ingested media; ingested files are immutable"
        )

    digest = hash_file(media_path)
    if any(item.private_media_hash == digest for item in manifest.sources):
        raise BundleError(f"duplicate media content already ingested: {digest}")

    destination_directory = media_directory(bundle_root, source_id)
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / f"{digest[:12]}{media_path.suffix.lower()}"
    shutil.copy2(media_path, destination)

    copied_digest = hash_file(destination)
    if copied_digest != digest:
        destination.unlink(missing_ok=True)
        raise BundleError("media copy failed hash verification; ingestion aborted")

    record.private_media_hash = digest
    save_bundle_manifest(bundle_root, manifest)
    return record, destination, digest


def find_media_file(bundle_root: Path, record: ReferenceSourceRecord) -> Path:
    if record.private_media_hash is None:
        raise BundleError(f"source {record.source_id} has no ingested media")
    directory = media_directory(bundle_root, record.source_id)
    candidates = sorted(path for path in directory.glob("*") if path.is_file())
    for candidate in candidates:
        if hash_file(candidate) == record.private_media_hash:
            return candidate
    raise BundleError(
        f"no media file matching the recorded hash for source {record.source_id}"
    )


# --- deterministic scoring ------------------------------------------------------

# Documented composite weights. Positive-component weights sum to 1.0 so a
# flawless, penalty-free source scores exactly 1.0; penalties subtract.
DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "exact_variant_match": 0.22,
    "english_confirmation": 0.10,
    "surface_visibility": 0.14,
    "angles_score": 0.10,
    "macro_score": 0.08,
    "lighting_diversity": 0.08,
    "resolution_score": 0.10,
    "alignment_success": 0.18,
    "compression_penalty": 0.30,
    "editing_risk_penalty": 0.35,
    "proxy_risk_penalty": 0.50,
}

POSITIVE_COMPONENTS: tuple[str, ...] = (
    "exact_variant_match",
    "english_confirmation",
    "surface_visibility",
    "angles_score",
    "macro_score",
    "lighting_diversity",
    "resolution_score",
    "alignment_success",
)

PENALTY_COMPONENTS: tuple[str, ...] = (
    "compression_penalty",
    "editing_risk_penalty",
    "proxy_risk_penalty",
)

# Documented deterministic component mappings.
SURFACE_VISIBILITY_BY_PROTECTION: dict[Protection, float] = {
    Protection.RAW: 1.0,
    Protection.SLEEVED: 0.7,
    Protection.TOPLOADER: 0.5,
    Protection.SLABBED: 0.35,
    Protection.UNKNOWN: 0.4,
}

LIGHTING_DIVERSITY_BY_USEFULNESS: dict[LightingUsefulness, float] = {
    LightingUsefulness.NONE: 0.0,
    LightingUsefulness.LOW: 0.35,
    LightingUsefulness.MEDIUM: 0.7,
    LightingUsefulness.HIGH: 1.0,
    LightingUsefulness.UNKNOWN: 0.25,
}

COMPRESSION_PENALTY_BY_LEVEL: dict[CompressionLevel, float] = {
    CompressionLevel.LOW: 0.0,
    CompressionLevel.MEDIUM: 0.4,
    CompressionLevel.HIGH: 0.8,
    CompressionLevel.UNKNOWN: 0.5,
}

EDITING_PENALTY_BY_LIKELIHOOD: dict[EditingLikelihood, float] = {
    EditingLikelihood.LOW: 0.0,
    EditingLikelihood.MEDIUM: 0.5,
    EditingLikelihood.HIGH: 1.0,
    EditingLikelihood.UNKNOWN: 0.6,
}

PROXY_PENALTY_BY_RISK: dict[ProxyRisk, float] = {
    ProxyRisk.LOW: 0.0,
    ProxyRisk.MEDIUM: 0.5,
    ProxyRisk.HIGH: 1.0,
}

USEFUL_ANGLES_SATURATION = 5
RESOLUTION_SCORE_FULL_MARK_PX = 1200
RESOLUTION_UNKNOWN_SCORE = 0.25

TIER_A_MINIMUM_COMPOSITE = 0.75
TIER_A_MINIMUM_VARIANT_MATCH = 0.9
TIER_B_MINIMUM_COMPOSITE = 0.50
TIER_B_MINIMUM_VARIANT_MATCH = 0.6


def _score_components(
    source: ReferenceSourceRecord,
    *,
    alignment_success: float,
) -> dict[str, float]:
    if source.resolution is None:
        resolution_score = RESOLUTION_UNKNOWN_SCORE
    else:
        short_side = min(source.resolution.width, source.resolution.height)
        resolution_score = min(short_side / RESOLUTION_SCORE_FULL_MARK_PX, 1.0)
    return {
        "exact_variant_match": float(source.variant_confidence),
        "english_confirmation": 1.0 if source.language is Language.EN else 0.0,
        "surface_visibility": SURFACE_VISIBILITY_BY_PROTECTION[source.protection],
        "angles_score": min(source.useful_angles / USEFUL_ANGLES_SATURATION, 1.0),
        "macro_score": 1.0 if source.macro_available else 0.0,
        "lighting_diversity": LIGHTING_DIVERSITY_BY_USEFULNESS[source.lighting_usefulness],
        "resolution_score": resolution_score,
        "alignment_success": max(0.0, min(float(alignment_success), 1.0)),
        "compression_penalty": COMPRESSION_PENALTY_BY_LEVEL[source.compression_level],
        "editing_risk_penalty": EDITING_PENALTY_BY_LIKELIHOOD[source.editing_likelihood],
        "proxy_risk_penalty": PROXY_PENALTY_BY_RISK[source.proxy_counterfeit_risk],
    }


def _classify_source_tier(
    source: ReferenceSourceRecord,
    components: dict[str, float],
    composite: float,
) -> tuple[SourceTier, str]:
    if source.retrieval_status is RetrievalStatus.BLOCKED:
        return SourceTier.C, "retrieval blocked: no ingested media evidence"
    if source.private_media_hash is None:
        return SourceTier.C, "no ingested media: nothing hash-recorded to score"
    if (
        composite >= TIER_A_MINIMUM_COMPOSITE
        and components["exact_variant_match"] >= TIER_A_MINIMUM_VARIANT_MATCH
        and components["proxy_risk_penalty"] == 0.0
    ):
        return SourceTier.A, (
            f"composite {composite:.4f} >= {TIER_A_MINIMUM_COMPOSITE}, variant match "
            f">= {TIER_A_MINIMUM_VARIANT_MATCH}, proxy/counterfeit risk low"
        )
    if (
        composite >= TIER_B_MINIMUM_COMPOSITE
        and components["exact_variant_match"] >= TIER_B_MINIMUM_VARIANT_MATCH
        and components["proxy_risk_penalty"] < 1.0
    ):
        return SourceTier.B, (
            f"composite {composite:.4f} >= {TIER_B_MINIMUM_COMPOSITE} and variant match "
            f">= {TIER_B_MINIMUM_VARIANT_MATCH}; below tier-A thresholds"
        )
    return SourceTier.C, (
        f"composite {composite:.4f} or variant confidence below tier-B thresholds, "
        "or proxy/counterfeit risk high"
    )


def score_source(
    source: ReferenceSourceRecord,
    *,
    alignment_success: float,
    computed_at: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> SourceQualityScore:
    """Deterministic composite score for one source.

    ``composite = clip(sum(w_i * positive_i) - sum(w_j * penalty_j), 0, 1)``
    rounded to 4 decimals. All component derivations are fixed lookup tables
    documented in this module; identical inputs always produce identical output.
    """
    active_weights = dict(weights or DEFAULT_SCORE_WEIGHTS)
    missing = [
        name
        for name in (*POSITIVE_COMPONENTS, *PENALTY_COMPONENTS)
        if name not in active_weights
    ]
    if missing:
        raise BundleError(f"score weights missing components: {', '.join(missing)}")

    components = _score_components(source, alignment_success=alignment_success)
    positive = sum(active_weights[name] * components[name] for name in POSITIVE_COMPONENTS)
    penalty = sum(active_weights[name] * components[name] for name in PENALTY_COMPONENTS)
    composite = round(max(0.0, min(positive - penalty, 1.0)), 4)
    tier, rationale = _classify_source_tier(source, components, composite)

    return SourceQualityScore(
        source_id=source.source_id,
        weights=active_weights,
        composite_score=composite,
        tier=tier,
        tier_rationale=rationale,
        computed_at=computed_at or datetime.now(UTC),
        **components,
    )


def alignment_success_from_diagnostics(bundle_root: Path, source_id: str) -> float:
    """Read the normalization outcome: 1.0 accepted, else 0.0 (fail closed)."""
    path = bundle_root / NORMALIZE_DIAGNOSTICS_DIRECTORY / f"{source_id}.json"
    if not path.is_file():
        return 0.0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0.0
    return 1.0 if payload.get("status") == "accepted" else 0.0


def score_bundle_sources(
    bundle_root: Path,
    *,
    computed_at: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> list[SourceQualityScore]:
    manifest = load_bundle_manifest(bundle_root)
    if not manifest.sources:
        raise BundleError("bundle has no sources to score")
    scores = [
        score_source(
            source,
            alignment_success=alignment_success_from_diagnostics(bundle_root, source.source_id),
            computed_at=computed_at,
            weights=weights,
        )
        for source in manifest.sources
    ]
    payload = [score.model_dump(mode="json", exclude_none=True) for score in scores]
    _write_json_atomic(
        bundle_root / SOURCE_SCORES_FILENAME,
        json.dumps(payload, indent=2) + "\n",
    )
    return scores


# --- bundle coverage ---------------------------------------------------------------
#
# Bundle-level coverage scores what the bundle proves *as a whole*, alongside
# (never replacing) per-source quality scoring. The record is a NEW artifact
# (``review/bundle-coverage.json``) with the documented structure below; the
# frozen reference-source-quality schema is not touched.
#
# Guardrails (both directions):
#
# - No weak-source promotion: coverage never changes any SourceQualityScore,
#   and a source below the per-route floors (failed/absent registration,
#   variant confidence < 0.9, high proxy risk, high editing likelihood)
#   contributes nothing to the multi-angle route.
# - No single-view-only rejection: a coherent bundle of >=3 registered
#   single-view sources spanning >=3 distinct angles may reach reviewed
#   tier-B eligibility even though each frame alone carries the single-angle
#   penalty. Human review is still required for tier B; tier A is unchanged.

COVERAGE_RECORD_VERSION = "1.0.0"

# Marker a human reviewer places in review_notes when seller/listing
# attribution cannot be established. All such sources collapse into ONE
# independent-source family (they could all be the same actor).
PROVENANCE_UNKNOWN_MARKER = "PROVENANCE UNKNOWN"

# Optional human-recorded viewing-angle marker in review_notes, e.g.
# ``ANGLE: tilt-left``. Diagnostics pose metadata takes precedence.
ANGLE_MARKER_PREFIX = "ANGLE:"

COVERAGE_AXES: tuple[str, ...] = (
    "temporal_sequence",
    "angle_span",
    "lighting_consistency",
    "macro_coverage",
    "independent_sources",
    "variant_confidence",
    "interference_diversity",
)

# Documented coverage weights; they sum to 1.0.
DEFAULT_COVERAGE_WEIGHTS: dict[str, float] = {
    "temporal_sequence": 0.10,
    "angle_span": 0.20,
    "lighting_consistency": 0.15,
    "macro_coverage": 0.10,
    "independent_sources": 0.15,
    "variant_confidence": 0.20,
    "interference_diversity": 0.10,
}

ANGLE_SPAN_SATURATION = 3
INDEPENDENT_SOURCE_SATURATION = 3

# Lighting-consistency same-session factor: >=2 accepted sources sharing a
# named seller attribution are treated as same-session lighting evidence.
LIGHTING_INDEPENDENT_SESSION_FACTOR = 0.6

INTERFERENCE_DIVERSITY_MIXED = 1.0
INTERFERENCE_DIVERSITY_ALL_CLEAN = 0.8
INTERFERENCE_DIVERSITY_ALL_FLAGGED = 0.3

# Multi-angle reviewed-B route floors (documented in
# docs/operations/bundle-coverage-scoring.md).
COVERAGE_ROUTE_MINIMUM_SOURCES = 3
COVERAGE_ROUTE_MINIMUM_DISTINCT_ANGLES = 3
COVERAGE_ROUTE_MINIMUM_VARIANT_CONFIDENCE = 0.9
COVERAGE_ROUTE_COMPOSITE_FLOOR = 0.55


class CoverageAxis(StrictModel):
    score: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class MultiAngleRouteResult(StrictModel):
    """Reviewed tier-B eligibility route computed from qualifying sources only."""

    qualifying_source_ids: list[str] = Field(default_factory=list)
    distinct_angles: int = Field(ge=0)
    minimum_variant_confidence: float = Field(ge=0, le=1)
    composite_floor: float = Field(ge=0, le=1)
    # Independent-review finding (PR #15): the route may be satisfied by a
    # single provenance family (a contributor's controlled session IS one
    # family), but that fact must be visible to the human reviewer, never
    # implicit. Single-family satisfaction is flagged in the rationale.
    qualifying_family_count: int = Field(ge=0, default=0)
    single_family: bool = False
    satisfied: bool
    rationale: str = Field(min_length=1)


class BundleCoverageRecord(StrictModel):
    record_version: str = Field(default=COVERAGE_RECORD_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    bundle_id: str = Field(pattern=SLUG_PATTERN)
    computed_at: datetime
    accepted_source_ids: list[str] = Field(default_factory=list)
    independent_family_count: int = Field(ge=0)
    distinct_angle_count: int = Field(ge=0)
    axes: dict[str, CoverageAxis]
    weights: dict[str, float]
    composite: float = Field(ge=0, le=1)
    multi_angle_route: MultiAngleRouteResult

    @model_validator(mode="after")
    def axes_and_weights_cover_all_seven(self) -> BundleCoverageRecord:
        expected = set(COVERAGE_AXES)
        if set(self.axes) != expected:
            raise ValueError("coverage record must contain exactly the seven documented axes")
        if set(self.weights) != expected:
            raise ValueError("coverage weights must cover exactly the seven documented axes")
        for name, weight in self.weights.items():
            if weight < 0:
                raise ValueError(f"coverage weight {name} must be non-negative")
        return self


def _normalize_diagnostics_payload(bundle_root: Path, source_id: str) -> dict[str, Any] | None:
    path = bundle_root / NORMALIZE_DIAGNOSTICS_DIRECTORY / f"{source_id}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _registration_accepted(payload: dict[str, Any] | None) -> bool:
    return payload is not None and payload.get("status") == "accepted"


def _angle_label(source: ReferenceSourceRecord, payload: dict[str, Any] | None) -> str | None:
    """Viewing-angle label: diagnostics pose metadata first, else review-note marker.

    Sources with neither are *unlabeled*; all unlabeled sources collapse into
    a single angle bucket (fail closed: unproven diversity is not diversity).
    """
    if payload is not None:
        pose = payload.get("pose")
        if isinstance(pose, dict):
            label = pose.get("angle_label")
            if isinstance(label, str) and label.strip():
                return f"pose:{label.strip().lower()}"
    notes = source.review_notes or ""
    marker_index = notes.find(ANGLE_MARKER_PREFIX)
    if marker_index >= 0:
        remainder = notes[marker_index + len(ANGLE_MARKER_PREFIX):]
        label = remainder.split("\n")[0].split(";")[0].strip().lower()
        if label:
            return f"note:{label}"
    return None


def _distinct_angle_count(labels: list[str | None]) -> int:
    named = {label for label in labels if label}
    unlabeled_bucket = 1 if any(label is None for label in labels) else 0
    return len(named) + unlabeled_bucket


def _provenance_family_key(source: ReferenceSourceRecord) -> str:
    """Independent-source family attribution — never the source_id.

    Every source whose review notes carry the PROVENANCE UNKNOWN marker
    collapses into ONE shared family: unattributed listings could all
    originate from the same actor.
    """
    if source.review_notes and PROVENANCE_UNKNOWN_MARKER in source.review_notes:
        return "provenance-unknown"
    if source.seller_uploader and source.seller_uploader.strip():
        return f"seller:{source.seller_uploader.strip().lower()}"
    return f"listing:{source.source_url.strip().lower()}"


def _route_qualifying(
    accepted: list[ReferenceSourceRecord],
) -> tuple[list[ReferenceSourceRecord], list[str]]:
    """Per-source floors for the multi-angle route; a weak source contributes nothing."""
    qualifying: list[ReferenceSourceRecord] = []
    exclusions: list[str] = []
    for source in accepted:
        reasons: list[str] = []
        if source.variant_confidence < COVERAGE_ROUTE_MINIMUM_VARIANT_CONFIDENCE:
            reasons.append(
                f"variant confidence {source.variant_confidence:.2f} < "
                f"{COVERAGE_ROUTE_MINIMUM_VARIANT_CONFIDENCE}"
            )
        if source.proxy_counterfeit_risk is ProxyRisk.HIGH:
            reasons.append("high proxy/counterfeit risk")
        if source.editing_likelihood is EditingLikelihood.HIGH:
            reasons.append("high editing likelihood")
        if reasons:
            exclusions.append(f"{source.source_id}: {'; '.join(reasons)}")
        else:
            qualifying.append(source)
    return qualifying, exclusions


def compute_bundle_coverage(
    bundle_root: Path,
    *,
    computed_at: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> BundleCoverageRecord:
    """Deterministic bundle-level coverage record (seven 0-1 axes + composite).

    ``composite = clip(sum(w_axis * score_axis), 0, 1)`` rounded to 4 decimals.
    Only *accepted* sources count toward any axis: retrieved, media ingested,
    and normalization/registration diagnostics recorded as accepted.
    """
    manifest = load_bundle_manifest(bundle_root)
    if not manifest.sources:
        raise BundleError("bundle has no sources to compute coverage for")

    active_weights = dict(weights or DEFAULT_COVERAGE_WEIGHTS)
    missing = [name for name in COVERAGE_AXES if name not in active_weights]
    if missing:
        raise BundleError(f"coverage weights missing axes: {', '.join(missing)}")

    diagnostics = {
        source.source_id: _normalize_diagnostics_payload(bundle_root, source.source_id)
        for source in manifest.sources
    }
    accepted = [
        source
        for source in manifest.sources
        if source.retrieval_status is RetrievalStatus.RETRIEVED
        and source.private_media_hash is not None
        and _registration_accepted(diagnostics[source.source_id])
    ]
    accepted_ids = [source.source_id for source in accepted]
    axes: dict[str, CoverageAxis] = {}

    # 1. Continuous temporal sequence: registered video/sequence media present.
    video_ids = [s.source_id for s in accepted if s.media_form is MediaForm.VIDEO]
    axes["temporal_sequence"] = CoverageAxis(
        score=1.0 if video_ids else 0.0,
        rationale=(
            f"registered video/sequence media from: {', '.join(video_ids)}"
            if video_ids
            else "no registered video/sequence media in the bundle"
        ),
    )

    # 2. Angle span: distinct registered viewing angles. Pose metadata in the
    # normalization diagnostics wins; else the human ANGLE: review-note marker;
    # unlabeled sources collapse into one bucket (documented fail-closed proxy).
    angle_labels = [_angle_label(s, diagnostics[s.source_id]) for s in accepted]
    distinct_angles = _distinct_angle_count(angle_labels)
    axes["angle_span"] = CoverageAxis(
        score=round(min(distinct_angles / ANGLE_SPAN_SATURATION, 1.0), 4),
        rationale=(
            f"{distinct_angles} distinct registered viewing angle(s) across "
            f"{len(accepted)} accepted source(s); unlabeled sources collapse into one bucket "
            f"(saturates at {ANGLE_SPAN_SATURATION})"
        ),
    )

    # 3. Lighting consistency: legible lighting plus same-session evidence
    # (>=2 accepted sources sharing a named, provenance-known seller).
    if accepted:
        legible = [
            s
            for s in accepted
            if s.lighting_usefulness in (LightingUsefulness.MEDIUM, LightingUsefulness.HIGH)
        ]
        legible_fraction = len(legible) / len(accepted)
        session_sellers: dict[str, int] = {}
        for source in accepted:
            key = _provenance_family_key(source)
            if key.startswith("seller:"):
                session_sellers[key] = session_sellers.get(key, 0) + 1
        same_session = any(count >= 2 for count in session_sellers.values())
        factor = 1.0 if same_session else LIGHTING_INDEPENDENT_SESSION_FACTOR
        lighting_score = round(legible_fraction * factor, 4)
        lighting_rationale = (
            f"{len(legible)}/{len(accepted)} accepted source(s) with legible lighting; "
            + (
                "same-session evidence: >=2 accepted sources share a named seller"
                if same_session
                else f"no same-session evidence (factor {LIGHTING_INDEPENDENT_SESSION_FACTOR})"
            )
        )
    else:
        lighting_score = 0.0
        lighting_rationale = "no accepted-registration sources"
    axes["lighting_consistency"] = CoverageAxis(score=lighting_score, rationale=lighting_rationale)

    # 4. Macro coverage: at least one accepted macro source.
    macro_ids = [s.source_id for s in accepted if s.macro_available]
    axes["macro_coverage"] = CoverageAxis(
        score=1.0 if macro_ids else 0.0,
        rationale=(
            f"accepted macro coverage from: {', '.join(macro_ids)}"
            if macro_ids
            else "no accepted source offers macro coverage"
        ),
    )

    # 5. Independent source count: seller/listing attribution families;
    # PROVENANCE UNKNOWN sources collapse into ONE family; never source_id count.
    families = {_provenance_family_key(source) for source in accepted}
    family_count = len(families)
    axes["independent_sources"] = CoverageAxis(
        score=round(min(family_count / INDEPENDENT_SOURCE_SATURATION, 1.0), 4),
        rationale=(
            f"{family_count} independent attribution family(ies) among {len(accepted)} "
            "accepted source(s); provenance-unknown sources collapse into one family "
            f"(saturates at {INDEPENDENT_SOURCE_SATURATION})"
        ),
    )

    # 6. Exact-variant confidence: min/median across accepted sources.
    if accepted:
        confidences = [s.variant_confidence for s in accepted]
        confidence_min = min(confidences)
        confidence_median = float(median(confidences))
        variant_score = round((confidence_min + confidence_median) / 2, 4)
        variant_rationale = (
            f"variant confidence min {confidence_min:.2f}, median {confidence_median:.2f} "
            f"across {len(accepted)} accepted source(s)"
        )
    else:
        variant_score = 0.0
        variant_rationale = "no accepted-registration sources"
    axes["variant_confidence"] = CoverageAxis(score=variant_score, rationale=variant_rationale)

    # 7. Interference diversity: variety of clean vs flagged views. A missing
    # interference report counts as flagged (fail closed).
    if accepted:
        flagged_count = 0
        for source in accepted:
            payload = diagnostics[source.source_id] or {}
            interference = payload.get("interference")
            flagged = interference.get("flagged", True) if isinstance(interference, dict) else True
            flagged_count += 1 if flagged else 0
        clean_count = len(accepted) - flagged_count
        if clean_count and flagged_count:
            interference_score = INTERFERENCE_DIVERSITY_MIXED
            interference_rationale = (
                f"both clean ({clean_count}) and interference-flagged ({flagged_count}) views: "
                "interference can be separated from card appearance"
            )
        elif clean_count:
            interference_score = INTERFERENCE_DIVERSITY_ALL_CLEAN
            interference_rationale = f"all {clean_count} accepted view(s) clean; no interference contrast available"
        else:
            interference_score = INTERFERENCE_DIVERSITY_ALL_FLAGGED
            interference_rationale = f"all {flagged_count} accepted view(s) interference-flagged or unreported"
    else:
        interference_score = 0.0
        interference_rationale = "no accepted-registration sources"
    axes["interference_diversity"] = CoverageAxis(
        score=interference_score, rationale=interference_rationale
    )

    composite = round(
        max(0.0, min(sum(active_weights[name] * axes[name].score for name in COVERAGE_AXES), 1.0)),
        4,
    )

    # Multi-angle reviewed-B route: computed over qualifying sources only.
    qualifying, exclusions = _route_qualifying(accepted)
    qualifying_labels = [_angle_label(s, diagnostics[s.source_id]) for s in qualifying]
    route_angles = _distinct_angle_count(qualifying_labels)
    route_min_confidence = (
        min(s.variant_confidence for s in qualifying) if qualifying else 0.0
    )
    conditions = [
        (
            len(qualifying) >= COVERAGE_ROUTE_MINIMUM_SOURCES,
            f"{len(qualifying)}/{COVERAGE_ROUTE_MINIMUM_SOURCES} qualifying accepted-registration sources",
        ),
        (
            route_angles >= COVERAGE_ROUTE_MINIMUM_DISTINCT_ANGLES,
            f"{route_angles}/{COVERAGE_ROUTE_MINIMUM_DISTINCT_ANGLES} distinct angles among qualifying sources",
        ),
        (
            route_min_confidence >= COVERAGE_ROUTE_MINIMUM_VARIANT_CONFIDENCE,
            f"minimum variant confidence {route_min_confidence:.2f} "
            f"(floor {COVERAGE_ROUTE_MINIMUM_VARIANT_CONFIDENCE})",
        ),
        (
            composite >= COVERAGE_ROUTE_COMPOSITE_FLOOR,
            f"coverage composite {composite:.4f} (floor {COVERAGE_ROUTE_COMPOSITE_FLOOR})",
        ),
    ]
    satisfied = all(held for held, _ in conditions)
    rationale_parts = [
        ("PASS " if held else "FAIL ") + description for held, description in conditions
    ]
    if exclusions:
        rationale_parts.append("excluded weak sources: " + " | ".join(exclusions))
    qualifying_families = {_provenance_family_key(s) for s in qualifying}
    single_family = len(qualifying_families) <= 1
    if satisfied and single_family:
        rationale_parts.append(
            "SINGLE-FAMILY ROUTE: all qualifying sources belong to one provenance "
            "family (one seller/contributor); the named human tier-B reviewer must "
            "confirm the angle diversity is genuine and the family is trusted"
        )
    rationale_parts.append(
        "human review is still required for tier-B eligibility; tier A is unaffected"
    )
    route = MultiAngleRouteResult(
        qualifying_source_ids=[s.source_id for s in qualifying],
        distinct_angles=route_angles,
        minimum_variant_confidence=round(route_min_confidence, 4),
        composite_floor=COVERAGE_ROUTE_COMPOSITE_FLOOR,
        qualifying_family_count=len(qualifying_families),
        single_family=single_family,
        satisfied=satisfied,
        rationale="; ".join(rationale_parts),
    )

    return BundleCoverageRecord(
        bundle_id=manifest.bundle_id,
        computed_at=computed_at or datetime.now(UTC),
        accepted_source_ids=accepted_ids,
        independent_family_count=family_count,
        distinct_angle_count=distinct_angles,
        axes=axes,
        weights=active_weights,
        composite=composite,
        multi_angle_route=route,
    )


def coverage_bundle(
    bundle_root: Path,
    *,
    computed_at: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> BundleCoverageRecord:
    """Compute and persist the coverage record as ``review/bundle-coverage.json``."""
    record = compute_bundle_coverage(bundle_root, computed_at=computed_at, weights=weights)
    _write_json_atomic(
        bundle_root / BUNDLE_COVERAGE_FILENAME,
        record.model_dump_json(indent=2, exclude_none=True) + "\n",
    )
    return record


# --- bundle tiering ---------------------------------------------------------------

BUNDLE_TIER_A_MINIMUM_A_SOURCES = 2
BUNDLE_TIER_B_MINIMUM_B_SOURCES = 2


def compute_bundle_tier(
    bundle_id: str,
    source_scores: list[SourceQualityScore],
    *,
    human_reviewed_tier_b: bool = False,
    reviewer: str | None = None,
    coverage: BundleCoverageRecord | None = None,
) -> BundleTierRecord:
    """Aggregate source tiers into the bundle tier gate.

    Robustness rule (ADR-0002: no single source may dominate):

    - Tier A requires at least two independent tier-A sources.
    - Tier B requires at least one tier-A source, two tier-B-or-better
      sources, OR a satisfied coverage multi-angle route (>=3 qualifying
      accepted-registration sources spanning >=3 distinct angles at variant
      confidence >= 0.9 with the coverage composite over its documented
      floor). Coverage can only ever lift C to B; it never touches per-source
      scores, never reaches tier A, and never bypasses human review.
    - Anything else is tier C.

    Eligibility is fail-closed: tier A is eligible; tier B is eligible only
    with ``human_reviewed_tier_b`` recorded by a named reviewer; tier C never.
    """
    if not source_scores:
        raise BundleError("cannot tier a bundle without source scores")
    if coverage is not None and coverage.bundle_id != bundle_id:
        raise BundleError(
            f"coverage record belongs to bundle {coverage.bundle_id}, not {bundle_id}"
        )
    a_count = sum(score.tier is SourceTier.A for score in source_scores)
    b_or_better = sum(score.tier in (SourceTier.A, SourceTier.B) for score in source_scores)
    coverage_route = coverage is not None and coverage.multi_angle_route.satisfied

    if a_count >= BUNDLE_TIER_A_MINIMUM_A_SOURCES:
        tier = SourceTier.A
    elif a_count >= 1 or b_or_better >= BUNDLE_TIER_B_MINIMUM_B_SOURCES or coverage_route:
        tier = SourceTier.B
    else:
        tier = SourceTier.C

    if tier is SourceTier.A:
        eligible = True
    elif tier is SourceTier.B:
        eligible = bool(human_reviewed_tier_b and reviewer)
    else:
        eligible = False

    return BundleTierRecord(
        bundle_id=bundle_id,
        tier=tier,
        source_scores=source_scores,
        human_reviewed_tier_b=human_reviewed_tier_b,
        reviewer=reviewer,
        eligible_for_profile=eligible,
    )


def tier_bundle(
    bundle_root: Path,
    *,
    human_reviewed_tier_b: bool = False,
    reviewer: str | None = None,
    computed_at: datetime | None = None,
) -> BundleTierRecord:
    scores = score_bundle_sources(bundle_root, computed_at=computed_at)
    coverage = coverage_bundle(bundle_root, computed_at=computed_at)
    manifest = load_bundle_manifest(bundle_root)
    record = compute_bundle_tier(
        manifest.bundle_id,
        scores,
        human_reviewed_tier_b=human_reviewed_tier_b,
        reviewer=reviewer,
        coverage=coverage,
    )
    _write_json_atomic(
        bundle_root / BUNDLE_TIER_FILENAME,
        record.model_dump_json(indent=2, exclude_none=True) + "\n",
    )
    manifest.tier = record.tier
    save_bundle_manifest(bundle_root, manifest)
    return record


# --- validation --------------------------------------------------------------------

def validate_bundle(bundle_root: Path) -> dict[str, Any]:
    """In-code mirror of the frozen-schema invariants plus integrity checks."""
    errors: list[str] = []
    try:
        manifest = load_bundle_manifest(bundle_root)
    except (BundleError, ValueError) as exc:
        return {"valid": False, "errors": [str(exc)], "bundle_id": None, "sources": 0}

    expected_digest = compute_manifest_digest(manifest)
    if manifest.manifest_digest != expected_digest:
        errors.append(
            "manifest digest mismatch: "
            f"recorded {manifest.manifest_digest}, computed {expected_digest}"
        )

    if not manifest.source_ids:
        errors.append("bundle has no sources (frozen schema requires at least one)")
    recorded_ids = {record.source_id for record in manifest.sources}
    for source_id in manifest.source_ids:
        if source_id not in recorded_ids:
            errors.append(f"source_id without a full source record: {source_id}")

    tasks_by_url = {task.source_url for task in list_acquisition_tasks(bundle_root)}
    for record in manifest.sources:
        if record.retrieval_status is RetrievalStatus.BLOCKED:
            if record.source_url not in tasks_by_url:
                errors.append(
                    f"blocked source {record.source_id} has no acquisition task retaining its URL"
                )
            continue
        if record.private_media_hash is None:
            continue
        try:
            find_media_file(bundle_root, record)
        except BundleError as exc:
            errors.append(str(exc))

    if manifest.variant_verification.verified and not manifest.variant_verification.verifier:
        errors.append("verified variant verification is missing a named human verifier")

    tier_path = bundle_root / BUNDLE_TIER_FILENAME
    if tier_path.is_file():
        try:
            tier_record = BundleTierRecord.model_validate_json(
                tier_path.read_text(encoding="utf-8")
            )
            if tier_record.bundle_id != manifest.bundle_id:
                errors.append("bundle tier record belongs to a different bundle")
            elif manifest.tier is not tier_record.tier:
                errors.append(
                    f"manifest tier {manifest.tier} does not match tier record {tier_record.tier}"
                )
        except ValueError as exc:
            errors.append(f"invalid bundle tier record: {exc}")

    return {
        "valid": not errors,
        "errors": errors,
        "bundle_id": manifest.bundle_id,
        "sources": len(manifest.sources),
        "tier": None if manifest.tier is None else manifest.tier.value,
    }
