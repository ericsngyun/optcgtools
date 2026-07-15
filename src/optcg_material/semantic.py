from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

import cv2
import numpy as np
from blake3 import blake3
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SAM2_REPOSITORY = "https://github.com/facebookresearch/sam2.git"
SAM2_PINNED_COMMIT = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
SEGMENTATION_SCHEMA_VERSION = "1.0.0"
REGION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,95}$")


class SemanticError(RuntimeError):
    """Raised when semantic proposals or review artifacts are invalid."""


class SemanticRegion(StrEnum):
    CHARACTER = "character"
    BACKGROUND = "background"
    MANGA_PANEL = "manga-panel"
    FRAME = "frame"
    BORDER = "border"
    TITLE_PLATE = "title-plate"
    COST = "cost"
    POWER = "power"
    ICONS = "icons"
    RULES_TEXT = "rules-text"
    BLACK_INK = "black-ink"
    GOLD_LINEWORK = "gold-linework"
    METALLIC_ORNAMENT = "metallic-ornament"
    FOIL_FIELD = "foil-field"
    OTHER = "other"


class RunStatus(StrEnum):
    PROPOSED = "proposed"
    REVIEW_IN_PROGRESS = "review-in-progress"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class CorrectionOperation(StrEnum):
    REPLACE = "replace"
    UNION = "union"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PromptPoint(StrictModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    foreground: bool = True


class PromptBox(StrictModel):
    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(gt=0)
    y_max: float = Field(gt=0)

    @model_validator(mode="after")
    def box_must_have_positive_area(self) -> PromptBox:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("prompt box must have positive width and height")
        return self


class RegionPrompt(StrictModel):
    region_id: str
    semantic_region: SemanticRegion
    frame_index: int = Field(default=0, ge=0)
    object_id: str | None = Field(default=None, max_length=96)
    points: list[PromptPoint] = Field(default_factory=list)
    box: PromptBox | None = None
    mask_input_path: str | None = None
    multimask_output: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("region_id")
    @classmethod
    def validate_region_id(cls, value: str) -> str:
        if not REGION_ID_PATTERN.fullmatch(value):
            raise ValueError("region_id must be a lowercase slug")
        return value

    @field_validator("mask_input_path")
    @classmethod
    def validate_mask_input_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return safe_relative_path(value)

    @model_validator(mode="after")
    def prompt_requires_input(self) -> RegionPrompt:
        if not self.points and self.box is None and self.mask_input_path is None:
            raise ValueError("region prompt needs points, a box, or a previous mask input")
        if self.object_id is None:
            self.object_id = self.region_id
        return self


class SegmentationRequest(StrictModel):
    schema_version: str = SEGMENTATION_SCHEMA_VERSION
    run_id: str
    session_id: str
    mode: Annotated[str, Field(pattern=r"^(image|video)$")]
    source_path: str
    output_directory: str = "processed/semantic"
    prompts: list[RegionPrompt]
    source_frame_paths: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("run_id", "session_id")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if not REGION_ID_PATTERN.fullmatch(value):
            raise ValueError("run_id and session_id must be lowercase slugs")
        return value

    @field_validator("source_path", "output_directory")
    @classmethod
    def validate_paths(cls, value: str) -> str:
        return safe_relative_path(value)

    @field_validator("source_frame_paths")
    @classmethod
    def validate_frame_paths(cls, values: list[str]) -> list[str]:
        return [safe_relative_path(value) for value in values]

    @model_validator(mode="after")
    def prompt_ids_must_be_unique(self) -> SegmentationRequest:
        identities = [(prompt.frame_index, prompt.region_id) for prompt in self.prompts]
        if len(identities) != len(set(identities)):
            raise ValueError("region prompts must be unique by frame_index and region_id")
        if self.mode == "image" and any(prompt.frame_index != 0 for prompt in self.prompts):
            raise ValueError("image segmentation prompts must use frame_index=0")
        return self


class ModelProvenance(StrictModel):
    backend: str = "sam2.1"
    repository: str = SAM2_REPOSITORY
    repository_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] = SAM2_PINNED_COMMIT
    config_path: str
    checkpoint_path: str
    checkpoint_blake3: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    device: str
    torch_version: str
    sam2_version: str | None = None
    vos_optimized: bool = False
    offload_video_to_cpu: bool = True
    offload_state_to_cpu: bool = False

    @field_validator("config_path", "checkpoint_path")
    @classmethod
    def validate_model_paths(cls, value: str) -> str:
        return safe_relative_or_local_path(value)


class MaskProposal(StrictModel):
    proposal_id: str
    region_id: str
    semantic_region: SemanticRegion
    object_id: str
    frame_index: int = Field(ge=0)
    source_frame_path: str
    mask_path: str
    uncertainty_path: str
    low_res_logits_path: str | None = None
    predicted_iou: float | None = Field(default=None, ge=-1, le=1)
    mean_uncertainty: float = Field(ge=0, le=1)
    foreground_ratio: float = Field(ge=0, le=1)
    prompt_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    mask_blake3: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    uncertainty_blake3: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator(
        "source_frame_path",
        "mask_path",
        "uncertainty_path",
        "low_res_logits_path",
    )
    @classmethod
    def validate_artifact_paths(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return safe_relative_path(value)


class MaskCorrection(StrictModel):
    correction_id: str
    proposal_id: str
    operation: CorrectionOperation
    correction_mask_path: str
    output_mask_path: str
    reviewer: str = Field(min_length=1, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notes: str | None = Field(default=None, max_length=2000)
    correction_mask_blake3: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None
    output_mask_blake3: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None

    @field_validator("correction_id", "proposal_id")
    @classmethod
    def validate_correction_slug(cls, value: str) -> str:
        if not REGION_ID_PATTERN.fullmatch(value):
            raise ValueError("correction_id and proposal_id must be lowercase slugs")
        return value

    @field_validator("correction_mask_path", "output_mask_path")
    @classmethod
    def validate_correction_paths(cls, value: str) -> str:
        return safe_relative_path(value)


class SegmentationRun(StrictModel):
    schema_version: str = SEGMENTATION_SCHEMA_VERSION
    run_id: str
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: RunStatus = RunStatus.PROPOSED
    request_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    model: ModelProvenance
    proposals: list[MaskProposal] = Field(default_factory=list)
    corrections: list[MaskCorrection] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=4000)


def safe_relative_path(value: str) -> str:
    if "\\" in value or "://" in value:
        raise ValueError("artifact paths must be repository-style relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("~"):
        raise ValueError("artifact paths must remain inside the session root")
    if not value or value.endswith("/"):
        raise ValueError("artifact path must point to a file or explicit directory name")
    return path.as_posix()


def safe_relative_or_local_path(value: str) -> str:
    if "://" in value:
        raise ValueError("model paths may not be remote URLs")
    if not value:
        raise ValueError("model path may not be empty")
    return value


def canonical_digest(payload: BaseModel | dict[str, Any]) -> str:
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json", exclude_none=True)
    else:
        data = payload
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return blake3(encoded).hexdigest()


def file_digest(path: Path) -> str:
    digest = blake3()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def uncertainty_from_logits(logits: np.ndarray) -> np.ndarray:
    clipped = np.clip(logits.astype(np.float32), -20.0, 20.0)
    probabilities = 1.0 / (1.0 + np.exp(-clipped))
    uncertainty = 1.0 - (2.0 * np.abs(probabilities - 0.5))
    return np.clip(uncertainty, 0.0, 1.0)


def write_mask(path: Path, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded_mask = mask.astype(bool).astype(np.uint8) * 255
    success, encoded = cv2.imencode(".png", encoded_mask)
    if not success:
        raise SemanticError(f"unable to encode mask: {path}")
    encoded.tofile(path)


def write_uncertainty(path: Path, uncertainty: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded_uncertainty = np.round(np.clip(uncertainty, 0, 1) * 255).astype(np.uint8)
    success, encoded = cv2.imencode(".png", encoded_uncertainty)
    if not success:
        raise SemanticError(f"unable to encode uncertainty: {path}")
    encoded.tofile(path)


def read_binary_mask(path: Path, expected_shape: tuple[int, int] | None = None) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise SemanticError(f"unable to decode mask: {path}")
    if expected_shape is not None and image.shape != expected_shape:
        image = cv2.resize(
            image,
            (expected_shape[1], expected_shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
    return image > 127


def apply_mask_correction(
    session_root: Path,
    proposal_mask_path: str,
    correction: MaskCorrection,
) -> MaskCorrection:
    proposal_path = session_root / safe_relative_path(proposal_mask_path)
    correction_path = session_root / correction.correction_mask_path
    output_path = session_root / correction.output_mask_path

    proposal = read_binary_mask(proposal_path)
    reviewed = read_binary_mask(correction_path, expected_shape=proposal.shape)

    if correction.operation is CorrectionOperation.REPLACE:
        output = reviewed
    elif correction.operation is CorrectionOperation.UNION:
        output = np.logical_or(proposal, reviewed)
    elif correction.operation is CorrectionOperation.SUBTRACT:
        output = np.logical_and(proposal, np.logical_not(reviewed))
    elif correction.operation is CorrectionOperation.INTERSECT:
        output = np.logical_and(proposal, reviewed)
    else:
        raise SemanticError(f"unsupported correction operation: {correction.operation}")

    write_mask(output_path, output)
    correction.correction_mask_blake3 = file_digest(correction_path)
    correction.output_mask_blake3 = file_digest(output_path)
    return correction


def load_request(path: Path) -> SegmentationRequest:
    return SegmentationRequest.model_validate_json(path.read_text(encoding="utf-8"))


def save_run(path: Path, run: SegmentationRun) -> None:
    run.updated_at = datetime.now(UTC)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(run.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    temporary.replace(path)
