from __future__ import annotations

import json
import mimetypes
import shutil
from datetime import UTC, datetime
from pathlib import Path

from blake3 import blake3
from PIL import Image, UnidentifiedImageError

from .models import CaptureDirection, CaptureFile, CaptureKind, CaptureSession

MANIFEST_FILENAME = "capture-session.json"
CHUNK_SIZE = 1024 * 1024


class ProvenanceError(RuntimeError):
    """Raised when capture provenance cannot be established safely."""


def hash_file(path: Path) -> str:
    digest = blake3()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as image:
            return image.width, image.height
    except (UnidentifiedImageError, OSError):
        return None, None


def infer_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def load_manifest(session_root: Path) -> CaptureSession:
    manifest_path = session_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ProvenanceError(f"missing manifest: {manifest_path}")
    return CaptureSession.model_validate_json(manifest_path.read_text(encoding="utf-8"))


def save_manifest(session_root: Path, session: CaptureSession) -> Path:
    session.updated_at = datetime.now(UTC)
    manifest_path = session_root / MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        session.model_dump_json(indent=2, exclude_none=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    return manifest_path


def add_capture_file(
    session_root: Path,
    source: Path,
    kind: CaptureKind,
    *,
    angle_degrees: float | None = None,
    direction: CaptureDirection = CaptureDirection.NONE,
    light_label: str | None = None,
    captured_at: datetime | None = None,
    copy_into_session: bool = True,
) -> CaptureFile:
    if not source.is_file():
        raise ProvenanceError(f"capture source does not exist: {source}")

    session = load_manifest(session_root)
    digest = hash_file(source)
    if any(item.blake3 == digest for item in session.files):
        raise ProvenanceError(f"duplicate capture content already exists: {digest}")

    destination_directory = session_root / "raw" / kind.value
    destination_directory.mkdir(parents=True, exist_ok=True)
    safe_name = f"{len(session.files):04d}-{digest[:12]}{source.suffix.lower()}"
    destination = destination_directory / safe_name

    if copy_into_session:
        shutil.copy2(source, destination)
    else:
        destination = source.resolve()
        try:
            destination.relative_to(session_root.resolve())
        except ValueError as exc:
            raise ProvenanceError("non-copied captures must already be inside the session root") from exc

    width, height = inspect_dimensions(destination)
    relative_path = destination.relative_to(session_root).as_posix()
    record = CaptureFile(
        path=relative_path,
        kind=kind,
        blake3=digest,
        bytes=destination.stat().st_size,
        media_type=infer_media_type(destination),
        width=width,
        height=height,
        captured_at=captured_at,
        angle_degrees=angle_degrees,
        direction=direction,
        light_label=light_label,
        source_filename=source.name,
    )
    session.files.append(record)
    save_manifest(session_root, session)
    return record


def verify_manifest_files(session_root: Path, session: CaptureSession) -> list[str]:
    errors: list[str] = []
    root = session_root.resolve()

    for record in session.files:
        path = (root / record.path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append(f"path escaped session root: {record.path}")
            continue

        if not path.is_file():
            errors.append(f"missing file: {record.path}")
            continue

        actual_size = path.stat().st_size
        if actual_size != record.bytes:
            errors.append(
                f"size mismatch for {record.path}: manifest={record.bytes}, actual={actual_size}"
            )

        actual_hash = hash_file(path)
        if actual_hash != record.blake3:
            errors.append(
                f"hash mismatch for {record.path}: manifest={record.blake3}, actual={actual_hash}"
            )

    return errors


def write_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = CaptureSession.model_json_schema()
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
