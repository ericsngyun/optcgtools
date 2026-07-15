from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SESSION_SCHEMA_VERSION = "1.0.0"


class CaptureKind(StrEnum):
    ALBEDO = "albedo"
    BACK = "back"
    TILT_X = "tilt-x"
    TILT_Y = "tilt-y"
    TILT_X_VIDEO = "tilt-x-video"
    TILT_Y_VIDEO = "tilt-y-video"
    LIGHT_HARD = "light-hard"
    LIGHT_SOFT = "light-soft"
    RAKE = "rake"
    MACRO = "macro"


class RightsStatus(StrEnum):
    OWNED_CAPTURE = "owned-capture"
    LICENSED = "licensed"
    RESTRICTED_RESEARCH = "restricted-research"
    UNKNOWN = "unknown"


class AuthenticationStatus(StrEnum):
    VERIFIED = "verified"
    PENDING = "pending"
    REJECTED = "rejected"


class Language(StrEnum):
    EN = "EN"
    JP = "JP"
    OTHER = "OTHER"


class CaptureDirection(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    FRONT = "front"
    NONE = "none"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CardIdentity(StrictModel):
    card_id: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    set_code: str = Field(min_length=2, max_length=32)
    rarity_label: str | None = Field(default=None, max_length=80)
    language: Language = Language.EN
    print_run: str | None = Field(default=None, max_length=120)
    finish_family_hypothesis: str | None = Field(default=None, max_length=120)


class CameraMetadata(StrictModel):
    operator: str = Field(min_length=1, max_length=160)
    camera_model: str | None = Field(default=None, max_length=160)
    lens: str | None = Field(default=None, max_length=160)
    focal_length_mm: float | None = Field(default=None, gt=0, le=1000)
    camera_distance_mm: float | None = Field(default=None, gt=0, le=10000)
    white_balance_kelvin: int | None = Field(default=None, ge=1500, le=15000)
    exposure_locked: bool = True
    focus_locked: bool = True
    raw_available: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class RightsMetadata(StrictModel):
    owner: str = Field(min_length=1, max_length=200)
    status: RightsStatus = RightsStatus.UNKNOWN
    public_derivatives_allowed: bool = False
    public_albedo_allowed: bool = False
    license_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class AuthenticationMetadata(StrictModel):
    status: AuthenticationStatus = AuthenticationStatus.PENDING
    method: str | None = Field(default=None, max_length=500)
    verifier: str | None = Field(default=None, max_length=160)
    verified_at: datetime | None = None
    evidence_reference: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def verified_requires_evidence(self) -> AuthenticationMetadata:
        if self.status is AuthenticationStatus.VERIFIED:
            if not self.method or not self.verifier:
                raise ValueError("verified authentication requires method and verifier")
        return self


class CaptureFile(StrictModel):
    path: str
    kind: CaptureKind
    blake3: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    bytes: int = Field(ge=1)
    media_type: str = Field(min_length=3, max_length=120)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    captured_at: datetime | None = None
    angle_degrees: float | None = Field(default=None, ge=-180, le=180)
    direction: CaptureDirection = CaptureDirection.NONE
    light_label: str | None = Field(default=None, max_length=120)
    source_filename: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def path_must_be_safe_and_relative(cls, value: str) -> str:
        if "\\" in value or "://" in value:
            raise ValueError("capture paths must be repository-style relative paths")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.startswith("~"):
            raise ValueError("capture paths must remain inside the session root")
        if not value or value.endswith("/"):
            raise ValueError("capture path must point to a file")
        return path.as_posix()


class CaptureSession(StrictModel):
    schema_version: str = SESSION_SCHEMA_VERSION
    session_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$")]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    card: CardIdentity
    camera: CameraMetadata
    rights: RightsMetadata
    authentication: AuthenticationMetadata
    files: list[CaptureFile] = Field(default_factory=list)
    pipeline_commit: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def files_must_be_unique(self) -> CaptureSession:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("capture file paths must be unique")
        hashes = [item.blake3 for item in self.files]
        if len(hashes) != len(set(hashes)):
            raise ValueError("duplicate file content is not allowed in one capture session")
        return self


class CompletenessRequirement(StrictModel):
    kind: CaptureKind
    minimum: int = Field(ge=0)
    alternatives: tuple[CaptureKind, ...] = ()


DEFAULT_COMPLETENESS_REQUIREMENTS: tuple[CompletenessRequirement, ...] = (
    CompletenessRequirement(kind=CaptureKind.ALBEDO, minimum=1),
    CompletenessRequirement(
        kind=CaptureKind.TILT_X,
        minimum=7,
        alternatives=(CaptureKind.TILT_X_VIDEO,),
    ),
    CompletenessRequirement(
        kind=CaptureKind.TILT_Y,
        minimum=7,
        alternatives=(CaptureKind.TILT_Y_VIDEO,),
    ),
    CompletenessRequirement(kind=CaptureKind.LIGHT_HARD, minimum=7),
    CompletenessRequirement(kind=CaptureKind.LIGHT_SOFT, minimum=3),
    CompletenessRequirement(kind=CaptureKind.RAKE, minimum=4),
    CompletenessRequirement(kind=CaptureKind.MACRO, minimum=4),
)


class CompletenessResult(StrictModel):
    valid: bool
    counts: dict[str, int]
    missing: list[str]


def validate_completeness(
    session: CaptureSession,
    requirements: tuple[CompletenessRequirement, ...] = DEFAULT_COMPLETENESS_REQUIREMENTS,
) -> CompletenessResult:
    counts: dict[str, int] = {}
    for item in session.files:
        counts[item.kind.value] = counts.get(item.kind.value, 0) + 1

    missing: list[str] = []
    for requirement in requirements:
        actual = counts.get(requirement.kind.value, 0)
        alternative_satisfied = any(counts.get(kind.value, 0) > 0 for kind in requirement.alternatives)
        if actual < requirement.minimum and not alternative_satisfied:
            alternatives = ", ".join(kind.value for kind in requirement.alternatives)
            suffix = f" or one of [{alternatives}]" if alternatives else ""
            missing.append(
                f"{requirement.kind.value}: need {requirement.minimum}, found {actual}{suffix}"
            )

    if session.authentication.status is not AuthenticationStatus.VERIFIED:
        missing.append("authentication: session is not verified")
    if session.rights.status is RightsStatus.UNKNOWN:
        missing.append("rights: rights status is unknown")

    return CompletenessResult(valid=not missing, counts=counts, missing=missing)
