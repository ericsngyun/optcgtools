"""CLI for Lane A observed-appearance envelope extraction (ADR-0002).

Emits observed appearance proposals only — never physical BRDF values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from .appearance_envelope import (
    AppearanceEnvelopeError,
    extract_appearance_envelopes,
    load_extraction_manifest,
)

app = typer.Typer(
    name="optcg-appearance",
    help=(
        "Extract robust observed-appearance envelopes from normalized "
        "public-reference images (Lane A proposals, never physical claims)."
    ),
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


@app.command("extract")
def extract_command(
    input_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Envelope output directory."),
    ] = None,
) -> None:
    """Emit one schema-valid appearance-envelope JSON per manifest region."""
    output_dir = output or input_root / "appearance"
    try:
        manifest = load_extraction_manifest(manifest_path)
        artifacts = extract_appearance_envelopes(input_root, manifest, output_dir)
    except (AppearanceEnvelopeError, ValidationError, OSError) as exc:
        _fail(str(exc))
    summary = [
        {
            "region_id": artifact.envelope.region_id,
            "label": artifact.envelope.label,
            "evidence_state": artifact.envelope.evidence_state,
            "source_count": artifact.envelope.source_count,
            "outlier_sources_excluded": artifact.envelope.outlier_sources_excluded,
            "envelope": str(artifact.envelope_path),
            "per_pixel_confidence_map": str(artifact.confidence_map_path),
            "diagnostics": str(artifact.diagnostics_path),
        }
        for artifact in artifacts
    ]
    console.print_json(json.dumps(summary))


@app.command("validate-manifest")
def validate_manifest_command(
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate an extraction manifest (sources, weights, masks, regions)."""
    try:
        manifest = load_extraction_manifest(manifest_path)
    except (ValidationError, OSError) as exc:
        _fail(str(exc))
    console.print_json(manifest.model_dump_json(exclude_none=True))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
