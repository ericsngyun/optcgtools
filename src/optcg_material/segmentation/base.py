"""Stable segmentation-backend interface.

SAM 2.1 (pinned) is the reproducible baseline; SAM 3 is an optional challenger;
reviewed manual masks are authoritative. Backends propose — they never approve.
Compare backends only on the same reviewed benchmark masks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..semantic import MaskProposal, SegmentationRequest


class BackendCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_segmentation: bool = False
    video_propagation: bool = False
    prompt_points: bool = False
    prompt_boxes: bool = False
    prompt_masks: bool = False
    reports_uncertainty: bool = False
    requires_gpu: bool = False
    authoritative_for_approval: bool = Field(
        default=False,
        description="Only reviewed human masks are authoritative; model backends never are.",
    )


class BackendIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str | None = None
    source_repository: str | None = None
    source_commit: str | None = None
    checkpoint_path: str | None = None
    checkpoint_blake3: str | None = None
    device: str | None = None


class BackendUnavailableError(RuntimeError):
    """Raised when a backend's environment or provenance cannot be satisfied."""


class SegmentationBackend(ABC):
    """Contract every segmentation backend implements.

    Implementations must persist full provenance (prompts, source commit,
    checkpoint hash, environment) with every proposal and must surface real
    uncertainty rather than fabricated crisp edges.
    """

    name: str

    @abstractmethod
    def capabilities(self) -> BackendCapabilities: ...

    @abstractmethod
    def identity(self) -> BackendIdentity:
        """Resolved model identity; raises BackendUnavailableError when the
        environment (imports, checkpoint, pinned commit) cannot be verified."""

    @abstractmethod
    def check_environment(self) -> list[str]:
        """Return human-readable environment problems; empty means usable."""

    @abstractmethod
    def segment_image(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]: ...

    @abstractmethod
    def propagate_video(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]: ...
