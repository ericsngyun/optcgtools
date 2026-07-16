"""Manual backend: reviewer-supplied masks.

Human-reviewed masks are the authoritative source for approved semantic
regions. This backend ingests reviewer-drawn masks (each prompt's
``mask_input_path``) into the standard proposal contract with zero model
uncertainty and full content hashing, so downstream tooling treats manual
and model output uniformly — approval still happens in the review ledger.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..semantic import (
    MaskProposal,
    SegmentationRequest,
    SemanticError,
    canonical_digest,
    file_digest,
    read_binary_mask,
    write_mask,
    write_uncertainty,
)
from .base import BackendCapabilities, BackendIdentity, SegmentationBackend


class ManualBackend(SegmentationBackend):
    name = "manual"

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            image_segmentation=True,
            video_propagation=False,
            prompt_masks=True,
            reports_uncertainty=True,
            authoritative_for_approval=True,
        )

    def identity(self) -> BackendIdentity:
        return BackendIdentity(name=self.name, version="reviewer-supplied")

    def check_environment(self) -> list[str]:
        return []

    def segment_image(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]:
        proposals: list[MaskProposal] = []
        output_root = session_root / request.output_directory / request.run_id
        for prompt in request.prompts:
            if prompt.mask_input_path is None:
                raise SemanticError(
                    f"manual backend requires mask_input_path for region '{prompt.region_id}'"
                )
            mask = read_binary_mask(session_root / prompt.mask_input_path)
            mask_path = output_root / f"{prompt.region_id}-mask.png"
            uncertainty_path = output_root / f"{prompt.region_id}-uncertainty.png"
            write_mask(mask_path, mask)
            write_uncertainty(uncertainty_path, np.zeros(mask.shape, dtype=np.float32))
            proposals.append(
                MaskProposal(
                    proposal_id=f"{request.run_id}-{prompt.region_id}",
                    region_id=prompt.region_id,
                    semantic_region=prompt.semantic_region,
                    object_id=prompt.object_id or prompt.region_id,
                    frame_index=prompt.frame_index,
                    source_frame_path=request.source_path,
                    mask_path=mask_path.relative_to(session_root).as_posix(),
                    uncertainty_path=uncertainty_path.relative_to(session_root).as_posix(),
                    mean_uncertainty=0.0,
                    foreground_ratio=float(mask.mean()),
                    prompt_digest=canonical_digest(prompt),
                    mask_blake3=file_digest(mask_path),
                    uncertainty_blake3=file_digest(uncertainty_path),
                )
            )
        return proposals

    def propagate_video(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]:
        raise SemanticError(
            "manual backend does not propagate video; draw or correct per-frame masks"
        )
