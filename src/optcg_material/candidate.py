from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .geometry import CANONICAL_HEIGHT, CANONICAL_WIDTH, GeometryError, warp_card, write_image
from .quality import read_image


class CandidateError(RuntimeError):
    """Raised when a synthesized renderer frame cannot be canonicalized safely."""


def parse_quad(payload: str | list[list[float]] | dict[str, Any]) -> np.ndarray:
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise CandidateError(f"invalid quad JSON: {exc}") from exc
    else:
        decoded = payload

    if isinstance(decoded, dict):
        decoded = decoded.get("corners")
    quad = np.asarray(decoded, dtype=np.float32)
    if quad.shape != (4, 2):
        raise CandidateError("quad must contain exactly four [x, y] points")
    if not np.all(np.isfinite(quad)):
        raise CandidateError("quad contains non-finite coordinates")
    return quad


def canonicalize_render(
    source: Path,
    destination: Path,
    quad: str | list[list[float]] | dict[str, Any],
    *,
    width: int = CANONICAL_WIDTH,
    height: int = CANONICAL_HEIGHT,
) -> np.ndarray:
    image = read_image(source)
    points = parse_quad(quad)
    image_height, image_width = image.shape[:2]
    if np.any(points[:, 0] < -2) or np.any(points[:, 0] > image_width + 2):
        raise CandidateError("quad x coordinates fall outside the renderer image")
    if np.any(points[:, 1] < -2) or np.any(points[:, 1] > image_height + 2):
        raise CandidateError("quad y coordinates fall outside the renderer image")

    try:
        canonical, _ = warp_card(image, points, width=width, height=height)
    except GeometryError as exc:
        raise CandidateError(str(exc)) from exc
    write_image(destination, canonical)
    return canonical
