from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from optcg_material.models import CaptureKind, Language
from optcg_material.provenance import (
    ProvenanceError,
    add_capture_file,
    load_manifest,
    verify_manifest_files,
)
from optcg_material.session import initialize_session


def write_test_image(path: Path) -> None:
    image = np.full((1800, 1300, 3), 128, dtype=np.uint8)
    cv2.rectangle(image, (80, 80), (1220, 1720), (245, 245, 245), 20)
    success, encoded = cv2.imencode(".png", image)
    assert success
    encoded.tofile(path)


def create_session(root: Path) -> None:
    initialize_session(
        root,
        session_id="op05-119-luffy-en-001",
        card_id="OP05-119",
        card_name="Monkey.D.Luffy",
        set_code="OP05",
        language=Language.EN,
        operator="GenkiStuff Lab",
        rights_owner="GenkiStuff",
    )


def test_add_capture_hashes_and_copies(tmp_path: Path) -> None:
    session_root = tmp_path / "session"
    source = tmp_path / "capture.png"
    write_test_image(source)
    create_session(session_root)

    record = add_capture_file(session_root, source, CaptureKind.ALBEDO)
    manifest = load_manifest(session_root)

    assert (session_root / record.path).is_file()
    assert len(record.blake3) == 64
    assert manifest.files[0].blake3 == record.blake3
    assert verify_manifest_files(session_root, manifest) == []


def test_duplicate_capture_is_rejected(tmp_path: Path) -> None:
    session_root = tmp_path / "session"
    source = tmp_path / "capture.png"
    write_test_image(source)
    create_session(session_root)
    add_capture_file(session_root, source, CaptureKind.ALBEDO)

    with pytest.raises(ProvenanceError):
        add_capture_file(session_root, source, CaptureKind.TILT_X)


def test_manifest_detects_tampering(tmp_path: Path) -> None:
    session_root = tmp_path / "session"
    source = tmp_path / "capture.png"
    write_test_image(source)
    create_session(session_root)
    record = add_capture_file(session_root, source, CaptureKind.ALBEDO)

    stored = session_root / record.path
    stored.write_bytes(stored.read_bytes() + b"tamper")
    errors = verify_manifest_files(session_root, load_manifest(session_root))

    assert any("size mismatch" in error for error in errors)
    assert any("hash mismatch" in error for error in errors)
