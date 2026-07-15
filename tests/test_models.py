from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from optcg_material.models import (
    AuthenticationMetadata,
    AuthenticationStatus,
    CameraMetadata,
    CaptureFile,
    CaptureKind,
    CaptureSession,
    CardIdentity,
    RightsMetadata,
    RightsStatus,
    validate_completeness,
)


def build_session() -> CaptureSession:
    return CaptureSession(
        session_id="op01-120-shanks-en-001",
        card=CardIdentity(card_id="OP01-120", name="Shanks", set_code="OP01"),
        camera=CameraMetadata(operator="GenkiStuff Lab"),
        rights=RightsMetadata(owner="GenkiStuff", status=RightsStatus.OWNED_CAPTURE),
        authentication=AuthenticationMetadata(
            status=AuthenticationStatus.VERIFIED,
            method="authenticated inventory intake",
            verifier="reviewer@example.test",
            verified_at=datetime.now(UTC),
        ),
    )


def test_capture_path_rejects_traversal() -> None:
    with pytest.raises(ValidationError):
        CaptureFile(
            path="../outside.png",
            kind=CaptureKind.ALBEDO,
            blake3="a" * 64,
            bytes=10,
            media_type="image/png",
        )


def test_verified_authentication_requires_human_evidence() -> None:
    with pytest.raises(ValidationError):
        AuthenticationMetadata(status=AuthenticationStatus.VERIFIED)


def test_duplicate_content_is_rejected() -> None:
    session = build_session()
    first = CaptureFile(
        path="raw/albedo/first.png",
        kind=CaptureKind.ALBEDO,
        blake3="a" * 64,
        bytes=10,
        media_type="image/png",
    )
    second = CaptureFile(
        path="raw/tilt-x/second.png",
        kind=CaptureKind.TILT_X,
        blake3="a" * 64,
        bytes=11,
        media_type="image/png",
    )
    with pytest.raises(ValidationError):
        session.files = [first, second]


def test_completeness_fails_closed() -> None:
    session = build_session()
    session.files.append(
        CaptureFile(
            path="raw/albedo/first.png",
            kind=CaptureKind.ALBEDO,
            blake3="b" * 64,
            bytes=10,
            media_type="image/png",
        )
    )
    result = validate_completeness(session)
    assert not result.valid
    assert any("tilt-x" in item for item in result.missing)
