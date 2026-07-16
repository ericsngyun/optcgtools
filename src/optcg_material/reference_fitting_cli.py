"""CLI for Lane A cross-reference analysis-by-synthesis fitting (`optcg-reference-fit`).

Fits ONE reference-derived renderer profile across all usable public-reference
observations and emits the frozen-schema fitting report plus render/diff artifacts.
Exit codes: 0 fit accepted, 1 usage/input error, 3 single-reference overfit
rejection (hard gate), 4 renderer-model-limit diagnostic (finding; renderer is
never extended from here)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from .reference_fitting import (
    ReferenceFitError,
    ReferenceFitOptions,
    fit_reference_set,
    load_observation_manifest,
    write_manifest_schema,
)

EXIT_OVERFIT_REJECTED = 3
EXIT_MODEL_LIMIT = 4

app = typer.Typer(
    name="optcg-reference-fit",
    help="Fit one reference-derived profile jointly across public-reference observations.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


@app.command("fit")
def fit_command(
    root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")],
    rounds: Annotated[int, typer.Option(min=1, max=5)] = 2,
    generated_at: Annotated[
        datetime | None,
        typer.Option(help="Fixed report timestamp for reproducible reruns."),
    ] = None,
) -> None:
    """Jointly fit one profile across an observation manifest; write report + artifacts."""
    try:
        manifest = load_observation_manifest(manifest_path)
        options = ReferenceFitOptions(rounds=rounds)
        outcome = fit_reference_set(
            root, manifest, output_dir, options=options, generated_at=generated_at
        )
    except (ReferenceFitError, ValidationError, ValueError, OSError) as exc:
        _fail(str(exc))
        return
    console.print_json(outcome.report.model_dump_json())
    console.print(f"report: {outcome.report_path}")
    console.print(f"profile: {outcome.profile_path}")
    if outcome.report.single_reference_overfit_flag:
        console.print(
            "[bold red]rejected:[/bold red] single-reference overfit — fit quality is "
            f"concentrated in {', '.join(outcome.report.privileged_reference_ids)}"
        )
        raise typer.Exit(code=EXIT_OVERFIT_REJECTED)
    if outcome.model_limit_diagnostic is not None:
        console.print(f"[bold red]rejected:[/bold red] {outcome.model_limit_diagnostic}")
        raise typer.Exit(code=EXIT_MODEL_LIMIT)
    if not outcome.accepted:
        _fail("; ".join(outcome.rejection_reasons))


@app.command("validate-manifest")
def validate_manifest_command(
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate an observation manifest without reading image content."""
    try:
        manifest = load_observation_manifest(manifest_path)
    except (ValidationError, OSError) as exc:
        _fail(str(exc))
        return
    console.print_json(manifest.model_dump_json(exclude_none=True))


@app.command("write-schema")
def schema_command(
    output: Annotated[Path, typer.Argument()] = Path(
        "schemas/reference-observation-set.schema.json"
    ),
) -> None:
    """Emit the canonical observation-set manifest JSON Schema."""
    write_manifest_schema(output)
    console.print(f"wrote {output}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
