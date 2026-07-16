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


def test_registry_lists_exactly_three_roles() -> None:
    assert available_backends() == ("manual", "sam2.1", "sam3.1")


def test_unknown_backend_rejected() -> None:
    with pytest.raises(KeyError, match="unknown segmentation backend"):
        create_backend("sam3")


def test_sam31_reports_pinned_provenance_identity() -> None:
    backend = create_backend("sam3.1")
    identity = backend.identity()
    assert identity.name == "sam3.1"
    assert identity.source_repository == "https://github.com/facebookresearch/sam3.git"
    assert identity.source_commit == "20dba30a35a497606b06cf241f5b5605ea10e77e"
    assert (
        identity.checkpoint_sha256
        == "0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6"
    )
    # identity is the provenance record downstream consumers embed
    dumped = identity.model_dump()
    assert dumped["source_commit"] == identity.source_commit
    assert dumped["checkpoint_sha256"] == identity.checkpoint_sha256


def test_sam31_refuses_without_checkpoint(tmp_path: Path) -> None:
    backend = create_backend(
        "sam3.1", checkpoint_path=tmp_path / "sam3.1_multiplex.pt"
    )
    problems = backend.check_environment()
    assert any("missing checkpoint" in problem for problem in problems)
    request = SegmentationRequest(
        run_id="sam31-run-001",
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
    with pytest.raises(BackendUnavailableError, match="missing checkpoint"):
        backend.segment_image(tmp_path, request)
    with pytest.raises(BackendUnavailableError, match="missing checkpoint"):
        backend.propagate_video(tmp_path, request)


def test_sam31_refuses_on_checkpoint_hash_mismatch(tmp_path: Path) -> None:
    fake_checkpoint = tmp_path / "sam3.1_multiplex.pt"
    fake_checkpoint.write_bytes(b"not the official sam3.1 checkpoint")
    backend = create_backend("sam3.1", checkpoint_path=fake_checkpoint)
    problems = backend.check_environment()
    assert any("checkpoint hash mismatch" in problem for problem in problems)
    assert any("checkpoint size mismatch" in problem for problem in problems)
    request = SegmentationRequest(
        run_id="sam31-run-002",
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
    with pytest.raises(BackendUnavailableError, match="checkpoint hash mismatch"):
        backend.segment_image(tmp_path, request)


def test_sam31_never_claims_availability_in_base_environment() -> None:
    backend = create_backend("sam3.1")
    assert backend.capabilities().requires_gpu
    assert not backend.capabilities().authoritative_for_approval
    assert backend.check_environment()  # never empty in the base environment


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
