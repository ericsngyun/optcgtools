from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import CaptureDirection, CaptureKind, CaptureSession
from .provenance import load_manifest
from .quality import read_image
from .semantic import file_digest, read_binary_mask, safe_relative_path

MAP_SCHEMA_VERSION = "1.0.0"
EPSILON = 1e-6


class MaterialMapError(RuntimeError):
    """Raised when registered evidence is insufficient for measured map extraction."""


class MaterialMapSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_angular_frames: int = Field(default=3, ge=2)
    preferred_angular_frames: int = Field(default=7, ge=3)
    percentile_low: float = Field(default=5.0, ge=0, le=49)
    percentile_high: float = Field(default=95.0, ge=51, le=100)
    robust_floor_percentile: float = Field(default=5.0, ge=0, le=50)
    robust_ceiling_percentile: float = Field(default=99.0, ge=50, le=100)
    clearcoat_blur_sigma: float = Field(default=18.0, ge=0)
    texture_blur_sigma: float = Field(default=4.0, ge=0.1)
    normal_strength: float = Field(default=1.6, ge=0, le=10)
    semantic_prior_strength: float = Field(default=0.35, ge=0, le=1)


class MaterialExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MAP_SCHEMA_VERSION
    run_id: str
    session_id: str
    output_directory: str = "processed/material"
    semantic_masks: dict[str, str] = Field(default_factory=dict)
    settings: MaterialMapSettings = Field(default_factory=MaterialMapSettings)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("output_directory")
    @classmethod
    def validate_output_directory(cls, value: str) -> str:
        return safe_relative_path(value)

    @field_validator("semantic_masks")
    @classmethod
    def validate_semantic_masks(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: safe_relative_path(value) for key, value in values.items()}


class MapArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str
    path: str
    blake3: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    color_space: str
    interpretation: str


class MaterialExtractionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MAP_SCHEMA_VERSION
    run_id: str
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "proposal"
    settings: MaterialMapSettings
    input_files: list[dict[str, Any]]
    artifacts: list[MapArtifact]
    statistics: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class FrameSample:
    path: str
    kind: CaptureKind
    image: np.ndarray
    angle_degrees: float | None
    direction: CaptureDirection
    blake3: str


@dataclass(frozen=True)
class SequenceMeasurement:
    frame_count: int
    luma_range: np.ndarray
    luma_variance: np.ndarray
    chroma_variance: np.ndarray
    peak_angle: np.ndarray | None
    angle_confidence: np.ndarray


@dataclass(frozen=True)
class DerivedMaterialMaps:
    albedo_bgr: np.ndarray
    foil: np.ndarray
    metallic: np.ndarray
    gloss: np.ndarray
    suppression: np.ndarray
    texture: np.ndarray
    normal_rgb: np.ndarray
    direction_rgb: np.ndarray
    confidence: np.ndarray
    raw_measurements: dict[str, np.ndarray]
    statistics: dict[str, Any]
    warnings: list[str]


def srgb_to_linear_rgb(image_bgr: np.ndarray) -> np.ndarray:
    rgb = image_bgr[..., ::-1].astype(np.float32) / 255.0
    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        np.power((rgb + 0.055) / 1.055, 2.4),
    ).astype(np.float32)


def luminance(linear_rgb: np.ndarray) -> np.ndarray:
    return (
        0.2126 * linear_rgb[..., 0]
        + 0.7152 * linear_rgb[..., 1]
        + 0.0722 * linear_rgb[..., 2]
    ).astype(np.float32)


def robust_normalize(
    values: np.ndarray,
    *,
    floor_percentile: float = 5.0,
    ceiling_percentile: float = 99.0,
) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros_like(values, dtype=np.float32)
    floor = float(np.percentile(finite, floor_percentile))
    ceiling = float(np.percentile(finite, ceiling_percentile))
    if ceiling - floor <= EPSILON:
        return np.zeros_like(values, dtype=np.float32)
    return np.clip((values.astype(np.float32) - floor) / (ceiling - floor), 0, 1)


def _linear_stack(images: list[np.ndarray]) -> np.ndarray:
    if not images:
        raise MaterialMapError("cannot measure an empty image sequence")
    shape = images[0].shape
    if any(image.shape != shape for image in images):
        raise MaterialMapError("all registered frames must have identical dimensions")
    return np.stack([srgb_to_linear_rgb(image) for image in images], axis=0)


def measure_sequence(
    images: list[np.ndarray],
    angles: list[float | None],
    settings: MaterialMapSettings,
) -> SequenceMeasurement:
    stack = _linear_stack(images)
    luma = luminance(stack)
    low = np.percentile(luma, settings.percentile_low, axis=0)
    high = np.percentile(luma, settings.percentile_high, axis=0)
    luma_range = (high - low).astype(np.float32)
    luma_variance = np.var(luma, axis=0).astype(np.float32)

    channel_sum = np.sum(stack, axis=-1, keepdims=True)
    chromaticity = stack / np.maximum(channel_sum, EPSILON)
    chroma_center = np.median(chromaticity, axis=0)
    chroma_variance = np.mean(
        np.sum(np.square(chromaticity - chroma_center), axis=-1),
        axis=0,
    ).astype(np.float32)

    peak_indices = np.argmax(luma, axis=0)
    valid_angles = len(angles) == len(images) and all(angle is not None for angle in angles)
    peak_angle: np.ndarray | None = None
    if valid_angles:
        angle_values = np.asarray([float(angle) for angle in angles], dtype=np.float32)
        peak_angle = angle_values[peak_indices]

    normalized_range = robust_normalize(
        luma_range,
        floor_percentile=settings.robust_floor_percentile,
        ceiling_percentile=settings.robust_ceiling_percentile,
    )
    sample_confidence = min(1.0, len(images) / settings.preferred_angular_frames)
    angle_confidence = (normalized_range * sample_confidence).astype(np.float32)
    if not valid_angles:
        angle_confidence *= 0.4

    return SequenceMeasurement(
        frame_count=len(images),
        luma_range=luma_range,
        luma_variance=luma_variance,
        chroma_variance=chroma_variance,
        peak_angle=peak_angle,
        angle_confidence=angle_confidence,
    )


def _zero_measurement(shape: tuple[int, int]) -> SequenceMeasurement:
    zero = np.zeros(shape, dtype=np.float32)
    return SequenceMeasurement(
        frame_count=0,
        luma_range=zero.copy(),
        luma_variance=zero.copy(),
        chroma_variance=zero.copy(),
        peak_angle=None,
        angle_confidence=zero.copy(),
    )


def _measure_optional(
    samples: list[FrameSample],
    settings: MaterialMapSettings,
    shape: tuple[int, int],
    warnings: list[str],
    label: str,
) -> SequenceMeasurement:
    if len(samples) < settings.minimum_angular_frames:
        warnings.append(
            f"{label}: need at least {settings.minimum_angular_frames} frames, "
            f"found {len(samples)}"
        )
        return _zero_measurement(shape)
    return measure_sequence(
        [sample.image for sample in samples],
        [sample.angle_degrees for sample in samples],
        settings,
    )


def _semantic_prior(
    semantic_masks: dict[str, np.ndarray],
    names: tuple[str, ...],
    shape: tuple[int, int],
) -> np.ndarray:
    prior = np.zeros(shape, dtype=np.float32)
    for name in names:
        mask = semantic_masks.get(name)
        if mask is not None:
            prior = np.maximum(prior, mask.astype(np.float32))
    return prior


def _blend_prior(
    measured: np.ndarray,
    prior: np.ndarray,
    strength: float,
) -> np.ndarray:
    if strength <= 0 or not np.any(prior):
        return measured
    promoted = np.maximum(measured, prior * np.mean(measured[prior > 0] + 0.25))
    return np.clip((1.0 - strength) * measured + strength * promoted, 0, 1)


def _normal_from_raking(
    raking: dict[CaptureDirection, FrameSample],
    shape: tuple[int, int],
    strength: float,
    warnings: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    required = (
        CaptureDirection.LEFT,
        CaptureDirection.RIGHT,
        CaptureDirection.TOP,
        CaptureDirection.BOTTOM,
    )
    if not all(direction in raking for direction in required):
        warnings.append("normal-map: four reviewed raking directions are required")
        normal = np.zeros((*shape, 3), dtype=np.float32)
        normal[..., 0] = 0.5
        normal[..., 1] = 0.5
        normal[..., 2] = 1.0
        return normal, np.zeros(shape, dtype=np.float32)

    intensities = {
        direction: luminance(srgb_to_linear_rgb(raking[direction].image))
        for direction in required
    }
    horizontal_sum = intensities[CaptureDirection.LEFT] + intensities[CaptureDirection.RIGHT]
    vertical_sum = intensities[CaptureDirection.TOP] + intensities[CaptureDirection.BOTTOM]
    nx = (
        intensities[CaptureDirection.LEFT] - intensities[CaptureDirection.RIGHT]
    ) / np.maximum(horizontal_sum, EPSILON)
    ny = (
        intensities[CaptureDirection.TOP] - intensities[CaptureDirection.BOTTOM]
    ) / np.maximum(vertical_sum, EPSILON)

    nx *= strength
    ny *= strength
    nz = np.ones(shape, dtype=np.float32)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.stack(
        [
            nx / np.maximum(norm, EPSILON),
            ny / np.maximum(norm, EPSILON),
            nz / np.maximum(norm, EPSILON),
        ],
        axis=-1,
    )
    packed = np.clip(normal * 0.5 + 0.5, 0, 1).astype(np.float32)
    confidence = robust_normalize(
        np.abs(nx) + np.abs(ny),
        floor_percentile=5,
        ceiling_percentile=99,
    )
    return packed, confidence


def _direction_map(
    tilt_x: SequenceMeasurement,
    tilt_y: SequenceMeasurement,
    activity: np.ndarray,
) -> np.ndarray:
    shape = activity.shape
    angle_x = (
        np.radians(tilt_x.peak_angle)
        if tilt_x.peak_angle is not None
        else np.zeros(shape, dtype=np.float32)
    )
    angle_y = (
        np.radians(tilt_y.peak_angle)
        if tilt_y.peak_angle is not None
        else np.zeros(shape, dtype=np.float32)
    )
    vx = np.sin(angle_x).astype(np.float32)
    vy = np.sin(angle_y).astype(np.float32)
    magnitude = np.sqrt(vx * vx + vy * vy)
    safe = np.maximum(magnitude, EPSILON)
    vx = np.where(magnitude > EPSILON, vx / safe, 1.0)
    vy = np.where(magnitude > EPSILON, vy / safe, 0.0)
    return np.stack(
        [
            np.clip(vx * 0.5 + 0.5, 0, 1),
            np.clip(vy * 0.5 + 0.5, 0, 1),
            np.clip(activity, 0, 1),
        ],
        axis=-1,
    ).astype(np.float32)


def derive_material_maps(
    *,
    albedo_bgr: np.ndarray,
    tilt_x_samples: list[FrameSample],
    tilt_y_samples: list[FrameSample],
    hard_light_samples: list[FrameSample],
    soft_light_samples: list[FrameSample],
    raking_samples: dict[CaptureDirection, FrameSample],
    semantic_masks: dict[str, np.ndarray] | None = None,
    settings: MaterialMapSettings | None = None,
) -> DerivedMaterialMaps:
    limits = settings or MaterialMapSettings()
    shape = albedo_bgr.shape[:2]
    warnings: list[str] = []
    semantic = semantic_masks or {}

    tilt_x = _measure_optional(tilt_x_samples, limits, shape, warnings, "tilt-x")
    tilt_y = _measure_optional(tilt_y_samples, limits, shape, warnings, "tilt-y")
    hard = _measure_optional(hard_light_samples, limits, shape, warnings, "light-hard")
    soft = _measure_optional(soft_light_samples, limits, shape, warnings, "light-soft")

    tilt_luma = np.maximum(tilt_x.luma_range, tilt_y.luma_range)
    tilt_chroma = np.maximum(tilt_x.chroma_variance, tilt_y.chroma_variance)
    all_luma = np.maximum(tilt_luma, hard.luma_range)

    luma_activity = robust_normalize(
        all_luma,
        floor_percentile=limits.robust_floor_percentile,
        ceiling_percentile=limits.robust_ceiling_percentile,
    )
    chroma_activity = robust_normalize(
        tilt_chroma,
        floor_percentile=limits.robust_floor_percentile,
        ceiling_percentile=limits.robust_ceiling_percentile,
    )
    foil = np.clip(chroma_activity * np.sqrt(np.maximum(luma_activity, 0)), 0, 1)
    metallic = np.clip(luma_activity * np.power(1.0 - foil, 1.35), 0, 1)

    foil_prior = _semantic_prior(
        semantic,
        ("foil-field", "manga-panel", "background"),
        shape,
    )
    metallic_prior = _semantic_prior(
        semantic,
        ("gold-linework", "metallic-ornament", "title-plate", "frame"),
        shape,
    )
    foil = _blend_prior(foil, foil_prior, limits.semantic_prior_strength)
    metallic = _blend_prior(metallic, metallic_prior, limits.semantic_prior_strength)

    soft_activity = robust_normalize(
        soft.luma_range,
        floor_percentile=limits.robust_floor_percentile,
        ceiling_percentile=limits.robust_ceiling_percentile,
    )
    gloss = cv2.GaussianBlur(
        soft_activity,
        (0, 0),
        sigmaX=limits.clearcoat_blur_sigma,
        sigmaY=limits.clearcoat_blur_sigma,
    )
    gloss = robust_normalize(gloss, floor_percentile=3, ceiling_percentile=99)

    raking_images = [sample.image for sample in raking_samples.values()]
    if len(raking_images) >= 2:
        rake_stack = _linear_stack(raking_images)
        rake_range = np.ptp(luminance(rake_stack), axis=0)
        texture_source = robust_normalize(rake_range, floor_percentile=5, ceiling_percentile=99)
    else:
        warnings.append("texture-map: using hard-light fallback because raking coverage is incomplete")
        texture_source = robust_normalize(
            hard.luma_range,
            floor_percentile=limits.robust_floor_percentile,
            ceiling_percentile=limits.robust_ceiling_percentile,
        )
    texture_low = cv2.GaussianBlur(
        texture_source,
        (0, 0),
        sigmaX=limits.texture_blur_sigma,
        sigmaY=limits.texture_blur_sigma,
    )
    texture = robust_normalize(
        np.abs(texture_source - texture_low),
        floor_percentile=10,
        ceiling_percentile=99.5,
    )

    normal_rgb, normal_confidence = _normal_from_raking(
        raking_samples,
        shape,
        limits.normal_strength,
        warnings,
    )

    albedo_linear = srgb_to_linear_rgb(albedo_bgr)
    albedo_luma = luminance(albedo_linear)
    darkness = 1.0 - robust_normalize(albedo_luma, floor_percentile=1, ceiling_percentile=99)
    total_activity = np.maximum.reduce([foil, metallic, gloss])
    black_prior = _semantic_prior(semantic, ("black-ink", "rules-text"), shape)
    stable_dark = darkness * np.clip(1.0 - total_activity, 0, 1)
    suppression = np.maximum(stable_dark, black_prior * (0.5 + 0.5 * stable_dark))
    suppression = np.clip(suppression, 0, 1).astype(np.float32)

    directional_activity = np.maximum(foil, metallic)
    direction_rgb = _direction_map(tilt_x, tilt_y, directional_activity)

    sample_confidence = min(
        1.0,
        max(tilt_x.frame_count, tilt_y.frame_count, hard.frame_count)
        / limits.preferred_angular_frames,
    )
    response_confidence = np.maximum.reduce(
        [
            tilt_x.angle_confidence,
            tilt_y.angle_confidence,
            hard.angle_confidence,
            soft.angle_confidence,
        ]
    )
    confidence = np.clip(
        sample_confidence * (0.35 + 0.65 * response_confidence)
        * (0.75 + 0.25 * normal_confidence),
        0,
        1,
    ).astype(np.float32)

    statistics: dict[str, Any] = {
        "frame_counts": {
            "tilt-x": tilt_x.frame_count,
            "tilt-y": tilt_y.frame_count,
            "light-hard": hard.frame_count,
            "light-soft": soft.frame_count,
            "rake": len(raking_samples),
        },
        "mean_channels": {
            "foil": float(np.mean(foil)),
            "metallic": float(np.mean(metallic)),
            "gloss": float(np.mean(gloss)),
            "suppression": float(np.mean(suppression)),
            "texture": float(np.mean(texture)),
            "confidence": float(np.mean(confidence)),
        },
        "semantic_priors": sorted(semantic),
    }

    raw_measurements = {
        "tilt_x_luma_range": tilt_x.luma_range,
        "tilt_x_chroma_variance": tilt_x.chroma_variance,
        "tilt_y_luma_range": tilt_y.luma_range,
        "tilt_y_chroma_variance": tilt_y.chroma_variance,
        "hard_luma_range": hard.luma_range,
        "soft_luma_range": soft.luma_range,
        "normal_confidence": normal_confidence,
    }
    if tilt_x.peak_angle is not None:
        raw_measurements["tilt_x_peak_angle"] = tilt_x.peak_angle
    if tilt_y.peak_angle is not None:
        raw_measurements["tilt_y_peak_angle"] = tilt_y.peak_angle

    return DerivedMaterialMaps(
        albedo_bgr=albedo_bgr,
        foil=foil.astype(np.float32),
        metallic=metallic.astype(np.float32),
        gloss=gloss.astype(np.float32),
        suppression=suppression,
        texture=texture.astype(np.float32),
        normal_rgb=normal_rgb,
        direction_rgb=direction_rgb,
        confidence=confidence,
        raw_measurements=raw_measurements,
        statistics=statistics,
        warnings=warnings,
    )


def _registered_path(session_root: Path, record_path: str) -> Path:
    return session_root / "processed" / "registered" / f"{Path(record_path).stem}.png"


def load_registered_samples(
    session_root: Path,
    session: CaptureSession,
) -> list[FrameSample]:
    samples: list[FrameSample] = []
    for record in session.files:
        if not record.media_type.startswith("image/"):
            continue
        path = _registered_path(session_root, record.path)
        if not path.is_file():
            continue
        samples.append(
            FrameSample(
                path=path.relative_to(session_root).as_posix(),
                kind=record.kind,
                image=read_image(path),
                angle_degrees=record.angle_degrees,
                direction=record.direction,
                blake3=record.blake3,
            )
        )
    return samples


def _load_semantic_masks(
    session_root: Path,
    request: MaterialExtractionRequest,
    shape: tuple[int, int],
) -> dict[str, np.ndarray]:
    masks: dict[str, np.ndarray] = {}
    for name, relative_path in request.semantic_masks.items():
        masks[name] = read_binary_mask(
            session_root / relative_path,
            expected_shape=shape,
        ).astype(np.float32)
    return masks


def _write_png(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if values.ndim == 2:
        encoded_values = np.round(np.clip(values, 0, 1) * 255).astype(np.uint8)
    elif values.ndim == 3 and values.shape[-1] == 3:
        encoded_values = np.round(np.clip(values, 0, 1) * 255).astype(np.uint8)[..., ::-1]
    else:
        raise MaterialMapError(f"unsupported PNG map dimensions: {values.shape}")
    success, encoded = cv2.imencode(".png", encoded_values)
    if not success:
        raise MaterialMapError(f"unable to encode map: {path}")
    encoded.tofile(path)


def _artifact(
    session_root: Path,
    path: Path,
    *,
    channel: str,
    width: int,
    height: int,
    color_space: str,
    interpretation: str,
    media_type: str = "image/png",
) -> MapArtifact:
    return MapArtifact(
        channel=channel,
        path=path.relative_to(session_root).as_posix(),
        blake3=file_digest(path),
        media_type=media_type,
        width=width,
        height=height,
        color_space=color_space,
        interpretation=interpretation,
    )


def extract_material_maps(
    session_root: Path,
    request: MaterialExtractionRequest,
) -> MaterialExtractionManifest:
    session = load_manifest(session_root)
    if request.session_id != session.session_id:
        raise MaterialMapError(
            f"request session_id {request.session_id} does not match {session.session_id}"
        )

    samples = load_registered_samples(session_root, session)
    albedo_samples = [sample for sample in samples if sample.kind is CaptureKind.ALBEDO]
    if not albedo_samples:
        raise MaterialMapError("registered albedo frame is required")
    albedo = albedo_samples[0].image
    shape = albedo.shape[:2]

    def angular(kind: CaptureKind) -> list[FrameSample]:
        selected = [sample for sample in samples if sample.kind is kind]
        return sorted(
            selected,
            key=lambda sample: (
                sample.angle_degrees is None,
                sample.angle_degrees if sample.angle_degrees is not None else 0,
                sample.path,
            ),
        )

    raking: dict[CaptureDirection, FrameSample] = {}
    for sample in samples:
        if sample.kind is CaptureKind.RAKE and sample.direction is not CaptureDirection.NONE:
            raking.setdefault(sample.direction, sample)

    semantic_masks = _load_semantic_masks(session_root, request, shape)
    derived = derive_material_maps(
        albedo_bgr=albedo,
        tilt_x_samples=angular(CaptureKind.TILT_X),
        tilt_y_samples=angular(CaptureKind.TILT_Y),
        hard_light_samples=angular(CaptureKind.LIGHT_HARD),
        soft_light_samples=angular(CaptureKind.LIGHT_SOFT),
        raking_samples=raking,
        semantic_masks=semantic_masks,
        settings=request.settings,
    )

    run_root = session_root / request.output_directory / request.run_id
    run_root.mkdir(parents=True, exist_ok=True)
    height, width = shape
    artifacts: list[MapArtifact] = []

    albedo_path = run_root / "albedo.png"
    success, encoded_albedo = cv2.imencode(".png", derived.albedo_bgr)
    if not success:
        raise MaterialMapError("unable to encode albedo")
    encoded_albedo.tofile(albedo_path)
    artifacts.append(
        _artifact(
            session_root,
            albedo_path,
            channel="albedo",
            width=width,
            height=height,
            color_space="sRGB",
            interpretation="registered diffuse reference; not automatically public",
        )
    )

    grayscale_channels = {
        "foil-mask": (derived.foil, "angle-dependent chromatic activity proposal"),
        "metallic-mask": (derived.metallic, "brightness-varying low-chroma metallic proposal"),
        "gloss-mask": (derived.gloss, "broad soft-light clearcoat response proposal"),
        "suppression-mask": (derived.suppression, "stable dark-ink diffraction suppression proposal"),
        "texture-mask": (derived.texture, "high-frequency raking/hard-light response proposal"),
        "confidence-map": (derived.confidence, "measurement confidence and sampling support"),
    }
    for channel, (values, interpretation) in grayscale_channels.items():
        path = run_root / f"{channel}.png"
        _write_png(path, values)
        artifacts.append(
            _artifact(
                session_root,
                path,
                channel=channel,
                width=width,
                height=height,
                color_space="linear scalar encoded as 8-bit grayscale",
                interpretation=interpretation,
            )
        )

    for channel, values, interpretation in (
        (
            "normal-map",
            derived.normal_rgb,
            "tangent-style normal proposal estimated from opposing raking lights",
        ),
        (
            "direction-map",
            derived.direction_rgb,
            "RG directional vector with B angle-dependent activity confidence",
        ),
    ):
        path = run_root / f"{channel}.png"
        _write_png(path, values)
        artifacts.append(
            _artifact(
                session_root,
                path,
                channel=channel,
                width=width,
                height=height,
                color_space="linear RGB data",
                interpretation=interpretation,
            )
        )

    raw_path = run_root / "raw-measurements.npz"
    np.savez_compressed(
        raw_path,
        **{
            key: np.asarray(value, dtype=np.float16)
            for key, value in derived.raw_measurements.items()
        },
    )
    artifacts.append(
        _artifact(
            session_root,
            raw_path,
            channel="raw-measurements",
            width=width,
            height=height,
            color_space="linear float16 arrays",
            interpretation="unregularized measured sequence features",
            media_type="application/x-npz",
        )
    )

    input_files = [
        {
            "path": sample.path,
            "kind": sample.kind.value,
            "angle_degrees": sample.angle_degrees,
            "direction": sample.direction.value,
            "source_blake3": sample.blake3,
            "registered_blake3": file_digest(session_root / sample.path),
        }
        for sample in samples
    ]
    manifest = MaterialExtractionManifest(
        run_id=request.run_id,
        session_id=request.session_id,
        settings=request.settings,
        input_files=input_files,
        artifacts=artifacts,
        statistics=derived.statistics,
        warnings=derived.warnings,
    )
    manifest_path = run_root / "material-extraction.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2, exclude_none=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_extraction_request(path: Path) -> MaterialExtractionRequest:
    return MaterialExtractionRequest.model_validate_json(path.read_text(encoding="utf-8"))


def write_extraction_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(MaterialExtractionRequest.model_json_schema(), indent=2) + "\n",
        encoding="utf-8",
    )
