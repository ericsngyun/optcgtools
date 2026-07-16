from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from .models import RightsStatus
from .promotion import (
    ActorType,
    ProfileState,
    PromotionAction,
    PromotionError,
    PromotionEvent,
    append_promotion,
    current_revision_state,
    load_promotion_ledger,
    new_event_id,
)

app = typer.Typer(
    name="optcg-promote",
    help="Append-only profile promotion ledger (approval state machine).",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()

LedgerArgument = Annotated[Path, typer.Argument(help="Promotion ledger JSONL path")]
ActorOption = Annotated[str, typer.Option("--actor", help="Named human, agent, or CI identity")]
ActorTypeOption = Annotated[ActorType, typer.Option("--actor-type")]


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _parse_hashes(values: list[str]) -> list[str]:
    return [value.strip().lower() for value in values if value.strip()]


def _parse_json_option(raw: str | None, option: str) -> dict:
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"{option} must be a JSON object: {exc}")
    if not isinstance(parsed, dict):
        _fail(f"{option} must be a JSON object")
    return parsed


def _append(ledger: Path, **fields) -> None:
    try:
        event = PromotionEvent(event_id=new_event_id(), sequence=0, **fields)
        event = append_promotion(ledger, event)
    except (PromotionError, ValidationError, ValueError) as exc:
        _fail(str(exc))
        return
    console.print(
        f"recorded [bold]{event.action}[/bold] -> {event.to_state} "
        f"(revision {event.revision}, seq {event.sequence}, {event.event_id})"
    )


@app.command("open-revision")
def open_revision_command(
    ledger: LedgerArgument,
    profile_id: Annotated[str, typer.Option("--profile-id")],
    actor: ActorOption,
    actor_type: ActorTypeOption,
    revision: Annotated[int, typer.Option("--revision", min=1)],
    to_state: Annotated[ProfileState, typer.Option("--to-state")] = (
        ProfileState.AUTHENTICATED_CAPTURE_INGESTED
    ),
    source_session: Annotated[str | None, typer.Option("--source-session")] = None,
    input_hash: Annotated[list[str], typer.Option("--input-hash")] = [],  # noqa: B006 - typer collects repeats
    fingerprint: Annotated[
        str | None, typer.Option("--fingerprint", help='JSON object, e.g. {"captures":"<hash>"}')
    ] = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    """Open a new profile revision at an entry state."""
    _append(
        ledger,
        profile_id=profile_id,
        revision=revision,
        action=PromotionAction.OPEN_REVISION,
        to_state=to_state,
        actor=actor,
        actor_type=actor_type,
        source_session=source_session,
        input_hashes=_parse_hashes(input_hash),
        fingerprint=_parse_json_option(fingerprint, "--fingerprint"),
        reason=reason,
    )


@app.command("promote")
def promote_command(
    ledger: LedgerArgument,
    profile_id: Annotated[str, typer.Option("--profile-id")],
    from_state: Annotated[ProfileState, typer.Option("--from-state")],
    to_state: Annotated[ProfileState, typer.Option("--to-state")],
    actor: ActorOption,
    actor_type: ActorTypeOption,
    revision: Annotated[int, typer.Option("--revision", min=1)],
    source_session: Annotated[str | None, typer.Option("--source-session")] = None,
    input_hash: Annotated[list[str], typer.Option("--input-hash")] = [],  # noqa: B006
    evidence_packet: Annotated[str | None, typer.Option("--evidence-packet")] = None,
    metrics: Annotated[str | None, typer.Option("--metrics", help="JSON object of numbers")] = None,
    technical_reviewer: Annotated[str | None, typer.Option("--technical-reviewer")] = None,
    rights_reviewer: Annotated[str | None, typer.Option("--rights-reviewer")] = None,
    rights_status: Annotated[RightsStatus | None, typer.Option("--rights-status")] = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    """Advance one state. Review transitions require --actor-type human and a named reviewer."""
    raw_metrics = _parse_json_option(metrics, "--metrics")
    _append(
        ledger,
        profile_id=profile_id,
        revision=revision,
        action=PromotionAction.PROMOTE,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        actor_type=actor_type,
        source_session=source_session,
        input_hashes=_parse_hashes(input_hash),
        evidence_packet=evidence_packet,
        metrics={key: float(value) for key, value in raw_metrics.items()},
        technical_reviewer=technical_reviewer,
        rights_reviewer=rights_reviewer,
        rights_status=rights_status,
        reason=reason,
    )


@app.command("demote")
def demote_command(
    ledger: LedgerArgument,
    profile_id: Annotated[str, typer.Option("--profile-id")],
    from_state: Annotated[ProfileState, typer.Option("--from-state")],
    to_state: Annotated[ProfileState, typer.Option("--to-state")],
    actor: ActorOption,
    actor_type: ActorTypeOption,
    revision: Annotated[int, typer.Option("--revision", min=1)],
    reason: Annotated[str, typer.Option("--reason", help="The failed gate or superseding evidence")],
) -> None:
    """Move to an earlier state after a failed gate; requires a reason."""
    _append(
        ledger,
        profile_id=profile_id,
        revision=revision,
        action=PromotionAction.DEMOTE,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        actor_type=actor_type,
        reason=reason,
    )


@app.command("status")
def status_command(
    ledger: LedgerArgument,
    profile_id: Annotated[str, typer.Option("--profile-id")],
) -> None:
    """Show the verified current revision and state for a profile."""
    try:
        events = load_promotion_ledger(ledger)
    except PromotionError as exc:
        _fail(str(exc))
        return
    state = current_revision_state(events, profile_id)
    if state is None:
        console.print(f"no events for profile [bold]{profile_id}[/bold]")
        raise typer.Exit(code=1)
    console.print(f"profile: [bold]{state.profile_id}[/bold]")
    console.print(f"revision: {state.revision}")
    console.print(f"state: [bold]{state.state}[/bold]")
    console.print(f"fingerprint: {json.dumps(state.fingerprint, sort_keys=True)}")
    console.print(f"head digest: {state.head_digest}")
