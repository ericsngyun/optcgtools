"""``optcg-reference-normalize`` — per-image reference normalization CLI.

Normalizes geometry only (rectification + registration to a clean English
reference) and records exposure/white-balance metadata; it never equalizes
color or brightness across sources. Weak alignment is rejected with a
diagnostic record, and originals are always retained byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from .reference_bundle import BundleError
from .reference_normalize import (
    NormalizationStatus,
    NormalizationThresholds,
    NormalizeError,
    load_normalization_record,
    normalize_bundle,
    summarize_records,
)

app = typer.Typer(
    name="optcg-reference-normalize",
    help="Rectify and register reference media; reject weak alignment honestly.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()

BundleRootArgument = Annotated[
    Path, typer.Argument(exists=True, file_okay=False, help="Private bundle root")
]


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _load_manual_quads(path: Path | None) -> dict[str, list[list[float]]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise NormalizeError("manual-quads file must be an object keyed by source_id")
    return payload


@app.command("run")
def run_command(
    bundle_root: BundleRootArgument,
    reference: Annotated[
        Path,
        typer.Option(
            "--reference",
            exists=True,
            dir_okay=False,
            help="Clean English reference image for printed-feature registration",
        ),
    ],
    source_id: Annotated[
        list[str],
        typer.Option("--source-id", help="Limit to specific sources (repeatable)"),
    ] = [],  # noqa: B006 - typer collects repeated options
    manual_quads: Annotated[
        Path | None, typer.Option("--manual-quads", exists=True, dir_okay=False)
    ] = None,
    minimum_inlier_ratio: Annotated[
        float, typer.Option("--min-inlier-ratio", min=0.0, max=1.0)
    ] = 0.45,
    maximum_reprojection_error: Annotated[
        float, typer.Option("--max-reprojection-error", min=0.1)
    ] = 3.0,
) -> None:
    """Normalize geometry for every retrieved source with ingested media."""
    thresholds = NormalizationThresholds(
        minimum_inlier_ratio=minimum_inlier_ratio,
        maximum_median_reprojection_error=maximum_reprojection_error,
    )
    try:
        records = normalize_bundle(
            bundle_root,
            reference_path=reference,
            thresholds=thresholds,
            source_ids=source_id or None,
            manual_quads=_load_manual_quads(manual_quads),
        )
    except (BundleError, NormalizeError, ValidationError, json.JSONDecodeError) as exc:
        _fail(str(exc))

    table = Table("Source", "Status", "Inliers", "Reproj. err", "Interference", "Reasons")
    for record in records:
        registration = record.registration
        interference = record.interference
        table.add_row(
            record.source_id,
            record.status.value,
            "-" if registration is None else str(registration.inliers),
            "-"
            if registration is None
            else f"{registration.median_reprojection_error:.2f}px",
            "-"
            if interference is None
            else ("flagged" if interference.flagged else "none found"),
            "; ".join(record.reasons),
        )
    console.print(table)
    summary = summarize_records(records)
    console.print(
        f"accepted {summary['accepted']}, rejected {summary['rejected']}, "
        f"skipped {summary['skipped']}"
    )
    if any(record.status is NormalizationStatus.REJECTED for record in records):
        raise typer.Exit(code=2)


@app.command("show")
def show_command(
    bundle_root: BundleRootArgument,
    source_id: Annotated[str, typer.Argument()],
) -> None:
    """Print the stored normalization diagnostic record for one source."""
    try:
        record = load_normalization_record(bundle_root, source_id)
    except (NormalizeError, ValidationError) as exc:
        _fail(str(exc))
    console.print_json(record.model_dump_json(exclude_none=True))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
