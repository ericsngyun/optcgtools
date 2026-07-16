"""SAM 3 backend — optional challenger, intentionally unavailable.

Policy (AGENTS.md / docs/agent-ops): SAM 2.1 stays the reproducible baseline.
A SAM 3 implementation may only be added when an official Meta source
repository and checkpoint can be independently verified and pinned, and it
must be benchmarked against the same reviewed masks as SAM 2.1. Until then
this backend reports itself unavailable instead of pretending capability.
"""

from __future__ import annotations

from pathlib import Path

from ..semantic import MaskProposal, SegmentationRequest
from .base import (
    BackendCapabilities,
    BackendIdentity,
    BackendUnavailableError,
    SegmentationBackend,
)

_UNAVAILABLE = (
    "sam3 backend is a placeholder: no independently verified official source "
    "and pinned checkpoint have been recorded yet; use the sam2.1 baseline"
)


class Sam3Backend(SegmentationBackend):
    name = "sam3"

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(requires_gpu=True)

    def identity(self) -> BackendIdentity:
        raise BackendUnavailableError(_UNAVAILABLE)

    def check_environment(self) -> list[str]:
        return [_UNAVAILABLE]

    def segment_image(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]:
        raise BackendUnavailableError(_UNAVAILABLE)

    def propagate_video(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]:
        raise BackendUnavailableError(_UNAVAILABLE)
