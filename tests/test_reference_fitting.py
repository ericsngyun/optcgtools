from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from optcg_material.material_maps import luminance, srgb_to_linear_rgb
from optcg_material.reference_fitting import (
    FORBIDDEN_CLAIM_PHRASES,
    FitPolicy,
    Observation,
    ObservationFrame,
    ObservationSetManifest,
    ReferenceFitOptions,
    ReferenceFitOutcome,
    ReferenceMaterialParams,
    fit_reference_set,
    linear_rgb_to_srgb_bgr,
    render_planar_candidate,
    write_linear_srgb_png,
)
from optcg_material.reference_fitting_cli import app
from optcg_material.semantic import file_digest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "docs" / "agent-ops" / "reference-fitting-report.schema.json"

WIDTH = 110
HEIGHT = 150
FIXED_TIME = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
GROUND_TRUTH = ReferenceMaterialParams(specular_strength=0.65, roughness=0.35, metallic=0.7)
SEQUENCE_SOURCE_ID = "seq-video-01"

runner = CliRunner()


def albedo_bgr() -> np.ndarray:
    image = np.full((HEIGHT, WIDTH, 3), 52, dtype=np.uint8)
    cv2.rectangle(image, (6, 6), (WIDTH - 7, HEIGHT - 7), (96, 104, 128), -1)
    cv2.rectangle(image, (10, 100), (WIDTH - 11, 140), (20, 20, 24), -1)
    cv2.circle(image, (40, 52), 20, (30, 180, 240), -1)
    cv2.circle(image, (78, 60), 12, (200, 120, 60), -1)
    return image


def wrong_albedo_bgr(kind: str) -> np.ndarray:
    base = albedo_bgr()
    if kind == "inverted":
        return (255 - base).astype(np.uint8)
    rolled = base[..., [1, 2, 0]]
    return rolled.astype(np.uint8)


def write_bgr(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    assert success
    encoded.tofile(path)


def synthesize_source(
    root: Path,
    source_id: str,
    frame_specs: list[dict[str, float]],
    albedo_linear: np.ndarray,
    *,
    media_form: str = "still",
    material: ReferenceMaterialParams = GROUND_TRUTH,
    interference: bool = False,
) -> Observation:
    frames: list[ObservationFrame] = []
    for index, spec in enumerate(frame_specs):
        frame_id = f"frame-{index:02d}"
        render = render_planar_candidate(
            albedo_linear,
            material,
            azimuth_deg=spec["azimuth"],
            elevation_deg=spec["elevation"],
            glare_x=spec["glare_x"],
            glare_y=spec["glare_y"],
            hardness=spec["hardness"],
            exposure=spec["exposure"],
        )
        image_path = f"obs/{source_id}-{frame_id}.png"
        write_linear_srgb_png(root / image_path, render)
        mask_path: str | None = None
        if interference:
            mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
            mask[8:28, 70:104] = 255
            mask_path = f"obs/{source_id}-{frame_id}-interference.png"
            write_bgr(root / mask_path, mask)
        frames.append(
            ObservationFrame(
                frame_id=frame_id,
                image_path=image_path,
                interference_mask_path=mask_path,
            )
        )
    return Observation(source_id=source_id, media_form=media_form, frames=frames)  # type: ignore[arg-type]


def build_coherent_root(root: Path) -> ObservationSetManifest:
    albedo_image = albedo_bgr()
    write_bgr(root / "albedo.png", albedo_image)
    albedo_linear = srgb_to_linear_rgb(albedo_image)
    observations = [
        synthesize_source(
            root,
            "still-shop-01",
            [
                {
                    "azimuth": 35.0,
                    "elevation": 55.0,
                    "glare_x": 0.62,
                    "glare_y": 0.38,
                    "hardness": 2.5,
                    "exposure": 1.0,
                }
            ],
            albedo_linear,
        ),
        synthesize_source(
            root,
            "still-listing-02",
            [
                {
                    "azimuth": 150.0,
                    "elevation": 40.0,
                    "glare_x": 0.35,
                    "glare_y": 0.60,
                    "hardness": 2.0,
                    "exposure": 0.85,
                }
            ],
            albedo_linear,
            interference=True,
        ),
        synthesize_source(
            root,
            "still-auction-03",
            [
                {
                    "azimuth": 250.0,
                    "elevation": 65.0,
                    "glare_x": 0.42,
                    "glare_y": 0.42,
                    "hardness": 3.0,
                    "exposure": 1.2,
                }
            ],
            albedo_linear,
        ),
        synthesize_source(
            root,
            SEQUENCE_SOURCE_ID,
            [
                {
                    "azimuth": 0.0,
                    "elevation": 50.0,
                    "glare_x": 0.30,
                    "glare_y": 0.45,
                    "hardness": 2.5,
                    "exposure": 1.0,
                },
                {
                    "azimuth": 0.0,
                    "elevation": 50.0,
                    "glare_x": 0.50,
                    "glare_y": 0.45,
                    "hardness": 2.5,
                    "exposure": 1.0,
                },
                {
                    "azimuth": 0.0,
                    "elevation": 50.0,
                    "glare_x": 0.70,
                    "glare_y": 0.45,
                    "hardness": 2.5,
                    "exposure": 1.0,
                },
            ],
            albedo_linear,
            media_form="sequence",
        ),
    ]
    manifest = ObservationSetManifest(
        run_id="reference-fit-coherent-001",
        bundle_id="op01-001-test-bundle",
        albedo_path="albedo.png",
        observations=observations,
    )
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def build_overfit_root(root: Path) -> ObservationSetManifest:
    albedo_image = albedo_bgr()
    write_bgr(root / "albedo.png", albedo_image)
    albedo_linear = srgb_to_linear_rgb(albedo_image)
    inverted_linear = srgb_to_linear_rgb(wrong_albedo_bgr("inverted"))
    rolled_linear = srgb_to_linear_rgb(wrong_albedo_bgr("rolled"))
    observations = [
        synthesize_source(
            root,
            "good-a",
            [
                {
                    "azimuth": 40.0,
                    "elevation": 55.0,
                    "glare_x": 0.60,
                    "glare_y": 0.40,
                    "hardness": 2.5,
                    "exposure": 1.0,
                }
            ],
            albedo_linear,
        ),
        synthesize_source(
            root,
            "bad-b",
            [
                {
                    "azimuth": 120.0,
                    "elevation": 45.0,
                    "glare_x": 0.40,
                    "glare_y": 0.55,
                    "hardness": 2.0,
                    "exposure": 1.0,
                }
            ],
            inverted_linear,
        ),
        synthesize_source(
            root,
            "bad-c",
            [
                {
                    "azimuth": 260.0,
                    "elevation": 60.0,
                    "glare_x": 0.50,
                    "glare_y": 0.35,
                    "hardness": 3.0,
                    "exposure": 1.1,
                }
            ],
            rolled_linear,
        ),
    ]
    manifest = ObservationSetManifest(
        run_id="reference-fit-overfit-001",
        bundle_id="op01-001-test-bundle",
        albedo_path="albedo.png",
        observations=observations,
    )
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


@pytest.fixture(scope="module")
def coherent_case(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, ObservationSetManifest]:
    root = tmp_path_factory.mktemp("coherent-root")
    return root, build_coherent_root(root)


@pytest.fixture(scope="module")
def coherent_outcome(
    coherent_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> ReferenceFitOutcome:
    root, manifest = coherent_case
    output = tmp_path_factory.mktemp("coherent-out")
    return fit_reference_set(root, manifest, output, generated_at=FIXED_TIME)


@pytest.fixture(scope="module")
def overfit_case(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, ObservationSetManifest]:
    root = tmp_path_factory.mktemp("overfit-root")
    return root, build_overfit_root(root)


@pytest.fixture(scope="module")
def overfit_outcome(
    overfit_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> ReferenceFitOutcome:
    root, manifest = overfit_case
    output = tmp_path_factory.mktemp("overfit-out")
    return fit_reference_set(root, manifest, output, generated_at=FIXED_TIME)


def test_joint_fit_recovers_shared_material(coherent_outcome: ReferenceFitOutcome) -> None:
    material = coherent_outcome.material
    assert coherent_outcome.accepted
    assert coherent_outcome.rejection_reasons == ()
    assert material.specular_strength == pytest.approx(GROUND_TRUTH.specular_strength, abs=0.15)
    assert material.roughness == pytest.approx(GROUND_TRUTH.roughness, abs=0.15)
    assert material.metallic == pytest.approx(GROUND_TRUTH.metallic, abs=0.3)
    assert coherent_outcome.report.aggregate_loss < 0.06
    assert not coherent_outcome.report.single_reference_overfit_flag
    assert coherent_outcome.report.privileged_reference_ids == []


def test_exposure_error_stays_in_nuisance_not_material(
    coherent_outcome: ReferenceFitOutcome,
) -> None:
    """Sources were synthesized at exposures 1.0 / 0.85 / 1.2; the fitted exposure
    scales must track them (material has no gain parameter to absorb this)."""
    by_source = {fit.source_id: fit for fit in coherent_outcome.report.per_source}
    expected = {"still-shop-01": 1.0, "still-listing-02": 0.85, "still-auction-03": 1.2}
    for source_id, exposure in expected.items():
        assert by_source[source_id].exposure_scale == pytest.approx(exposure, rel=0.2)
    assert by_source["still-shop-01"].exposure_scale > by_source["still-listing-02"].exposure_scale
    assert (
        by_source["still-auction-03"].exposure_scale > by_source["still-shop-01"].exposure_scale
    )


def test_identical_inputs_produce_identical_reports(
    coherent_case: tuple[Path, ObservationSetManifest],
    coherent_outcome: ReferenceFitOutcome,
    tmp_path: Path,
) -> None:
    root, manifest = coherent_case
    rerun = fit_reference_set(root, manifest, tmp_path, generated_at=FIXED_TIME)
    first = coherent_outcome.report_path.read_text(encoding="utf-8")
    second = rerun.report_path.read_text(encoding="utf-8")
    assert first == second
    first_renders = sorted(coherent_outcome.report_path.parent.glob("renders/*.png"))
    second_renders = sorted(rerun.report_path.parent.glob("renders/*.png"))
    assert [path.name for path in first_renders] == [path.name for path in second_renders]
    for left, right in zip(first_renders, second_renders, strict=True):
        assert file_digest(left) == file_digest(right)
    assert file_digest(coherent_outcome.profile_path) == file_digest(rerun.profile_path)


def test_single_reference_overfit_is_rejected(overfit_outcome: ReferenceFitOutcome) -> None:
    report = overfit_outcome.report
    assert report.single_reference_overfit_flag is True
    assert report.privileged_reference_ids == ["good-a"]
    assert overfit_outcome.accepted is False
    assert any("single-reference overfit" in reason for reason in overfit_outcome.rejection_reasons)
    outlier_ids = {entry.source_id for entry in report.outlier_report}
    assert {"bad-b", "bad-c"} <= outlier_ids


def test_consistency_score_orders_coherent_above_incoherent(
    coherent_outcome: ReferenceFitOutcome, overfit_outcome: ReferenceFitOutcome
) -> None:
    coherent = coherent_outcome.report.cross_reference_consistency_score
    incoherent = overfit_outcome.report.cross_reference_consistency_score
    assert 0.0 <= incoherent < coherent <= 1.0
    assert coherent - incoherent > 0.2


def test_reports_validate_against_frozen_schema(
    coherent_outcome: ReferenceFitOutcome, overfit_outcome: ReferenceFitOutcome
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for outcome in (coherent_outcome, overfit_outcome):
        payload = json.loads(outcome.report_path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(payload), key=str)
        assert errors == [], [error.message for error in errors]


def test_sequence_source_emits_highlight_trajectory(
    coherent_outcome: ReferenceFitOutcome,
) -> None:
    by_source = {fit.source_id: fit for fit in coherent_outcome.report.per_source}
    trajectory = by_source[SEQUENCE_SOURCE_ID].highlight_trajectory
    assert trajectory is not None
    assert len(trajectory) == 3
    observed_x = [float(entry["observed_x"]) for entry in trajectory]
    assert observed_x == sorted(observed_x)
    for entry in trajectory:
        assert float(entry["distance_px"]) < 12.0
    for source_id in ("still-shop-01", "still-listing-02", "still-auction-03"):
        assert by_source[source_id].highlight_trajectory is None


def test_report_artifacts_and_vocabulary(coherent_outcome: ReferenceFitOutcome) -> None:
    output_dir = coherent_outcome.report_path.parent
    for fit in coherent_outcome.report.per_source:
        assert (output_dir / fit.candidate_render_path).is_file()
        assert (output_dir / fit.difference_image_path).is_file()
        assert fit.regional_error
        assert all(value >= 0 for value in fit.regional_error.values())
        assert "highlight-lobe" in fit.regional_error
    profile = json.loads(coherent_outcome.profile_path.read_text(encoding="utf-8"))
    assert profile["lane"] == "reference"
    assert profile["label"] == "reference-derived"
    assert coherent_outcome.report.profile_blake3 == file_digest(coherent_outcome.profile_path)
    serialized = coherent_outcome.report_path.read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN_CLAIM_PHRASES:
        assert phrase not in serialized


def test_manifest_validation_rejects_malformed_observations() -> None:
    with pytest.raises(ValueError, match="exactly one frame"):
        Observation(
            source_id="bad-still",
            media_form="still",
            frames=[
                ObservationFrame(frame_id="frame-00", image_path="a.png"),
                ObservationFrame(frame_id="frame-01", image_path="b.png"),
            ],
        )
    with pytest.raises(ValueError, match="at least two"):
        Observation(
            source_id="bad-seq",
            media_form="sequence",
            frames=[ObservationFrame(frame_id="frame-00", image_path="a.png")],
        )
    with pytest.raises(ValueError, match="unique"):
        ObservationSetManifest(
            run_id="run-01",
            bundle_id="bundle-01",
            observations=[
                Observation(
                    source_id="dup",
                    frames=[ObservationFrame(frame_id="frame-00", image_path="a.png")],
                ),
                Observation(
                    source_id="dup",
                    frames=[ObservationFrame(frame_id="frame-00", image_path="b.png")],
                ),
            ],
        )


def test_cli_fit_accepts_coherent_set(
    coherent_case: tuple[Path, ObservationSetManifest], tmp_path: Path
) -> None:
    root, _ = coherent_case
    result = runner.invoke(
        app,
        [
            "fit",
            str(root),
            str(root / "manifest.json"),
            "--output-dir",
            str(tmp_path),
            "--rounds",
            "1",
            "--generated-at",
            "2026-07-16T12:00:00",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "reference-fit-report.json").is_file()
    assert (tmp_path / "profile.json").is_file()


def test_cli_fit_rejects_overfit_set(
    overfit_case: tuple[Path, ObservationSetManifest], tmp_path: Path
) -> None:
    root, _ = overfit_case
    result = runner.invoke(
        app,
        [
            "fit",
            str(root),
            str(root / "manifest.json"),
            "--output-dir",
            str(tmp_path),
            "--rounds",
            "1",
        ],
    )
    assert result.exit_code == 3, result.output
    payload = json.loads((tmp_path / "reference-fit-report.json").read_text(encoding="utf-8"))
    assert payload["single_reference_overfit_flag"] is True
    assert payload["privileged_reference_ids"] == ["good-a"]


def test_uniformly_mediocre_fit_is_rejected(
    coherent_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """M3 (adversarial code review): a profile that fits no source well must be
    rejected, not silently accepted because it avoided the overfit and
    model-limit rejections. Tightening the accept threshold below any
    achievable error simulates the uniformly-mediocre observation set."""
    root, manifest = coherent_case
    output = tmp_path_factory.mktemp("mediocre-out")
    options = ReferenceFitOptions(accept_error_threshold=1e-6)
    outcome = fit_reference_set(
        root, manifest, output, options=options, generated_at=FIXED_TIME
    )
    assert not outcome.accepted
    assert any("insufficient fit quality" in reason for reason in outcome.rejection_reasons)


def test_incoherent_consistency_is_rejected_by_floor(
    coherent_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    root, manifest = coherent_case
    output = tmp_path_factory.mktemp("consistency-out")
    options = ReferenceFitOptions(min_consistency_score=1.0)
    outcome = fit_reference_set(
        root, manifest, output, options=options, generated_at=FIXED_TIME
    )
    assert not outcome.accepted
    assert any("consistency" in reason for reason in outcome.rejection_reasons)


# ---------------------------------------------------------------------------
# FitPolicy: reference-synthesis-fit calibration fixtures
# (task packet convergence-p3-reference-fit-policy)
#
# GOOD: coherent multi-angle observations of a known profile, degraded with
# per-source exposure scaling, white-balance gains, and JPEG compression —
# must ACCEPT under reference-synthesis-fit (and here demonstrably rejects
# under physical-fit, mirroring the jp-aa-fit-002 miscalibration).
# BAD: reversed hue order / displaced highlight / activation on wrong regions /
# mutually incoherent sources — each must REJECT with the failing metric NAMED.
# ---------------------------------------------------------------------------

CAL_WIDTH = 96
CAL_HEIGHT = 128
CAL_TRUTH = ReferenceMaterialParams(specular_strength=0.6, roughness=0.35, metallic=0.6)
CAL_OPTIONS = ReferenceFitOptions(rounds=1)
REFERENCE_POLICY = FitPolicy.REFERENCE_SYNTHESIS
CAL_WB_GAINS = {
    "good-a": (1.10, 1.00, 0.90),
    "good-b": (0.90, 1.02, 1.10),
    "good-c": (1.05, 0.94, 1.06),
}
CAL_GOOD_SPECS = [
    (
        "good-a",
        {
            "azimuth": 40.0,
            "elevation": 60.0,
            "glare_x": 0.62,
            "glare_y": 0.36,
            "hardness": 2.6,
            "exposure": 0.8,
        },
    ),
    (
        "good-b",
        {
            "azimuth": 160.0,
            "elevation": 35.0,
            "glare_x": 0.34,
            "glare_y": 0.62,
            "hardness": 1.8,
            "exposure": 1.05,
        },
    ),
    (
        "good-c",
        {
            "azimuth": 260.0,
            "elevation": 70.0,
            "glare_x": 0.48,
            "glare_y": 0.44,
            "hardness": 3.2,
            "exposure": 1.3,
        },
    ),
]


def calibration_albedo_bgr() -> np.ndarray:
    """Card-like albedo with a pastel horizontal hue ramp so hue ordering is
    informative along the x axis."""
    image = np.full((CAL_HEIGHT, CAL_WIDTH, 3), 52, dtype=np.uint8)
    cv2.rectangle(image, (5, 5), (CAL_WIDTH - 6, CAL_HEIGHT - 6), (92, 100, 118), -1)
    hsv = np.zeros((CAL_HEIGHT, CAL_WIDTH, 3), dtype=np.uint8)
    hsv[..., 0] = np.linspace(8, 150, CAL_WIDTH).astype(np.uint8)[None, :]
    hsv[..., 1] = 95
    hsv[..., 2] = 175
    ramp = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    image[30:96, 8 : CAL_WIDTH - 8] = ramp[30:96, 8 : CAL_WIDTH - 8]
    cv2.rectangle(image, (8, 102), (CAL_WIDTH - 9, 118), (26, 26, 32), -1)
    cv2.circle(image, (26, 18), 8, (40, 170, 230), -1)
    return image


def plain_albedo_bgr() -> np.ndarray:
    """Distractor-free albedo for the displaced-highlight construction."""
    image = np.full((CAL_HEIGHT, CAL_WIDTH, 3), 55, dtype=np.uint8)
    cv2.rectangle(image, (5, 5), (CAL_WIDTH - 6, CAL_HEIGHT - 6), (105, 108, 112), -1)
    cv2.rectangle(image, (8, 102), (CAL_WIDTH - 9, 118), (28, 28, 32), -1)
    return image


def jpeg_degrade(bgr: np.ndarray, quality: int) -> np.ndarray:
    ok, buffer = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def gaussian_blob(shape: tuple[int, int], cx: float, cy: float, sigma: float) -> np.ndarray:
    height, width = shape
    xx, yy = np.meshgrid(np.linspace(0.0, 1.0, width), np.linspace(0.0, 1.0, height))
    return np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma**2)).astype(np.float32)


def white_balance_shift(gains: tuple[float, float, float]):
    def transform(render: np.ndarray) -> np.ndarray:
        scaled = render * np.asarray(gains, dtype=np.float32)[None, None, :]
        return np.clip(scaled, 0.0, 1.0).astype(np.float32)

    return transform


def reverse_hue(render: np.ndarray) -> np.ndarray:
    """Mirror chromaticity along x while preserving per-pixel luminance."""
    mirrored = render[:, ::-1, :]
    scale = (luminance(render) + 1e-6) / (luminance(mirrored) + 1e-6)
    return np.clip(mirrored * scale[..., None], 0.0, 1.0).astype(np.float32)


def make_reference_source(
    root: Path,
    source_id: str,
    specs: list[dict[str, float]],
    albedo_linear: np.ndarray,
    *,
    material: ReferenceMaterialParams = CAL_TRUTH,
    jpeg_quality: int | None = None,
    transform=None,
) -> Observation:
    frames: list[ObservationFrame] = []
    for index, spec in enumerate(specs):
        frame_id = f"frame-{index:02d}"
        render = render_planar_candidate(
            albedo_linear,
            material,
            azimuth_deg=spec["azimuth"],
            elevation_deg=spec["elevation"],
            glare_x=spec["glare_x"],
            glare_y=spec["glare_y"],
            hardness=spec["hardness"],
            exposure=spec["exposure"],
        )
        if transform is not None:
            render = transform(render)
        bgr = linear_rgb_to_srgb_bgr(render)
        if jpeg_quality is not None:
            bgr = jpeg_degrade(bgr, jpeg_quality)
        image_path = f"obs/{source_id}-{frame_id}.png"
        write_bgr(root / image_path, bgr)
        frames.append(ObservationFrame(frame_id=frame_id, image_path=image_path))
    return Observation(source_id=source_id, frames=frames)


def build_policy_manifest(
    root: Path, run_id: str, observations: list[Observation]
) -> ObservationSetManifest:
    manifest = ObservationSetManifest(
        run_id=run_id,
        bundle_id="op01-001-policy-bundle",
        albedo_path="albedo.png",
        observations=observations,
    )
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def write_calibration_albedo(root: Path, albedo_bgr_image: np.ndarray) -> np.ndarray:
    write_bgr(root / "albedo.png", albedo_bgr_image)
    return srgb_to_linear_rgb(albedo_bgr_image)


@pytest.fixture(scope="module")
def good_reference_case(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, ObservationSetManifest]:
    root = tmp_path_factory.mktemp("policy-good-root")
    albedo_linear = write_calibration_albedo(root, calibration_albedo_bgr())
    observations = [
        make_reference_source(
            root,
            source_id,
            [spec],
            albedo_linear,
            jpeg_quality=40,
            transform=white_balance_shift(CAL_WB_GAINS[source_id]),
        )
        for source_id, spec in CAL_GOOD_SPECS
    ]
    return root, build_policy_manifest(root, "policy-good-001", observations)


@pytest.fixture(scope="module")
def good_reference_outcome(
    good_reference_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> ReferenceFitOutcome:
    root, manifest = good_reference_case
    output = tmp_path_factory.mktemp("policy-good-out")
    return fit_reference_set(
        root,
        manifest,
        output,
        options=CAL_OPTIONS,
        generated_at=FIXED_TIME,
        policy=REFERENCE_POLICY,
    )


@pytest.fixture(scope="module")
def hue_reversed_outcome(tmp_path_factory: pytest.TempPathFactory) -> ReferenceFitOutcome:
    root = tmp_path_factory.mktemp("policy-hue-root")
    albedo_linear = write_calibration_albedo(root, calibration_albedo_bgr())
    specs = [
        (
            "hue-a",
            {
                "azimuth": 90.0,
                "elevation": 35.0,
                "glare_x": 0.40,
                "glare_y": 0.50,
                "hardness": 2.2,
                "exposure": 1.0,
            },
        ),
        (
            "hue-b",
            {
                "azimuth": 270.0,
                "elevation": 40.0,
                "glare_x": 0.60,
                "glare_y": 0.55,
                "hardness": 2.6,
                "exposure": 0.9,
            },
        ),
        (
            "hue-c",
            {
                "azimuth": 90.0,
                "elevation": 45.0,
                "glare_x": 0.52,
                "glare_y": 0.48,
                "hardness": 2.0,
                "exposure": 1.15,
            },
        ),
    ]
    observations = [
        make_reference_source(root, source_id, [spec], albedo_linear, transform=reverse_hue)
        for source_id, spec in specs
    ]
    manifest = build_policy_manifest(root, "policy-hue-001", observations)
    output = tmp_path_factory.mktemp("policy-hue-out")
    return fit_reference_set(
        root,
        manifest,
        output,
        options=CAL_OPTIONS,
        generated_at=FIXED_TIME,
        policy=REFERENCE_POLICY,
    )


@pytest.fixture(scope="module")
def displaced_highlight_outcome(
    tmp_path_factory: pytest.TempPathFactory,
) -> ReferenceFitOutcome:
    root = tmp_path_factory.mktemp("policy-displaced-root")
    albedo_linear = write_calibration_albedo(root, plain_albedo_bgr())
    diffuse_only = CAL_TRUTH.model_copy(update={"specular_strength": 0.0})

    def displaced(first: tuple[float, float], second: tuple[float, float]):
        def transform(render: np.ndarray) -> np.ndarray:
            blob = 0.55 * gaussian_blob(render.shape[:2], first[0], first[1], 0.05)
            blob += 0.55 * gaussian_blob(render.shape[:2], second[0], second[1], 0.05)
            return np.clip(render + blob[..., None], 0.0, 1.0).astype(np.float32)

        return transform

    specs = [
        ("blob-a", 45.0, 1.0, (0.25, 0.30), (0.75, 0.70)),
        ("blob-b", 135.0, 0.9, (0.72, 0.32), (0.28, 0.68)),
        ("blob-c", 225.0, 1.15, (0.30, 0.72), (0.70, 0.26)),
    ]
    observations = [
        make_reference_source(
            root,
            source_id,
            [
                {
                    "azimuth": azimuth,
                    "elevation": 55.0,
                    "glare_x": 0.5,
                    "glare_y": 0.5,
                    "hardness": 2.5,
                    "exposure": exposure,
                }
            ],
            albedo_linear,
            material=diffuse_only,
            transform=displaced(first, second),
        )
        for source_id, azimuth, exposure, first, second in specs
    ]
    manifest = build_policy_manifest(root, "policy-displaced-001", observations)
    output = tmp_path_factory.mktemp("policy-displaced-out")
    return fit_reference_set(
        root,
        manifest,
        output,
        options=CAL_OPTIONS,
        generated_at=FIXED_TIME,
        policy=REFERENCE_POLICY,
    )


@pytest.fixture(scope="module")
def wrong_region_outcome(tmp_path_factory: pytest.TempPathFactory) -> ReferenceFitOutcome:
    root = tmp_path_factory.mktemp("policy-region-root")
    albedo_linear = write_calibration_albedo(root, calibration_albedo_bgr())
    diffuse_only = CAL_TRUTH.model_copy(update={"specular_strength": 0.0})

    def border_ring(render: np.ndarray) -> np.ndarray:
        height, width = render.shape[:2]
        ring = np.zeros((height, width), np.float32)
        ring[4:14, 4:-4] = 1.0
        ring[-14:-4, 4:-4] = 1.0
        ring[4:-4, 4:12] = 1.0
        ring[4:-4, -12:-4] = 1.0
        ring = cv2.GaussianBlur(ring, (9, 9), 2.0)
        return np.clip(render + 0.4 * ring[..., None], 0.0, 1.0).astype(np.float32)

    specs = [("ring-a", 45.0, 1.0), ("ring-b", 135.0, 0.85), ("ring-c", 225.0, 1.2)]
    observations = [
        make_reference_source(
            root,
            source_id,
            [
                {
                    "azimuth": azimuth,
                    "elevation": 55.0,
                    "glare_x": 0.5,
                    "glare_y": 0.5,
                    "hardness": 2.5,
                    "exposure": exposure,
                }
            ],
            albedo_linear,
            material=diffuse_only,
            transform=border_ring,
        )
        for source_id, azimuth, exposure in specs
    ]
    manifest = build_policy_manifest(root, "policy-region-001", observations)
    output = tmp_path_factory.mktemp("policy-region-out")
    return fit_reference_set(
        root,
        manifest,
        output,
        options=CAL_OPTIONS,
        generated_at=FIXED_TIME,
        policy=REFERENCE_POLICY,
    )


@pytest.fixture(scope="module")
def incoherent_case(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, ObservationSetManifest]:
    root = tmp_path_factory.mktemp("policy-incoherent-root")
    albedo_linear = write_calibration_albedo(root, calibration_albedo_bgr())
    strengths = {"inc-a": 0.02, "inc-b": 0.9, "inc-c": 0.4, "inc-d": 0.7}
    specs = [
        ("inc-a", 40.0, 55.0, 0.60, 0.40, 2.4, 1.0),
        ("inc-b", 150.0, 45.0, 0.36, 0.58, 2.2, 0.9),
        ("inc-c", 250.0, 65.0, 0.46, 0.44, 2.8, 1.2),
        ("inc-d", 320.0, 50.0, 0.55, 0.60, 2.0, 1.1),
    ]
    observations = [
        make_reference_source(
            root,
            source_id,
            [
                {
                    "azimuth": azimuth,
                    "elevation": elevation,
                    "glare_x": glare_x,
                    "glare_y": glare_y,
                    "hardness": hardness,
                    "exposure": exposure,
                }
            ],
            albedo_linear,
            material=CAL_TRUTH.model_copy(update={"specular_strength": strengths[source_id]}),
        )
        for source_id, azimuth, elevation, glare_x, glare_y, hardness, exposure in specs
    ]
    return root, build_policy_manifest(root, "policy-incoherent-001", observations)


@pytest.fixture(scope="module")
def incoherent_outcome(
    incoherent_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> ReferenceFitOutcome:
    root, manifest = incoherent_case
    output = tmp_path_factory.mktemp("policy-incoherent-out")
    return fit_reference_set(
        root,
        manifest,
        output,
        options=CAL_OPTIONS,
        generated_at=FIXED_TIME,
        policy=REFERENCE_POLICY,
    )


@pytest.fixture(scope="module")
def coherent_reference_outcome(
    coherent_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> ReferenceFitOutcome:
    root, manifest = coherent_case
    output = tmp_path_factory.mktemp("coherent-reference-out")
    return fit_reference_set(
        root,
        manifest,
        output,
        options=CAL_OPTIONS,
        generated_at=FIXED_TIME,
        policy=REFERENCE_POLICY,
    )


def test_noisy_good_set_accepts_under_reference_synthesis(
    good_reference_outcome: ReferenceFitOutcome,
) -> None:
    """Exposure/WB/JPEG degradation must not fail the perceptual policy: the
    render still activates the right regions with the right hue ordering."""
    assert good_reference_outcome.accepted
    assert good_reference_outcome.rejection_reasons == ()
    for fit in good_reference_outcome.report.per_source:
        assert fit.regional_error["policy-reference-synthesis-fit"] == 1.0
        assert fit.regional_error["policy-activation-iou"] > 0.5
        assert fit.regional_error["policy-composite"] > 0.8
        # Stills-only set: no temporal metric anywhere, and no penalty for it.
        assert "policy-temporal-coherence" not in fit.regional_error


def test_noisy_good_set_rejects_under_physical_fit(
    good_reference_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The same degraded-but-coherent set fails the absolute linear-RGB policy —
    the jp-aa-fit-002 pattern; the policies measure different things."""
    root, manifest = good_reference_case
    output = tmp_path_factory.mktemp("policy-good-physical-out")
    outcome = fit_reference_set(
        root,
        manifest,
        output,
        options=CAL_OPTIONS,
        generated_at=FIXED_TIME,
        policy=FitPolicy.PHYSICAL,
    )
    assert not outcome.accepted
    assert any(
        "insufficient fit quality" in reason or "consistency" in reason
        for reason in outcome.rejection_reasons
    )


def test_reversed_hue_order_rejects_with_metric_named(
    hue_reversed_outcome: ReferenceFitOutcome,
) -> None:
    assert not hue_reversed_outcome.accepted
    assert any("[hue-ordering]" in reason for reason in hue_reversed_outcome.rejection_reasons)
    for fit in hue_reversed_outcome.report.per_source:
        assert fit.regional_error["policy-hue-ordering"] < -0.5


def test_displaced_highlight_rejects_with_metric_named(
    displaced_highlight_outcome: ReferenceFitOutcome,
) -> None:
    assert not displaced_highlight_outcome.accepted
    assert any(
        "[highlight-position]" in reason
        for reason in displaced_highlight_outcome.rejection_reasons
    )


def test_wrong_region_activation_rejects_with_metric_named(
    wrong_region_outcome: ReferenceFitOutcome,
) -> None:
    assert not wrong_region_outcome.accepted
    assert any(
        "[regional-foil-activation]" in reason
        for reason in wrong_region_outcome.rejection_reasons
    )
    outlier_ids = {entry.source_id for entry in wrong_region_outcome.report.outlier_report}
    assert {"ring-a", "ring-b", "ring-c"} <= outlier_ids


def test_incoherent_sources_reject_with_metric_named(
    incoherent_outcome: ReferenceFitOutcome,
) -> None:
    assert not incoherent_outcome.accepted
    assert any(
        "[relative-intensity-coherence]" in reason
        for reason in incoherent_outcome.rejection_reasons
    )


def test_policy_reports_validate_against_frozen_schema(
    good_reference_outcome: ReferenceFitOutcome,
    hue_reversed_outcome: ReferenceFitOutcome,
    incoherent_outcome: ReferenceFitOutcome,
) -> None:
    """Policy metadata lives in regional_error keys and outlier entries only;
    the frozen report schema stays intact."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for outcome in (good_reference_outcome, hue_reversed_outcome, incoherent_outcome):
        payload = json.loads(outcome.report_path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(payload), key=str)
        assert errors == [], [error.message for error in errors]


def test_reference_policy_on_coherent_set_scores_temporal_for_sequences_only(
    coherent_reference_outcome: ReferenceFitOutcome,
) -> None:
    assert coherent_reference_outcome.accepted
    by_source = {fit.source_id: fit for fit in coherent_reference_outcome.report.per_source}
    assert by_source[SEQUENCE_SOURCE_ID].regional_error["policy-temporal-coherence"] > 0.6
    for source_id in ("still-shop-01", "still-listing-02", "still-auction-03"):
        assert "policy-temporal-coherence" not in by_source[source_id].regional_error


def test_explicit_physical_policy_matches_default_byte_for_byte(
    coherent_case: tuple[Path, ObservationSetManifest],
    coherent_outcome: ReferenceFitOutcome,
    tmp_path: Path,
) -> None:
    """Regression guard: policy='physical-fit' is the pre-policy behaviour,
    decision for decision and report byte for byte."""
    root, manifest = coherent_case
    rerun = fit_reference_set(
        root, manifest, tmp_path, generated_at=FIXED_TIME, policy="physical-fit"
    )
    assert rerun.accepted == coherent_outcome.accepted
    assert rerun.rejection_reasons == coherent_outcome.rejection_reasons
    assert rerun.report_path.read_text(encoding="utf-8") == coherent_outcome.report_path.read_text(
        encoding="utf-8"
    )


def test_overfit_rejection_active_under_reference_policy(
    overfit_case: tuple[Path, ObservationSetManifest],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The single-reference-overfit hard gate stays in force in both policies."""
    root, manifest = overfit_case
    output = tmp_path_factory.mktemp("policy-overfit-out")
    outcome = fit_reference_set(
        root,
        manifest,
        output,
        options=CAL_OPTIONS,
        generated_at=FIXED_TIME,
        policy=REFERENCE_POLICY,
    )
    assert outcome.report.single_reference_overfit_flag is True
    assert not outcome.accepted
    assert any("single-reference overfit" in reason for reason in outcome.rejection_reasons)


def test_cli_policy_flag_selects_physical_fit(
    coherent_case: tuple[Path, ObservationSetManifest], tmp_path: Path
) -> None:
    root, _ = coherent_case
    result = runner.invoke(
        app,
        [
            "fit",
            str(root),
            str(root / "manifest.json"),
            "--output-dir",
            str(tmp_path),
            "--rounds",
            "1",
            "--policy",
            "physical-fit",
            "--generated-at",
            "2026-07-16T12:00:00",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "reference-fit-report.json").read_text(encoding="utf-8"))
    assert all(
        "policy-physical-fit" in entry["regional_error"] for entry in payload["per_source"]
    )


def test_cli_default_policy_names_failing_metric(
    incoherent_case: tuple[Path, ObservationSetManifest], tmp_path: Path
) -> None:
    """The CLI defaults to reference-synthesis-fit and reports the named metric
    on rejection (exit 1: policy-criteria rejection, not overfit/model-limit)."""
    root, _ = incoherent_case
    result = runner.invoke(
        app,
        [
            "fit",
            str(root),
            str(root / "manifest.json"),
            "--output-dir",
            str(tmp_path),
            "--rounds",
            "1",
        ],
    )
    assert result.exit_code == 1, result.output
    flattened = result.output.replace("\n", "")
    assert "relative-intensity-coherence" in flattened


def test_circular_correlation_orders_hue_sequences() -> None:
    from optcg_material import reference_fitting as rf

    angles = np.linspace(-1.2, 1.2, 9)
    same = rf._circular_correlation(angles, angles + 0.1)
    reversed_corr = rf._circular_correlation(angles, angles[::-1])
    assert same is not None and same > 0.95
    assert reversed_corr is not None and reversed_corr < -0.95
    assert rf._circular_correlation(np.zeros(5), angles[:5]) is None


def test_structural_similarity_is_exposure_and_gain_invariant() -> None:
    from optcg_material import reference_fitting as rf

    rng = np.random.default_rng(7)
    luma = cv2.GaussianBlur(rng.random((64, 48)).astype(np.float32), (7, 7), 1.2)
    valid = np.ones(luma.shape, dtype=bool)
    assert rf._structural_similarity(luma, luma * 0.5, valid) > 0.98
    assert rf._structural_similarity(luma, luma * 1.8 + 0.05, valid) > 0.98
    shuffled = cv2.GaussianBlur(rng.random(luma.shape).astype(np.float32), (7, 7), 1.2)
    assert rf._structural_similarity(luma, shuffled, valid) < 0.5


def test_intensity_coherence_contract() -> None:
    from optcg_material import reference_fitting as rf

    # Fewer than three sources: not computable.
    assert rf._intensity_coherence([1.0, 2.0], [1.0, 2.0]) is None
    # Sources agree about foil intensity: coherent, skipped (never penalized).
    assert rf._intensity_coherence([1.0, 1.05, 0.98], [1.0, 1.02, 0.99]) is None
    # Observed levels disagree wildly while the render cannot track them.
    score = rf._intensity_coherence([0.05, 2.0, 1.0, 1.5], [1.0, 1.05, 0.95, 1.02])
    assert score is not None and score < 0.25
    # Tracked variation scores high.
    tracked = rf._intensity_coherence([0.1, 2.0, 1.0], [0.12, 1.9, 1.05])
    assert tracked is not None and tracked > 0.8
