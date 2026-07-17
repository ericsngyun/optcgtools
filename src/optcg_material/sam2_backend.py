from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import shutil
import subprocess
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .quality import read_image
from .semantic import (
    SAM2_PINNED_COMMIT,
    MaskProposal,
    ModelProvenance,
    RegionPrompt,
    SegmentationRequest,
    SegmentationRun,
    SemanticError,
    canonical_digest,
    file_digest,
    read_binary_mask,
    save_run,
    uncertainty_from_logits,
    write_mask,
    write_uncertainty,
)


class Sam2Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_config_path: str = "configs/sam2.1/sam2.1_hiera_b+.yaml"
    checkpoint_path: Path
    device: str = "cuda"
    repository_commit: str = SAM2_PINNED_COMMIT
    allow_unpinned_source: bool = False
    vos_optimized: bool = False
    offload_video_to_cpu: bool = True
    offload_state_to_cpu: bool = False
    async_loading_frames: bool = False
    jpeg_quality: int = Field(default=100, ge=90, le=100)


class Sam2UnavailableError(SemanticError):
    """Raised when the optional SAM 2.1 environment is unavailable or untrusted."""


def _import_sam2() -> tuple[Any, Any, Any, Any, Any]:
    try:
        torch = importlib.import_module("torch")
        sam2 = importlib.import_module("sam2")
        build_sam = importlib.import_module("sam2.build_sam")
        image_predictor_module = importlib.import_module("sam2.sam2_image_predictor")
    except ImportError as exc:
        raise Sam2UnavailableError(
            "SAM 2.1 is optional and not installed. Run scripts/install-sam2.sh "
            "inside a GPU-capable environment."
        ) from exc
    return (
        torch,
        sam2,
        build_sam.build_sam2,
        build_sam.build_sam2_video_predictor,
        image_predictor_module.SAM2ImagePredictor,
    )


def _installed_sam2_commit(sam2_module: Any) -> str | None:
    package_directory = Path(next(iter(sam2_module.__path__))).resolve()
    repository_root = package_directory.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        value = os.environ.get("SAM2_REPOSITORY_COMMIT")
        return value.strip().lower() if value else None
    return result.stdout.strip().lower()


def _sam2_version() -> str | None:
    for package_name in ("SAM-2", "sam-2", "sam2"):
        try:
            return importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def _verify_environment(
    settings: Sam2Settings,
    sam2_module: Any,
    torch: Any,
) -> ModelProvenance:
    checkpoint = settings.checkpoint_path.resolve()
    if not checkpoint.is_file():
        raise Sam2UnavailableError(f"SAM 2.1 checkpoint does not exist: {checkpoint}")

    installed_commit = _installed_sam2_commit(sam2_module)
    if installed_commit is None:
        raise Sam2UnavailableError(
            "unable to prove the installed SAM 2 source commit; install from the pinned git checkout"
        )
    if installed_commit != settings.repository_commit and not settings.allow_unpinned_source:
        raise Sam2UnavailableError(
            "installed SAM 2 source does not match the approved pin: "
            f"installed={installed_commit}, expected={settings.repository_commit}"
        )

    return ModelProvenance(
        repository_commit=installed_commit,
        model_config=settings.model_config_path,
        checkpoint_path=str(checkpoint),
        checkpoint_blake3=file_digest(checkpoint),
        device=settings.device,
        torch_version=str(torch.__version__),
        sam2_version=_sam2_version(),
        vos_optimized=settings.vos_optimized,
        offload_video_to_cpu=settings.offload_video_to_cpu,
        offload_state_to_cpu=settings.offload_state_to_cpu,
    )


def _inference_context(torch: Any, device: str) -> ExitStack:
    stack = ExitStack()
    stack.enter_context(torch.inference_mode())
    if device.startswith("cuda"):
        stack.enter_context(torch.autocast("cuda", dtype=torch.bfloat16))
    return stack


def _prompt_arrays(prompt: RegionPrompt) -> tuple[np.ndarray | None, np.ndarray | None]:
    if not prompt.points:
        return None, None
    coordinates = np.asarray([[point.x, point.y] for point in prompt.points], dtype=np.float32)
    labels = np.asarray([1 if point.foreground else 0 for point in prompt.points], dtype=np.int32)
    return coordinates, labels


def _prompt_box(prompt: RegionPrompt) -> np.ndarray | None:
    if prompt.box is None:
        return None
    return np.asarray(
        [prompt.box.x_min, prompt.box.y_min, prompt.box.x_max, prompt.box.y_max],
        dtype=np.float32,
    )


def _load_image_mask_input(session_root: Path, prompt: RegionPrompt) -> np.ndarray | None:
    if prompt.mask_input_path is None:
        return None
    path = session_root / prompt.mask_input_path
    if path.suffix.lower() == ".npz":
        with np.load(path) as payload:
            if "logits" not in payload:
                raise SemanticError(f"mask-input archive lacks 'logits': {path}")
            logits = np.asarray(payload["logits"], dtype=np.float32)
    else:
        binary = read_binary_mask(path)
        logits = np.where(binary, 8.0, -8.0).astype(np.float32)
        logits = cv2.resize(logits, (256, 256), interpolation=cv2.INTER_LINEAR)
    if logits.ndim == 2:
        logits = logits[None, :, :]
    return logits


def _proposal_paths(
    session_root: Path,
    request: SegmentationRequest,
    proposal_id: str,
) -> tuple[Path, Path, Path]:
    run_root = session_root / request.output_directory / request.run_id
    proposal_root = run_root / "proposals"
    return (
        proposal_root / f"{proposal_id}-mask.png",
        proposal_root / f"{proposal_id}-uncertainty.png",
        proposal_root / f"{proposal_id}-low-res-logits.npz",
    )


def _relative(session_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(session_root.resolve()).as_posix()
    except ValueError as exc:
        raise SemanticError(f"artifact escaped session root: {path}") from exc


def _build_proposal(
    *,
    session_root: Path,
    request: SegmentationRequest,
    prompt: RegionPrompt,
    frame_index: int,
    source_frame_path: str,
    logits: np.ndarray,
    predicted_iou: float | None,
    low_res_logits: np.ndarray | None,
) -> MaskProposal:
    proposal_id = f"{prompt.region_id}-f{frame_index:05d}"
    mask_path, uncertainty_path, low_res_path = _proposal_paths(
        session_root,
        request,
        proposal_id,
    )
    binary = np.asarray(logits > 0, dtype=bool)
    uncertainty = uncertainty_from_logits(logits)
    write_mask(mask_path, binary)
    write_uncertainty(uncertainty_path, uncertainty)

    low_res_relative: str | None = None
    if low_res_logits is not None:
        low_res_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(low_res_path, logits=np.asarray(low_res_logits, dtype=np.float16))
        low_res_relative = _relative(session_root, low_res_path)

    return MaskProposal(
        proposal_id=proposal_id,
        region_id=prompt.region_id,
        semantic_region=prompt.semantic_region,
        object_id=prompt.object_id or prompt.region_id,
        frame_index=frame_index,
        source_frame_path=source_frame_path,
        mask_path=_relative(session_root, mask_path),
        uncertainty_path=_relative(session_root, uncertainty_path),
        low_res_logits_path=low_res_relative,
        predicted_iou=predicted_iou,
        mean_uncertainty=float(np.mean(uncertainty)),
        foreground_ratio=float(np.mean(binary)),
        prompt_digest=canonical_digest(prompt),
        mask_blake3=file_digest(mask_path),
        uncertainty_blake3=file_digest(uncertainty_path),
    )


def run_image_segmentation(
    session_root: Path,
    request: SegmentationRequest,
    settings: Sam2Settings,
) -> SegmentationRun:
    if request.mode != "image":
        raise SemanticError("image worker requires request.mode='image'")

    torch, sam2_module, build_sam2, _, image_predictor_class = _import_sam2()
    model_record = _verify_environment(settings, sam2_module, torch)
    source_path = session_root / request.source_path
    image_bgr = read_image(source_path)
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    model = build_sam2(
        settings.model_config_path,
        str(settings.checkpoint_path.resolve()),
        device=settings.device,
    )
    predictor = image_predictor_class(model)
    proposals: list[MaskProposal] = []

    with _inference_context(torch, settings.device):
        predictor.set_image(image_rgb)
        for prompt in request.prompts:
            point_coords, point_labels = _prompt_arrays(prompt)
            box = _prompt_box(prompt)
            mask_input = _load_image_mask_input(session_root, prompt)
            multimask = prompt.multimask_output
            if multimask is None:
                multimask = len(prompt.points) <= 1 and box is None and mask_input is None

            masks, scores, low_res_masks = predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                box=box,
                mask_input=mask_input,
                multimask_output=multimask,
                return_logits=True,
            )
            best_index = int(np.argmax(scores))
            proposals.append(
                _build_proposal(
                    session_root=session_root,
                    request=request,
                    prompt=prompt,
                    frame_index=0,
                    source_frame_path=request.source_path,
                    logits=np.asarray(masks[best_index], dtype=np.float32),
                    predicted_iou=float(scores[best_index]),
                    low_res_logits=np.asarray(low_res_masks[best_index], dtype=np.float32),
                )
            )

    run = SegmentationRun(
        run_id=request.run_id,
        session_id=request.session_id,
        request_digest=canonical_digest(request),
        model=model_record,
        proposals=proposals,
    )
    run_path = session_root / request.output_directory / request.run_id / "segmentation-run.json"
    save_run(run_path, run)
    return run


def _prepare_video_source(
    session_root: Path,
    request: SegmentationRequest,
    settings: Sam2Settings,
) -> tuple[Path, list[str]]:
    if not request.source_frame_paths:
        source = session_root / request.source_path
        if not source.exists():
            raise SemanticError(f"video source does not exist: {source}")
        return source, []

    staging = session_root / request.output_directory / request.run_id / "sam2-jpeg-input"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    for frame_index, relative_path in enumerate(request.source_frame_paths):
        image = read_image(session_root / relative_path)
        destination = staging / f"{frame_index:05d}.jpg"
        success, encoded = cv2.imencode(
            ".jpg",
            image,
            [cv2.IMWRITE_JPEG_QUALITY, settings.jpeg_quality],
        )
        if not success:
            raise SemanticError(f"unable to stage SAM 2 JPEG frame: {relative_path}")
        encoded.tofile(destination)
    return staging, request.source_frame_paths


def _video_prompt_lookup(prompts: list[RegionPrompt]) -> dict[str, RegionPrompt]:
    lookup: dict[str, RegionPrompt] = {}
    for prompt in prompts:
        object_id = prompt.object_id or prompt.region_id
        existing = lookup.get(object_id)
        if existing is not None and existing.semantic_region is not prompt.semantic_region:
            raise SemanticError(
                f"video object {object_id} maps to conflicting semantic regions"
            )
        lookup.setdefault(object_id, prompt)
    return lookup


def run_video_segmentation(
    session_root: Path,
    request: SegmentationRequest,
    settings: Sam2Settings,
) -> SegmentationRun:
    if request.mode != "video":
        raise SemanticError("video worker requires request.mode='video'")

    torch, sam2_module, _, build_video_predictor, _ = _import_sam2()
    model_record = _verify_environment(settings, sam2_module, torch)
    video_source, frame_paths = _prepare_video_source(session_root, request, settings)
    predictor = build_video_predictor(
        settings.model_config_path,
        str(settings.checkpoint_path.resolve()),
        device=settings.device,
        vos_optimized=settings.vos_optimized,
    )
    prompt_lookup = _video_prompt_lookup(request.prompts)
    proposals: list[MaskProposal] = []

    with _inference_context(torch, settings.device):
        state = predictor.init_state(
            video_path=str(video_source),
            offload_video_to_cpu=settings.offload_video_to_cpu,
            offload_state_to_cpu=settings.offload_state_to_cpu,
            async_loading_frames=settings.async_loading_frames,
        )

        for prompt in request.prompts:
            object_id = prompt.object_id or prompt.region_id
            if prompt.mask_input_path is not None and not prompt.points and prompt.box is None:
                mask = read_binary_mask(session_root / prompt.mask_input_path)
                predictor.add_new_mask(
                    state,
                    frame_idx=prompt.frame_index,
                    obj_id=object_id,
                    mask=mask,
                )
            else:
                point_coords, point_labels = _prompt_arrays(prompt)
                predictor.add_new_points_or_box(
                    state,
                    frame_idx=prompt.frame_index,
                    obj_id=object_id,
                    points=point_coords,
                    labels=point_labels,
                    box=_prompt_box(prompt),
                )

        for frame_index, object_ids, mask_logits in predictor.propagate_in_video(state):
            logits_array = mask_logits.detach().float().cpu().numpy()
            for object_index, raw_object_id in enumerate(object_ids):
                object_id = str(raw_object_id)
                prompt = prompt_lookup.get(object_id)
                if prompt is None:
                    raise SemanticError(f"SAM 2 returned unknown object id: {object_id}")
                source_frame = (
                    frame_paths[frame_index]
                    if frame_paths and frame_index < len(frame_paths)
                    else request.source_path
                )
                logits = np.squeeze(logits_array[object_index]).astype(np.float32)
                proposals.append(
                    _build_proposal(
                        session_root=session_root,
                        request=request,
                        prompt=prompt,
                        frame_index=int(frame_index),
                        source_frame_path=source_frame,
                        logits=logits,
                        predicted_iou=None,
                        low_res_logits=None,
                    )
                )

        predictor.reset_state(state)

    run = SegmentationRun(
        run_id=request.run_id,
        session_id=request.session_id,
        request_digest=canonical_digest(request),
        model=model_record,
        proposals=proposals,
    )
    run_path = session_root / request.output_directory / request.run_id / "segmentation-run.json"
    save_run(run_path, run)
    return run


def write_environment_report(path: Path, settings: Sam2Settings) -> None:
    torch, sam2_module, _, _, _ = _import_sam2()
    report = _verify_environment(settings, sam2_module, torch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(), indent=2) + "\n", encoding="utf-8")
