from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .material_maps import luminance, robust_normalize, srgb_to_linear_rgb
from .quality import read_image
from .semantic import file_digest, read_binary_mask, safe_relative_path

FIT_SCHEMA_VERSION = "1.0.0"
EPSILON = 1e-6


class FitError(RuntimeError):
    """Raised when matched reference/candidate evidence cannot be evaluated safely."""


class FitLossWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    linear_rgb: float = Field(default=1.0, ge=0)
    gradient: float = Field(default=0.35, ge=0)
    highlight_centroid: float = Field(default=0.65, ge=0)
    hue: float = Field(default=0.45, ge=0)
    temporal_delta: float = Field(default=0.4, ge=0)
    exposure: float = Field(default=0.25, ge=0)


class FitRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=96)
    mask_path: str
    weight: float = Field(default=1.0, gt=0, le=100)

    @field_validator("mask_path")
    @classmethod
    def validate_mask_path(cls, value: str) -> str:
        return safe_relative_path(value)


class FitFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    reference_path: str
    candidate_path: str
    angle_x_degrees: float | None = Field(default=None, ge=-180, le=180)
    angle_y_degrees: float | None = Field(default=None, ge=-180, le=180)
    light_azimuth_degrees: float | None = Field(default=None, ge=-360, le=360)
    light_elevation_degrees: float | None = Field(default=None, ge=-90, le=90)
    regions: list[FitRegion] = Field(default_factory=list)

    @field_validator("reference_path", "candidate_path")
    @classmethod
    def validate_image_paths(cls, value: str) -> str:
        return safe_relative_path(value)


class FitSequenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = FIT_SCHEMA_VERSION
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    session_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,95}$")
    profile_path: str | None = None
    output_path: str = "review/fit-report.json"
    weights: FitLossWeights = Field(default_factory=FitLossWeights)
    highlight_percentile: float = Field(default=96.0, ge=80, le=99.9)
    allow_resize: bool = False
    frames: list[FitFrame] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("profile_path", "output_path")
    @classmethod
    def validate_optional_paths(cls, value: str | None) -> str | None:
        return safe_relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def frame_ids_must_be_unique(self) -> FitSequenceRequest:
        ids = [frame.frame_id for frame in self.frames]
        if len(ids) != len(set(ids)):
            raise ValueError("fit frame ids must be unique")
        return self


class RegionMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pixels: int = Field(ge=1)
    weight: float = Field(gt=0)
    linear_rgb_mae: float = Field(ge=0)
    gradient_mae: float = Field(ge=0)
    hue_error: float = Field(ge=0, le=1)
    highlight_centroid_error: float = Field(ge=0)
    exposure_error: float = Field(ge=0)


class FrameMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    reference_blake3: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_blake3: str = Field(pattern=r"^[0-9a-f]{64}$")
    linear_rgb_mae: float = Field(ge=0)
    gradient_mae: float = Field(ge=0)
    hue_error: float = Field(ge=0, le=1)
    highlight_centroid_error: float = Field(ge=0)
    exposure_error: float = Field(ge=0)
    weighted_loss: float = Field(ge=0)
    regions: list[RegionMetric] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FitReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = FIT_SCHEMA_VERSION
    run_id: str
    session_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    profile_blake3: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    weights: FitLossWeights
    aggregate_loss: float = Field(ge=0)
    mean_linear_rgb_mae: float = Field(ge=0)
    mean_gradient_mae: float = Field(ge=0)
    mean_hue_error: float = Field(ge=0, le=1)
    mean_highlight_centroid_error: float = Field(ge=0)
    mean_exposure_error: float = Field(ge=0)
    temporal_delta_error: float = Field(ge=0)
    frames: list[FrameMetric]
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class PreparedFrame:
    frame: FitFrame
    reference_path: Path
    candidate_path: Path
    reference_linear: np.ndarray
    candidate_linear: np.ndarray
    regions: list[tuple[FitRegion, np.ndarray]]
    warnings: list[str]


def _gradient_magnitude(linear_rgb: np.ndarray) -> np.ndarray:
    luma = luminance(linear_rgb)
    gx = cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx * gx + gy * gy)


def _opponent_hue(linear_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    red = linear_rgb[..., 0]
    green = linear_rgb[..., 1]
    blue = linear_rgb[..., 2]
    x = red - 0.5 * (green + blue)
    y = (np.sqrt(3.0) / 2.0) * (green - blue)
    hue = np.arctan2(y, x)
    chroma = np.sqrt(x * x + y * y)
    return hue, chroma


def _circular_hue_error(
    reference: np.ndarray,
    candidate: np.ndarray,
    mask: np.ndarray,
) -> float:
    reference_hue, reference_chroma = _opponent_hue(reference)
    candidate_hue, candidate_chroma = _opponent_hue(candidate)
    chroma = np.minimum(reference_chroma, candidate_chroma)
    eligible = mask & (chroma > np.percentile(chroma[mask], 35) if np.any(mask) else False)
    if not np.any(eligible):
        return 0.0
    delta = np.angle(np.exp(1j * (candidate_hue[eligible] - reference_hue[eligible])))
    weights = chroma[eligible] + EPSILON
    return float(np.average(np.abs(delta) / np.pi, weights=weights))


def _highlight_centroid(luma: np.ndarray, mask: np.ndarray, percentile: float) -> tuple[float, float] | None:
    values = luma[mask]
    if values.size < 4:
        return None
    threshold = float(np.percentile(values, percentile))
    highlight = mask & (luma >= threshold)
    coordinates = np.argwhere(highlight)
    if coordinates.size == 0:
        return None
    weights = np.maximum(luma[highlight] - threshold, EPSILON)
    y = float(np.average(coordinates[:, 0], weights=weights))
    x = float(np.average(coordinates[:, 1], weights=weights))
    return x, y


def _highlight_centroid_error(
    reference_luma: np.ndarray,
    candidate_luma: np.ndarray,
    mask: np.ndarray,
    percentile: float,
) -> float:
    reference = _highlight_centroid(reference_luma, mask, percentile)
    candidate = _highlight_centroid(candidate_luma, mask, percentile)
    if reference is None and candidate is None:
        return 0.0
    if reference is None or candidate is None:
        return 1.0
    diagonal = np.hypot(reference_luma.shape[1], reference_luma.shape[0])
    return float(np.hypot(candidate[0] - reference[0], candidate[1] - reference[1]) / diagonal)


def _region_metrics(
    reference: np.ndarray,
    candidate: np.ndarray,
    mask: np.ndarray,
    *,
    percentile: float,
) -> dict[str, float]:
    if mask.dtype != bool:
        mask = mask.astype(bool)
    if not np.any(mask):
        raise FitError("evaluation mask contains no pixels")

    rgb_error = np.abs(reference - candidate)
    reference_gradient = _gradient_magnitude(reference)
    candidate_gradient = _gradient_magnitude(candidate)
    reference_luma = luminance(reference)
    candidate_luma = luminance(candidate)

    return {
        "linear_rgb_mae": float(np.mean(rgb_error[mask])),
        "gradient_mae": float(np.mean(np.abs(reference_gradient - candidate_gradient)[mask])),
        "hue_error": _circular_hue_error(reference, candidate, mask),
        "highlight_centroid_error": _highlight_centroid_error(
            reference_luma,
            candidate_luma,
            mask,
            percentile,
        ),
        "exposure_error": float(abs(np.mean(reference_luma[mask]) - np.mean(candidate_luma[mask]))),
    }


def _weighted_loss(metrics: dict[str, float], weights: FitLossWeights) -> float:
    return float(
        metrics["linear_rgb_mae"] * weights.linear_rgb
        + metrics["gradient_mae"] * weights.gradient
        + metrics["highlight_centroid_error"] * weights.highlight_centroid
        + metrics["hue_error"] * weights.hue
        + metrics["exposure_error"] * weights.exposure
    )


def _prepare_frame(root: Path, frame: FitFrame, allow_resize: bool) -> PreparedFrame:
    reference_path = root / frame.reference_path
    candidate_path = root / frame.candidate_path
    reference_bgr = read_image(reference_path)
    candidate_bgr = read_image(candidate_path)
    warnings: list[str] = []

    if reference_bgr.shape[:2] != candidate_bgr.shape[:2]:
        if not allow_resize:
            raise FitError(
                f"frame {frame.frame_id} dimensions differ: "
                f"reference={reference_bgr.shape[:2]}, candidate={candidate_bgr.shape[:2]}"
            )
        candidate_bgr = cv2.resize(
            candidate_bgr,
            (reference_bgr.shape[1], reference_bgr.shape[0]),
            interpolation=cv2.INTER_LANCZOS4,
        )
        warnings.append("candidate resized to reference dimensions")

    shape = reference_bgr.shape[:2]
    regions: list[tuple[FitRegion, np.ndarray]] = []
    for region in frame.regions:
        mask = read_binary_mask(root / region.mask_path, expected_shape=shape)
        if not np.any(mask):
            warnings.append(f"region {region.name} is empty and was ignored")
            continue
        regions.append((region, mask))

    return PreparedFrame(
        frame=frame,
        reference_path=reference_path,
        candidate_path=candidate_path,
        reference_linear=srgb_to_linear_rgb(reference_bgr),
        candidate_linear=srgb_to_linear_rgb(candidate_bgr),
        regions=regions,
        warnings=warnings,
    )


def _evaluate_prepared(
    prepared: PreparedFrame,
    request: FitSequenceRequest,
) -> FrameMetric:
    height, width = prepared.reference_linear.shape[:2]
    full_mask = np.ones((height, width), dtype=bool)
    global_metrics = _region_metrics(
        prepared.reference_linear,
        prepared.candidate_linear,
        full_mask,
        percentile=request.highlight_percentile,
    )

    region_results: list[RegionMetric] = []
    weighted_region_losses: list[float] = []
    weighted_region_weights: list[float] = []
    for region, mask in prepared.regions:
        metrics = _region_metrics(
            prepared.reference_linear,
            prepared.candidate_linear,
            mask,
            percentile=request.highlight_percentile,
        )
        region_results.append(
            RegionMetric(
                name=region.name,
                pixels=int(np.count_nonzero(mask)),
                weight=region.weight,
                **metrics,
            )
        )
        weighted_region_losses.append(_weighted_loss(metrics, request.weights) * region.weight)
        weighted_region_weights.append(region.weight)

    global_loss = _weighted_loss(global_metrics, request.weights)
    if weighted_region_weights:
        regional_loss = sum(weighted_region_losses) / sum(weighted_region_weights)
        frame_loss = 0.45 * global_loss + 0.55 * regional_loss
    else:
        frame_loss = global_loss

    return FrameMetric(
        frame_id=prepared.frame.frame_id,
        width=width,
        height=height,
        reference_blake3=file_digest(prepared.reference_path),
        candidate_blake3=file_digest(prepared.candidate_path),
        weighted_loss=frame_loss,
        regions=region_results,
        warnings=prepared.warnings,
        **global_metrics,
    )


def _temporal_delta_error(prepared: list[PreparedFrame]) -> float:
    if len(prepared) < 2:
        return 0.0
    losses: list[float] = []
    for previous, current in zip(prepared, prepared[1:], strict=False):
        reference_delta = current.reference_linear - previous.reference_linear
        candidate_delta = current.candidate_linear - previous.candidate_linear
        losses.append(float(np.mean(np.abs(reference_delta - candidate_delta))))
    return float(np.mean(losses))


def evaluate_fit_sequence(root: Path, request: FitSequenceRequest) -> FitReport:
    prepared = [_prepare_frame(root, frame, request.allow_resize) for frame in request.frames]
    metrics = [_evaluate_prepared(frame, request) for frame in prepared]
    temporal_error = _temporal_delta_error(prepared)
    mean_frame_loss = float(np.mean([frame.weighted_loss for frame in metrics]))
    aggregate = mean_frame_loss + temporal_error * request.weights.temporal_delta
    warnings = [warning for frame in metrics for warning in frame.warnings]

    profile_hash = None
    if request.profile_path is not None:
        profile = root / request.profile_path
        if not profile.is_file():
            raise FitError(f"profile does not exist: {request.profile_path}")
        profile_hash = file_digest(profile)

    report = FitReport(
        run_id=request.run_id,
        session_id=request.session_id,
        profile_blake3=profile_hash,
        weights=request.weights,
        aggregate_loss=aggregate,
        mean_linear_rgb_mae=float(np.mean([frame.linear_rgb_mae for frame in metrics])),
        mean_gradient_mae=float(np.mean([frame.gradient_mae for frame in metrics])),
        mean_hue_error=float(np.mean([frame.hue_error for frame in metrics])),
        mean_highlight_centroid_error=float(
            np.mean([frame.highlight_centroid_error for frame in metrics])
        ),
        mean_exposure_error=float(np.mean([frame.exposure_error for frame in metrics])),
        temporal_delta_error=temporal_error,
        frames=metrics,
        warnings=warnings,
    )

    output = root / request.output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    return report


def load_fit_request(path: Path) -> FitSequenceRequest:
    return FitSequenceRequest.model_validate_json(path.read_text(encoding="utf-8"))


def write_fit_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(FitSequenceRequest.model_json_schema(), indent=2) + "\n", encoding="utf-8")
