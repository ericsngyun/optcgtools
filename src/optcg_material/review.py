from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import AuthenticationStatus, RightsStatus
from .provenance import load_manifest
from .semantic import canonical_digest

REVIEW_SCHEMA_VERSION = "1.0.0"
REVIEW_LOG_RELATIVE_PATH = "review/review-log.jsonl"
EVENT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{7,63}$"

PUBLISHABLE_CONFIDENCE = ("capture-validated", "production-validated")
FORBIDDEN_ASSET_PATH_PARTS = ("raw", "private-references", "source")


class ReviewError(RuntimeError):
    """Raised when review events or publication gates are invalid."""


class ReviewItem(StrEnum):
    CARD_IDENTITY = "card-identity"
    CAPTURE_QUALITY = "capture-quality"
    REGISTRATION = "registration"
    SEMANTIC_MASKS = "semantic-masks"
    MATERIAL_MAPS = "material-maps"
    MATCHED_RENDERS = "matched-renders"
    RIGHTS = "rights"
    PRODUCTION_PROFILE = "production-profile"


TECHNICAL_ITEMS: tuple[ReviewItem, ...] = (
    ReviewItem.CARD_IDENTITY,
    ReviewItem.CAPTURE_QUALITY,
    ReviewItem.REGISTRATION,
    ReviewItem.SEMANTIC_MASKS,
    ReviewItem.MATERIAL_MAPS,
    ReviewItem.MATCHED_RENDERS,
)


class ReviewAction(StrEnum):
    OPEN_REVIEW = "open-review"
    COMMENT = "comment"
    RESOLVE_COMMENT = "resolve-comment"
    APPROVE_ITEM = "approve-item"
    REJECT_ITEM = "reject-item"
    APPROVE_TECHNICAL = "approve-technical"
    APPROVE_RIGHTS = "approve-rights"
    APPROVE_PRODUCTION = "approve-production"
    REVOKE_APPROVAL = "revoke-approval"


APPROVAL_ACTIONS: tuple[ReviewAction, ...] = (
    ReviewAction.APPROVE_TECHNICAL,
    ReviewAction.APPROVE_RIGHTS,
    ReviewAction.APPROVE_PRODUCTION,
)


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    NEEDS_REVISION = "needs-revision"
    TECHNICALLY_APPROVED = "technically-approved"
    RIGHTS_APPROVED = "rights-approved"
    PRODUCTION_APPROVED = "production-approved"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ReviewEvent(StrictModel):
    schema_version: str = REVIEW_SCHEMA_VERSION
    event_id: Annotated[str, Field(pattern=EVENT_ID_PATTERN)]
    sequence: int = Field(ge=0)
    session_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$")]
    reviewer: str = Field(min_length=1, max_length=160)
    action: ReviewAction
    item: ReviewItem | None = None
    channel: str | None = Field(default=None, max_length=64)
    profile_version: str | None = Field(default=None, max_length=160)
    comment: str | None = Field(default=None, max_length=4000)
    requires_resolution: bool = False
    target_event_id: Annotated[str | None, Field(pattern=EVENT_ID_PATTERN)] = None
    before_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None
    after_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previous_event_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None
    event_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None

    @field_validator("reviewer")
    @classmethod
    def reviewer_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reviewer must be a named human, not whitespace")
        return value

    @model_validator(mode="after")
    def action_specific_fields(self) -> ReviewEvent:
        if self.action in (ReviewAction.APPROVE_ITEM, ReviewAction.REJECT_ITEM) and self.item is None:
            raise ValueError(f"{self.action} requires an item")
        if self.action is ReviewAction.COMMENT and not (self.comment and self.comment.strip()):
            raise ValueError("comment events require a non-empty comment")
        if (
            self.action in (ReviewAction.RESOLVE_COMMENT, ReviewAction.REVOKE_APPROVAL)
            and self.target_event_id is None
        ):
            raise ValueError(f"{self.action} requires target_event_id")
        if self.action is ReviewAction.REJECT_ITEM and not (self.comment and self.comment.strip()):
            raise ValueError("rejections must explain what needs revision")
        return self

    def content_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        payload.pop("event_digest", None)
        return canonical_digest(payload)


class ItemDecision(StrictModel):
    item: ReviewItem
    approved: bool
    reviewer: str
    event_id: str
    sequence: int


class ApprovalRecord(StrictModel):
    action: ReviewAction
    reviewer: str
    event_id: str
    sequence: int
    active: bool
    invalidated_by: str | None = None


class ReviewStatusReport(StrictModel):
    session_id: str
    state: ReviewState
    event_count: int
    head_digest: str | None
    item_decisions: dict[str, ItemDecision] = Field(default_factory=dict)
    unresolved_required_comments: list[str] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)


class PublicationReport(StrictModel):
    passed: bool
    state: ReviewState
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    profile_digest: str | None = None
    ledger_head_digest: str | None = None
    checked_assets: dict[str, str] = Field(default_factory=dict)


def review_log_path(session_root: Path) -> Path:
    return session_root / REVIEW_LOG_RELATIVE_PATH


def new_event_id() -> str:
    return f"rev-{uuid.uuid4().hex}"


def load_ledger(session_root: Path, *, verify: bool = True) -> list[ReviewEvent]:
    path = review_log_path(session_root)
    if not path.is_file():
        return []
    events: list[ReviewEvent] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(ReviewEvent.model_validate_json(line))
        except ValueError as exc:
            raise ReviewError(f"invalid review event on line {line_number}: {exc}") from exc
    if verify:
        verify_ledger(events)
    return events


def verify_ledger(events: list[ReviewEvent]) -> None:
    previous_digest: str | None = None
    for index, event in enumerate(events):
        if event.sequence != index:
            raise ReviewError(
                f"review ledger sequence break at index {index}: got {event.sequence}"
            )
        if event.previous_event_digest != previous_digest:
            raise ReviewError(f"review ledger chain break at sequence {index}")
        expected = event.content_digest()
        if event.event_digest != expected:
            raise ReviewError(
                f"review event {event.event_id} digest mismatch: ledger was modified"
            )
        previous_digest = event.event_digest


def append_event(
    session_root: Path,
    *,
    reviewer: str,
    action: ReviewAction,
    item: ReviewItem | None = None,
    channel: str | None = None,
    profile_version: str | None = None,
    comment: str | None = None,
    requires_resolution: bool = False,
    target_event_id: str | None = None,
    before_digest: str | None = None,
    after_digest: str | None = None,
) -> ReviewEvent:
    session = load_manifest(session_root)
    events = load_ledger(session_root)
    _guard_action(
        events,
        action=action,
        item=item,
        target_event_id=target_event_id,
    )

    previous_digest = events[-1].event_digest if events else None
    event = ReviewEvent(
        event_id=new_event_id(),
        sequence=len(events),
        session_id=session.session_id,
        reviewer=reviewer,
        action=action,
        item=item,
        channel=channel,
        profile_version=profile_version,
        comment=comment,
        requires_resolution=requires_resolution,
        target_event_id=target_event_id,
        before_digest=before_digest,
        after_digest=after_digest,
        previous_event_digest=previous_digest,
    )
    event.event_digest = event.content_digest()

    path = review_log_path(session_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json(exclude_none=True) + "\n")
        handle.flush()
    return event


def _guard_action(
    events: list[ReviewEvent],
    *,
    action: ReviewAction,
    item: ReviewItem | None,
    target_event_id: str | None,
) -> None:
    report = _analyze(events)

    if action is ReviewAction.RESOLVE_COMMENT:
        by_id = {event.event_id: event for event in events}
        target = by_id.get(target_event_id or "")
        if target is None or target.action is not ReviewAction.COMMENT:
            raise ReviewError("resolve-comment must target an existing comment event")
        if not target.requires_resolution:
            raise ReviewError("resolve-comment target does not require resolution")
        if target_event_id not in report.unresolved_required_comments:
            raise ReviewError("comment is already resolved")

    if action is ReviewAction.REVOKE_APPROVAL:
        approvals = {record.event_id: record for record in report.approvals}
        record = approvals.get(target_event_id or "")
        if record is None:
            raise ReviewError("revoke-approval must target an approval event")
        if not record.active:
            raise ReviewError("approval is already inactive")

    if action is ReviewAction.APPROVE_TECHNICAL:
        _require_clean(report)
        missing = [
            technical_item.value
            for technical_item in TECHNICAL_ITEMS
            if not _item_approved(report, technical_item)
        ]
        if missing:
            raise ReviewError(
                "technical approval requires approved items; missing: " + ", ".join(missing)
            )

    if action is ReviewAction.APPROVE_RIGHTS:
        _require_clean(report)
        if not _item_approved(report, ReviewItem.RIGHTS):
            raise ReviewError("rights approval requires an approved rights item")

    if action is ReviewAction.APPROVE_PRODUCTION:
        _require_clean(report)
        if not _item_approved(report, ReviewItem.PRODUCTION_PROFILE):
            raise ReviewError("production approval requires an approved production-profile item")
        if not _approval_active(report, ReviewAction.APPROVE_TECHNICAL):
            raise ReviewError("production approval requires an active technical approval")
        if not _approval_active(report, ReviewAction.APPROVE_RIGHTS):
            raise ReviewError("production approval requires an active rights approval")


def _require_clean(report: ReviewStatusReport) -> None:
    rejected = [
        decision.item.value
        for decision in report.item_decisions.values()
        if not decision.approved
    ]
    if rejected:
        raise ReviewError("approval blocked by rejected items: " + ", ".join(sorted(rejected)))
    if report.unresolved_required_comments:
        raise ReviewError(
            "approval blocked by unresolved required comments: "
            + ", ".join(report.unresolved_required_comments)
        )


def _item_approved(report: ReviewStatusReport, item: ReviewItem) -> bool:
    decision = report.item_decisions.get(item.value)
    return decision is not None and decision.approved


def _approval_active(report: ReviewStatusReport, action: ReviewAction) -> bool:
    return any(record.action is action and record.active for record in report.approvals)


def _analyze(events: list[ReviewEvent]) -> ReviewStatusReport:
    session_id = events[0].session_id if events else "unknown"
    item_decisions: dict[str, ItemDecision] = {}
    unresolved: dict[str, ReviewEvent] = {}
    approvals: list[ApprovalRecord] = []

    for event in events:
        if event.action in (ReviewAction.APPROVE_ITEM, ReviewAction.REJECT_ITEM) and event.item:
            item_decisions[event.item.value] = ItemDecision(
                item=event.item,
                approved=event.action is ReviewAction.APPROVE_ITEM,
                reviewer=event.reviewer,
                event_id=event.event_id,
                sequence=event.sequence,
            )
        elif event.action is ReviewAction.COMMENT and event.requires_resolution:
            unresolved[event.event_id] = event
        elif event.action is ReviewAction.RESOLVE_COMMENT and event.target_event_id:
            unresolved.pop(event.target_event_id, None)
        elif event.action in APPROVAL_ACTIONS:
            approvals.append(
                ApprovalRecord(
                    action=event.action,
                    reviewer=event.reviewer,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    active=True,
                )
            )
        elif event.action is ReviewAction.REVOKE_APPROVAL and event.target_event_id:
            for record in approvals:
                if record.event_id == event.target_event_id and record.active:
                    record.active = False
                    record.invalidated_by = event.event_id

        # Any regression after an approval means the approval no longer covers
        # the reviewed state: the reviewer must approve again.
        if event.action is ReviewAction.REJECT_ITEM or (
            event.action is ReviewAction.COMMENT and event.requires_resolution
        ):
            for record in approvals:
                if record.active and record.sequence < event.sequence:
                    record.active = False
                    record.invalidated_by = event.event_id

    return ReviewStatusReport(
        session_id=session_id,
        state=ReviewState.UNREVIEWED,
        event_count=len(events),
        head_digest=events[-1].event_digest if events else None,
        item_decisions=item_decisions,
        unresolved_required_comments=sorted(unresolved),
        approvals=approvals,
    )


def derive_status(events: list[ReviewEvent]) -> ReviewStatusReport:
    report = _analyze(events)
    rejected = any(not decision.approved for decision in report.item_decisions.values())
    dirty = rejected or bool(report.unresolved_required_comments)

    technical = _approval_active(report, ReviewAction.APPROVE_TECHNICAL)
    rights = _approval_active(report, ReviewAction.APPROVE_RIGHTS)
    production = _approval_active(report, ReviewAction.APPROVE_PRODUCTION)

    if dirty:
        state = ReviewState.NEEDS_REVISION
    elif production and technical and rights:
        state = ReviewState.PRODUCTION_APPROVED
    elif technical and rights:
        state = ReviewState.RIGHTS_APPROVED
    elif technical:
        state = ReviewState.TECHNICALLY_APPROVED
    else:
        state = ReviewState.UNREVIEWED

    report.state = state
    return report


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_uri_is_safe(uri: str) -> bool:
    if "://" in uri or uri.startswith("//"):
        return True  # remote delivery URI; hash check is skipped with a warning
    if "\\" in uri or uri.startswith(("/", "~")):
        return False
    parts = PurePosixPath(uri).parts
    if ".." in parts:
        return False
    return not any(part in FORBIDDEN_ASSET_PATH_PARTS for part in parts)


def check_publication(
    session_root: Path,
    profile_path: Path,
    schema_path: Path,
    *,
    assets_root: Path | None = None,
) -> PublicationReport:
    errors: list[str] = []
    warnings: list[str] = []
    checked_assets: dict[str, str] = {}
    state = ReviewState.UNREVIEWED
    head_digest: str | None = None

    try:
        events = load_ledger(session_root)
        status = derive_status(events)
        state = status.state
        head_digest = status.head_digest
        if state is not ReviewState.PRODUCTION_APPROVED:
            errors.append(f"review state is '{state}', publication requires 'production-approved'")
    except (ReviewError, OSError) as exc:
        errors.append(f"review ledger failed verification: {exc}")

    try:
        session = load_manifest(session_root)
        if session.authentication.status is not AuthenticationStatus.VERIFIED:
            errors.append("capture session authentication is not verified")
        if session.rights.status is RightsStatus.UNKNOWN:
            errors.append("capture session rights status is unknown")
        if not session.rights.public_derivatives_allowed:
            errors.append("rights record does not allow public derivatives")
    except Exception as exc:  # report every gate failure instead of crashing the gate
        errors.append(f"capture session manifest failed to load: {exc}")

    profile: dict[str, Any] | None = None
    profile_digest: str | None = None
    try:
        raw = profile_path.read_text(encoding="utf-8")
        profile = json.loads(raw)
        profile_digest = hashlib.sha256(raw.encode()).hexdigest()
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"profile failed to load: {exc}")

    if profile is not None:
        try:
            import jsonschema

            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = jsonschema.Draft202012Validator(schema)
            for issue in sorted(validator.iter_errors(profile), key=str):
                errors.append(f"profile schema violation: {issue.message}")
        except OSError as exc:
            errors.append(f"profile schema failed to load: {exc}")

        provenance = profile.get("provenance", {})
        if provenance.get("reviewStatus") != "approved":
            errors.append("profile provenance.reviewStatus must be 'approved'")
        if not provenance.get("reviewer"):
            errors.append("profile provenance.reviewer is required for publication")

        confidence = profile.get("classification", {}).get("confidence")
        if confidence not in PUBLISHABLE_CONFIDENCE:
            errors.append(
                f"classification confidence '{confidence}' is below capture-validated"
            )

        root = (assets_root or profile_path.parent).resolve()
        for name, asset in profile.get("assets", {}).items():
            uri = asset.get("uri", "")
            if not _asset_uri_is_safe(uri):
                errors.append(f"asset '{name}' points outside approved delivery paths: {uri}")
                continue
            if "://" in uri or uri.startswith("//"):
                warnings.append(f"asset '{name}' is remote; hash not verified locally: {uri}")
                continue
            expected = asset.get("sha256")
            if expected is None:
                errors.append(f"asset '{name}' is missing a sha256 content hash")
                continue
            candidate = (root / uri).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                errors.append(f"asset '{name}' escapes the assets root: {uri}")
                continue
            if not candidate.is_file():
                errors.append(f"asset '{name}' file is missing: {uri}")
                continue
            actual = _sha256_file(candidate)
            checked_assets[name] = actual
            if actual != expected.lower():
                errors.append(
                    f"asset '{name}' hash mismatch: profile={expected}, actual={actual}"
                )

    return PublicationReport(
        passed=not errors,
        state=state,
        errors=errors,
        warnings=warnings,
        profile_digest=profile_digest,
        ledger_head_digest=head_digest,
        checked_assets=checked_assets,
    )
