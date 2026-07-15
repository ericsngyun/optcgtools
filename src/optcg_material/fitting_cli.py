from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from .fitting import FitError, evaluate_fit_sequence, load_fit_request, write_fit_schema

app = typer.Typer(
    name="optcg-fit",
    help="Evaluate matched physical and synthesized card render sequences.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


@app.command("evaluate")
def evaluate_command(
    root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Compute interpretable losses for one matched reference/candidate sequence."""
    try:
        request = load_fit_request(request_path)
        report = evaluate_fit_sequence(root, request)
    except (FitError, ValidationError, OSError) as exc:
        _fail(str(exc))
    console.print_json(report.model_dump_json(exclude_none=True))


@app.command("validate-request")
def validate_request_command(
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate a fitting request without reading image content."""
    try:
        request = load_fit_request(request_path)
    except (FitError, ValidationError, OSError) as exc:
        _fail(str(exc))
    console.print_json(request.model_dump_json(exclude_none=True))


@app.command("write-schema")
def schema_command(
    output: Annotated[Path, typer.Argument()] = Path("schemas/fit-sequence.schema.json"),
) -> None:
    """Emit the canonical fitting request JSON Schema."""
    write_fit_schema(output)
    console.print(f"wrote {output}")


if __name__ == "__main__":
    app()
