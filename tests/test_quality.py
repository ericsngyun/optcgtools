from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from optcg_material.quality import (
    FrameQuality,
    QualityThresholds,
    apply_group_exposure_gate,
    evaluate_frame,
)


def write_image(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(".png", image)
    assert success
    encoded.tofile(path)


def detailed_frame(value: int = 128) -> np.ndarray:
    image = np.full((1800, 1300, 3), value, dtype=np.uint8)
    for y in range(50, 1750, 30):
        cv2.line(image, (40, y), (1260, y), (255 - value, value // 2, 80), 3)
    cv2.circle(image, (650, 900), 350, (30, 220, 120), 15)
    return image


def test_sharp_frame_passes(tmp_path: Path) -> None:
    path = tmp_path / "sharp.png"
    write_image(path, detailed_frame())
    report = evaluate_frame(path)
    assert report.accepted


def test_blurred_frame_fails(tmp_path: Path) -> None:
    path = tmp_path / "blurred.png"
    image = cv2.GaussianBlur(detailed_frame(), (81, 81), 25)
    write_image(path, image)
    report = evaluate_frame(
        path,
        QualityThresholds(min_laplacian_variance=100.0),
    )
    assert not report.accepted
    assert any("blur gate failed" in reason for reason in report.reasons)


def test_clipped_frame_fails(tmp_path: Path) -> None:
    path = tmp_path / "clipped.png"
    image = np.full((1800, 1300, 3), 255, dtype=np.uint8)
    write_image(path, image)
    report = evaluate_frame(path)
    assert not report.accepted
    assert any("bright clipping" in reason for reason in report.reasons)


def report(path: str, luminance: float) -> FrameQuality:
    return FrameQuality(
        path=path,
        decodable=True,
        width=1300,
        height=1800,
        laplacian_variance=200,
        mean_luminance=luminance,
        dark_clip_ratio=0,
        bright_clip_ratio=0,
        channel_clip_ratio=0,
        accepted=True,
    )


def test_group_exposure_drift_fails_outlier() -> None:
    groups = {
        "tilt-x": [
            report("a.png", 0.48),
            report("b.png", 0.50),
            report("c.png", 0.72),
        ]
    }
    diagnostics = apply_group_exposure_gate(groups, max_deviation=0.08)
    assert not groups["tilt-x"][2].accepted
    assert any("exposure drift" in reason for reason in groups["tilt-x"][2].reasons)
    assert diagnostics[0].outlier_count == 1
