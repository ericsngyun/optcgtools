from __future__ import annotations

import cv2
import numpy as np
import pytest

from optcg_material.geometry import (
    CANONICAL_HEIGHT,
    CANONICAL_WIDTH,
    GeometryError,
    detect_card_quad,
    register_residual,
    warp_card,
)


def synthetic_card(width: int = 718, height: int = 1000) -> np.ndarray:
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


def perspective_scene() -> np.ndarray:
    card = synthetic_card()
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


def test_detect_and_rectify_card() -> None:
    scene = perspective_scene()
    candidate = detect_card_quad(scene)
    rectified, _ = warp_card(scene, candidate.points)

    assert candidate.score > 0.56
    assert rectified.shape[:2] == (CANONICAL_HEIGHT, CANONICAL_WIDTH)
    assert float(rectified.mean()) > 50


def test_blank_scene_is_rejected() -> None:
    blank = np.full((1800, 1400, 3), 96, dtype=np.uint8)
    with pytest.raises(GeometryError):
        detect_card_quad(blank)


def test_severely_occluded_card_is_rejected() -> None:
    scene = perspective_scene()
    cv2.rectangle(scene, (0, 0), (1250, 2400), (25, 25, 25), -1)
    with pytest.raises(GeometryError):
        detect_card_quad(scene)


def test_residual_registration_reduces_alignment_error() -> None:
    reference = cv2.resize(
        synthetic_card(),
        (CANONICAL_WIDTH, CANONICAL_HEIGHT),
        interpolation=cv2.INTER_CUBIC,
    )
    transform = np.float32([[1.0, 0.006, 6.0], [-0.004, 1.0, -8.0], [0.0, 0.0, 1.0]])
    moving = cv2.warpPerspective(
        reference,
        transform,
        (CANONICAL_WIDTH, CANONICAL_HEIGHT),
        borderMode=cv2.BORDER_REFLECT,
    )
    before = float(np.mean(cv2.absdiff(reference, moving)))
    result = register_residual(moving, reference)
    after = float(np.mean(cv2.absdiff(reference, result.image)))

    assert result.inliers >= 14
    assert result.reprojection_error < 2.5
    assert after < before * 0.55
