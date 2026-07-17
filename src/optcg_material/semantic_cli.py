from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from .sam2_backend import (
    Sam2Settings,
    Sam2UnavailableError,
    run_image_segmentation,
    run_video_segmentation,
    write_environment_report,
)
from .semantic import (
    CorrectionOperation,
    MaskCorrection,
    RunStatus,
    SegmentationRun,
    SemanticError,
    apply_mask_correction,
    load_request,
    save_run,
)

app = typer.Typer(
    name="optcg-semantic",
    help="Reviewable semantic-region proposals for registered OPTCG captures.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _settings(
    *,
    checkpoint: Path,
    config_path: str,
    device: str,
    allow_unpinned_source: bool,
    vos_optimized: bool = False,
    offload_state_to_cpu: bool = False,
) -> Sam2Settings:
    return Sam2Settings(
        model_config_path=config_path,
        checkpoint_path=checkpoint,
        device=device,
        allow_unpinned_source=allow_unpinned_source,
        vos_optimized=vos_optimized,
        offload_state_to_cpu=offload_state_to_cpu,
    )


@app.command("check-environment")
def check_environment_command(
    checkpoint: Annotated[Path, typer.Option("--checkpoint", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output")] = Path("sam2-environment.json"),
    config_path: Annotated[
        str, typer.Option("--config")
    ] = "configs/sam2.1/sam2.1_hiera_b+.yaml",
    device: Annotated[str, typer.Option("--device")] = "cuda",
    allow_unpinned_source: Annotated[
        bool, typer.Option("--allow-unpinned-source")
    ] = False,
) -> None:
    """Verify the SAM 2 source commit and hash the selected checkpoint."""
    try:
        write_environment_report(
            output,
            _settings(
                checkpoint=checkpoint,
                config_path=config_path,
                device=device,
                allow_unpinned_source=allow_unpinned_source,
            ),
        )
    except (Sam2UnavailableError, SemanticError, ValidationError) as exc:
        _fail(str(exc))
    console.print(f"wrote verified environment report to {output}")


@app.command("image")
def image_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    checkpoint: Annotated[Path, typer.Option("--checkpoint", exists=True, dir_okay=False)],
    config_path: Annotated[
        str, typer.Option("--config")
    ] = "configs/sam2.1/sam2.1_hiera_b+.yaml",
    device: Annotated[str, typer.Option("--device")] = "cuda",
    allow_unpinned_source: Annotated[
        bool, typer.Option("--allow-unpinned-source")
    ] = False,
) -> None:
    """Generate image-mask proposals, uncertainty, scores, and refinement logits."""
    try:
        request = load_request(request_path)
        run = run_image_segmentation(
            session_root,
            request,
            _settings(
                checkpoint=checkpoint,
                config_path=config_path,
                device=device,
                allow_unpinned_source=allow_unpinned_source,
            ),
        )
    except (Sam2UnavailableError, SemanticError, ValidationError, OSError) as exc:
        _fail(str(exc))
    console.print_json(run.model_dump_json(exclude_none=True))


@app.command("video")
def video_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    checkpoint: Annotated[Path, typer.Option("--checkpoint", exists=True, dir_okay=False)],
    config_path: Annotated[
        str, typer.Option("--config")
    ] = "configs/sam2.1/sam2.1_hiera_b+.yaml",
    device: Annotated[str, typer.Option("--device")] = "cuda",
    vos_optimized: Annotated[bool, typer.Option("--vos-optimized")] = False,
    offload_state_to_cpu: Annotated[
        bool, typer.Option("--offload-state-to-cpu")
    ] = False,
    allow_unpinned_source: Annotated[
        bool, typer.Option("--allow-unpinned-source")
    ] = False,
) -> None:
    """Propagate prompted regions through a registered card sequence."""
    try:
        request = load_request(request_path)
        run = run_video_segmentation(
            session_root,
            request,
            _settings(
                checkpoint=checkpoint,
                config_path=config_path,
                device=device,
                allow_unpinned_source=allow_unpinned_source,
                vos_optimized=vos_optimized,
                offload_state_to_cpu=offload_state_to_cpu,
            ),
        )
    except (Sam2UnavailableError, SemanticError, ValidationError, OSError) as exc:
        _fail(str(exc))
    console.print_json(run.model_dump_json(exclude_none=True))


@app.command("correct")
def correct_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    run_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    proposal_id: Annotated[str, typer.Option("--proposal-id")],
    correction_id: Annotated[str, typer.Option("--correction-id")],
    correction_mask_path: Annotated[str, typer.Option("--correction-mask")],
    output_mask_path: Annotated[str, typer.Option("--output-mask")],
    operation: Annotated[CorrectionOperation, typer.Option("--operation")],
    reviewer: Annotated[str, typer.Option("--reviewer")],
    notes: Annotated[str | None, typer.Option("--notes")] = None,
) -> None:
    """Apply a reviewed replace/union/subtract/intersect correction and retain history."""
    try:
        run = SegmentationRun.model_validate_json(run_path.read_text(encoding="utf-8"))
        proposal = next(
            (item for item in run.proposals if item.proposal_id == proposal_id),
            None,
        )
        if proposal is None:
            raise SemanticError(f"unknown proposal id: {proposal_id}")
        correction = MaskCorrection(
            correction_id=correction_id,
            proposal_id=proposal_id,
            operation=operation,
            correction_mask_path=correction_mask_path,
            output_mask_path=output_mask_path,
            reviewer=reviewer,
            notes=notes,
        )
        completed = apply_mask_correction(session_root, proposal.mask_path, correction)
        run.corrections.append(completed)
        run.status = RunStatus.REVIEW_IN_PROGRESS
        save_run(run_path, run)
    except (SemanticError, ValidationError, OSError, StopIteration) as exc:
        _fail(str(exc))
    console.print_json(json.dumps(completed.model_dump(mode="json", exclude_none=True)))


@app.command("validate-request")
def validate_request_command(
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate prompt geometry and paths without loading a model."""
    try:
        request = load_request(request_path)
    except (SemanticError, ValidationError, OSError) as exc:
        _fail(str(exc))
    console.print_json(request.model_dump_json(exclude_none=True))


if __name__ == "__main__":
    app()
