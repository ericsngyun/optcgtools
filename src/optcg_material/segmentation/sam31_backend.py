"""SAM 3.1 backend — the pinned optional challenger.

Official-release verification (performed 2026-07-16, plain ``git ls-remote``
and public GitHub / Hugging Face REST APIs, no browser impersonation):

- ``git ls-remote https://github.com/facebookresearch/sam3.git`` shows branch
  ``refs/heads/sam3.1`` at ``20dba30a35a497606b06cf241f5b5605ea10e77e``
  (commit "SAM 3.1 Release", committed 2026-03-27T16:42:44Z). Repository
  ``main`` README ("Latest updates", 03/27/2026) announces the SAM 3.1 Object
  Multiplex release with checkpoints on Hugging Face ``facebook/sam3.1`` and
  details in ``RELEASE_SAM3p1.md``.
- ``https://api.github.com/repos/facebookresearch/segment-anything-3`` /
  ``git ls-remote`` for that name: repository does not exist.
- ``git ls-remote https://github.com/facebookresearch/sam2.git`` has no 3.x
  tags or branches.
- ``https://huggingface.co/api/models/facebook/sam3.1?blobs=true`` (official
  Meta org; repo is gated "manual") publishes the checkpoint file
  ``sam3.1_multiplex.pt`` with LFS sha256
  ``0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6`` and
  size 3502755717 bytes at HF revision
  ``daa63191845a41281374e725f4c9e51c7a824460``.

Policy (AGENTS.md / docs/agent-ops): SAM 2.1 remains the reproducible
baseline. This backend is hash-gated: it refuses to run unless the locally
present checkpoint's sha256 matches the published pin above. The checkpoint
itself is gated on Hugging Face (manual access request) and must be fetched
by a human with an authenticated account — agents never automate around
access controls.

Optional runtime dependencies (never installed into the base macOS
environment; per the official repository install docs they require Python
>= 3.12, PyTorch >= 2.7 with CUDA >= 12.6, and the ``sam3`` package from the
pinned source revision): the inference adapter therefore only activates in a
separate CUDA challenger environment. Until that environment plus the shared
reviewed-mask benchmark harness exist, ``segment_image``/``propagate_video``
refuse with an explicit reason even when the pins verify — refusal is honest;
pretended capability is not. Segmentation output remains a semantic prior:
masks, prompts, uncertainty, and provenance only — no appearance or material
claims.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..semantic import MaskProposal, SegmentationRequest
from .base import (
    BackendCapabilities,
    BackendIdentity,
    BackendUnavailableError,
    SegmentationBackend,
)

# Provenance: git ls-remote https://github.com/facebookresearch/sam3.git,
# retrieved 2026-07-16. refs/heads/sam3.1 head, commit "SAM 3.1 Release"
# (2026-03-27T16:42:44Z), announced in the repository README and
# RELEASE_SAM3p1.md.
SAM31_REPOSITORY = "https://github.com/facebookresearch/sam3.git"
SAM31_PINNED_COMMIT = "20dba30a35a497606b06cf241f5b5605ea10e77e"

# Provenance: https://huggingface.co/api/models/facebook/sam3.1?blobs=true,
# retrieved 2026-07-16. Official Meta Hugging Face org, gated repository
# (manual access approval); LFS pointer for sam3.1_multiplex.pt states the
# sha256 and byte size below at HF revision
# daa63191845a41281374e725f4c9e51c7a824460.
SAM31_CHECKPOINT_HF_REPO = "facebook/sam3.1"
SAM31_CHECKPOINT_HF_REVISION = "daa63191845a41281374e725f4c9e51c7a824460"
SAM31_CHECKPOINT_FILENAME = "sam3.1_multiplex.pt"
SAM31_CHECKPOINT_SHA256 = "0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6"
SAM31_CHECKPOINT_SIZE_BYTES = 3502755717

_INFERENCE_NOT_WIRED = (
    "sam3.1 inference is not wired into the base environment: it requires the "
    "optional CUDA challenger environment (Python>=3.12, PyTorch>=2.7 with "
    "CUDA>=12.6, sam3 package at the pinned revision) and the shared "
    "reviewed-mask benchmark harness; use the sam2.1 baseline"
)


class Sam31Backend(SegmentationBackend):
    """Pinned SAM 3.1 challenger; refuses to run until provenance verifies."""

    name = "sam3.1"

    def __init__(
        self,
        checkpoint_path: str | Path = Path("checkpoints") / SAM31_CHECKPOINT_FILENAME,
        device: str = "cuda",
    ) -> None:
        self.checkpoint_path = Path(checkpoint_path)
        self.device = device

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            image_segmentation=True,
            video_propagation=True,
            prompt_points=True,
            prompt_boxes=True,
            prompt_masks=True,
            reports_uncertainty=True,
            requires_gpu=True,  # official install requires a CUDA >= 12.6 GPU
        )

    def identity(self) -> BackendIdentity:
        """Declared pinned identity; this is the provenance record consumers embed.

        Local checkpoint verification happens in ``check_environment`` and is
        enforced again before any run.
        """
        return BackendIdentity(
            name=self.name,
            version="sam3.1-object-multiplex-2026-03-27",
            source_repository=SAM31_REPOSITORY,
            source_commit=SAM31_PINNED_COMMIT,
            checkpoint_path=str(self.checkpoint_path),
            checkpoint_sha256=SAM31_CHECKPOINT_SHA256,
            device=self.device,
        )

    def check_environment(self) -> list[str]:
        problems: list[str] = []
        try:
            import sam3  # noqa: F401  # optional dependency, CUDA environment only
        except ImportError:
            problems.append(
                "sam3 package is not importable: install it only in the optional "
                f"CUDA challenger environment from {SAM31_REPOSITORY} at pinned "
                f"commit {SAM31_PINNED_COMMIT}; never into the base environment"
            )
        problems.extend(self._verify_checkpoint())
        if not problems:
            problems.append(_INFERENCE_NOT_WIRED)
        return problems

    def _verify_checkpoint(self) -> list[str]:
        """Compare the local checkpoint against the published official pin."""
        if not self.checkpoint_path.is_file():
            return [
                f"missing checkpoint: {self.checkpoint_path} (request access to "
                f"{SAM31_CHECKPOINT_HF_REPO} on Hugging Face and download "
                f"{SAM31_CHECKPOINT_FILENAME} manually; the repo is gated)"
            ]
        problems: list[str] = []
        size = self.checkpoint_path.stat().st_size
        if size != SAM31_CHECKPOINT_SIZE_BYTES:
            problems.append(
                f"checkpoint size mismatch: expected {SAM31_CHECKPOINT_SIZE_BYTES} "
                f"bytes, found {size} bytes at {self.checkpoint_path}"
            )
        digest = hashlib.sha256()
        with self.checkpoint_path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        local_sha256 = digest.hexdigest()
        if local_sha256 != SAM31_CHECKPOINT_SHA256:
            problems.append(
                f"checkpoint hash mismatch: expected sha256 {SAM31_CHECKPOINT_SHA256}, "
                f"computed {local_sha256} for {self.checkpoint_path}; refusing to run "
                "on an unverified checkpoint"
            )
        return problems

    def _refuse_unless_verified(self) -> None:
        problems = self.check_environment()
        if problems:
            raise BackendUnavailableError("; ".join(problems))

    def segment_image(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]:
        self._refuse_unless_verified()
        raise BackendUnavailableError(_INFERENCE_NOT_WIRED)

    def propagate_video(
        self, session_root: Path, request: SegmentationRequest
    ) -> list[MaskProposal]:
        self._refuse_unless_verified()
        raise BackendUnavailableError(_INFERENCE_NOT_WIRED)
