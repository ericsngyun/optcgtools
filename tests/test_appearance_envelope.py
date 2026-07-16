from __future__ import annotations

import colorsys
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from optcg_material.appearance_cli import app
from optcg_material.appearance_envelope import (
    AppearanceEnvelopeError,
    AppearanceExtractionManifest,
    RegionArtifacts,
    assert_proposal_language,
    extract_appearance_envelopes,
    load_extraction_manifest,
)

HEIGHT = 64
WIDTH = 64
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "agent-ops"
    / "appearance-envelope.schema.json"
)


def flat(value: float) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), value, dtype=np.float32)


def _encode_srgb_bgr(linear_rgb: np.ndarray) -> np.ndarray:
    clipped = np.clip(linear_rgb, 0.0, 1.0)
    srgb = np.where(
        clipped <= 0.0031308,
        clipped * 12.92,
        1.055 * np.power(clipped, 1.0 / 2.4) - 0.055,
    )
    return np.round(np.clip(srgb, 0.0, 1.0) * 255.0).astype(np.uint8)[..., ::-1]


def build_bundle(
    root: Path,
    images: dict[str, np.ndarray],
    *,
    interference: dict[str, np.ndarray] | None = None,
    weights: dict[str, float] | None = None,
) -> Path:
    (root / "normalized").mkdir(parents=True, exist_ok=True)
    entries = []
    for source_id, linear_rgb in images.items():
        image_rel = f"normalized/{source_id}.png"
        assert cv2.imwrite(str(root / image_rel), _encode_srgb_bgr(linear_rgb))
        entry: dict[str, object] = {
            "source_id": source_id,
            "image": image_rel,
            "confidence_weight": (weights or {}).get(source_id, 1.0),
        }
        if interference and source_id in interference:
            mask_rel = f"normalized/{source_id}.interference.png"
            mask = interference[source_id].astype(np.uint8) * 255
            assert cv2.imwrite(str(root / mask_rel), mask)
            entry["interference_mask"] = mask_rel
        entries.append(entry)
    manifest = {
        "schema_version": "1.0.0",
        "bundle_id": "op01-001-alt-art-en",
        "card_id": "OP01-001",
        "registration_state": "normalized-registered",
        "sources": entries,
    }
    manifest_path = root / "extraction-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def run_extraction(root: Path, manifest_path: Path) -> list[RegionArtifacts]:
    manifest = load_extraction_manifest(manifest_path)
    return extract_appearance_envelopes(root, manifest, root / "appearance")


def baseline_gray_images() -> dict[str, np.ndarray]:
    return {
        "src-a": flat(0.40),
        "src-b": flat(0.41),
        "src-c": flat(0.42),
        "src-d": flat(0.43),
    }


def test_overexposed_source_cannot_dominate(tmp_path: Path) -> None:
    baseline = run_extraction(
        tmp_path / "clean", build_bundle(tmp_path / "clean", baseline_gray_images())
    )[0].envelope

    images = baseline_gray_images()
    images["src-hot"] = flat(0.41) * 8.0  # three stops overexposed, fully clipped
    poisoned = run_extraction(
        tmp_path / "hot", build_bundle(tmp_path / "hot", images)
    )[0].envelope

    assert "src-hot" in poisoned.outlier_sources_excluded
    assert "src-hot" not in poisoned.contributing_source_ids
    assert abs(poisoned.brightness.median - baseline.brightness.median) < 0.01
    assert abs(poisoned.brightness.max - baseline.brightness.max) < 0.01
    assert abs(poisoned.brightness.min - baseline.brightness.min) < 0.01
    assert poisoned.evidence_state == "source-supported"


def test_manipulated_bright_source_is_rejected_with_reason(tmp_path: Path) -> None:
    baseline = run_extraction(
        tmp_path / "clean", build_bundle(tmp_path / "clean", baseline_gray_images())
    )[0].envelope

    images = baseline_gray_images()
    images["src-edit"] = flat(0.84)  # doubled brightness, below the clip threshold
    artifact = run_extraction(tmp_path / "edit", build_bundle(tmp_path / "edit", images))[0]

    assert "src-edit" in artifact.envelope.outlier_sources_excluded
    assert abs(artifact.envelope.brightness.median - baseline.brightness.median) < 0.01
    reasons = artifact.diagnostics["outlier_sources_excluded"]
    assert "src-edit" in reasons
    assert "outlier" in reasons["src-edit"] or "clipped" in reasons["src-edit"]


def test_interference_regions_are_excluded_from_statistics(tmp_path: Path) -> None:
    plain = {"src-a": flat(0.45), "src-b": flat(0.45), "src-c": flat(0.45)}
    baseline = run_extraction(
        tmp_path / "plain", build_bundle(tmp_path / "plain", plain)
    )[0].envelope

    banded = dict(plain)
    banded_image = flat(0.45)
    banded_image[0:8, :, :] = 0.95  # sleeve glare band
    banded["src-c"] = banded_image
    band_mask = np.zeros((HEIGHT, WIDTH), dtype=bool)
    band_mask[0:8, :] = True
    artifact = run_extraction(
        tmp_path / "banded",
        build_bundle(tmp_path / "banded", banded, interference={"src-c": band_mask}),
    )[0]

    assert artifact.envelope.brightness.max < 0.5
    assert abs(artifact.envelope.brightness.median - baseline.brightness.median) < 1e-6
    assert abs(artifact.envelope.brightness.max - baseline.brightness.max) < 1e-6

    confidence = cv2.imread(str(artifact.confidence_map_path), cv2.IMREAD_GRAYSCALE)
    assert confidence is not None
    assert float(confidence[0:8, :].mean()) < float(confidence[16:, :].mean())


def test_specular_activation_requires_two_source_agreement(tmp_path: Path) -> None:
    def with_highlight(base: float) -> np.ndarray:
        image = flat(base)
        yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
        disk = (yy - 32) ** 2 + (xx - 32) ** 2 <= 6**2
        image[disk] = 0.9
        return image

    lone = {
        "src-a": with_highlight(0.30),
        "src-b": flat(0.30),
        "src-c": flat(0.30),
        "src-d": flat(0.30),
    }
    lone_envelope = run_extraction(
        tmp_path / "lone", build_bundle(tmp_path / "lone", lone)
    )[0].envelope
    assert lone_envelope.specular_activation_frequency == 0.0
    assert lone_envelope.proposals.clearcoat == 0.0

    agreeing = dict(lone)
    agreeing["src-b"] = with_highlight(0.30)
    agree_envelope = run_extraction(
        tmp_path / "agree", build_bundle(tmp_path / "agree", agreeing)
    )[0].envelope
    assert agree_envelope.specular_activation_frequency > 0.0


def hue_travel_images() -> dict[str, np.ndarray]:
    images: dict[str, np.ndarray] = {}
    for source_id, hue in (("src-a", 100.0), ("src-b", 120.0), ("src-c", 140.0), ("src-d", 160.0)):
        image = flat(0.45)
        patch_rgb = colorsys.hsv_to_rgb(hue / 360.0, 0.6, 0.5)
        image[16:48, :, :] = np.asarray(patch_rgb, dtype=np.float32)
        image[56:64, :, :] = 0.02  # stable dark ink band
        images[source_id] = image
    return images


def test_hue_range_foil_travel_and_ink_suppression(tmp_path: Path) -> None:
    envelope = run_extraction(
        tmp_path / "hue", build_bundle(tmp_path / "hue", hue_travel_images())
    )[0].envelope

    assert abs(envelope.hue_range.dominant_hue_axis_deg - 130.0) < 5.0
    assert abs(envelope.hue_range.min_deg - 100.0) < 6.0
    assert abs(envelope.hue_range.max_deg - 160.0) < 6.0
    # Cross-source hue travel in the patch is a foil signal, not a metallic one.
    assert envelope.proposals.foil > 0.25
    assert envelope.proposals.foil > envelope.proposals.metallic
    # The dark band is stable across sources: ~12.5% of the region.
    assert 0.08 < envelope.proposals.black_ink_suppression < 0.17
    assert envelope.chroma_variance > 0


def test_texture_frequency_and_direction(tmp_path: Path) -> None:
    xx = np.arange(WIDTH, dtype=np.float32)
    stripes = 0.4 + 0.1 * np.sin(2.0 * np.pi * xx / 8.0)
    image = np.repeat(stripes[None, :], HEIGHT, axis=0)[..., None].repeat(3, axis=-1)
    envelope = run_extraction(
        tmp_path / "tex",
        build_bundle(tmp_path / "tex", {"src-a": image.copy(), "src-b": image.copy()}),
    )[0].envelope

    assert abs(envelope.proposals.texture_frequency - 0.125) < 0.01
    direction = envelope.proposals.texture_direction_deg % 180.0
    assert direction < 10.0 or direction > 170.0
    assert envelope.proposals.confidence["texture_frequency"] > 0.3


def test_output_carries_proposal_label_and_no_physical_claims(tmp_path: Path) -> None:
    artifact = run_extraction(
        tmp_path / "hue", build_bundle(tmp_path / "hue", hue_travel_images())
    )[0]

    for path in (artifact.envelope_path, artifact.diagnostics_path):
        text = path.read_text(encoding="utf-8").lower()
        assert "measured" not in text
        assert "human-reviewed" not in text

    payload = json.loads(artifact.envelope_path.read_text(encoding="utf-8"))
    assert payload["label"] == "observed-appearance-proposal"
    assert payload["evidence_state"] in {"source-supported", "inferred"}
    with pytest.raises(AppearanceEnvelopeError):
        assert_proposal_language('{"claim": "measured"}')
    with pytest.raises(AppearanceEnvelopeError):
        assert_proposal_language('{"claim": "human-reviewed"}')


def test_envelope_validates_against_frozen_schema(tmp_path: Path) -> None:
    images = baseline_gray_images()
    images["src-hot"] = flat(0.41) * 8.0  # exercise outlier_sources_excluded too
    artifact = run_extraction(tmp_path / "hot", build_bundle(tmp_path / "hot", images))[0]

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    payload = json.loads(artifact.envelope_path.read_text(encoding="utf-8"))
    Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    ).validate(payload)


def test_per_pixel_confidence_map_is_emitted_and_recorded(tmp_path: Path) -> None:
    artifact = run_extraction(
        tmp_path / "clean", build_bundle(tmp_path / "clean", baseline_gray_images())
    )[0]

    assert artifact.envelope.per_pixel_confidence_map == "full-card.confidence.png"
    assert artifact.confidence_map_path.name == "full-card.confidence.png"
    assert artifact.confidence_map_path.is_file()
    values = cv2.imread(str(artifact.confidence_map_path), cv2.IMREAD_GRAYSCALE)
    assert values is not None
    assert values.shape == (HEIGHT, WIDTH)
    assert float(values.mean()) > 200  # full coverage from four agreeing sources


def test_refuses_unregistered_or_misaligned_input(tmp_path: Path) -> None:
    root = tmp_path / "misaligned"
    images = {"src-a": flat(0.4), "src-b": np.full((32, WIDTH, 3), 0.4, dtype=np.float32)}
    manifest_path = build_bundle(root, images)
    manifest = load_extraction_manifest(manifest_path)
    with pytest.raises(AppearanceEnvelopeError, match="refusing unregistered"):
        extract_appearance_envelopes(root, manifest, root / "appearance")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["registration_state"] = "raw"
    with pytest.raises(ValueError, match="registration_state"):
        AppearanceExtractionManifest.model_validate(payload)


def test_cli_extract_emits_schema_valid_envelopes(tmp_path: Path) -> None:
    root = tmp_path / "cli"
    manifest_path = build_bundle(root, baseline_gray_images())
    output_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["extract", str(root), str(manifest_path), "--output", str(output_dir)],
    )
    assert result.exit_code == 0, result.output
    envelope_path = output_dir / "full-card.appearance-envelope.json"
    assert envelope_path.is_file()
    assert (output_dir / "full-card.confidence.png").is_file()
    assert (output_dir / "full-card.appearance-diagnostics.json").is_file()
    payload = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert payload["label"] == "observed-appearance-proposal"
