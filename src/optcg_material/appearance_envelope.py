"""Observed-appearance envelope extraction for Lane A (reference) bundles.

This module aggregates robust appearance statistics across normalized,
registered public-reference photographs of one exact card print variant
(ADR-0002). Its outputs are observed appearance proposals — never physical
BRDF measurements: nothing here touches an authenticated capture rig, so no
value produced by this module may ever be labeled as a physical measurement
or as human-reviewed. Every generated envelope carries the constant label
``observed-appearance-proposal`` and an evidence state restricted to
``source-supported`` or ``inferred``.

Input contract (kept deliberately independent of the reference-bundle module;
consumption is by file/dict shape only):

- a directory of normalized, registered images (identical dimensions);
- optional per-image interference masks (nonzero = sleeve/slab/toploader
  glare or occlusion; those pixels are excluded from every statistic);
- a JSON manifest listing sources with per-source confidence weights and
  optional named regions with masks.

Robustness: per-source summaries use medians, MADs, and chroma-weighted
quantiles; cross-source aggregation uses confidence-weighted medians; whole
sources are rejected (and recorded with reasons) when clipped, under-sampled,
or luminance-median outliers, so a single overexposed or manipulated source
cannot dominate any envelope value. Clipped and zero-coverage regions are
marked in the per-pixel confidence map and diagnostics instead of being
filled in.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

ENVELOPE_SCHEMA_VERSION = "1.0.0"
ENVELOPE_LABEL = "observed-appearance-proposal"
EVIDENCE_SOURCE_SUPPORTED = "source-supported"
EVIDENCE_INFERRED = "inferred"
FORBIDDEN_CLAIM_PHRASES = ("measured", "human-reviewed")
ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{1,95}$"
REGION_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
EPSILON = 1e-6
_MAD_TO_SIGMA = 1.4826
_MODIFIED_Z_FACTOR = 0.6745

ROBUST_METHOD = (
    "per-source robust summaries (median, MAD, chroma-weighted hue quantiles) "
    "aggregated by confidence-weighted medians across sources; sources rejected "
    "for highlight clipping, under-sampling, or luminance-median modified "
    "z-score outliers; circular statistics for hue axes and texture direction"
)


class AppearanceEnvelopeError(RuntimeError):
    """Raised when reference evidence is unusable for envelope extraction."""


def _safe_relative_path(value: str) -> str:
    posix = PurePosixPath(value)
    if posix.is_absolute() or ":" in value or ".." in posix.parts or not posix.parts:
        raise ValueError(f"unsafe relative path: {value!r}")
    return posix.as_posix()


class AppearanceEnvelopeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_outlier_z_threshold: float = Field(default=3.5, gt=0)
    clip_value: float = Field(default=0.985, gt=0, le=1)
    max_clipped_fraction: float = Field(default=0.35, ge=0, le=1)
    min_region_pixels: int = Field(default=16, ge=1)
    chroma_floor: float = Field(default=0.02, ge=0)
    specular_mad_multiplier: float = Field(default=4.0, gt=0)
    specular_luminance_floor: float = Field(default=0.10, gt=0)
    specular_min_fraction: float = Field(default=1e-3, gt=0)
    # Hard floor of 2: a single source can never propose specular activation.
    specular_min_sources: int = Field(default=2, ge=2)
    clearcoat_blur_sigma: float = Field(default=9.0, gt=0)
    preferred_source_count: int = Field(default=4, ge=2)
    metallic_spread_scale: float = Field(default=0.35, gt=0)
    foil_hue_dispersion_scale_deg: float = Field(default=45.0, gt=0)
    hue_range_trim_quantile: float = Field(default=0.1, ge=0, lt=0.5)
    ink_darkness_threshold: float = Field(default=0.06, gt=0)
    ink_stability_threshold: float = Field(default=0.02, gt=0)


class SourceImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=ID_PATTERN)
    image: str
    interference_mask: str | None = None
    confidence_weight: float = Field(default=1.0, ge=0, le=1)

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        return _safe_relative_path(value)

    @field_validator("interference_mask")
    @classmethod
    def validate_interference_mask(cls, value: str | None) -> str | None:
        return None if value is None else _safe_relative_path(value)


class RegionSpecInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str = Field(pattern=REGION_ID_PATTERN)
    mask: str | None = None

    @field_validator("mask")
    @classmethod
    def validate_mask(cls, value: str | None) -> str | None:
        return None if value is None else _safe_relative_path(value)


class AppearanceExtractionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=ENVELOPE_SCHEMA_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    bundle_id: str = Field(pattern=ID_PATTERN)
    card_id: str = Field(min_length=2, max_length=64)
    # Refusal gate: this module only accepts sequences declared normalized and
    # registered by the upstream normalization step.
    registration_state: Literal["normalized-registered"]
    sources: list[SourceImageInput] = Field(min_length=1)
    regions: list[RegionSpecInput] = Field(
        default_factory=lambda: [RegionSpecInput(region_id="full-card")]
    )
    settings: AppearanceEnvelopeSettings = Field(default_factory=AppearanceEnvelopeSettings)

    @field_validator("sources")
    @classmethod
    def validate_unique_source_ids(
        cls, values: list[SourceImageInput]
    ) -> list[SourceImageInput]:
        seen = {source.source_id for source in values}
        if len(seen) != len(values):
            raise ValueError("source_id values must be unique")
        return values

    @field_validator("regions")
    @classmethod
    def validate_unique_region_ids(cls, values: list[RegionSpecInput]) -> list[RegionSpecInput]:
        seen = {region.region_id for region in values}
        if len(seen) != len(values):
            raise ValueError("region_id values must be unique")
        return values


class BrightnessEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float
    max: float
    variance: float = Field(ge=0)
    median: float


class HueRangeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_deg: float = Field(ge=0, le=360)
    max_deg: float = Field(ge=0, le=360)
    dominant_hue_axis_deg: float = Field(ge=0, le=360)


class AppearanceProposals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metallic: float = Field(ge=0, le=1)
    foil: float = Field(ge=0, le=1)
    clearcoat: float = Field(ge=0, le=1)
    black_ink_suppression: float = Field(ge=0, le=1)
    texture_frequency: float = Field(ge=0)
    texture_direction_deg: float = Field(ge=0, le=360)
    confidence: dict[str, float]

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, values: dict[str, float]) -> dict[str, float]:
        for key, value in values.items():
            if not 0 <= value <= 1:
                raise ValueError(f"confidence[{key}] must lie in [0, 1]")
        return values


class AppearanceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=ENVELOPE_SCHEMA_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    bundle_id: str = Field(pattern=ID_PATTERN)
    card_id: str = Field(min_length=2, max_length=64)
    region_id: str = Field(min_length=1)
    source_count: int = Field(ge=1)
    contributing_source_ids: list[str] = Field(min_length=1)
    brightness: BrightnessEnvelope
    chroma_variance: float = Field(ge=0)
    hue_range: HueRangeEnvelope
    specular_activation_frequency: float = Field(ge=0, le=1)
    proposals: AppearanceProposals
    per_pixel_confidence_map: str | None = None
    robust_method: str = ROBUST_METHOD
    outlier_sources_excluded: list[str] = Field(default_factory=list)
    label: Literal["observed-appearance-proposal"] = ENVELOPE_LABEL
    evidence_state: Literal["source-supported", "inferred"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class LoadedSource:
    source_id: str
    weight: float
    luminance: np.ndarray
    hue_deg: np.ndarray
    chroma: np.ndarray
    usable: np.ndarray
    clipped: np.ndarray


@dataclass(frozen=True)
class SourceRegionStats:
    source_id: str
    weight: float
    pixel_count: int
    clipped_fraction: float
    lum_min: float
    lum_max: float
    lum_median: float
    lum_variance: float
    chroma_variance: float
    chromatic_fraction: float
    hue_axis_deg: float | None
    hue_dev_low: float
    hue_dev_high: float
    specular_fraction: float
    broad_highlight_fraction: float
    texture_frequency: float
    texture_direction_deg: float
    texture_strength: float


@dataclass(frozen=True)
class RegionEnvelopeResult:
    envelope: AppearanceEnvelope
    confidence_map: np.ndarray
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class RegionArtifacts:
    envelope: AppearanceEnvelope
    envelope_path: Path
    confidence_map_path: Path
    diagnostics_path: Path
    diagnostics: dict[str, Any]


def assert_proposal_language(serialized: str) -> None:
    """Refuse to emit output that claims physical-lane evidence states."""
    lowered = serialized.lower()
    for phrase in FORBIDDEN_CLAIM_PHRASES:
        if phrase in lowered:
            raise AppearanceEnvelopeError(
                f"generated output contains a forbidden physical-claim phrase: {phrase!r}"
            )


def srgb_to_linear(image_bgr: np.ndarray) -> np.ndarray:
    rgb = image_bgr[..., ::-1].astype(np.float32) / 255.0
    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        np.power((rgb + 0.055) / 1.055, 2.4),
    ).astype(np.float32)


def linear_luminance(linear_rgb: np.ndarray) -> np.ndarray:
    return (
        0.2126 * linear_rgb[..., 0]
        + 0.7152 * linear_rgb[..., 1]
        + 0.0722 * linear_rgb[..., 2]
    ).astype(np.float32)


def _hue_and_chroma(linear_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    red = linear_rgb[..., 0]
    green = linear_rgb[..., 1]
    blue = linear_rgb[..., 2]
    max_channel = np.max(linear_rgb, axis=-1)
    min_channel = np.min(linear_rgb, axis=-1)
    chroma = (max_channel - min_channel).astype(np.float32)
    safe = np.maximum(chroma, EPSILON)
    sector = np.where(
        max_channel == red,
        ((green - blue) / safe) % 6.0,
        np.where(
            max_channel == green,
            (blue - red) / safe + 2.0,
            (red - green) / safe + 4.0,
        ),
    )
    hue = (sector * 60.0) % 360.0
    return hue.astype(np.float32), chroma


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    flat_values = np.asarray(values, dtype=np.float64).ravel()
    flat_weights = np.asarray(weights, dtype=np.float64).ravel()
    if flat_values.size == 0:
        return 0.0
    total = float(np.sum(flat_weights))
    if total <= EPSILON:
        return float(np.quantile(flat_values, quantile))
    order = np.argsort(flat_values, kind="stable")
    ordered_values = flat_values[order]
    cumulative = np.cumsum(flat_weights[order])
    index = int(np.searchsorted(cumulative, quantile * total, side="left"))
    return float(ordered_values[min(index, ordered_values.size - 1)])


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    return _weighted_quantile(values, weights, 0.5)


def _wrap_degrees(value: float) -> float:
    return float(value % 360.0)


def _signed_angle_difference(value_deg: np.ndarray | float, reference_deg: float) -> Any:
    return ((np.asarray(value_deg, dtype=np.float64) - reference_deg + 180.0) % 360.0) - 180.0


def _circular_mean_degrees(
    degrees_values: np.ndarray,
    weights: np.ndarray,
    *,
    period: float = 360.0,
) -> tuple[float, float]:
    """Weighted circular mean; returns (mean in [0, period), resultant length)."""
    angles = np.radians(np.asarray(degrees_values, dtype=np.float64) * (360.0 / period))
    flat_weights = np.asarray(weights, dtype=np.float64)
    total = float(np.sum(flat_weights))
    if angles.size == 0 or total <= EPSILON:
        return 0.0, 0.0
    sin_sum = float(np.sum(flat_weights * np.sin(angles))) / total
    cos_sum = float(np.sum(flat_weights * np.cos(angles))) / total
    length = math.hypot(sin_sum, cos_sum)
    if length <= EPSILON:
        return 0.0, 0.0
    mean = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
    return mean * (period / 360.0), length


def _texture_signature(
    luminance: np.ndarray,
    valid: np.ndarray,
) -> tuple[float, float, float]:
    """Dominant spatial frequency (cycles/pixel), direction of variation, strength."""
    rows, cols = np.nonzero(valid)
    if rows.size < 64:
        return 0.0, 0.0, 0.0
    crop = luminance[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]
    mask = valid[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]
    height, width = crop.shape
    if min(height, width) < 8:
        return 0.0, 0.0, 0.0
    mean = float(crop[mask].mean())
    field = np.where(mask, crop.astype(np.float64) - mean, 0.0)
    magnitude = np.abs(np.fft.fftshift(np.fft.fft2(field)))
    freq_y = np.fft.fftshift(np.fft.fftfreq(height))
    freq_x = np.fft.fftshift(np.fft.fftfreq(width))
    radius = np.hypot(freq_y[:, None], freq_x[None, :])
    admissible = (radius >= 2.0 / min(height, width)) & (radius <= 0.5)
    if not bool(np.any(admissible)):
        return 0.0, 0.0, 0.0
    candidates = np.where(admissible, magnitude, 0.0)
    peak_row, peak_col = np.unravel_index(int(np.argmax(candidates)), candidates.shape)
    frequency = float(radius[peak_row, peak_col])
    direction = math.degrees(
        math.atan2(float(freq_y[peak_row]), float(freq_x[peak_col]))
    ) % 180.0
    peak = float(candidates[peak_row, peak_col])
    background = float(np.median(magnitude[admissible])) + EPSILON
    prominence = peak / background
    strength = float(np.clip(1.0 - 3.0 / max(prominence, 3.0), 0.0, 1.0))
    return frequency, direction, strength


def _source_region_stats(
    source: LoadedSource,
    region_mask: np.ndarray,
    settings: AppearanceEnvelopeSettings,
) -> SourceRegionStats:
    region_usable = region_mask & source.usable
    usable_count = int(np.count_nonzero(region_usable))
    clipped_count = int(np.count_nonzero(source.clipped & region_usable))
    clipped_fraction = clipped_count / usable_count if usable_count else 0.0
    valid = region_usable & ~source.clipped
    pixel_count = int(np.count_nonzero(valid))
    if pixel_count == 0:
        return SourceRegionStats(
            source_id=source.source_id,
            weight=source.weight,
            pixel_count=0,
            clipped_fraction=clipped_fraction,
            lum_min=0.0,
            lum_max=0.0,
            lum_median=0.0,
            lum_variance=0.0,
            chroma_variance=0.0,
            chromatic_fraction=0.0,
            hue_axis_deg=None,
            hue_dev_low=0.0,
            hue_dev_high=0.0,
            specular_fraction=0.0,
            broad_highlight_fraction=0.0,
            texture_frequency=0.0,
            texture_direction_deg=0.0,
            texture_strength=0.0,
        )

    luminance_values = source.luminance[valid].astype(np.float64)
    lum_median = float(np.median(luminance_values))
    lum_mad = float(np.median(np.abs(luminance_values - lum_median)))

    chroma_values = source.chroma[valid].astype(np.float64)
    chromatic = chroma_values > settings.chroma_floor
    chromatic_fraction = float(np.mean(chromatic))
    hue_axis: float | None = None
    hue_dev_low = 0.0
    hue_dev_high = 0.0
    if bool(np.any(chromatic)):
        hues = source.hue_deg[valid][chromatic].astype(np.float64)
        hue_weights = chroma_values[chromatic]
        axis, _resultant = _circular_mean_degrees(hues, hue_weights)
        deviations = _signed_angle_difference(hues, axis)
        hue_axis = axis
        hue_dev_low = _weighted_quantile(deviations, hue_weights, 0.02)
        hue_dev_high = _weighted_quantile(deviations, hue_weights, 0.98)

    specular_threshold = lum_median + max(
        _MAD_TO_SIGMA * settings.specular_mad_multiplier * lum_mad,
        settings.specular_luminance_floor,
    )
    highlight = (source.luminance > specular_threshold) & valid
    specular_fraction = float(np.count_nonzero(highlight) / pixel_count)
    if specular_fraction > 0:
        blurred = cv2.GaussianBlur(
            highlight.astype(np.float32),
            (0, 0),
            sigmaX=settings.clearcoat_blur_sigma,
            sigmaY=settings.clearcoat_blur_sigma,
        )
        broad_highlight_fraction = float(np.mean(blurred[valid] > 0.35))
    else:
        broad_highlight_fraction = 0.0

    texture_frequency, texture_direction, texture_strength = _texture_signature(
        source.luminance, valid
    )

    return SourceRegionStats(
        source_id=source.source_id,
        weight=source.weight,
        pixel_count=pixel_count,
        clipped_fraction=clipped_fraction,
        lum_min=float(np.min(luminance_values)),
        lum_max=float(np.max(luminance_values)),
        lum_median=lum_median,
        lum_variance=float(np.var(luminance_values)),
        chroma_variance=float(np.var(chroma_values)),
        chromatic_fraction=chromatic_fraction,
        hue_axis_deg=hue_axis,
        hue_dev_low=float(hue_dev_low),
        hue_dev_high=float(hue_dev_high),
        specular_fraction=specular_fraction,
        broad_highlight_fraction=broad_highlight_fraction,
        texture_frequency=texture_frequency,
        texture_direction_deg=texture_direction,
        texture_strength=texture_strength,
    )


def _reject_outlier_sources(
    stats: list[SourceRegionStats],
    settings: AppearanceEnvelopeSettings,
) -> tuple[list[SourceRegionStats], dict[str, str]]:
    excluded: dict[str, str] = {}
    usable: list[SourceRegionStats] = []
    for stat in stats:
        if stat.pixel_count < settings.min_region_pixels:
            excluded[stat.source_id] = (
                f"under-sampled region: {stat.pixel_count} usable pixels "
                f"< {settings.min_region_pixels}"
            )
        elif stat.clipped_fraction > settings.max_clipped_fraction:
            excluded[stat.source_id] = (
                f"clipped highlights: fraction {stat.clipped_fraction:.3f} "
                f"> {settings.max_clipped_fraction}"
            )
        else:
            usable.append(stat)

    if len(usable) >= 3:
        medians = np.asarray([stat.lum_median for stat in usable], dtype=np.float64)
        center = float(np.median(medians))
        deviations = np.abs(medians - center)
        mad = max(float(np.median(deviations)), 1e-4)
        scores = _MODIFIED_Z_FACTOR * deviations / mad
        inliers: list[SourceRegionStats] = []
        for stat, score in zip(usable, scores, strict=True):
            if float(score) > settings.source_outlier_z_threshold:
                excluded[stat.source_id] = (
                    f"luminance-median outlier: modified z-score {float(score):.1f} "
                    f"> {settings.source_outlier_z_threshold}"
                )
            else:
                inliers.append(stat)
        usable = inliers
    return usable, excluded


def _aggregate_hue_range(
    inliers: list[SourceRegionStats],
    settings: AppearanceEnvelopeSettings,
    notes: list[str],
) -> tuple[HueRangeEnvelope, float]:
    chromatic = [
        stat
        for stat in inliers
        if stat.hue_axis_deg is not None and stat.chromatic_fraction > 0
    ]
    if not chromatic:
        notes.append(
            "no pixels above the chroma floor in any contributing source; "
            "hue range reported as zeros with zero confidence, not synthesized"
        )
        return HueRangeEnvelope(min_deg=0.0, max_deg=0.0, dominant_hue_axis_deg=0.0), 0.0

    axes = np.asarray([stat.hue_axis_deg for stat in chromatic], dtype=np.float64)
    axis_weights = np.asarray(
        [stat.weight * stat.chromatic_fraction for stat in chromatic], dtype=np.float64
    )
    dominant_axis, _resultant = _circular_mean_degrees(axes, axis_weights)
    axis_deviations = _signed_angle_difference(axes, dominant_axis)
    lows = axis_deviations + np.asarray([stat.hue_dev_low for stat in chromatic])
    highs = axis_deviations + np.asarray([stat.hue_dev_high for stat in chromatic])
    trim = settings.hue_range_trim_quantile
    low = _weighted_quantile(lows, axis_weights, trim)
    high = _weighted_quantile(highs, axis_weights, 1.0 - trim)
    hue_range = HueRangeEnvelope(
        min_deg=_wrap_degrees(dominant_axis + low),
        max_deg=_wrap_degrees(dominant_axis + high),
        dominant_hue_axis_deg=_wrap_degrees(dominant_axis),
    )
    coverage = float(np.mean([stat.chromatic_fraction for stat in chromatic]))
    return hue_range, coverage


def compute_region_envelope(
    *,
    bundle_id: str,
    card_id: str,
    region_id: str,
    sources: list[LoadedSource],
    region_mask: np.ndarray | None,
    settings: AppearanceEnvelopeSettings | None = None,
) -> RegionEnvelopeResult:
    """Compute one region's appearance envelope from loaded, registered sources."""
    limits = settings or AppearanceEnvelopeSettings()
    if not sources:
        raise AppearanceEnvelopeError("at least one source is required")
    shape = sources[0].luminance.shape
    mask = (
        np.ones(shape, dtype=bool)
        if region_mask is None
        else region_mask.astype(bool)
    )
    if mask.shape != shape:
        raise AppearanceEnvelopeError(
            f"region mask shape {mask.shape} does not match image shape {shape}"
        )

    notes: list[str] = []
    stats = [_source_region_stats(source, mask, limits) for source in sources]
    inliers, excluded = _reject_outlier_sources(stats, limits)
    if not inliers:
        raise AppearanceEnvelopeError(
            f"region {region_id!r}: every source was excluded "
            f"({'; '.join(sorted(excluded))}); refusing to synthesize an envelope"
        )

    inlier_ids = {stat.source_id for stat in inliers}
    inlier_sources = [source for source in sources if source.source_id in inlier_ids]
    weights = np.asarray([stat.weight for stat in inliers], dtype=np.float64)

    def wmedian(attribute: str) -> float:
        values = np.asarray([getattr(stat, attribute) for stat in inliers], dtype=np.float64)
        return _weighted_median(values, weights)

    brightness_median = wmedian("lum_median")
    brightness = BrightnessEnvelope(
        min=min(wmedian("lum_min"), brightness_median),
        max=max(wmedian("lum_max"), brightness_median),
        variance=max(wmedian("lum_variance"), 0.0),
        median=brightness_median,
    )
    chroma_variance = max(wmedian("chroma_variance"), 0.0)
    hue_range, chromatic_coverage = _aggregate_hue_range(inliers, limits, notes)

    activating = [
        stat for stat in inliers if stat.specular_fraction >= limits.specular_min_fraction
    ]
    if len(activating) >= limits.specular_min_sources:
        activating_weights = np.asarray([stat.weight for stat in activating])
        specular_frequency = float(
            np.clip(
                _weighted_median(
                    np.asarray([stat.specular_fraction for stat in activating]),
                    activating_weights,
                ),
                0.0,
                1.0,
            )
        )
        clearcoat = float(
            np.clip(
                _weighted_median(
                    np.asarray([stat.broad_highlight_fraction for stat in activating]),
                    activating_weights,
                ),
                0.0,
                1.0,
            )
        )
        specular_agreement = len(activating) / len(inliers)
    else:
        if activating:
            notes.append(
                f"specular activation observed in only {len(activating)} source(s); "
                f"{limits.specular_min_sources} independent sources are required, "
                "so specular and clearcoat proposals stay zero"
            )
        specular_frequency = 0.0
        clearcoat = 0.0
        specular_agreement = 0.0

    valid_stack = np.stack(
        [mask & source.usable & ~source.clipped for source in inlier_sources]
    )
    luminance_stack = np.ma.array(
        np.stack([source.luminance for source in inlier_sources]).astype(np.float64),
        mask=~valid_stack,
    )
    coverage_count = valid_stack.sum(axis=0)
    multi = (coverage_count >= 2) & mask
    multi_fraction = float(np.count_nonzero(multi) / max(np.count_nonzero(mask), 1))

    luminance_median_px = np.ma.median(luminance_stack, axis=0).filled(0.0)
    luminance_mad_px = np.ma.median(
        np.ma.abs(luminance_stack - luminance_median_px[None, ...]), axis=0
    ).filled(0.0)

    chroma_stack = np.stack([source.chroma for source in inlier_sources])
    chromatic_stack = valid_stack & (chroma_stack > limits.chroma_floor)
    chromatic_count = chromatic_stack.sum(axis=0)
    hue_vectors = np.exp(1j * np.radians(np.stack([s.hue_deg for s in inlier_sources])))
    mean_vector = np.where(chromatic_stack, hue_vectors, 0).sum(axis=0) / np.maximum(
        chromatic_count, 1
    )
    resultant = np.abs(mean_vector)
    dispersion_deg = np.degrees(
        np.sqrt(-2.0 * np.log(np.clip(resultant, EPSILON, 1.0)))
    )
    foil_eligible = (chromatic_count >= 2) & mask
    if bool(np.any(foil_eligible)):
        foil = float(
            np.clip(
                float(np.median(dispersion_deg[foil_eligible]))
                / limits.foil_hue_dispersion_scale_deg,
                0.0,
                1.0,
            )
        )
    else:
        foil = 0.0
    foil_eligible_fraction = float(
        np.count_nonzero(foil_eligible) / max(np.count_nonzero(mask), 1)
    )

    if bool(np.any(multi)):
        relative_spread = luminance_mad_px / np.maximum(luminance_median_px, EPSILON)
        metallic_raw = float(
            np.clip(
                float(np.median(relative_spread[multi])) / limits.metallic_spread_scale,
                0.0,
                1.0,
            )
        )
    else:
        metallic_raw = 0.0
        notes.append(
            "fewer than two sources overlap on any pixel; cross-source metallic "
            "spread stays zero with zero confidence"
        )
    metallic = float(np.clip(metallic_raw * (1.0 - foil), 0.0, 1.0))

    stable_dark = (
        multi
        & (luminance_median_px < limits.ink_darkness_threshold)
        & (luminance_mad_px < limits.ink_stability_threshold)
    )
    black_ink = float(np.count_nonzero(stable_dark) / max(np.count_nonzero(multi), 1))

    texture_strengths = np.asarray([stat.texture_strength for stat in inliers])
    texture_weights = weights * texture_strengths
    if float(np.sum(texture_weights)) > EPSILON:
        texture_frequency = _weighted_median(
            np.asarray([stat.texture_frequency for stat in inliers]), texture_weights
        )
        texture_direction, _resultant = _circular_mean_degrees(
            np.asarray([stat.texture_direction_deg for stat in inliers]),
            texture_weights,
            period=180.0,
        )
        texture_strength = _weighted_median(texture_strengths, weights)
    else:
        texture_frequency = 0.0
        texture_direction = 0.0
        texture_strength = 0.0

    total_weight = float(np.sum(weights))
    if total_weight > EPSILON:
        confidence_map = (
            (weights[:, None, None] * valid_stack).sum(axis=0) / total_weight
        ).astype(np.float32)
    else:
        confidence_map = np.zeros(shape, dtype=np.float32)
    confidence_map = np.where(mask, confidence_map, 0.0).astype(np.float32)
    region_pixels = max(np.count_nonzero(mask), 1)
    coverage = float(confidence_map[mask].mean()) if bool(np.any(mask)) else 0.0
    zero_coverage_fraction = float(
        np.count_nonzero((coverage_count == 0) & mask) / region_pixels
    )
    if zero_coverage_fraction > 0:
        notes.append(
            f"{zero_coverage_fraction:.3f} of the region has no usable coverage; "
            "marked as zero confidence rather than filled in"
        )

    base_confidence = float(
        np.clip(len(inliers) / limits.preferred_source_count, 0.0, 1.0) * coverage
    )
    confidence = {
        "metallic": float(np.clip(base_confidence * multi_fraction, 0.0, 1.0)),
        "foil": float(np.clip(base_confidence * foil_eligible_fraction, 0.0, 1.0)),
        "clearcoat": float(np.clip(base_confidence * specular_agreement, 0.0, 1.0)),
        "black_ink_suppression": float(np.clip(base_confidence * multi_fraction, 0.0, 1.0)),
        "texture_frequency": float(np.clip(base_confidence * texture_strength, 0.0, 1.0)),
        "texture_direction_deg": float(np.clip(base_confidence * texture_strength, 0.0, 1.0)),
        "hue_range": float(np.clip(base_confidence * chromatic_coverage, 0.0, 1.0)),
        "specular_activation_frequency": float(
            np.clip(base_confidence * specular_agreement, 0.0, 1.0)
        ),
    }

    evidence_state = (
        EVIDENCE_SOURCE_SUPPORTED if len(inliers) >= 2 else EVIDENCE_INFERRED
    )
    if evidence_state == EVIDENCE_INFERRED:
        notes.append(
            "only one contributing source; every value in this envelope is inferred"
        )

    envelope = AppearanceEnvelope(
        bundle_id=bundle_id,
        card_id=card_id,
        region_id=region_id,
        source_count=len(inliers),
        contributing_source_ids=sorted(inlier_ids),
        brightness=brightness,
        chroma_variance=chroma_variance,
        hue_range=hue_range,
        specular_activation_frequency=specular_frequency,
        proposals=AppearanceProposals(
            metallic=metallic,
            foil=foil,
            clearcoat=clearcoat,
            black_ink_suppression=black_ink,
            texture_frequency=float(texture_frequency),
            texture_direction_deg=_wrap_degrees(texture_direction),
            confidence=confidence,
        ),
        robust_method=ROBUST_METHOD,
        outlier_sources_excluded=sorted(excluded),
        evidence_state=evidence_state,
    )
    diagnostics: dict[str, Any] = {
        "label": ENVELOPE_LABEL,
        "region_id": region_id,
        "robust_method": ROBUST_METHOD,
        "outlier_sources_excluded": dict(sorted(excluded.items())),
        "zero_coverage_fraction": zero_coverage_fraction,
        "multi_source_fraction": multi_fraction,
        "notes": notes,
        "per_source": [
            {
                "source_id": stat.source_id,
                "contributing": stat.source_id in inlier_ids,
                "usable_pixels": stat.pixel_count,
                "clipped_fraction": round(stat.clipped_fraction, 6),
                "luminance_median": round(stat.lum_median, 6),
                "chromatic_fraction": round(stat.chromatic_fraction, 6),
                "specular_activation_fraction": round(stat.specular_fraction, 6),
                "texture_strength": round(stat.texture_strength, 6),
            }
            for stat in stats
        ],
    }
    return RegionEnvelopeResult(
        envelope=envelope,
        confidence_map=confidence_map,
        diagnostics=diagnostics,
    )


def _read_grayscale_mask(path: Path, expected_shape: tuple[int, int]) -> np.ndarray:
    raw = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if raw is None:
        raise AppearanceEnvelopeError(f"unable to read mask: {path}")
    if raw.shape != expected_shape:
        raise AppearanceEnvelopeError(
            f"mask {path} shape {raw.shape} does not match image shape {expected_shape}; "
            "refusing unregistered input"
        )
    return raw >= 128


def load_sources(
    input_root: Path,
    manifest: AppearanceExtractionManifest,
) -> list[LoadedSource]:
    """Load normalized/registered source images; refuse mismatched dimensions."""
    loaded: list[LoadedSource] = []
    expected_shape: tuple[int, int] | None = None
    for source in manifest.sources:
        image_path = input_root / source.image
        raw = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if raw is None:
            raise AppearanceEnvelopeError(f"unable to read source image: {image_path}")
        shape = raw.shape[:2]
        if expected_shape is None:
            expected_shape = shape
        elif shape != expected_shape:
            raise AppearanceEnvelopeError(
                f"source {source.source_id} shape {shape} does not match "
                f"{expected_shape}; refusing unregistered input"
            )
        linear = srgb_to_linear(raw)
        luminance = linear_luminance(linear)
        hue, chroma = _hue_and_chroma(linear)
        clipped = np.max(linear, axis=-1) >= manifest.settings.clip_value
        usable = np.ones(shape, dtype=bool)
        if source.interference_mask is not None:
            interference = _read_grayscale_mask(
                input_root / source.interference_mask, shape
            )
            usable &= ~interference
        loaded.append(
            LoadedSource(
                source_id=source.source_id,
                weight=source.confidence_weight,
                luminance=luminance,
                hue_deg=hue,
                chroma=chroma,
                usable=usable,
                clipped=clipped,
            )
        )
    return loaded


def _write_confidence_png(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = np.round(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)
    if not cv2.imwrite(str(path), encoded):
        raise AppearanceEnvelopeError(f"unable to write confidence map: {path}")


def extract_appearance_envelopes(
    input_root: Path,
    manifest: AppearanceExtractionManifest,
    output_dir: Path,
) -> list[RegionArtifacts]:
    """Extract one schema-valid envelope (plus confidence map) per region."""
    sources = load_sources(input_root, manifest)
    shape = sources[0].luminance.shape
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[RegionArtifacts] = []
    for region in manifest.regions:
        region_mask = (
            None
            if region.mask is None
            else _read_grayscale_mask(input_root / region.mask, shape)
        )
        result = compute_region_envelope(
            bundle_id=manifest.bundle_id,
            card_id=manifest.card_id,
            region_id=region.region_id,
            sources=sources,
            region_mask=region_mask,
            settings=manifest.settings,
        )
        confidence_name = f"{region.region_id}.confidence.png"
        confidence_path = output_dir / confidence_name
        _write_confidence_png(confidence_path, result.confidence_map)

        envelope = result.envelope.model_copy(
            update={"per_pixel_confidence_map": confidence_name}
        )
        envelope_text = (
            json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )
        diagnostics_text = json.dumps(result.diagnostics, indent=2, sort_keys=True) + "\n"
        assert_proposal_language(envelope_text)
        assert_proposal_language(diagnostics_text)

        envelope_path = output_dir / f"{region.region_id}.appearance-envelope.json"
        diagnostics_path = output_dir / f"{region.region_id}.appearance-diagnostics.json"
        envelope_path.write_text(envelope_text, encoding="utf-8")
        diagnostics_path.write_text(diagnostics_text, encoding="utf-8")
        artifacts.append(
            RegionArtifacts(
                envelope=envelope,
                envelope_path=envelope_path,
                confidence_map_path=confidence_path,
                diagnostics_path=diagnostics_path,
                diagnostics=result.diagnostics,
            )
        )
    return artifacts


def load_extraction_manifest(path: Path) -> AppearanceExtractionManifest:
    return AppearanceExtractionManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )
