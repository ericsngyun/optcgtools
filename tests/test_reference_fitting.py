from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from optcg_material.material_maps import srgb_to_linear_rgb
from optcg_material.reference_fitting import (
    FORBIDDEN_CLAIM_PHRASES,
    Observation,
    ObservationFrame,
    ObservationSetManifest,
    ReferenceFitOptions,
    ReferenceFitOutcome,
    ReferenceMaterialParams,
    fit_reference_set,
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
