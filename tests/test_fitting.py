from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from optcg_material.fitting import (
    FitFrame,
    FitRegion,
    FitSequenceRequest,
    evaluate_fit_sequence,
)

HEIGHT = 180
WIDTH = 130


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    assert success
    encoded.tofile(path)


def write_mask(path: Path, mask: np.ndarray) -> None:
    write_image(path, mask.astype(np.uint8) * 255)


def reference_frame(shift: int = 0, hue: tuple[int, int, int] = (30, 190, 245)) -> np.ndarray:
    image = np.full((HEIGHT, WIDTH, 3), 38, dtype=np.uint8)
    cv2.rectangle(image, (8, 8), (WIDTH - 9, HEIGHT - 9), (80, 92, 115), -1)
    cv2.rectangle(image, (12, 112), (WIDTH - 13, 164), (13, 13, 14), -1)
    center = (46 + shift, 64)
    cv2.circle(image, center, 24, hue, -1)
    cv2.circle(image, center, 9, (250, 250, 250), -1)
    return image


def build_request(candidate_names: list[str]) -> FitSequenceRequest:
    frames = []
    for index, candidate in enumerate(candidate_names):
        frames.append(
            FitFrame(
                frame_id=f"frame-{index:02d}",
                reference_path=f"reference/frame-{index:02d}.png",
                candidate_path=f"candidate/{candidate}",
                angle_x_degrees=float(index * 10),
                regions=[
                    FitRegion(
                        name="foil-field",
                        mask_path="masks/foil.png",
                        weight=2.0,
                    )
                ],
            )
        )
    return FitSequenceRequest(
        run_id="synthetic-fit-001",
        session_id="synthetic-session-001",
        output_path="review/fit-report.json",
        frames=frames,
    )


def prepare_root(tmp_path: Path) -> None:
    mask = np.zeros((HEIGHT, WIDTH), dtype=bool)
    mask[30:98, 18:88] = True
    write_mask(tmp_path / "masks" / "foil.png", mask)
    for index in range(3):
        write_image(tmp_path / "reference" / f"frame-{index:02d}.png", reference_frame(index * 6))


def test_identical_sequence_has_near_zero_loss(tmp_path: Path) -> None:
    prepare_root(tmp_path)
    candidates = []
    for index in range(3):
        name = f"identical-{index:02d}.png"
        write_image(tmp_path / "candidate" / name, reference_frame(index * 6))
        candidates.append(name)

    report = evaluate_fit_sequence(tmp_path, build_request(candidates))
    assert report.aggregate_loss == pytest.approx(0, abs=1e-7)
    assert report.temporal_delta_error == pytest.approx(0, abs=1e-7)
    assert (tmp_path / "review" / "fit-report.json").is_file()


def test_wrong_highlight_trajectory_increases_loss(tmp_path: Path) -> None:
    prepare_root(tmp_path)
    candidates = []
    for index in range(3):
        name = f"wrong-position-{index:02d}.png"
        write_image(tmp_path / "candidate" / name, reference_frame(30 - index * 3))
        candidates.append(name)

    report = evaluate_fit_sequence(tmp_path, build_request(candidates))
    assert report.mean_highlight_centroid_error > 0.05
    assert report.temporal_delta_error > 0.01
    assert report.aggregate_loss > 0.08


def test_wrong_hue_is_detected(tmp_path: Path) -> None:
    prepare_root(tmp_path)
    candidates = []
    for index in range(3):
        name = f"wrong-hue-{index:02d}.png"
        write_image(
            tmp_path / "candidate" / name,
            reference_frame(index * 6, hue=(220, 40, 40)),
        )
        candidates.append(name)

    report = evaluate_fit_sequence(tmp_path, build_request(candidates))
    assert report.mean_hue_error > 0.1
    assert report.aggregate_loss > 0.04


def test_dimension_mismatch_fails_closed(tmp_path: Path) -> None:
    prepare_root(tmp_path)
    write_image(
        tmp_path / "candidate" / "small.png",
        cv2.resize(reference_frame(), (64, 90)),
    )
    request = build_request(["small.png"])
    with pytest.raises(Exception, match="dimensions differ"):
        evaluate_fit_sequence(tmp_path, request)
