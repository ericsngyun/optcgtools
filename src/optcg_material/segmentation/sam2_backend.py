"""SAM 2.1 backend adapter — the reproducible baseline.

Delegates to the existing pinned implementation in
``optcg_material.sam2_backend`` without changing its behavior.
"""

from __future__ import annotations

from pathlib import Path

from ..sam2_backend import (
    Sam2Settings,
    Sam2UnavailableError,
    run_image_segmentation,
    run_video_segmentation,
)
from ..semantic import (
    SAM2_PINNED_COMMIT,
    SAM2_REPOSITORY,
    MaskProposal,
    SegmentationRequest,
)
from .base import (
    BackendCapabilities,
    BackendIdentity,
    BackendUnavailableError,
    SegmentationBackend,
)


class Sam2Backend(SegmentationBackend):
    name = "sam2.1"

    def __init__(self, settings: Sam2Settings) -> None:
        self.settings = settings

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            image_segmentation=True,
            video_propagation=True,
            prompt_points=True,
            prompt_boxes=True,
            prompt_masks=True,
            reports_uncertainty=True,
            requires_gpu=False,  # CPU-capable, but slow; GPU work runs in a separate environment
        )

    def identity(self) -> BackendIdentity:
        return BackendIdentity(
            name=self.name,
            source_repository=SAM2_REPOSITORY,
            source_commit=SAM2_PINNED_COMMIT,
            checkpoint_path=str(self.settings.checkpoint_path),
            device=self.settings.device,
        )

    def check_environment(self) -> list[str]:
        problems: list[str] = []
        try:
            from ..sam2_backend import _import_sam2

            _import_sam2()
        except Sam2UnavailableError as exc:
            problems.append(str(exc))
        if not Path(self.settings.checkpoint_path).is_file():
            problems.append(f"missing checkpoint: {self.settings.checkpoint_path}")
        return problems

    def segment_image(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]:
        try:
            run = run_image_segmentation(session_root, request, self.settings)
        except Sam2UnavailableError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        return run.proposals

    def propagate_video(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]:
        try:
            run = run_video_segmentation(session_root, request, self.settings)
        except Sam2UnavailableError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        return run.proposals
