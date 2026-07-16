from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .provenance import ProvenanceError
from .review import (
    ReviewAction,
    ReviewError,
    ReviewItem,
    append_event,
    check_publication,
    derive_status,
    load_ledger,
)

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "card-material-profile.schema.json"

app = typer.Typer(
    name="optcg-review",
    help="Immutable human-review ledger and publication gate for material profiles.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _append(session_root: Path, **kwargs) -> None:
    try:
        event = append_event(session_root, **kwargs)
    except (ReviewError, ProvenanceError, ValueError) as exc:
        _fail(str(exc))
        return
    console.print(f"recorded [bold]{event.action}[/bold] as {event.event_id} (seq {event.sequence})")


ReviewerOption = Annotated[str, typer.Option("--reviewer", help="Named human reviewer")]
SessionArgument = Annotated[Path, typer.Argument(help="Private capture-session directory")]


@app.command("open")
def open_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    profile_version: Annotated[str | None, typer.Option("--profile-version")] = None,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    """Open a review for the session."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.OPEN_REVIEW,
        profile_version=profile_version,
        comment=comment,
    )


@app.command("comment")
def comment_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    comment: Annotated[str, typer.Option("--comment")],
    item: Annotated[ReviewItem | None, typer.Option("--item")] = None,
    channel: Annotated[str | None, typer.Option("--channel")] = None,
    requires_resolution: Annotated[bool, typer.Option("--blocking/--non-blocking")] = False,
) -> None:
    """Record a review comment; blocking comments prevent approval until resolved."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.COMMENT,
        item=item,
        channel=channel,
        comment=comment,
        requires_resolution=requires_resolution,
    )


@app.command("resolve")
def resolve_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    target: Annotated[str, typer.Option("--target", help="Comment event id to resolve")],
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    """Resolve a blocking comment."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.RESOLVE_COMMENT,
        target_event_id=target,
        comment=comment,
    )


@app.command("approve-item")
def approve_item_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    item: Annotated[ReviewItem, typer.Option("--item")],
    channel: Annotated[str | None, typer.Option("--channel")] = None,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
    before_digest: Annotated[str | None, typer.Option("--before-digest")] = None,
    after_digest: Annotated[str | None, typer.Option("--after-digest")] = None,
) -> None:
    """Approve one required review item."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.APPROVE_ITEM,
        item=item,
        channel=channel,
        comment=comment,
        before_digest=before_digest,
        after_digest=after_digest,
    )


@app.command("reject-item")
def reject_item_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    item: Annotated[ReviewItem, typer.Option("--item")],
    comment: Annotated[str, typer.Option("--comment", help="What must be revised")],
    channel: Annotated[str | None, typer.Option("--channel")] = None,
) -> None:
    """Reject one required review item; the session drops to needs-revision."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.REJECT_ITEM,
        item=item,
        channel=channel,
        comment=comment,
    )


@app.command("approve-technical")
def approve_technical_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    """Grant technical approval; requires every technical item approved."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.APPROVE_TECHNICAL,
        comment=comment,
    )


@app.command("approve-rights")
def approve_rights_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    """Grant rights approval; requires an approved rights item."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.APPROVE_RIGHTS,
        comment=comment,
    )


@app.command("approve-production")
def approve_production_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    profile_version: Annotated[str | None, typer.Option("--profile-version")] = None,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    """Grant production approval; requires active technical and rights approvals."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.APPROVE_PRODUCTION,
        profile_version=profile_version,
        comment=comment,
    )


@app.command("revoke")
def revoke_command(
    session_root: SessionArgument,
    reviewer: ReviewerOption,
    target: Annotated[str, typer.Option("--target", help="Approval event id to revoke")],
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    """Revoke a previously granted approval."""
    _append(
        session_root,
        reviewer=reviewer,
        action=ReviewAction.REVOKE_APPROVAL,
        target_event_id=target,
        comment=comment,
    )


@app.command("status")
def status_command(session_root: SessionArgument) -> None:
    """Show the derived review state and checklist."""
    try:
        events = load_ledger(session_root)
    except ReviewError as exc:
        _fail(str(exc))
        return
    report = derive_status(events)

    console.print(f"session: [bold]{report.session_id}[/bold]")
    console.print(f"state: [bold]{report.state}[/bold]  events: {report.event_count}")
    if report.head_digest:
        console.print(f"head digest: {report.head_digest}")

    table = Table(title="Required review items")
    table.add_column("item")
    table.add_column("decision")
    table.add_column("reviewer")
    for item in ReviewItem:
        decision = report.item_decisions.get(item.value)
        if decision is None:
            table.add_row(item.value, "[yellow]undecided[/yellow]", "-")
        elif decision.approved:
            table.add_row(item.value, "[green]approved[/green]", decision.reviewer)
        else:
            table.add_row(item.value, "[red]rejected[/red]", decision.reviewer)
    console.print(table)

    if report.unresolved_required_comments:
        console.print(
            "[red]unresolved blocking comments:[/red] "
            + ", ".join(report.unresolved_required_comments)
        )
    for approval in report.approvals:
        flag = "[green]active[/green]" if approval.active else "[red]inactive[/red]"
        console.print(f"{approval.action}: {flag} by {approval.reviewer} ({approval.event_id})")


@app.command("log")
def log_command(session_root: SessionArgument) -> None:
    """Print the verified review event log."""
    try:
        events = load_ledger(session_root)
    except ReviewError as exc:
        _fail(str(exc))
        return
    for event in events:
        console.print(event.model_dump_json(exclude_none=True))


@app.command("verify")
def verify_command(session_root: SessionArgument) -> None:
    """Verify the review ledger hash chain."""
    try:
        events = load_ledger(session_root)
    except ReviewError as exc:
        _fail(str(exc))
        return
    console.print(f"ledger verified: {len(events)} events")


@app.command("check-publish")
def check_publish_command(
    session_root: SessionArgument,
    profile: Annotated[Path, typer.Option("--profile", help="Material profile JSON")],
    schema: Annotated[Path, typer.Option("--schema")] = DEFAULT_SCHEMA_PATH,
    assets_root: Annotated[Path | None, typer.Option("--assets-root")] = None,
    report_path: Annotated[Path | None, typer.Option("--report", help="Write the JSON report here")] = None,
) -> None:
    """Run every publication gate; exit non-zero when any gate fails."""
    report = check_publication(session_root, profile, schema, assets_root=assets_root)

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
        )

    for warning in report.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")
    for error in report.errors:
        console.print(f"[red]blocked:[/red] {error}")

    if report.passed:
        console.print("[green]publication gates passed[/green]")
    else:
        console.print(f"[bold red]publication blocked[/bold red] (state: {report.state})")
        raise typer.Exit(code=1)
