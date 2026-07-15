from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class QualityThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_width: int = Field(default=1200, ge=320)
    min_height: int = Field(default=1600, ge=480)
    min_laplacian_variance: float = Field(default=70.0, ge=0)
    max_dark_clip_ratio: float = Field(default=0.08, ge=0, le=1)
    max_bright_clip_ratio: float = Field(default=0.03, ge=0, le=1)
    min_mean_luminance: float = Field(default=0.08, ge=0, le=1)
    max_mean_luminance: float = Field(default=0.92, ge=0, le=1)
    max_channel_clip_ratio: float = Field(default=0.06, ge=0, le=1)


class FrameQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    decodable: bool
    width: int | None = None
    height: int | None = None
    laplacian_variance: float | None = None
    mean_luminance: float | None = None
    dark_clip_ratio: float | None = None
    bright_clip_ratio: float | None = None
    channel_clip_ratio: float | None = None
    accepted: bool
    reasons: list[str] = Field(default_factory=list)


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"unable to decode image: {path}")
    return image


def evaluate_frame(
    path: Path,
    thresholds: QualityThresholds | None = None,
) -> FrameQuality:
    limits = thresholds or QualityThresholds()
    try:
        image = read_image(path)
    except ValueError as exc:
        return FrameQuality(path=str(path), decodable=False, accepted=False, reasons=[str(exc)])

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    normalized = gray.astype(np.float32) / 255.0

    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_luminance = float(normalized.mean())
    dark_clip_ratio = float(np.mean(normalized <= (4.0 / 255.0)))
    bright_clip_ratio = float(np.mean(normalized >= (251.0 / 255.0)))
    channel_clip_ratio = float(
        np.mean(np.any((image <= 4) | (image >= 251), axis=2))
    )

    reasons: list[str] = []
    if width < limits.min_width or height < limits.min_height:
        reasons.append(
            f"resolution below {limits.min_width}x{limits.min_height}: {width}x{height}"
        )
    if laplacian_variance < limits.min_laplacian_variance:
        reasons.append(
            "blur gate failed: "
            f"{laplacian_variance:.2f} < {limits.min_laplacian_variance:.2f}"
        )
    if dark_clip_ratio > limits.max_dark_clip_ratio:
        reasons.append(
            f"dark clipping too high: {dark_clip_ratio:.4f} > {limits.max_dark_clip_ratio:.4f}"
        )
    if bright_clip_ratio > limits.max_bright_clip_ratio:
        reasons.append(
            "bright clipping too high: "
            f"{bright_clip_ratio:.4f} > {limits.max_bright_clip_ratio:.4f}"
        )
    if not limits.min_mean_luminance <= mean_luminance <= limits.max_mean_luminance:
        reasons.append(
            "mean luminance outside range: "
            f"{mean_luminance:.4f} not in "
            f"[{limits.min_mean_luminance:.4f}, {limits.max_mean_luminance:.4f}]"
        )
    if channel_clip_ratio > limits.max_channel_clip_ratio:
        reasons.append(
            "channel clipping too high: "
            f"{channel_clip_ratio:.4f} > {limits.max_channel_clip_ratio:.4f}"
        )

    return FrameQuality(
        path=str(path),
        decodable=True,
        width=width,
        height=height,
        laplacian_variance=laplacian_variance,
        mean_luminance=mean_luminance,
        dark_clip_ratio=dark_clip_ratio,
        bright_clip_ratio=bright_clip_ratio,
        channel_clip_ratio=channel_clip_ratio,
        accepted=not reasons,
        reasons=reasons,
    )
