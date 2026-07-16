"""Analysis-by-synthesis fitting over UNCONTROLLED public-reference observations (Lane A).

ADR-0002 reference lane. One renderer profile (shared, interpretable, physically
bounded material parameters) is fitted jointly across all usable observations of a
bundle; per-source nuisance parameters (card pose residual, light direction, glare
center, light hardness, exposure scale) are free per source. Camera exposure error
is always absorbed by the per-source ``exposure`` nuisance, never by material
parameters (the material block has no global gain).

Hard gates encoded here:

- A profile whose fit quality is concentrated in a single privileged reference is
  rejected (``single_reference_overfit_flag``); this is a failure, not a warning.
- If the observed response exceeds what the planar renderer model can represent,
  a diagnostic is recorded and the fit is rejected; the renderer is never extended
  from this module.

All geometry is deterministic planar card geometry; nothing is inferred from
photographs. No output claims physical measurement — labels are restricted to the
reference-derived vocabulary. Optimization is grid/coordinate descent only
(no randomness), so identical inputs produce identical reports.

This module consumes observation manifests by file/dict contract only; it does not
import the bundle modules (parallel build).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .fitting import FitLossWeights
from .material_maps import luminance, srgb_to_linear_rgb
from .quality import read_image
from .semantic import file_digest, read_binary_mask, safe_relative_path

REFERENCE_FIT_SCHEMA_VERSION = "1.0.0"
EPSILON = 1e-6

REFERENCE_LANE_LABEL = "reference-derived"
REFERENCE_LANE_CLAIM = "visually fitted across real-card references; not a physical measurement"
ALLOWED_REFERENCE_LABELS = (
    "reference-derived",
    "source-supported simulation",
    "visually fitted across real-card references",
)
FORBIDDEN_CLAIM_PHRASES = ("capture-validated", "physically measured", "physically exact")

REPORT_FILENAME = "reference-fit-report.json"
PROFILE_FILENAME = "profile.json"

ELEVATION_BOUNDS = (5.0, 90.0)
HARDNESS_BOUNDS = (1.0, 4.0)
EXPOSURE_BOUNDS = (0.25, 4.0)
POSE_ROTATION_BOUND = 3.0
POSE_TRANSLATION_BOUND = 6.0
GLARE_BOUNDS = (-0.2, 1.2)
ROUGHNESS_BOUNDS = (0.05, 1.0)


class ReferenceFitError(RuntimeError):
    """Raised when a public-reference observation set cannot be fitted safely."""


class RendererModelLimitError(ReferenceFitError):
    """Raised via diagnostics when the standardized renderer model cannot represent
    the observed response. Recorded as a finding; never worked around here."""


# ---------------------------------------------------------------------------
# Input contract (file/dict; parallel to the frozen bundle schemas)
# ---------------------------------------------------------------------------


class ObservationFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    image_path: str
    interference_mask_path: str | None = None

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str) -> str:
        return safe_relative_path(value)

    @field_validator("interference_mask_path")
    @classmethod
    def validate_mask_path(cls, value: str | None) -> str | None:
        return safe_relative_path(value) if value is not None else None


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    media_form: Literal["still", "sequence"] = "still"
    frames: list[ObservationFrame] = Field(min_length=1)
    variant_confidence: float = Field(default=1.0, ge=0, le=1)
    quality_prior: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_frames(self) -> Observation:
        ids = [frame.frame_id for frame in self.frames]
        if len(ids) != len(set(ids)):
            raise ValueError("observation frame ids must be unique")
        if self.media_form == "still" and len(self.frames) != 1:
            raise ValueError("still observations must contain exactly one frame")
        if self.media_form == "sequence" and len(self.frames) < 2:
            raise ValueError("sequence observations require at least two ordered frames")
        return self

    @property
    def prior_weight(self) -> float:
        return float(self.variant_confidence * self.quality_prior)


class ObservationSetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REFERENCE_FIT_SCHEMA_VERSION
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    bundle_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    albedo_path: str | None = None
    observations: list[Observation] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("albedo_path")
    @classmethod
    def validate_albedo_path(cls, value: str | None) -> str | None:
        return safe_relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def source_ids_must_be_unique(self) -> ObservationSetManifest:
        ids = [observation.source_id for observation in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation source ids must be unique")
        return self


class ReferenceMaterialParams(BaseModel):
    """Shared, interpretable, physically bounded renderer material parameters.

    Deliberately contains no global gain: brightness differences between sources
    are per-source exposure nuisance, never material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specular_strength: float = Field(default=0.5, ge=0, le=1)
    roughness: float = Field(default=0.4, ge=ROUGHNESS_BOUNDS[0], le=ROUGHNESS_BOUNDS[1])
    metallic: float = Field(default=0.5, ge=0, le=1)


class ReferenceFitOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    weights: FitLossWeights = Field(default_factory=FitLossWeights)
    highlight_percentile: float = Field(default=96.0, ge=80, le=99.9)
    rounds: int = Field(default=2, ge=1, le=5)
    accept_error_threshold: float = Field(default=0.06, gt=0)
    outlier_error_threshold: float = Field(default=0.12, gt=0)
    privilege_ratio: float = Field(default=2.0, ge=1)
    model_limit_threshold: float = Field(default=0.30, gt=0)
    min_valid_coverage: float = Field(default=0.2, gt=0, le=1)
    # Aggregate acceptance gate: a profile must genuinely fit multiple sources,
    # not merely avoid the overfit and model-limit rejections.
    min_accepted_sources: int = Field(default=2, ge=1)
    min_consistency_score: float = Field(default=0.35, ge=0, le=1)


# ---------------------------------------------------------------------------
# Frozen report contract (docs/agent-ops/reference-fitting-report.schema.json)
# ---------------------------------------------------------------------------


class LightDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    azimuth_deg: float = Field(ge=0, le=360)
    elevation_deg: float = Field(ge=-90, le=90)


class GlareCenter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class PerSourceFit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    estimated_pose: dict[str, float]
    light_direction: LightDirection
    glare_center: GlareCenter
    light_hardness: float = Field(ge=0)
    exposure_scale: float = Field(ge=0)
    confidence_weight: float = Field(ge=0, le=1)
    candidate_render_path: str = Field(min_length=1)
    difference_image_path: str = Field(min_length=1)
    regional_error: dict[str, float]
    highlight_trajectory: list[dict[str, float | str]] | None = None


class OutlierEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    reason: str = Field(min_length=1)
    metric: float


class ReferenceFittingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REFERENCE_FIT_SCHEMA_VERSION
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    bundle_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    profile_path: str = Field(min_length=1)
    profile_blake3: str = Field(pattern=r"^[0-9a-f]{64}$")
    per_source: list[PerSourceFit] = Field(min_length=1)
    cross_reference_consistency_score: float = Field(ge=0, le=1)
    single_reference_overfit_flag: bool
    privileged_reference_ids: list[str]
    outlier_report: list[OutlierEntry]
    aggregate_loss: float = Field(ge=0)
    generated_at: datetime


@dataclass(frozen=True)
class ReferenceFitOutcome:
    """Python-level fit outcome; ``accepted`` is the hard gate result."""

    report: ReferenceFittingReport
    material: ReferenceMaterialParams
    accepted: bool
    rejection_reasons: tuple[str, ...]
    model_limit_diagnostic: str | None
    report_path: Path
    profile_path: Path


# ---------------------------------------------------------------------------
# Deterministic planar forward model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameLight:
    azimuth_deg: float
    glare_x: float
    glare_y: float


@dataclass(frozen=True)
class SourceNuisance:
    elevation_deg: float
    hardness: float
    exposure: float
    rotation_deg: float
    translation_x_px: float
    translation_y_px: float
    frame_lights: tuple[FrameLight, ...]


# The diffuse term is deliberately elevation-independent: for a planar card the
# Lambert factor is spatially constant, so it is observationally inseparable from
# camera exposure. Folding it into a fixed constant makes per-source exposure
# identifiable from the card body alone and structurally prevents exposure error
# from trading against material parameters. Elevation still shapes the specular
# lobe elongation.
DIFFUSE_SHADING = 0.85


@dataclass(frozen=True)
class _RenderContext:
    """Precomputed per-fit constants so the inner optimization loop stays cheap."""

    albedo: np.ndarray
    chroma: np.ndarray
    xx: np.ndarray
    yy: np.ndarray


def _make_render_context(albedo_linear: np.ndarray) -> _RenderContext:
    height, width = albedo_linear.shape[:2]
    columns = np.linspace(0.0, 1.0, width, dtype=np.float32)
    rows = np.linspace(0.0, 1.0, height, dtype=np.float32)
    xx, yy = np.meshgrid(columns, rows)
    chroma = albedo_linear / (np.max(albedo_linear, axis=-1, keepdims=True) + EPSILON)
    return _RenderContext(albedo=albedo_linear, chroma=chroma, xx=xx, yy=yy)


def _render(
    context: _RenderContext,
    material: ReferenceMaterialParams,
    *,
    azimuth_deg: float,
    elevation_deg: float,
    glare_x: float,
    glare_y: float,
    hardness: float,
    exposure: float,
    rotation_deg: float = 0.0,
    translation_x_px: float = 0.0,
    translation_y_px: float = 0.0,
) -> np.ndarray:
    height, width = context.albedo.shape[:2]
    elevation = min(max(elevation_deg, ELEVATION_BOUNDS[0]), ELEVATION_BOUNDS[1])
    azimuth = math.radians(azimuth_deg)
    sigma = 0.04 + 0.30 * material.roughness
    elongation = 1.0 + 1.5 * (1.0 - math.sin(math.radians(elevation)))

    dx = context.xx - np.float32(glare_x)
    dy = context.yy - np.float32(glare_y)
    cos_a = math.cos(azimuth)
    sin_a = math.sin(azimuth)
    d_major = (cos_a * dx + sin_a * dy) / np.float32(sigma * elongation)
    d_minor = (-sin_a * dx + cos_a * dy) / np.float32(sigma)
    radius = np.sqrt(d_major * d_major + d_minor * d_minor)
    exponent = min(max(hardness, HARDNESS_BOUNDS[0]), HARDNESS_BOUNDS[1])
    lobe = np.exp(-0.5 * np.power(radius + EPSILON, exponent)).astype(np.float32)

    spec_color = (1.0 - material.metallic) + material.metallic * context.chroma
    shaded = context.albedo * np.float32(DIFFUSE_SHADING)
    specular = np.float32(material.specular_strength) * lobe[..., None] * spec_color
    render = np.float32(exposure) * (shaded + specular)
    render = np.clip(render, 0.0, 1.0).astype(np.float32)

    if rotation_deg != 0.0 or translation_x_px != 0.0 or translation_y_px != 0.0:
        matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), rotation_deg, 1.0)
        matrix[0, 2] += translation_x_px
        matrix[1, 2] += translation_y_px
        render = cv2.warpAffine(
            render,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        ).astype(np.float32)
    return render


def render_planar_candidate(
    albedo_linear: np.ndarray,
    material: ReferenceMaterialParams,
    *,
    azimuth_deg: float,
    elevation_deg: float,
    glare_x: float,
    glare_y: float,
    hardness: float,
    exposure: float,
    rotation_deg: float = 0.0,
    translation_x_px: float = 0.0,
    translation_y_px: float = 0.0,
) -> np.ndarray:
    """Render the deterministic planar card under one directional-light hypothesis.

    ``glare_x``/``glare_y`` are normalized [0, 1] card coordinates; hardness is a
    super-Gaussian lobe exponent (hard light => sharp-edged lobe), roughness sets
    lobe width, and the lobe elongates along the light azimuth at low elevation.
    Output is linear RGB clipped to [0, 1] (camera saturation)."""

    return _render(
        _make_render_context(albedo_linear),
        material,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
        glare_x=glare_x,
        glare_y=glare_y,
        hardness=hardness,
        exposure=exposure,
        rotation_deg=rotation_deg,
        translation_x_px=translation_x_px,
        translation_y_px=translation_y_px,
    )


def linear_rgb_to_srgb_bgr(linear_rgb: np.ndarray) -> np.ndarray:
    clipped = np.clip(linear_rgb, 0.0, 1.0)
    srgb = np.where(
        clipped <= 0.0031308,
        clipped * 12.92,
        1.055 * np.power(clipped, 1.0 / 2.4) - 0.055,
    )
    return np.round(srgb[..., ::-1] * 255.0).astype(np.uint8)


def write_linear_srgb_png(path: Path, linear_rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", linear_rgb_to_srgb_bgr(linear_rgb))
    if not success:
        raise ReferenceFitError(f"unable to encode render: {path}")
    encoded.tofile(path)


# ---------------------------------------------------------------------------
# Observation preparation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedFrameObservation:
    frame_id: str
    linear: np.ndarray
    luma: np.ndarray
    valid: np.ndarray


@dataclass(frozen=True)
class PreparedSource:
    observation: Observation
    frames: tuple[PreparedFrameObservation, ...]
    coverage: float
    usable: bool

    @property
    def source_id(self) -> str:
        return self.observation.source_id


def _prepare_source(root: Path, observation: Observation, min_coverage: float) -> PreparedSource:
    frames: list[PreparedFrameObservation] = []
    shape: tuple[int, int] | None = None
    for frame in observation.frames:
        image = read_image(root / frame.image_path)
        if shape is None:
            shape = image.shape[:2]
        elif image.shape[:2] != shape:
            raise ReferenceFitError(
                f"source {observation.source_id} frame {frame.frame_id} dimensions differ "
                f"from the first frame; registered observations must share one canonical size"
            )
        if frame.interference_mask_path is not None:
            interference = read_binary_mask(
                root / frame.interference_mask_path, expected_shape=shape
            )
            valid = ~interference
        else:
            valid = np.ones(shape, dtype=bool)
        linear = srgb_to_linear_rgb(image)
        frames.append(
            PreparedFrameObservation(
                frame_id=frame.frame_id,
                linear=linear,
                luma=luminance(linear),
                valid=valid,
            )
        )
    coverage = float(np.mean([np.mean(frame.valid) for frame in frames]))
    return PreparedSource(
        observation=observation,
        frames=tuple(frames),
        coverage=coverage,
        usable=coverage >= min_coverage,
    )


def _load_or_estimate_albedo(
    root: Path, manifest: ObservationSetManifest, sources: list[PreparedSource]
) -> np.ndarray:
    usable = [source for source in sources if source.usable]
    reference_shape = (usable or sources)[0].frames[0].linear.shape[:2]
    if manifest.albedo_path is not None:
        albedo = srgb_to_linear_rgb(read_image(root / manifest.albedo_path))
        if albedo.shape[:2] != reference_shape:
            raise ReferenceFitError(
                "albedo dimensions differ from registered observation dimensions"
            )
        return albedo
    stack: list[np.ndarray] = []
    for source in usable:
        for frame in source.frames:
            median_luma = float(np.median(frame.luma[frame.valid])) if np.any(frame.valid) else 0.0
            gain = 0.35 / (median_luma + EPSILON)
            stack.append(frame.linear * np.float32(min(gain, 8.0)))
    if not stack:
        raise ReferenceFitError("no usable observations available for albedo estimation")
    median = np.median(np.stack(stack, axis=0), axis=0).astype(np.float32)
    return np.clip(median / np.float32(DIFFUSE_SHADING), 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Loss terms
# ---------------------------------------------------------------------------


def _highlight_centroid(
    luma: np.ndarray, mask: np.ndarray, percentile: float
) -> tuple[float, float] | None:
    values = luma[mask]
    if values.size < 4:
        return None
    threshold = float(np.percentile(values, percentile))
    highlight = mask & (luma >= threshold)
    coordinates = np.argwhere(highlight)
    if coordinates.size == 0:
        return None
    weights = np.maximum(luma[highlight] - threshold, EPSILON)
    return (
        float(np.average(coordinates[:, 1], weights=weights)),
        float(np.average(coordinates[:, 0], weights=weights)),
    )


def _highlight_centroid_error(
    observed_luma: np.ndarray,
    rendered_luma: np.ndarray,
    mask: np.ndarray,
    percentile: float,
) -> float:
    observed = _highlight_centroid(observed_luma, mask, percentile)
    rendered = _highlight_centroid(rendered_luma, mask, percentile)
    if observed is None and rendered is None:
        return 0.0
    if observed is None or rendered is None:
        return 1.0
    diagonal = float(np.hypot(observed_luma.shape[1], observed_luma.shape[0]))
    return float(np.hypot(rendered[0] - observed[0], rendered[1] - observed[1]) / diagonal)


def _opponent_hue(linear_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    red, green, blue = (linear_rgb[..., channel] for channel in range(3))
    x = red - 0.5 * (green + blue)
    y = (np.sqrt(3.0) / 2.0) * (green - blue)
    return np.arctan2(y, x), np.sqrt(x * x + y * y)


def _hue_error(observed: np.ndarray, rendered: np.ndarray, mask: np.ndarray) -> float:
    observed_hue, observed_chroma = _opponent_hue(observed)
    rendered_hue, rendered_chroma = _opponent_hue(rendered)
    chroma = np.minimum(observed_chroma, rendered_chroma)
    if not np.any(mask):
        return 0.0
    eligible = mask & (chroma > np.percentile(chroma[mask], 35))
    if not np.any(eligible):
        return 0.0
    delta = np.angle(np.exp(1j * (rendered_hue[eligible] - observed_hue[eligible])))
    return float(np.average(np.abs(delta) / np.pi, weights=chroma[eligible] + EPSILON))


def _gradient_magnitude(luma: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx * gx + gy * gy)


def _frame_inner_loss(frame: PreparedFrameObservation, render: np.ndarray) -> float:
    """Fast optimization objective: masked linear-RGB MAE only.

    The full interpretable metric set (gradient, hue, highlight centroid, exposure,
    temporal delta) is computed once per source in ``_source_full_error`` and drives
    every acceptance decision."""
    if not np.any(frame.valid):
        return 0.0
    return float(np.mean(np.abs(render - frame.linear)[frame.valid]))


def _render_source_frame(
    context: _RenderContext,
    material: ReferenceMaterialParams,
    nuisance: SourceNuisance,
    index: int,
) -> np.ndarray:
    light = nuisance.frame_lights[index]
    return _render(
        context,
        material,
        azimuth_deg=light.azimuth_deg,
        elevation_deg=nuisance.elevation_deg,
        glare_x=light.glare_x,
        glare_y=light.glare_y,
        hardness=nuisance.hardness,
        exposure=nuisance.exposure,
        rotation_deg=nuisance.rotation_deg,
        translation_x_px=nuisance.translation_x_px,
        translation_y_px=nuisance.translation_y_px,
    )


def _source_inner_loss(
    source: PreparedSource,
    context: _RenderContext,
    material: ReferenceMaterialParams,
    nuisance: SourceNuisance,
) -> float:
    losses = [
        _frame_inner_loss(frame, _render_source_frame(context, material, nuisance, index))
        for index, frame in enumerate(source.frames)
    ]
    return float(np.mean(losses))


# ---------------------------------------------------------------------------
# Deterministic per-source nuisance estimation
# ---------------------------------------------------------------------------


def _initial_nuisance(source: PreparedSource, albedo: np.ndarray, percentile: float) -> SourceNuisance:
    height, width = source.frames[0].linear.shape[:2]
    lights: list[FrameLight] = []
    for frame in source.frames:
        centroid = _highlight_centroid(frame.luma, frame.valid, percentile)
        if centroid is None:
            centroid = ((width - 1) / 2.0, (height - 1) / 2.0)
        glare_x = centroid[0] / max(width - 1, 1)
        glare_y = centroid[1] / max(height - 1, 1)
        azimuth = math.degrees(math.atan2(glare_y - 0.5, glare_x - 0.5)) % 360.0
        lights.append(FrameLight(azimuth_deg=azimuth, glare_x=glare_x, glare_y=glare_y))
    albedo_luma = luminance(albedo)
    ratios: list[float] = []
    for frame in source.frames:
        if not np.any(frame.valid):
            continue
        observed = float(np.median(frame.luma[frame.valid]))
        base = float(np.median(albedo_luma[frame.valid])) * DIFFUSE_SHADING
        ratios.append(observed / (base + EPSILON))
    exposure = float(np.median(ratios)) if ratios else 1.0
    exposure = min(max(exposure, EXPOSURE_BOUNDS[0]), EXPOSURE_BOUNDS[1])
    return SourceNuisance(
        elevation_deg=45.0,
        hardness=2.0,
        exposure=exposure,
        rotation_deg=0.0,
        translation_x_px=0.0,
        translation_y_px=0.0,
        frame_lights=tuple(lights),
    )


def _best_of(candidates: list[float], evaluate: Callable[[float], float]) -> tuple[float, float]:
    best_value = candidates[0]
    best_loss = math.inf
    for value in candidates:
        loss = evaluate(value)
        if loss < best_loss:
            best_loss = loss
            best_value = value
    return best_value, best_loss


def _optimize_frame_light(
    source: PreparedSource,
    context: _RenderContext,
    material: ReferenceMaterialParams,
    nuisance: SourceNuisance,
    index: int,
) -> FrameLight:
    frame = source.frames[index]
    light = nuisance.frame_lights[index]

    def loss_for(candidate: FrameLight) -> float:
        lights = list(nuisance.frame_lights)
        lights[index] = candidate
        trial = replace(nuisance, frame_lights=tuple(lights))
        return _frame_inner_loss(frame, _render_source_frame(context, material, trial, index))

    for step in (0.05, 0.015):
        best = light
        best_loss = loss_for(light)
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                if dx == 0 and dy == 0:
                    continue
                candidate = replace(
                    light,
                    glare_x=min(max(light.glare_x + dx * step, GLARE_BOUNDS[0]), GLARE_BOUNDS[1]),
                    glare_y=min(max(light.glare_y + dy * step, GLARE_BOUNDS[0]), GLARE_BOUNDS[1]),
                )
                loss = loss_for(candidate)
                if loss < best_loss:
                    best_loss = loss
                    best = candidate
        light = best

    for span, step_deg in ((90.0, 15.0), (12.0, 4.0)):
        offsets = np.arange(-span, span + EPSILON, step_deg)
        candidates = [replace(light, azimuth_deg=(light.azimuth_deg + float(o)) % 360.0) for o in offsets]
        best = light
        best_loss = loss_for(light)
        for candidate in candidates:
            loss = loss_for(candidate)
            if loss < best_loss:
                best_loss = loss
                best = candidate
        light = best
    return light


def _optimize_source_nuisance(
    source: PreparedSource,
    context: _RenderContext,
    material: ReferenceMaterialParams,
    nuisance: SourceNuisance,
    options: ReferenceFitOptions,
) -> SourceNuisance:
    lights = [
        _optimize_frame_light(source, context, material, nuisance, index)
        for index in range(len(source.frames))
    ]
    nuisance = replace(nuisance, frame_lights=tuple(lights))

    def shared_loss(trial: SourceNuisance) -> float:
        return _source_inner_loss(source, context, material, trial)

    nuisance = replace(
        nuisance, exposure=_optimal_exposure(source, context, material, nuisance)
    )

    elevation_grid = [float(v) for v in np.linspace(*ELEVATION_BOUNDS, 7)]
    best_elevation, _ = _best_of(
        elevation_grid, lambda v: shared_loss(replace(nuisance, elevation_deg=v))
    )
    fine = [
        min(max(best_elevation + delta, ELEVATION_BOUNDS[0]), ELEVATION_BOUNDS[1])
        for delta in (-8.0, -4.0, 0.0, 4.0, 8.0)
    ]
    best_elevation, _ = _best_of(fine, lambda v: shared_loss(replace(nuisance, elevation_deg=v)))
    nuisance = replace(nuisance, elevation_deg=best_elevation)

    hardness_grid = [float(v) for v in np.linspace(*HARDNESS_BOUNDS, 7)]
    best_hardness, _ = _best_of(
        hardness_grid, lambda v: shared_loss(replace(nuisance, hardness=v))
    )
    fine = [
        min(max(best_hardness + delta, HARDNESS_BOUNDS[0]), HARDNESS_BOUNDS[1])
        for delta in (-0.4, -0.2, 0.0, 0.2, 0.4)
    ]
    best_hardness, _ = _best_of(fine, lambda v: shared_loss(replace(nuisance, hardness=v)))
    nuisance = replace(nuisance, hardness=best_hardness)

    def refine_exposure(current: SourceNuisance, factors: tuple[float, ...]) -> SourceNuisance:
        candidates = [
            min(max(current.exposure * factor, EXPOSURE_BOUNDS[0]), EXPOSURE_BOUNDS[1])
            for factor in factors
        ]
        best_exposure, _ = _best_of(
            candidates, lambda v: shared_loss(replace(current, exposure=v))
        )
        return replace(current, exposure=best_exposure)

    nuisance = replace(
        nuisance, exposure=_optimal_exposure(source, context, material, nuisance)
    )
    nuisance = refine_exposure(nuisance, (0.96, 0.98, 1.0, 1.02, 1.04))

    best_pose = (nuisance.rotation_deg, nuisance.translation_x_px, nuisance.translation_y_px)
    best_loss = shared_loss(nuisance)
    for rotation in (-1.5, 0.0, 1.5):
        for ty in (-3.0, 0.0, 3.0):
            for tx in (-3.0, 0.0, 3.0):
                if (rotation, tx, ty) == best_pose:
                    continue
                trial = replace(
                    nuisance,
                    rotation_deg=rotation,
                    translation_x_px=tx,
                    translation_y_px=ty,
                )
                loss = shared_loss(trial)
                if loss < best_loss:
                    best_loss = loss
                    best_pose = (rotation, tx, ty)
    return replace(
        nuisance,
        rotation_deg=best_pose[0],
        translation_x_px=best_pose[1],
        translation_y_px=best_pose[2],
    )


# ---------------------------------------------------------------------------
# Joint (shared) material fit
# ---------------------------------------------------------------------------


def _optimize_material(
    sources: list[PreparedSource],
    nuisances: dict[str, SourceNuisance],
    context: _RenderContext,
    material: ReferenceMaterialParams,
    options: ReferenceFitOptions,
) -> ReferenceMaterialParams:
    usable = [source for source in sources if source.usable]

    def total_loss(candidate: ReferenceMaterialParams) -> float:
        total = 0.0
        for source in usable:
            nuisance = nuisances[source.source_id]
            projected = replace(
                nuisance, exposure=_optimal_exposure(source, context, candidate, nuisance)
            )
            total += source.observation.prior_weight * _source_inner_loss(
                source, context, candidate, projected
            )
        return float(total)

    bounds = {
        "specular_strength": (0.0, 1.0),
        "roughness": ROUGHNESS_BOUNDS,
        "metallic": (0.0, 1.0),
    }
    for span, count in ((None, 9), (0.15, 9), (0.05, 5)):
        for name, (low, high) in bounds.items():
            current = float(getattr(material, name))
            if span is None:
                values = [float(v) for v in np.linspace(low, high, count)]
            else:
                values = [
                    min(max(current + float(delta), low), high)
                    for delta in np.linspace(-span, span, count)
                ]
            if current not in values:
                values.append(current)
            best_value = current
            best_loss = math.inf
            for value in values:
                candidate = material.model_copy(update={name: value})
                loss = total_loss(candidate)
                if loss < best_loss:
                    best_loss = loss
                    best_value = value
            material = material.model_copy(update={name: best_value})
    return material


# ---------------------------------------------------------------------------
# Final per-source metrics, gates, and score
# ---------------------------------------------------------------------------


def _source_full_error(
    source: PreparedSource,
    context: _RenderContext,
    material: ReferenceMaterialParams,
    nuisance: SourceNuisance,
    options: ReferenceFitOptions,
) -> tuple[float, list[np.ndarray]]:
    weights = options.weights
    renders = [
        _render_source_frame(context, material, nuisance, index)
        for index in range(len(source.frames))
    ]
    metrics: list[float] = []
    for frame, render in zip(source.frames, renders, strict=True):
        if not np.any(frame.valid):
            continue
        render_luma = luminance(render)
        linear_mae = float(np.mean(np.abs(render - frame.linear)[frame.valid]))
        gradient_mae = float(
            np.mean(
                np.abs(_gradient_magnitude(render_luma) - _gradient_magnitude(frame.luma))[
                    frame.valid
                ]
            )
        )
        hue = _hue_error(frame.linear, render, frame.valid)
        centroid = _highlight_centroid_error(
            frame.luma, render_luma, frame.valid, options.highlight_percentile
        )
        exposure_error = float(
            abs(np.mean(frame.luma[frame.valid]) - np.mean(render_luma[frame.valid]))
        )
        metrics.append(
            linear_mae * weights.linear_rgb
            + gradient_mae * weights.gradient
            + hue * weights.hue
            + centroid * weights.highlight_centroid
            + exposure_error * weights.exposure
        )
    error = float(np.mean(metrics)) if metrics else 1.0
    if len(source.frames) >= 2:
        deltas: list[float] = []
        for index in range(1, len(source.frames)):
            previous = source.frames[index - 1]
            current = source.frames[index]
            joint_valid = previous.valid & current.valid
            if not np.any(joint_valid):
                continue
            observed_delta = current.linear - previous.linear
            rendered_delta = renders[index] - renders[index - 1]
            deltas.append(float(np.mean(np.abs(observed_delta - rendered_delta)[joint_valid])))
        if deltas:
            error += float(np.mean(deltas)) * weights.temporal_delta
    return error, renders


def _detect_single_reference_overfit(
    errors: dict[str, float], options: ReferenceFitOptions
) -> tuple[bool, list[str]]:
    if not errors:
        return False, []
    if len(errors) == 1:
        return True, sorted(errors)
    good = sorted(
        source_id for source_id, error in errors.items() if error <= options.accept_error_threshold
    )
    if len(good) != 1:
        return False, []
    privileged = good[0]
    others = [error for source_id, error in errors.items() if source_id != privileged]
    floor = max(errors[privileged], options.accept_error_threshold / 2.0)
    concentrated = all(
        error > 2.0 * options.accept_error_threshold and error >= options.privilege_ratio * floor
        for error in others
    )
    return (True, [privileged]) if concentrated else (False, [])


def _consistency_score(errors: dict[str, float], options: ReferenceFitOptions) -> float:
    if not errors:
        return 0.0
    agreement = [math.exp(-error / options.accept_error_threshold) for error in errors.values()]
    mean_agreement = float(np.mean(agreement))
    count = len(agreement)
    if count == 1:
        concentration = 1.0
    else:
        shares = np.asarray(agreement, dtype=np.float64)
        total = float(np.sum(shares))
        concentration = (
            0.0
            if total <= EPSILON
            else float((np.max(shares / total) - 1.0 / count) / (1.0 - 1.0 / count))
        )
    return float(np.clip(mean_agreement * (1.0 - 0.5 * concentration), 0.0, 1.0))


def _regional_error_map(
    frame: PreparedFrameObservation, render: np.ndarray, lobe_mask: np.ndarray
) -> dict[str, float]:
    height, width = frame.linear.shape[:2]
    difference = np.mean(np.abs(render - frame.linear), axis=-1)
    regions: dict[str, float] = {}
    row_edges = np.linspace(0, height, 4, dtype=int)
    column_edges = np.linspace(0, width, 4, dtype=int)
    for row in range(3):
        for column in range(3):
            cell = np.zeros((height, width), dtype=bool)
            cell[row_edges[row] : row_edges[row + 1], column_edges[column] : column_edges[column + 1]] = True
            cell &= frame.valid
            if np.any(cell):
                regions[f"grid-r{row}-c{column}"] = float(np.mean(difference[cell]))
    highlight = lobe_mask & frame.valid
    if np.any(highlight):
        regions["highlight-lobe"] = float(np.mean(difference[highlight]))
    return regions


def _lobe_mask(
    shape: tuple[int, int], material: ReferenceMaterialParams, nuisance: SourceNuisance
) -> np.ndarray:
    height, width = shape
    light = nuisance.frame_lights[0]
    columns = np.linspace(0.0, 1.0, width, dtype=np.float32)
    rows = np.linspace(0.0, 1.0, height, dtype=np.float32)
    xx, yy = np.meshgrid(columns, rows)
    sigma = 0.04 + 0.30 * material.roughness
    elongation = 1.0 + 1.5 * (1.0 - math.sin(math.radians(nuisance.elevation_deg)))
    azimuth = math.radians(light.azimuth_deg)
    dx = xx - np.float32(light.glare_x)
    dy = yy - np.float32(light.glare_y)
    d_major = (math.cos(azimuth) * dx + math.sin(azimuth) * dy) / np.float32(sigma * elongation)
    d_minor = (-math.sin(azimuth) * dx + math.cos(azimuth) * dy) / np.float32(sigma)
    radius = np.sqrt(d_major * d_major + d_minor * d_minor)
    lobe = np.exp(-0.5 * np.power(radius + EPSILON, nuisance.hardness))
    return np.asarray(lobe > 0.5)


def _optimal_exposure(
    source: PreparedSource,
    context: _RenderContext,
    material: ReferenceMaterialParams,
    nuisance: SourceNuisance,
) -> float:
    """Closed-form per-source exposure (variable projection): the robust median of
    observed/rendered luminance ratios at unit exposure. Exposure is always solved
    per source and never traded against shared material parameters."""
    unit = replace(nuisance, exposure=1.0)
    ratios: list[float] = []
    for index, frame in enumerate(source.frames):
        unit_luma = luminance(_render_source_frame(context, material, unit, index))
        mask = frame.valid & (unit_luma > 0.02)
        if not np.any(mask):
            continue
        ratios.append(float(np.median(frame.luma[mask] / (unit_luma[mask] + EPSILON))))
    if not ratios:
        return nuisance.exposure
    return min(max(float(np.median(ratios)), EXPOSURE_BOUNDS[0]), EXPOSURE_BOUNDS[1])


def _highlight_trajectory(
    source: PreparedSource,
    renders: list[np.ndarray],
    percentile: float,
) -> list[dict[str, float | str]] | None:
    if source.observation.media_form != "sequence" or len(source.frames) < 2:
        return None
    entries: list[dict[str, float | str]] = []
    for frame, render in zip(source.frames, renders, strict=True):
        observed = _highlight_centroid(frame.luma, frame.valid, percentile)
        rendered = _highlight_centroid(luminance(render), frame.valid, percentile)
        if observed is None or rendered is None:
            continue
        entries.append(
            {
                "frame_id": frame.frame_id,
                "observed_x": observed[0],
                "observed_y": observed[1],
                "rendered_x": rendered[0],
                "rendered_y": rendered[1],
                "distance_px": float(
                    np.hypot(rendered[0] - observed[0], rendered[1] - observed[1])
                ),
            }
        )
    return entries if len(entries) >= 2 else None


def _circular_mean_deg(values: list[float]) -> float:
    radians = np.radians(np.asarray(values, dtype=np.float64))
    mean = math.degrees(
        math.atan2(float(np.mean(np.sin(radians))), float(np.mean(np.cos(radians))))
    )
    return mean % 360.0


def _assert_reference_vocabulary(serialized: str) -> None:
    lowered = serialized.lower()
    for phrase in FORBIDDEN_CLAIM_PHRASES:
        if phrase in lowered:
            raise ReferenceFitError(
                f"reference-lane output must not contain physical-claim phrase: {phrase!r}"
            )


# ---------------------------------------------------------------------------
# Top-level fit
# ---------------------------------------------------------------------------


def load_observation_manifest(path: Path) -> ObservationSetManifest:
    return ObservationSetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_manifest_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ObservationSetManifest.model_json_schema(), indent=2) + "\n",
        encoding="utf-8",
    )


def _write_profile(
    output_dir: Path, manifest: ObservationSetManifest, material: ReferenceMaterialParams
) -> Path:
    profile = {
        "schema_version": REFERENCE_FIT_SCHEMA_VERSION,
        "lane": "reference",
        "label": REFERENCE_LANE_LABEL,
        "claim": REFERENCE_LANE_CLAIM,
        "bundle_id": manifest.bundle_id,
        "run_id": manifest.run_id,
        "geometry": "deterministic-planar-card",
        "material": material.model_dump(),
    }
    serialized = json.dumps(profile, indent=2, sort_keys=True) + "\n"
    _assert_reference_vocabulary(serialized)
    path = output_dir / PROFILE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")
    return path


def _write_difference_image(path: Path, frame: PreparedFrameObservation, render: np.ndarray) -> None:
    difference = np.mean(np.abs(render - frame.linear), axis=-1)
    difference = np.where(frame.valid, difference, 0.0)
    image = np.round(np.clip(difference * 4.0, 0.0, 1.0) * 255.0).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise ReferenceFitError(f"unable to encode difference image: {path}")
    encoded.tofile(path)


def fit_reference_set(
    root: Path,
    manifest: ObservationSetManifest,
    output_dir: Path,
    *,
    options: ReferenceFitOptions | None = None,
    generated_at: datetime | None = None,
) -> ReferenceFitOutcome:
    """Jointly fit ONE reference-derived renderer profile across all usable observations.

    Deterministic given identical inputs (pass a fixed ``generated_at`` for
    byte-identical reports). Writes the fitted profile, per-source candidate renders,
    difference images, and the schema-conforming report under ``output_dir``."""

    options = options or ReferenceFitOptions()
    sources = [
        _prepare_source(root, observation, options.min_valid_coverage)
        for observation in manifest.observations
    ]
    usable = [source for source in sources if source.usable]
    if not usable:
        raise ReferenceFitError(
            "no usable observations: interference masks exclude too many pixels in every source"
        )
    albedo = _load_or_estimate_albedo(root, manifest, sources)
    for source in sources:
        if source.frames[0].linear.shape[:2] != albedo.shape[:2]:
            raise ReferenceFitError(
                f"source {source.source_id} dimensions differ from the canonical registered size"
            )

    context = _make_render_context(albedo)
    material = ReferenceMaterialParams()
    nuisances: dict[str, SourceNuisance] = {
        source.source_id: _initial_nuisance(source, albedo, options.highlight_percentile)
        for source in sources
    }
    for _ in range(options.rounds):
        for source in usable:
            nuisances[source.source_id] = _optimize_source_nuisance(
                source, context, material, nuisances[source.source_id], options
            )
        material = _optimize_material(sources, nuisances, context, material, options)
    for source in usable:
        nuisances[source.source_id] = _optimize_source_nuisance(
            source, context, material, nuisances[source.source_id], options
        )
    material = _optimize_material(sources, nuisances, context, material, options)
    for source in usable:
        nuisance = nuisances[source.source_id]
        nuisances[source.source_id] = replace(
            nuisance, exposure=_optimal_exposure(source, context, material, nuisance)
        )

    profile_path = _write_profile(output_dir, manifest, material)
    profile_hash = file_digest(profile_path)

    errors: dict[str, float] = {}
    per_source: list[PerSourceFit] = []
    outliers: list[OutlierEntry] = []
    for source in sources:
        nuisance = nuisances[source.source_id]
        error, renders = _source_full_error(source, context, material, nuisance, options)
        if source.usable:
            errors[source.source_id] = error

        render_relative = f"renders/{source.source_id}-{source.frames[0].frame_id}.png"
        for frame, render in zip(source.frames, renders, strict=True):
            write_linear_srgb_png(
                output_dir / "renders" / f"{source.source_id}-{frame.frame_id}.png", render
            )
        difference_relative = f"diffs/{source.source_id}.png"
        _write_difference_image(output_dir / difference_relative, source.frames[0], renders[0])

        height, width = source.frames[0].linear.shape[:2]
        glare_points = [
            (light.glare_x * (width - 1), light.glare_y * (height - 1))
            for light in nuisance.frame_lights
        ]
        per_source.append(
            PerSourceFit(
                source_id=source.source_id,
                estimated_pose={
                    "rotation_deg": nuisance.rotation_deg,
                    "translation_x_px": nuisance.translation_x_px,
                    "translation_y_px": nuisance.translation_y_px,
                },
                light_direction=LightDirection(
                    azimuth_deg=_circular_mean_deg(
                        [light.azimuth_deg for light in nuisance.frame_lights]
                    ),
                    elevation_deg=nuisance.elevation_deg,
                ),
                glare_center=GlareCenter(
                    x=float(np.mean([point[0] for point in glare_points])),
                    y=float(np.mean([point[1] for point in glare_points])),
                ),
                light_hardness=nuisance.hardness,
                exposure_scale=nuisance.exposure,
                confidence_weight=(
                    float(
                        np.clip(
                            source.observation.prior_weight
                            * math.exp(-error / (2.0 * options.accept_error_threshold)),
                            0.0,
                            1.0,
                        )
                    )
                    if source.usable
                    else 0.0
                ),
                candidate_render_path=render_relative,
                difference_image_path=difference_relative,
                regional_error=_regional_error_map(
                    source.frames[0],
                    renders[0],
                    _lobe_mask(source.frames[0].linear.shape[:2], material, nuisance),
                ),
                highlight_trajectory=_highlight_trajectory(
                    source, renders, options.highlight_percentile
                ),
            )
        )
        if not source.usable:
            outliers.append(
                OutlierEntry(
                    source_id=source.source_id,
                    reason=(
                        "interference mask leaves insufficient usable pixels "
                        f"(coverage {source.coverage:.3f} < {options.min_valid_coverage}); "
                        "excluded from the joint reference-derived fit"
                    ),
                    metric=source.coverage,
                )
            )
        elif error > options.outlier_error_threshold:
            outliers.append(
                OutlierEntry(
                    source_id=source.source_id,
                    reason=(
                        f"weighted residual {error:.4f} exceeds the cross-reference outlier "
                        f"threshold {options.outlier_error_threshold}; source is inconsistent "
                        "with the jointly fitted reference-derived profile"
                    ),
                    metric=error,
                )
            )

    overfit_flag, privileged = _detect_single_reference_overfit(errors, options)
    rejection_reasons: list[str] = []
    if overfit_flag:
        rejection_reasons.append(
            "single-reference overfit: fit quality is concentrated in "
            + ", ".join(privileged)
            + "; profile rejected"
        )

    # Aggregate acceptance gate: uniformly-mediocre fits (every source above the
    # accept threshold but below the model limit) and incoherent source sets are
    # rejections, not silent acceptances.
    accepted_sources = [
        source_id
        for source_id, error in errors.items()
        if error <= options.accept_error_threshold
    ]
    if not overfit_flag and len(accepted_sources) < options.min_accepted_sources:
        rejection_reasons.append(
            f"insufficient fit quality: only {len(accepted_sources)} source(s) at or below "
            f"the accept error threshold {options.accept_error_threshold}; at least "
            f"{options.min_accepted_sources} required"
        )
    consistency = _consistency_score(errors, options)
    if consistency < options.min_consistency_score:
        rejection_reasons.append(
            f"cross-reference consistency {consistency:.3f} is below the acceptance floor "
            f"{options.min_consistency_score}; the profile does not cohere across sources"
        )

    model_limit_diagnostic: str | None = None
    if errors and all(error > options.model_limit_threshold for error in errors.values()):
        model_limit_diagnostic = (
            "renderer-model-limit: no parameter setting of the standardized planar renderer "
            "reproduces the observed response in any source (all weighted residuals exceed "
            f"{options.model_limit_threshold}); recorded as a finding, renderer not extended"
        )
        rejection_reasons.append(model_limit_diagnostic)
        for source_id in sorted(errors):
            outliers.append(
                OutlierEntry(
                    source_id=source_id,
                    reason=model_limit_diagnostic,
                    metric=errors[source_id],
                )
            )

    prior_weights = {
        source.source_id: source.observation.prior_weight for source in sources if source.usable
    }
    total_prior = sum(prior_weights.values())
    aggregate_loss = (
        float(
            sum(errors[source_id] * prior_weights[source_id] for source_id in errors) / total_prior
        )
        if total_prior > EPSILON
        else float(np.mean(list(errors.values())))
    )

    report = ReferenceFittingReport(
        run_id=manifest.run_id,
        bundle_id=manifest.bundle_id,
        profile_path=PROFILE_FILENAME,
        profile_blake3=profile_hash,
        per_source=per_source,
        cross_reference_consistency_score=consistency,
        single_reference_overfit_flag=overfit_flag,
        privileged_reference_ids=privileged,
        outlier_report=outliers,
        aggregate_loss=aggregate_loss,
        generated_at=generated_at or datetime.now(UTC),
    )
    serialized = report.model_dump_json(indent=2)
    _assert_reference_vocabulary(serialized)
    report_path = output_dir / REPORT_FILENAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(serialized + "\n", encoding="utf-8")

    return ReferenceFitOutcome(
        report=report,
        material=material,
        accepted=not rejection_reasons,
        rejection_reasons=tuple(rejection_reasons),
        model_limit_diagnostic=model_limit_diagnostic,
        report_path=report_path,
        profile_path=profile_path,
    )
