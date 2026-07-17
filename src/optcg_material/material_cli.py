from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from .material_maps import (
    MaterialMapError,
    extract_material_maps,
    load_extraction_request,
    write_extraction_schema,
)
from .provenance import ProvenanceError

app = typer.Typer(
    name="optcg-maps",
    help="Derive reviewable material-map proposals from registered physical captures.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


@app.command("extract")
def extract_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Extract raw measurements and regularized proposal maps."""
    try:
        request = load_extraction_request(request_path)
        manifest = extract_material_maps(session_root, request)
    except (MaterialMapError, ProvenanceError, ValidationError, OSError) as exc:
        _fail(str(exc))
    console.print_json(manifest.model_dump_json(exclude_none=True))


@app.command("validate-request")
def validate_request_command(
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate extraction settings and semantic-mask paths."""
    try:
        request = load_extraction_request(request_path)
    except (MaterialMapError, ValidationError, OSError) as exc:
        _fail(str(exc))
    console.print_json(request.model_dump_json(exclude_none=True))


@app.command("write-schema")
def write_schema_command(
    output: Annotated[Path, typer.Argument()] = Path(
        "schemas/material-extraction-request.schema.json"
    ),
) -> None:
    """Emit the extraction request JSON Schema."""
    write_extraction_schema(output)
    console.print(f"wrote {output}")


if __name__ == "__main__":
    app()
