"""Shared helpers for agent-gate scripts. Stdlib only: hooks must run without uv."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BLOCK_EXIT_CODE = 2

PRIVATE_MEDIA_PREFIXES = (
    "private-references/",
    "raw-captures/",
    "marketplace-references/",
)

RAW_CAMERA_EXTENSIONS = {
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf",
    ".raw", ".pef", ".srw", ".x3f", ".iiq",
}
CHECKPOINT_EXTENSIONS = {".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".h5", ".gguf"}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".wmv", ".flv", ".mts", ".m2ts", ".3gp",
}
RASTER_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".avif", ".tif", ".tiff", ".bmp", ".heic",
    ".gif", ".jxl", ".jp2", ".ico", ".exr", ".hdr", ".psd",
}

# Reviewed synthetic fixtures and approved public derivatives may hold small
# rasters. Kept deliberately narrow: docs and examples must use vectors/JSON.
ALLOWED_RASTER_PREFIXES = (
    "public/img/",
    "public/approved/",
    "tests/fixtures/",
    "tests-web/fixtures/",
)
MAX_RASTER_BYTES = 500 * 1024

GENERATED_ARTIFACT_PREFIXES = (
    "dist/",
    "test-results/",
    "playwright-report/",
    "blob-report/",
    "node_modules/",
    ".venv/",
    "htmlcov/",
    "upstream/pokemon-cards-css/",
)
GENERATED_ARTIFACT_SUFFIXES = (".pyc", ".pyo", ".coverage", ".tmp")
GENERATED_ARTIFACT_PARTS = ("__pycache__", ".pytest_cache", ".vite")


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def staged_files() -> list[tuple[str, str]]:
    """Return (status, path) for staged changes. Renames report the new path."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-M"],
        check=True,
        capture_output=True,
        text=True,
    )
    entries: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            entries.append((parts[0][:1], parts[-1]))
    return entries


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], check=True, capture_output=True, text=True
    )
    return result.stdout.splitlines()


def normalize(path: str, root: Path | None = None) -> str:
    candidate = Path(path)
    if candidate.is_absolute() and root is not None:
        try:
            candidate = candidate.relative_to(root)
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def private_media_violation(path: str, size_bytes: int | None) -> str | None:
    lowered = path.lower()
    suffix = Path(lowered).suffix

    for prefix in PRIVATE_MEDIA_PREFIXES:
        if lowered.startswith(prefix) or f"/{prefix}" in lowered:
            return f"private capture directory must never enter the repository: {path}"
    if suffix in RAW_CAMERA_EXTENSIONS:
        return f"raw camera file blocked: {path}"
    if suffix in CHECKPOINT_EXTENSIONS:
        return f"model checkpoint blocked: {path}"
    if suffix in VIDEO_EXTENSIONS:
        return f"video capture blocked from the public repository: {path}"
    if suffix in RASTER_EXTENSIONS:
        if not lowered.startswith(ALLOWED_RASTER_PREFIXES):
            return (
                f"raster image outside reviewed fixture/derivative paths: {path} "
                f"(allowed: {', '.join(ALLOWED_RASTER_PREFIXES)})"
            )
        if size_bytes is not None and size_bytes > MAX_RASTER_BYTES:
            return (
                f"raster image exceeds {MAX_RASTER_BYTES // 1024} KiB "
                f"({size_bytes // 1024} KiB): {path}"
            )
    return None


def approved_asset_violation(status: str, path: str) -> str | None:
    parts = Path(path.lower()).parts
    if "approved" not in parts:
        return None
    if status in ("M", "D", "R"):
        return (
            f"approved assets are append-only; '{status}' on {path} requires a new "
            "revision with a review event instead of an in-place change"
        )
    return None


def generated_artifact_violation(path: str) -> str | None:
    lowered = path.lower()
    if lowered.startswith(GENERATED_ARTIFACT_PREFIXES):
        return f"generated artifact must not be committed: {path}"
    if lowered.endswith(GENERATED_ARTIFACT_SUFFIXES):
        return f"generated artifact must not be committed: {path}"
    if any(part in GENERATED_ARTIFACT_PARTS for part in Path(lowered).parts):
        return f"generated artifact must not be committed: {path}"
    return None


def report(violations: list[str], gate_name: str) -> int:
    if not violations:
        print(f"{gate_name}: clean")
        return 0
    for violation in violations:
        print(f"{gate_name}: BLOCKED: {violation}", file=sys.stderr)
    return BLOCK_EXIT_CODE
