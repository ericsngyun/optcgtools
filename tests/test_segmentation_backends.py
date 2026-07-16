from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from optcg_material.segmentation import (
    BackendUnavailableError,
    available_backends,
    create_backend,
)
from optcg_material.semantic import (
    RegionPrompt,
    SegmentationRequest,
    SemanticRegion,
    read_binary_mask,
    write_mask,
)


def test_registry_lists_all_backends() -> None:
    assert available_backends() == ("manual", "sam2.1", "sam3")


def test_unknown_backend_rejected() -> None:
    with pytest.raises(KeyError, match="unknown segmentation backend"):
        create_backend("sam3.1")


def test_sam3_is_explicitly_unavailable() -> None:
    backend = create_backend("sam3")
    problems = backend.check_environment()
    assert problems and "verified official source" in problems[0]
    with pytest.raises(BackendUnavailableError):
        backend.identity()


def test_manual_backend_is_authoritative_and_roundtrips(tmp_path: Path) -> None:
    frame = np.zeros((64, 48), dtype=bool)
    frame[10:30, 5:25] = True
    (tmp_path / "review").mkdir(parents=True)
    write_mask(tmp_path / "review" / "character.png", frame)
    (tmp_path / "processed").mkdir()
    write_mask(tmp_path / "processed" / "frame.png", frame)

    backend = create_backend("manual")
    assert backend.capabilities().authoritative_for_approval
    assert backend.check_environment() == []

    request = SegmentationRequest(
        run_id="manual-run-001",
        session_id="op05-119-luffy-en-001",
        mode="image",
        source_path="processed/frame.png",
        prompts=[
            RegionPrompt(
                region_id="character",
                semantic_region=SemanticRegion.CHARACTER,
                mask_input_path="review/character.png",
            )
        ],
    )
    proposals = backend.segment_image(tmp_path, request)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.mean_uncertainty == 0.0
    assert 0.1 < proposal.foreground_ratio < 0.2
    roundtrip = read_binary_mask(tmp_path / proposal.mask_path)
    assert np.array_equal(roundtrip, frame)


def test_manual_backend_requires_mask_input(tmp_path: Path) -> None:
    backend = create_backend("manual")
    request = SegmentationRequest(
        run_id="manual-run-002",
        session_id="op05-119-luffy-en-001",
        mode="image",
        source_path="processed/frame.png",
        prompts=[
            RegionPrompt(
                region_id="character",
                semantic_region=SemanticRegion.CHARACTER,
                points=[{"x": 1, "y": 1}],
            )
        ],
    )
    with pytest.raises(Exception, match="mask_input_path"):
        backend.segment_image(tmp_path, request)


def test_sam2_backend_reports_pinned_identity() -> None:
    from optcg_material.sam2_backend import Sam2Settings

    backend = create_backend(
        "sam2.1",
        settings=Sam2Settings(
            checkpoint_path="/nonexistent/sam2.1_hiera_base_plus.pt",
            model_config_path="configs/sam2.1/sam2.1_hiera_b+.yaml",
        ),
    )
    identity = backend.identity()
    assert identity.source_commit == "2b90b9f5ceec907a1c18123530e92e794ad901a4"
    problems = backend.check_environment()
    assert any("checkpoint" in problem for problem in problems)
