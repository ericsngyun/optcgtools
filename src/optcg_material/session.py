from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .geometry import GeometryError, rectify_path, register_residual, write_image
from .models import (
    AuthenticationMetadata,
    AuthenticationStatus,
    CameraMetadata,
    CaptureSession,
    CardIdentity,
    Language,
    RightsMetadata,
    RightsStatus,
    validate_completeness,
)
from .provenance import load_manifest, save_manifest, verify_manifest_files
from .quality import (
    FrameQuality,
    QualityThresholds,
    apply_group_exposure_gate,
    evaluate_frame,
    read_image,
)


class SessionError(RuntimeError):
    """Raised when a capture session cannot advance safely."""


def initialize_session(
    session_root: Path,
    *,
    session_id: str,
    card_id: str,
    card_name: str,
    set_code: str,
    language: Language,
    operator: str,
    rights_owner: str,
) -> CaptureSession:
    if session_root.exists() and any(session_root.iterdir()):
        raise SessionError(f"session directory is not empty: {session_root}")

    for path in (
        session_root / "raw",
        session_root / "processed" / "rectified",
        session_root / "processed" / "registered",
        session_root / "diagnostics" / "quality",
        session_root / "diagnostics" / "registration",
        session_root / "review",
    ):
        path.mkdir(parents=True, exist_ok=True)

    session = CaptureSession(
        session_id=session_id,
        card=CardIdentity(
            card_id=card_id,
            name=card_name,
            set_code=set_code,
            language=language,
        ),
        camera=CameraMetadata(operator=operator),
        rights=RightsMetadata(owner=rights_owner, status=RightsStatus.UNKNOWN),
        authentication=AuthenticationMetadata(status=AuthenticationStatus.PENDING),
    )
    save_manifest(session_root, session)
    return session


def validate_session(session_root: Path, *, strict_capture_set: bool = True) -> dict[str, Any]:
    session = load_manifest(session_root)
    integrity_errors = verify_manifest_files(session_root, session)
    completeness = validate_completeness(session)
    errors = list(integrity_errors)
    if strict_capture_set:
        errors.extend(completeness.missing)

    return {
        "valid": not errors,
        "session_id": session.session_id,
        "files": len(session.files),
        "integrity_errors": integrity_errors,
        "capture_counts": completeness.counts,
        "capture_requirements": completeness.missing,
        "errors": errors,
    }


def run_quality_preflight(
    session_root: Path,
    *,
    thresholds: QualityThresholds | None = None,
) -> list[FrameQuality]:
    session = load_manifest(session_root)
    limits = thresholds or QualityThresholds()
    reports: list[FrameQuality] = []
    groups: dict[str, list[FrameQuality]] = {}
    diagnostics = session_root / "diagnostics" / "quality"
    diagnostics.mkdir(parents=True, exist_ok=True)

    for record in session.files:
        if not record.media_type.startswith("image/"):
            continue
        report = evaluate_frame(session_root / record.path, limits)
        reports.append(report)
        groups.setdefault(record.kind.value, []).append(report)

    sequence_diagnostics = apply_group_exposure_gate(
        groups,
        max_deviation=limits.max_group_luminance_deviation,
        minimum_frames=limits.minimum_group_frames,
    )

    for report in reports:
        output = diagnostics / f"{Path(report.path).stem}.json"
        output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "thresholds": limits.model_dump(),
        "accepted": sum(report.accepted for report in reports),
        "rejected": sum(not report.accepted for report in reports),
        "sequence_exposure": [item.model_dump() for item in sequence_diagnostics],
        "reports": [report.model_dump() for report in reports],
    }
    (diagnostics / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return reports


def _load_manual_quads(path: Path | None) -> dict[str, list[list[float]]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SessionError("manual-quads file must be an object keyed by manifest path")
    return payload


def _matrix_payload(matrix: np.ndarray) -> list[list[float]]:
    return [[float(value) for value in row] for row in matrix]


def rectify_session(
    session_root: Path,
    *,
    manual_quads_path: Path | None = None,
    require_quality_pass: bool = True,
) -> list[dict[str, Any]]:
    session = load_manifest(session_root)
    quality_reports = {
        Path(report.path).resolve(): report
        for report in run_quality_preflight(session_root)
    }
    manual_quads = _load_manual_quads(manual_quads_path)
    results: list[dict[str, Any]] = []

    for record in session.files:
        if not record.media_type.startswith("image/"):
            continue
        source = session_root / record.path
        quality = quality_reports.get(source.resolve())
        if require_quality_pass and quality is not None and not quality.accepted:
            results.append(
                {
                    "path": record.path,
                    "status": "rejected-quality",
                    "reasons": quality.reasons,
                }
            )
            continue

        output = session_root / "processed" / "rectified" / f"{Path(record.path).stem}.png"
        sidecar = session_root / "diagnostics" / "registration" / f"{Path(record.path).stem}.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)

        try:
            warped, homography, candidate = rectify_path(
                source,
                manual_quad=manual_quads.get(record.path),
            )
            write_image(output, warped)
            result = {
                "path": record.path,
                "status": "rectified",
                "output": output.relative_to(session_root).as_posix(),
                "homography": _matrix_payload(homography),
                "detection": None
                if candidate is None
                else {
                    "score": candidate.score,
                    "area_ratio": candidate.area_ratio,
                    "aspect_ratio": candidate.aspect_ratio,
                    "rectangularity": candidate.rectangularity,
                    "quad": candidate.points.tolist(),
                },
            }
        except GeometryError as exc:
            result = {"path": record.path, "status": "rejected-geometry", "reason": str(exc)}

        sidecar.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        results.append(result)

    return results


def register_rectified_session(
    session_root: Path,
    *,
    stable_mask_path: Path | None = None,
) -> list[dict[str, Any]]:
    session = load_manifest(session_root)
    rectified_directory = session_root / "processed" / "rectified"
    registered_directory = session_root / "processed" / "registered"
    registered_directory.mkdir(parents=True, exist_ok=True)

    albedo_records = [record for record in session.files if record.kind.value == "albedo"]
    if not albedo_records:
        raise SessionError("an albedo frame is required as the registration reference")

    reference_path = rectified_directory / f"{Path(albedo_records[0].path).stem}.png"
    if not reference_path.is_file():
        raise SessionError("reference albedo has not been rectified")
    reference = read_image(reference_path)

    stable_mask = None
    if stable_mask_path is not None:
        stable_mask = cv2.imread(str(stable_mask_path), cv2.IMREAD_GRAYSCALE)
        if stable_mask is None:
            raise SessionError(f"unable to decode stable mask: {stable_mask_path}")
        stable_mask = cv2.resize(
            stable_mask,
            (reference.shape[1], reference.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )

    results: list[dict[str, Any]] = []
    for record in session.files:
        if not record.media_type.startswith("image/"):
            continue
        source = rectified_directory / f"{Path(record.path).stem}.png"
        if not source.is_file():
            results.append({"path": record.path, "status": "missing-rectified"})
            continue

        output = registered_directory / source.name
        if source == reference_path:
            write_image(output, reference)
            results.append(
                {
                    "path": record.path,
                    "status": "reference",
                    "output": output.relative_to(session_root).as_posix(),
                }
            )
            continue

        try:
            moving = read_image(source)
            registered = register_residual(moving, reference, stable_mask=stable_mask)
            write_image(output, registered.image)
            results.append(
                {
                    "path": record.path,
                    "status": "registered",
                    "output": output.relative_to(session_root).as_posix(),
                    "homography": _matrix_payload(registered.homography),
                    "matches": registered.matches,
                    "inliers": registered.inliers,
                    "inlier_ratio": registered.inlier_ratio,
                    "median_reprojection_error": registered.reprojection_error,
                }
            )
        except GeometryError as exc:
            results.append({"path": record.path, "status": "rejected-registration", "reason": str(exc)})

    summary_path = session_root / "diagnostics" / "registration" / "residual-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return results
