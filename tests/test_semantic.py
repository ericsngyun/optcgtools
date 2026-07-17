from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from optcg_material.semantic import (
    CorrectionOperation,
    MaskCorrection,
    ModelProvenance,
    PromptBox,
    PromptPoint,
    RegionPrompt,
    SemanticRegion,
    apply_mask_correction,
    canonical_digest,
    uncertainty_from_logits,
    write_mask,
)


def test_region_prompt_requires_spatial_input() -> None:
    with pytest.raises(ValidationError):
        RegionPrompt(
            region_id="character",
            semantic_region=SemanticRegion.CHARACTER,
        )


def test_prompt_box_requires_positive_area() -> None:
    with pytest.raises(ValidationError):
        PromptBox(x_min=10, y_min=10, x_max=5, y_max=20)


def test_prompt_digest_is_deterministic() -> None:
    prompt = RegionPrompt(
        region_id="character",
        semantic_region=SemanticRegion.CHARACTER,
        points=[PromptPoint(x=200, y=300, foreground=True)],
    )
    assert canonical_digest(prompt) == canonical_digest(prompt.model_copy())


def test_model_provenance_accepts_worker_config_alias() -> None:
    provenance = ModelProvenance(
        model_config="configs/sam2.1/sam2.1_hiera_b+.yaml",
        checkpoint_path="/models/sam2.1_hiera_base_plus.pt",
        checkpoint_blake3="a" * 64,
        device="cuda",
        torch_version="2.5.1",
    )
    assert provenance.config_path == "configs/sam2.1/sam2.1_hiera_b+.yaml"


def test_uncertainty_is_highest_near_boundary() -> None:
    logits = np.asarray([-8.0, 0.0, 8.0], dtype=np.float32)
    uncertainty = uncertainty_from_logits(logits)
    assert uncertainty[1] == pytest.approx(1.0)
    assert uncertainty[0] < 0.01
    assert uncertainty[2] < 0.01


def write_binary(path: Path, foreground: tuple[slice, slice]) -> None:
    mask = np.zeros((64, 64), dtype=bool)
    mask[foreground] = True
    write_mask(path, mask)


def test_mask_correction_union_is_hashed(tmp_path: Path) -> None:
    proposal_path = tmp_path / "processed" / "proposal.png"
    correction_path = tmp_path / "review" / "brush.png"
    output_path = tmp_path / "review" / "approved.png"
    write_binary(proposal_path, (slice(5, 25), slice(5, 25)))
    write_binary(correction_path, (slice(20, 40), slice(20, 40)))

    correction = MaskCorrection(
        correction_id="character-review-001",
        proposal_id="character-f00000",
        operation=CorrectionOperation.UNION,
        correction_mask_path="review/brush.png",
        output_mask_path="review/approved.png",
        reviewer="GenkiStuff reviewer",
    )
    result = apply_mask_correction(
        tmp_path,
        "processed/proposal.png",
        correction,
    )

    approved = cv2.imread(str(output_path), cv2.IMREAD_GRAYSCALE)
    assert approved is not None
    assert int(np.count_nonzero(approved)) > 400
    assert result.correction_mask_blake3 is not None
    assert result.output_mask_blake3 is not None
