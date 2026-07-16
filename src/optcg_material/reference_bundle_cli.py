"""``optcg-reference`` — Lane A public-reference bundle CLI (ADR-0002).

Verbs: init-bundle, verify-variant, add-source, add-media, acquisition-task,
score, tier, validate. There is intentionally no fetch/download verb: agents
never retrieve marketplace media and never automate around anti-bot controls;
blocked retrievals become human acquisition tasks.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from .models import Language, RightsStatus
from .reference_bundle import (
    AcquisitionStatus,
    BlockReason,
    BundleError,
    CompressionLevel,
    EditingLikelihood,
    LightingUsefulness,
    MediaForm,
    MediaResolution,
    Protection,
    ProxyRisk,
    ReferenceSourceRecord,
    RetrievalStatus,
    SourceType,
    add_media,
    add_source,
    create_acquisition_task,
    init_bundle,
    list_acquisition_tasks,
    record_variant_verification,
    score_bundle_sources,
    tier_bundle,
    validate_bundle,
)

app = typer.Typer(
    name="optcg-reference",
    help="Lane A public-reference bundle manifests, scoring, and tier gating.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()

BundleRootArgument = Annotated[
    Path, typer.Argument(help="Private bundle root outside any git repository")
]


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _parse_datetime(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@app.command("init-bundle")
def init_bundle_command(
    bundle_root: BundleRootArgument,
    bundle_id: Annotated[str, typer.Option("--bundle-id")],
    card_id: Annotated[str, typer.Option("--card-id")],
    set_code: Annotated[str, typer.Option("--set-code")],
    exact_print_variant: Annotated[str, typer.Option("--exact-print-variant")],
    region_release: Annotated[str, typer.Option("--region-release")],
    language: Annotated[Language, typer.Option("--language")] = Language.EN,
    rights_status: Annotated[
        RightsStatus, typer.Option("--rights-status")
    ] = RightsStatus.UNKNOWN,
    notes: Annotated[str | None, typer.Option("--notes")] = None,
) -> None:
    """Create the private bundle layout and an unverified manifest."""
    try:
        manifest = init_bundle(
            bundle_root,
            bundle_id=bundle_id,
            card_id=card_id,
            set_code=set_code,
            language=language,
            exact_print_variant=exact_print_variant,
            region_release=region_release,
            rights_status=rights_status,
            notes=notes,
        )
    except (BundleError, ValidationError) as exc:
        _fail(str(exc))
    console.print(f"created bundle [bold]{manifest.bundle_id}[/bold] at {bundle_root}")
    console.print("variant verification is [yellow]pending human review[/yellow]")


@app.command("verify-variant")
def verify_variant_command(
    bundle_root: BundleRootArgument,
    verifier: Annotated[str, typer.Option("--verifier", help="Named human reviewer")],
    method: Annotated[str, typer.Option("--method")],
    confidence: Annotated[float, typer.Option("--confidence", min=0.0, max=1.0)],
    notes: Annotated[str | None, typer.Option("--notes")] = None,
) -> None:
    """Record the human-only exact-print-variant verification."""
    try:
        record_variant_verification(
            bundle_root,
            verifier=verifier,
            method=method,
            confidence=confidence,
            notes=notes,
        )
    except (BundleError, ValidationError) as exc:
        _fail(str(exc))
    console.print(f"variant verification recorded by [bold]{verifier}[/bold]")


@app.command("add-source")
def add_source_command(
    bundle_root: BundleRootArgument,
    source_id: Annotated[str, typer.Option("--source-id")],
    source_url: Annotated[str, typer.Option("--source-url")],
    source_type: Annotated[SourceType, typer.Option("--source-type")],
    card_id: Annotated[str, typer.Option("--card-id")],
    exact_print_variant: Annotated[str, typer.Option("--exact-print-variant")],
    region_release: Annotated[str, typer.Option("--region-release")],
    protection: Annotated[Protection, typer.Option("--protection")],
    media_form: Annotated[MediaForm, typer.Option("--media-form")],
    useful_angles: Annotated[int, typer.Option("--useful-angles", min=0)],
    lighting: Annotated[LightingUsefulness, typer.Option("--lighting")],
    compression: Annotated[CompressionLevel, typer.Option("--compression")],
    editing_likelihood: Annotated[EditingLikelihood, typer.Option("--editing-likelihood")],
    variant_confidence: Annotated[float, typer.Option("--variant-confidence", min=0.0, max=1.0)],
    proxy_risk: Annotated[ProxyRisk, typer.Option("--proxy-risk")],
    rights_status: Annotated[RightsStatus, typer.Option("--rights-status")],
    retrieval_status: Annotated[RetrievalStatus, typer.Option("--retrieval-status")],
    language: Annotated[Language, typer.Option("--language")] = Language.EN,
    macro: Annotated[bool, typer.Option("--macro/--no-macro")] = False,
    retrieval_date: Annotated[
        str | None, typer.Option("--retrieval-date", help="ISO 8601; defaults to now")
    ] = None,
    seller: Annotated[str | None, typer.Option("--seller")] = None,
    width: Annotated[int | None, typer.Option("--width", min=1)] = None,
    height: Annotated[int | None, typer.Option("--height", min=1)] = None,
    review_notes: Annotated[str | None, typer.Option("--review-notes")] = None,
    reason_blocked: Annotated[
        BlockReason,
        typer.Option("--reason-blocked", help="Used only when --retrieval-status blocked"),
    ] = BlockReason.ANTI_BOT,
    requested_media: Annotated[str | None, typer.Option("--requested-media")] = None,
) -> None:
    """Register a public source URL; a blocked retrieval opens a human task."""
    resolution = None
    if width is not None and height is not None:
        resolution = MediaResolution(width=width, height=height)
    elif (width is None) != (height is None):
        _fail("--width and --height must be provided together")
    try:
        record = ReferenceSourceRecord(
            source_id=source_id,
            source_url=source_url,
            source_type=source_type,
            retrieval_date=_parse_datetime(retrieval_date),
            card_id=card_id,
            language=language,
            exact_print_variant=exact_print_variant,
            region_release=region_release,
            seller_uploader=seller,
            protection=protection,
            media_form=media_form,
            resolution=resolution,
            useful_angles=useful_angles,
            macro_available=macro,
            lighting_usefulness=lighting,
            compression_level=compression,
            editing_likelihood=editing_likelihood,
            variant_confidence=variant_confidence,
            proxy_counterfeit_risk=proxy_risk,
            rights_status=rights_status,
            retrieval_status=retrieval_status,
            review_notes=review_notes,
        )
        record, task = add_source(
            bundle_root,
            record,
            blocked_reason=reason_blocked,
            requested_media=requested_media,
        )
    except (BundleError, ValidationError, ValueError) as exc:
        _fail(str(exc))
    console.print(f"registered source [bold]{record.source_id}[/bold]")
    if task is not None:
        console.print(
            f"retrieval blocked ({task.reason_blocked.value}); opened acquisition "
            f"task [bold]{task.task_id}[/bold] for a human — no automated workaround exists"
        )


@app.command("add-media")
def add_media_command(
    bundle_root: BundleRootArgument,
    source_id: Annotated[str, typer.Argument()],
    media_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Hash-record and copy one human-acquired media file into private storage."""
    try:
        record, destination, digest = add_media(bundle_root, source_id, media_path)
    except (BundleError, ValidationError) as exc:
        _fail(str(exc))
    console.print(f"ingested media for [bold]{record.source_id}[/bold]")
    console.print(f"path: {destination}")
    console.print(f"blake3: {digest}")


@app.command("acquisition-task")
def acquisition_task_command(
    bundle_root: BundleRootArgument,
    list_tasks: Annotated[bool, typer.Option("--list")] = False,
    source_url: Annotated[str | None, typer.Option("--source-url")] = None,
    reason: Annotated[BlockReason, typer.Option("--reason")] = BlockReason.ANTI_BOT,
    requested_media: Annotated[str | None, typer.Option("--requested-media")] = None,
    task_id: Annotated[str | None, typer.Option("--task-id")] = None,
    assignee: Annotated[str | None, typer.Option("--assignee")] = None,
) -> None:
    """Create or list human acquisition tasks for blocked retrievals."""
    if list_tasks:
        tasks = list_acquisition_tasks(bundle_root)
        table = Table("Task", "URL", "Reason", "Status", "Assignee")
        for task in tasks:
            table.add_row(
                task.task_id,
                task.source_url,
                task.reason_blocked.value,
                task.status.value,
                task.assignee or "-",
            )
        console.print(table)
        open_count = sum(task.status is AcquisitionStatus.OPEN for task in tasks)
        console.print(f"{len(tasks)} task(s), {open_count} open")
        return
    if source_url is None or requested_media is None:
        _fail("--source-url and --requested-media are required unless --list is given")
    try:
        task = create_acquisition_task(
            bundle_root,
            source_url=source_url,
            reason_blocked=reason,
            requested_media=requested_media,
            task_id=task_id,
            assignee=assignee,
        )
    except (BundleError, ValidationError) as exc:
        _fail(str(exc))
    console.print(f"created acquisition task [bold]{task.task_id}[/bold] for a human")


@app.command("score")
def score_command(
    bundle_root: BundleRootArgument,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Deterministically score every source with the documented weights."""
    try:
        scores = score_bundle_sources(bundle_root)
    except (BundleError, ValidationError) as exc:
        _fail(str(exc))
    if json_output:
        console.print_json(
            json.dumps([score.model_dump(mode="json", exclude_none=True) for score in scores])
        )
        return
    table = Table("Source", "Composite", "Tier", "Rationale")
    for score in scores:
        table.add_row(
            score.source_id,
            f"{score.composite_score:.4f}",
            score.tier.value,
            score.tier_rationale,
        )
    console.print(table)


@app.command("tier")
def tier_command(
    bundle_root: BundleRootArgument,
    human_reviewed_tier_b: Annotated[
        bool,
        typer.Option(
            "--human-reviewed-tier-b/--not-human-reviewed",
            help="Only a named human reviewer may record a tier-B review",
        ),
    ] = False,
    reviewer: Annotated[str | None, typer.Option("--reviewer")] = None,
) -> None:
    """Aggregate source scores into the bundle tier and eligibility gate."""
    try:
        record = tier_bundle(
            bundle_root,
            human_reviewed_tier_b=human_reviewed_tier_b,
            reviewer=reviewer,
        )
    except (BundleError, ValidationError) as exc:
        _fail(str(exc))
    console.print(f"bundle tier: [bold]{record.tier.value}[/bold]")
    eligibility = "eligible" if record.eligible_for_profile else "NOT eligible"
    console.print(f"profile eligibility: [bold]{eligibility}[/bold]")
    if record.tier.value == "B" and not record.eligible_for_profile:
        console.print(
            "tier B requires a recorded human review "
            "(--human-reviewed-tier-b --reviewer <name>) before it is eligible"
        )


@app.command("validate")
def validate_command(
    bundle_root: BundleRootArgument,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Verify manifest digest, hashes, blocked-source tasks, and tier consistency."""
    result = validate_bundle(bundle_root)
    if json_output:
        console.print_json(json.dumps(result))
    else:
        console.print(f"bundle: [bold]{result['bundle_id']}[/bold]")
        console.print(f"sources: {result['sources']}")
        for error in result["errors"]:
            console.print(f"[red]• {error}[/red]")
        if result["valid"]:
            console.print("[bold green]valid[/bold green]")
    if not result["valid"]:
        raise typer.Exit(code=2)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
