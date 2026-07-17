from __future__ import annotations

import numpy as np

from optcg_material.material_maps import (
    FrameSample,
    MaterialMapSettings,
    derive_material_maps,
    measure_sequence,
)
from optcg_material.models import CaptureDirection, CaptureKind

HEIGHT = 128
WIDTH = 96
ANGLES = [-30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0]


def base_albedo() -> np.ndarray:
    rgb = np.full((HEIGHT, WIDTH, 3), 0.45, dtype=np.float32)
    rgb[:, :32] = np.asarray([0.28, 0.30, 0.34], dtype=np.float32)
    rgb[:, 40:72] = np.asarray([0.56, 0.46, 0.24], dtype=np.float32)
    rgb[94:124, 8:88] = np.asarray([0.015, 0.015, 0.015], dtype=np.float32)
    return np.round(rgb[..., ::-1] * 255).astype(np.uint8)


def angular_frame(angle: float) -> np.ndarray:
    rgb = base_albedo()[..., ::-1].astype(np.float32) / 255.0
    phase = np.radians(angle + 30.0)
    foil_color = np.asarray(
        [
            0.45 + 0.35 * np.sin(phase),
            0.45 + 0.35 * np.sin(phase + 2.1),
            0.45 + 0.35 * np.sin(phase + 4.2),
        ],
        dtype=np.float32,
    )
    rgb[10:88, 4:32] = np.clip(foil_color, 0.05, 0.95)

    metallic_value = float(np.clip(0.25 + ((angle + 30.0) / 60.0) * 0.65, 0, 1))
    rgb[10:88, 44:72] = metallic_value
    rgb[94:124, 8:88] = 0.015
    return np.round(np.clip(rgb, 0, 1)[..., ::-1] * 255).astype(np.uint8)


def soft_light_frame(angle: float) -> np.ndarray:
    image = base_albedo().astype(np.float32) / 255.0
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    center_x = 20.0 + ((angle + 30.0) / 60.0) * 56.0
    spot = np.exp(-((xx - center_x) ** 2 + (yy - 58.0) ** 2) / (2 * 21.0**2))
    image += spot[..., None] * 0.32
    return np.round(np.clip(image, 0, 1) * 255).astype(np.uint8)


def raking_frame(direction: CaptureDirection) -> np.ndarray:
    albedo = base_albedo().astype(np.float32) / 255.0
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    relief_x = np.sin(xx / 3.0) * 0.13
    relief_y = np.cos(yy / 4.0) * 0.13
    if direction is CaptureDirection.LEFT:
        response = relief_x
    elif direction is CaptureDirection.RIGHT:
        response = -relief_x
    elif direction is CaptureDirection.TOP:
        response = relief_y
    else:
        response = -relief_y
    albedo += response[..., None]
    return np.round(np.clip(albedo, 0, 1) * 255).astype(np.uint8)


def sample(
    image: np.ndarray,
    kind: CaptureKind,
    *,
    angle: float | None = None,
    direction: CaptureDirection = CaptureDirection.NONE,
    index: int = 0,
) -> FrameSample:
    return FrameSample(
        path=f"processed/registered/{kind.value}-{index}.png",
        kind=kind,
        image=image,
        angle_degrees=angle,
        direction=direction,
        blake3=f"{index + 1:064x}"[-64:],
    )


def test_sequence_measurement_tracks_peak_angles() -> None:
    images = [angular_frame(angle) for angle in ANGLES]
    measurement = measure_sequence(images, ANGLES, MaterialMapSettings())
    assert measurement.frame_count == len(ANGLES)
    assert measurement.peak_angle is not None
    assert measurement.luma_range.shape == (HEIGHT, WIDTH)
    assert float(np.mean(measurement.angle_confidence[10:88, 4:72])) > 0.1


def test_material_channels_separate_foil_metal_gloss_and_ink() -> None:
    tilt_x = [
        sample(angular_frame(angle), CaptureKind.TILT_X, angle=angle, index=index)
        for index, angle in enumerate(ANGLES)
    ]
    tilt_y = [
        sample(angular_frame(-angle), CaptureKind.TILT_Y, angle=angle, index=index)
        for index, angle in enumerate(ANGLES)
    ]
    hard = [
        sample(angular_frame(angle), CaptureKind.LIGHT_HARD, angle=angle, index=index)
        for index, angle in enumerate(ANGLES)
    ]
    soft = [
        sample(soft_light_frame(angle), CaptureKind.LIGHT_SOFT, angle=angle, index=index)
        for index, angle in enumerate(ANGLES)
    ]
    raking = {
        direction: sample(
            raking_frame(direction),
            CaptureKind.RAKE,
            direction=direction,
            index=index,
        )
        for index, direction in enumerate(
            (
                CaptureDirection.LEFT,
                CaptureDirection.RIGHT,
                CaptureDirection.TOP,
                CaptureDirection.BOTTOM,
            )
        )
    }

    maps = derive_material_maps(
        albedo_bgr=base_albedo(),
        tilt_x_samples=tilt_x,
        tilt_y_samples=tilt_y,
        hard_light_samples=hard,
        soft_light_samples=soft,
        raking_samples=raking,
    )

    foil_region = float(np.mean(maps.foil[10:88, 4:32]))
    metal_region = float(np.mean(maps.metallic[10:88, 44:72]))
    foil_in_metal = float(np.mean(maps.foil[10:88, 44:72]))
    metal_in_foil = float(np.mean(maps.metallic[10:88, 4:32]))
    dark_suppression = float(np.mean(maps.suppression[94:124, 8:88]))
    active_suppression = float(np.mean(maps.suppression[10:88, 4:72]))

    assert foil_region > foil_in_metal
    assert metal_region > metal_in_foil
    assert float(np.max(maps.gloss)) > 0.5
    assert dark_suppression > active_suppression
    assert float(np.std(maps.normal_rgb[..., 0])) > 0.01
    assert maps.direction_rgb.shape == (HEIGHT, WIDTH, 3)
    assert float(np.mean(maps.confidence)) > 0.2


def test_semantic_priors_remain_proposals_not_hard_overrides() -> None:
    foil_prior = np.zeros((HEIGHT, WIDTH), dtype=np.float32)
    foil_prior[20:60, 74:92] = 1.0
    maps = derive_material_maps(
        albedo_bgr=base_albedo(),
        tilt_x_samples=[
            sample(angular_frame(angle), CaptureKind.TILT_X, angle=angle, index=index)
            for index, angle in enumerate(ANGLES)
        ],
        tilt_y_samples=[],
        hard_light_samples=[],
        soft_light_samples=[],
        raking_samples={},
        semantic_masks={"foil-field": foil_prior},
        settings=MaterialMapSettings(semantic_prior_strength=0.35),
    )
    prior_region = maps.foil[20:60, 74:92]
    assert float(np.mean(prior_region)) > 0
    assert float(np.mean(prior_region)) < 1
    assert maps.warnings
