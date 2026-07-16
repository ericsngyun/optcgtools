from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from optcg_material.candidate import CandidateError, canonicalize_render, parse_quad
from optcg_material.geometry import CANONICAL_HEIGHT, CANONICAL_WIDTH


def write_image(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(".png", image)
    assert success
    encoded.tofile(path)


def synthetic_card() -> np.ndarray:
    card = np.full((1000, 718, 3), 218, dtype=np.uint8)
    cv2.rectangle(card, (4, 4), (713, 995), (15, 15, 15), 10)
    cv2.rectangle(card, (48, 80), (670, 680), (72, 132, 205), -1)
    cv2.circle(card, (359, 360), 165, (220, 185, 52), 13)
    cv2.putText(
        card,
        "CANONICAL",
        (75, 790),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.25,
        (20, 20, 20),
        3,
        cv2.LINE_AA,
    )
    return card


def test_canonicalize_renderer_perspective(tmp_path: Path) -> None:
    card = synthetic_card()
    canvas = np.full((900, 900, 3), 18, dtype=np.uint8)
    source = np.float32([[0, 0], [717, 0], [717, 999], [0, 999]])
    quad = np.float32([[205, 75], [715, 145], [670, 845], [160, 785]])
    transform = cv2.getPerspectiveTransform(source, quad)
    projected = cv2.warpPerspective(card, transform, (900, 900))
    mask = cv2.warpPerspective(
        np.full(card.shape[:2], 255, dtype=np.uint8),
        transform,
        (900, 900),
    )
    canvas[mask > 0] = projected[mask > 0]

    source_path = tmp_path / "perspective.png"
    output_path = tmp_path / "canonical.png"
    write_image(source_path, canvas)
    canonical = canonicalize_render(source_path, output_path, quad.tolist())

    expected = cv2.resize(card, (CANONICAL_WIDTH, CANONICAL_HEIGHT), interpolation=cv2.INTER_CUBIC)
    error = float(np.mean(cv2.absdiff(expected, canonical)))
    assert canonical.shape[:2] == (CANONICAL_HEIGHT, CANONICAL_WIDTH)
    assert output_path.is_file()
    assert error < 8.0


def test_parse_quad_rejects_invalid_shapes() -> None:
    with pytest.raises(CandidateError, match="four"):
        parse_quad("[[0, 0], [1, 0], [1, 1]]")


def test_canonicalize_rejects_out_of_bounds_quad(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    write_image(image_path, np.full((200, 200, 3), 80, dtype=np.uint8))
    with pytest.raises(CandidateError, match="outside"):
        canonicalize_render(
            image_path,
            tmp_path / "output.png",
            [[-50, 0], [150, 0], [150, 150], [0, 150]],
        )
