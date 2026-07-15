from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from .quality import read_image

CANONICAL_WIDTH = 1436
CANONICAL_HEIGHT = 2000
CARD_ASPECT = CANONICAL_WIDTH / CANONICAL_HEIGHT


class GeometryError(RuntimeError):
    """Raised when a card cannot be rectified or registered safely."""


@dataclass(frozen=True)
class QuadCandidate:
    points: np.ndarray
    score: float
    area_ratio: float
    aspect_ratio: float
    rectangularity: float


@dataclass(frozen=True)
class RegistrationResult:
    image: np.ndarray
    homography: np.ndarray
    matches: int
    inliers: int
    inlier_ratio: float
    reprojection_error: float


def order_quad(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    return np.array(
        [
            points[np.argmin(sums)],
            points[np.argmin(differences)],
            points[np.argmax(sums)],
            points[np.argmax(differences)],
        ],
        dtype=np.float32,
    )


def _side_lengths(ordered: np.ndarray) -> tuple[float, float]:
    top = float(np.linalg.norm(ordered[1] - ordered[0]))
    bottom = float(np.linalg.norm(ordered[2] - ordered[3]))
    left = float(np.linalg.norm(ordered[3] - ordered[0]))
    right = float(np.linalg.norm(ordered[2] - ordered[1]))
    return (top + bottom) / 2.0, (left + right) / 2.0


def _candidate_score(contour: np.ndarray, image_area: float) -> QuadCandidate | None:
    perimeter = cv2.arcLength(contour, True)
    polygon = cv2.approxPolyDP(contour, 0.018 * perimeter, True)
    if len(polygon) != 4 or not cv2.isContourConvex(polygon):
        return None

    area = abs(float(cv2.contourArea(polygon)))
    if area <= 0:
        return None
    area_ratio = area / image_area
    if area_ratio < 0.08:
        return None

    ordered = order_quad(polygon.reshape(4, 2))
    width, height = _side_lengths(ordered)
    if width <= 1 or height <= 1:
        return None

    aspect_ratio = min(width, height) / max(width, height)
    aspect_error = abs(np.log(max(aspect_ratio, 1e-6) / CARD_ASPECT))
    aspect_score = float(np.exp(-5.0 * aspect_error))

    minimum_rectangle = cv2.minAreaRect(polygon)
    rectangle_area = float(minimum_rectangle[1][0] * minimum_rectangle[1][1])
    rectangularity = min(1.0, area / max(rectangle_area, 1.0))

    border = np.concatenate([ordered[:, 0], ordered[:, 1]])
    finite_score = 1.0 if np.all(np.isfinite(border)) else 0.0
    score = finite_score * (
        0.52 * min(area_ratio / 0.65, 1.0)
        + 0.30 * aspect_score
        + 0.18 * rectangularity
    )
    return QuadCandidate(
        points=ordered,
        score=score,
        area_ratio=area_ratio,
        aspect_ratio=aspect_ratio,
        rectangularity=rectangularity,
    )


def detect_card_quad(image: np.ndarray, *, minimum_score: float = 0.56) -> QuadCandidate:
    if image.ndim != 3 or image.shape[2] != 3:
        raise GeometryError("expected a BGR color image")

    original_height, original_width = image.shape[:2]
    scale = min(1.0, 1800.0 / max(original_height, original_width))
    working = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    median = float(np.median(blurred))
    lower = int(max(20, 0.55 * median))
    upper = int(min(240, max(lower + 20, 1.45 * median)))
    edges = cv2.Canny(blurred, lower, upper)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(working.shape[0] * working.shape[1])
    candidates = [
        candidate
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:80]
        if (candidate := _candidate_score(contour, image_area)) is not None
    ]
    if not candidates:
        raise GeometryError("no plausible rectangular card boundary detected")

    best = max(candidates, key=lambda candidate: candidate.score)
    if best.score < minimum_score:
        raise GeometryError(
            f"best card boundary score {best.score:.3f} is below {minimum_score:.3f}"
        )

    if scale != 1.0:
        best = QuadCandidate(
            points=best.points / scale,
            score=best.score,
            area_ratio=best.area_ratio,
            aspect_ratio=best.aspect_ratio,
            rectangularity=best.rectangularity,
        )
    return best


def warp_card(
    image: np.ndarray,
    quad: np.ndarray,
    *,
    width: int = CANONICAL_WIDTH,
    height: int = CANONICAL_HEIGHT,
) -> tuple[np.ndarray, np.ndarray]:
    ordered = order_quad(quad)
    source_width, source_height = _side_lengths(ordered)
    if source_width > source_height:
        ordered = np.roll(ordered, -1, axis=0)
        ordered = order_quad(ordered)

    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    homography = cv2.getPerspectiveTransform(ordered, destination)
    warped = cv2.warpPerspective(
        image,
        homography,
        (width, height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return warped, homography


def rectify_path(
    source: Path,
    *,
    manual_quad: Iterable[Iterable[float]] | None = None,
) -> tuple[np.ndarray, np.ndarray, QuadCandidate | None]:
    image = read_image(source)
    if manual_quad is None:
        candidate = detect_card_quad(image)
        quad = candidate.points
    else:
        candidate = None
        quad = np.asarray(list(manual_quad), dtype=np.float32)
        if quad.shape != (4, 2):
            raise GeometryError("manual quad must contain four [x, y] points")
    warped, homography = warp_card(image, quad)
    return warped, homography, candidate


def register_residual(
    moving: np.ndarray,
    reference: np.ndarray,
    *,
    stable_mask: np.ndarray | None = None,
    minimum_matches: int = 24,
    minimum_inliers: int = 14,
) -> RegistrationResult:
    if moving.shape[:2] != reference.shape[:2]:
        raise GeometryError("moving and reference frames must use the same canonical dimensions")

    moving_gray = cv2.cvtColor(moving, cv2.COLOR_BGR2GRAY)
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    if stable_mask is not None:
        if stable_mask.shape != moving_gray.shape:
            raise GeometryError("stable mask dimensions do not match canonical frame")
        mask = (stable_mask > 0).astype(np.uint8) * 255
    else:
        mask = None

    cv2.setRNGSeed(20260715)
    detector = cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.02, edgeThreshold=12)
    keypoints_moving, descriptors_moving = detector.detectAndCompute(moving_gray, mask)
    keypoints_reference, descriptors_reference = detector.detectAndCompute(reference_gray, mask)

    if descriptors_moving is None or descriptors_reference is None:
        raise GeometryError("insufficient stable features for residual registration")

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    pairs = matcher.knnMatch(descriptors_moving, descriptors_reference, k=2)
    good = [first for first, second in pairs if first.distance < 0.72 * second.distance]
    if len(good) < minimum_matches:
        raise GeometryError(f"only {len(good)} feature matches; need {minimum_matches}")

    moving_points = np.float32([keypoints_moving[item.queryIdx].pt for item in good])
    reference_points = np.float32([keypoints_reference[item.trainIdx].pt for item in good])
    homography, inlier_mask = cv2.findHomography(
        moving_points,
        reference_points,
        cv2.USAC_MAGSAC,
        2.0,
        maxIters=10000,
        confidence=0.999,
    )
    if homography is None or inlier_mask is None:
        raise GeometryError("residual homography estimation failed")

    inliers = int(inlier_mask.sum())
    if inliers < minimum_inliers:
        raise GeometryError(f"only {inliers} inliers; need {minimum_inliers}")

    projected = cv2.perspectiveTransform(moving_points.reshape(-1, 1, 2), homography).reshape(-1, 2)
    errors = np.linalg.norm(projected - reference_points, axis=1)
    inlier_errors = errors[inlier_mask.reshape(-1).astype(bool)]
    reprojection_error = float(np.median(inlier_errors))

    registered = cv2.warpPerspective(
        moving,
        homography,
        (reference.shape[1], reference.shape[0]),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return RegistrationResult(
        image=registered,
        homography=homography,
        matches=len(good),
        inliers=inliers,
        inlier_ratio=inliers / len(good),
        reprojection_error=reprojection_error,
    )


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extension = path.suffix.lower() or ".png"
    success, encoded = cv2.imencode(extension, image)
    if not success:
        raise GeometryError(f"unable to encode output image: {path}")
    encoded.tofile(path)
