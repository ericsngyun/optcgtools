"""Segmentation backend registry.

Factories are lazy so listing backends never imports torch or model code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import SegmentationBackend


def _make_manual(**_: Any) -> SegmentationBackend:
    from .manual_backend import ManualBackend

    return ManualBackend()


def _make_sam2(**kwargs: Any) -> SegmentationBackend:
    from ..sam2_backend import Sam2Settings
    from .sam2_backend import Sam2Backend

    settings = kwargs.get("settings")
    if settings is None:
        settings = Sam2Settings(**kwargs)
    return Sam2Backend(settings)


def _make_sam31(**kwargs: Any) -> SegmentationBackend:
    from .sam31_backend import Sam31Backend

    return Sam31Backend(**kwargs)


_FACTORIES: dict[str, Callable[..., SegmentationBackend]] = {
    "manual": _make_manual,
    "sam2.1": _make_sam2,
    "sam3.1": _make_sam31,
}

DEFAULT_BACKEND = "sam2.1"


def available_backends() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def create_backend(name: str, **kwargs: Any) -> SegmentationBackend:
    try:
        factory = _FACTORIES[name]
    except KeyError as exc:
        raise KeyError(
            f"unknown segmentation backend '{name}'; available: {', '.join(available_backends())}"
        ) from exc
    return factory(**kwargs)
