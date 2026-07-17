from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from .models import RightsStatus
from .promotion import (
    PROMOTION_SCHEMA_VERSION,
    ActorType,
    Lane,
    ProfileState,
    PromotionAction,
    PromotionError,
    PromotionEvent,
    ReferenceState,
    append_promotion,
    current_revision_state,
    load_promotion_ledger,
    new_event_id,
)
from .reference_bundle import BundleTierRecord

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
LaneOption = Annotated[
    Lane, typer.Option("--lane", help="Promotion lane: physical (Lane B) or reference (Lane A)")
]


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


def _verify_bundle_tier_record(
    tier: str | None,
    reference_bundle_id: str | None,
    record_path: Path | None,
) -> str | None:
    """Returns the sha256 hex digest of the verified record (for the ledger
    fingerprint binding), or None when no tier is declared."""
    """Bind a declared ledger tier to the bundle's computed tier record.

    The promotion library stays IO-pure (CI replays ledgers without access to
    private bundles), so this operator-side check is where a self-declared
    `--source-quality-tier` is verified against `optcg-reference tier` output —
    including the fail-closed tier-B human-review requirement encoded in
    BundleTierRecord itself. Direct library callers can still self-declare;
    that residual is documented in the approval-state-machine threat model.
    """
    if tier is None:
        return None
    if record_path is None:
        _fail(
            "--bundle-tier-record is required when declaring --source-quality-tier "
            "on a reference-lane event (produce it with `optcg-reference tier`)"
        )
        return
    try:
        record = BundleTierRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        _fail(f"unreadable or invalid bundle tier record {record_path}: {exc}")
        return
    if reference_bundle_id and record.bundle_id != reference_bundle_id:
        _fail(
            f"tier record bundle_id '{record.bundle_id}' does not match "
            f"--reference-bundle-id '{reference_bundle_id}'"
        )
    if record.tier.value != tier:
        _fail(f"declared tier '{tier}' does not match computed tier '{record.tier.value}'")
    if not record.eligible_for_profile:
        _fail(
            f"bundle '{record.bundle_id}' is not eligible for a profile at tier "
            f"'{record.tier.value}' (tier C, or tier B without a recorded human review)"
        )
    import hashlib

    return hashlib.sha256(record_path.read_bytes()).hexdigest()


def _append(ledger: Path, **fields) -> None:
    # Keep `lane: None` (⇒ physical) for the common case so serialized events
    # stay byte-identical to the pre-two-lane ledger format.
    if fields.get("lane") is Lane.PHYSICAL:
        fields["lane"] = None
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
    lane: LaneOption = Lane.PHYSICAL,
    to_state: Annotated[
        str | None,
        typer.Option(
            "--to-state",
            help="Entry state; defaults to authenticated-capture-ingested (physical) "
            "or hypothesis (reference)",
        ),
    ] = None,
    source_session: Annotated[str | None, typer.Option("--source-session")] = None,
    input_hash: Annotated[list[str], typer.Option("--input-hash")] = [],  # noqa: B006 - typer collects repeats
    fingerprint: Annotated[
        str | None, typer.Option("--fingerprint", help='JSON object, e.g. {"captures":"<hash>"}')
    ] = None,
    reference_bundle_id: Annotated[str | None, typer.Option("--reference-bundle-id")] = None,
    source_quality_tier: Annotated[str | None, typer.Option("--source-quality-tier")] = None,
    adversarial_review: Annotated[str | None, typer.Option("--adversarial-review")] = None,
    linked_reference_revision: Annotated[
        int | None, typer.Option("--linked-reference-revision")
    ] = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    """Open a new profile revision at an entry state."""
    if to_state is None:
        to_state = (
            ReferenceState.HYPOTHESIS.value
            if lane is Lane.REFERENCE
            else ProfileState.AUTHENTICATED_CAPTURE_INGESTED.value
        )
    _append(
        ledger,
        profile_id=profile_id,
        revision=revision,
        action=PromotionAction.OPEN_REVISION,
        to_state=to_state,
        actor=actor,
        actor_type=actor_type,
        lane=lane,
        source_session=source_session,
        input_hashes=_parse_hashes(input_hash),
        fingerprint=_parse_json_option(fingerprint, "--fingerprint"),
        reference_bundle_id=reference_bundle_id,
        source_quality_tier=source_quality_tier,
        adversarial_review=adversarial_review,
        linked_reference_revision=linked_reference_revision,
        reason=reason,
    )


@app.command("promote")
def promote_command(
    ledger: LedgerArgument,
    profile_id: Annotated[str, typer.Option("--profile-id")],
    from_state: Annotated[str, typer.Option("--from-state")],
    to_state: Annotated[str, typer.Option("--to-state")],
    actor: ActorOption,
    actor_type: ActorTypeOption,
    revision: Annotated[int, typer.Option("--revision", min=1)],
    lane: LaneOption = Lane.PHYSICAL,
    source_session: Annotated[str | None, typer.Option("--source-session")] = None,
    input_hash: Annotated[list[str], typer.Option("--input-hash")] = [],  # noqa: B006
    evidence_packet: Annotated[str | None, typer.Option("--evidence-packet")] = None,
    metrics: Annotated[str | None, typer.Option("--metrics", help="JSON object of numbers")] = None,
    technical_reviewer: Annotated[str | None, typer.Option("--technical-reviewer")] = None,
    rights_reviewer: Annotated[str | None, typer.Option("--rights-reviewer")] = None,
    rights_status: Annotated[RightsStatus | None, typer.Option("--rights-status")] = None,
    reference_bundle_id: Annotated[str | None, typer.Option("--reference-bundle-id")] = None,
    source_quality_tier: Annotated[str | None, typer.Option("--source-quality-tier")] = None,
    adversarial_review: Annotated[str | None, typer.Option("--adversarial-review")] = None,
    linked_reference_revision: Annotated[
        int | None, typer.Option("--linked-reference-revision")
    ] = None,
    bundle_tier_record: Annotated[
        Path | None,
        typer.Option(
            "--bundle-tier-record",
            help="BundleTierRecord JSON from `optcg-reference tier`; required when "
            "declaring --source-quality-tier on a reference-lane event",
        ),
    ] = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    """Advance one state. Review transitions require --actor-type human and a named reviewer."""
    raw_metrics = _parse_json_option(metrics, "--metrics")
    fingerprint_extra: dict[str, str] = {}
    if lane is Lane.REFERENCE:
        tier_digest = _verify_bundle_tier_record(
            source_quality_tier, reference_bundle_id, bundle_tier_record
        )
        if tier_digest and source_quality_tier == "B":
            # Bind the verified record into the ledger (independent-review
            # finding, PR #15): reviewers can recompute this digest.
            fingerprint_extra["bundle-tier-record"] = tier_digest
    _append(
        ledger,
        profile_id=profile_id,
        revision=revision,
        action=PromotionAction.PROMOTE,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        actor_type=actor_type,
        lane=lane,
        source_session=source_session,
        input_hashes=_parse_hashes(input_hash),
        fingerprint=fingerprint_extra,
        evidence_packet=evidence_packet,
        metrics={key: float(value) for key, value in raw_metrics.items()},
        technical_reviewer=technical_reviewer,
        rights_reviewer=rights_reviewer,
        rights_status=rights_status,
        reference_bundle_id=reference_bundle_id,
        source_quality_tier=source_quality_tier,
        adversarial_review=adversarial_review,
        linked_reference_revision=linked_reference_revision,
        reason=reason,
    )


@app.command("demote")
def demote_command(
    ledger: LedgerArgument,
    profile_id: Annotated[str, typer.Option("--profile-id")],
    from_state: Annotated[str, typer.Option("--from-state")],
    to_state: Annotated[str, typer.Option("--to-state")],
    actor: ActorOption,
    actor_type: ActorTypeOption,
    revision: Annotated[int, typer.Option("--revision", min=1)],
    reason: Annotated[str, typer.Option("--reason", help="The failed gate or superseding evidence")],
    lane: LaneOption = Lane.PHYSICAL,
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
        lane=lane,
        reason=reason,
    )


@app.command("prototype-attestation")
def prototype_attestation_command(
    ledger: LedgerArgument,
    profile_id: Annotated[str, typer.Option("--profile-id")],
    profile: Annotated[Path, typer.Option("--profile", exists=True, dir_okay=False,
        help="The exact profile JSON the attestation binds (byte-level sha256)")],
    output: Annotated[Path, typer.Option("--output")],
    evidence_packet_file: Annotated[Path | None, typer.Option("--evidence-packet-file",
        exists=True, dir_okay=False,
        help="Evidence packet file to hash; defaults to the path recorded in the ledger")] = None,
) -> None:
    """Emit the canonical internal-reference-prototype attestation for the CSS
    compiler. Verifies the full ledger (digest chain + semantic replay) and
    refuses unless the head revision is lane=reference at
    internal-reference-prototype with every ladder requirement recorded. The
    JavaScript consumer validates this report's shape and byte bindings only —
    promotion semantics live here, never in JS."""
    import hashlib

    try:
        events = load_promotion_ledger(ledger)
    except PromotionError as exc:
        _fail(f"ledger failed verification: {exc}")
        return
    state = current_revision_state(events, profile_id)
    if state is None:
        _fail(f"no events for profile '{profile_id}'")
        return
    if state.lane is not Lane.REFERENCE:
        _fail(f"profile '{profile_id}' head revision is lane '{state.lane}', not reference")
        return
    if str(state.state) != "internal-reference-prototype":
        _fail(
            f"profile '{profile_id}' is at state '{state.state}', not "
            "internal-reference-prototype; no attestation can be issued"
        )
        return

    rev_events = [
        e for e in events if e.profile_id == profile_id and e.revision == state.revision
    ]
    proto_event = next(
        (e for e in reversed(rev_events)
         if e.action is PromotionAction.PROMOTE
         and str(e.to_state) == "internal-reference-prototype"),
        None,
    )
    if proto_event is None:
        _fail("no internal-reference-prototype promotion event found on the head revision")
        return

    def last(attr: str):
        return next((getattr(e, attr) for e in reversed(rev_events) if getattr(e, attr)), None)

    reference_bundle_id = last("reference_bundle_id")
    source_quality_tier = last("source_quality_tier")
    adversarial_review = proto_event.adversarial_review or last("adversarial_review")
    technical_reviewer = proto_event.technical_reviewer
    rights_status = last("rights_status")
    evidence_packet = proto_event.evidence_packet or last("evidence_packet")
    metrics_present = any(e.metrics for e in rev_events)
    input_hashes = sorted({h for e in rev_events for h in e.input_hashes})
    tier_record_digest = state.fingerprint.get("bundle-tier-record")

    problems = []
    if not reference_bundle_id:
        problems.append("no reference_bundle_id recorded")
    if source_quality_tier not in ("A", "B"):
        problems.append(f"source_quality_tier is '{source_quality_tier}', not A or B")
    if source_quality_tier == "B" and not tier_record_digest:
        problems.append("tier B without a bundle-tier-record fingerprint digest")
    if not adversarial_review:
        problems.append("no adversarial_review reference recorded")
    if not technical_reviewer:
        problems.append("no technical_reviewer on the prototype event")
    if rights_status in (None, RightsStatus.UNKNOWN):
        problems.append("rights_status is unresolved")
    if not evidence_packet:
        problems.append("no evidence_packet recorded")
    if not metrics_present:
        problems.append("no quantitative metrics recorded on the revision")
    if not input_hashes:
        problems.append("no input hashes recorded")
    if problems:
        _fail("ledger is missing prototype requirements: " + "; ".join(problems))
        return

    packet_path = evidence_packet_file or Path(evidence_packet)
    if not packet_path.is_file():
        _fail(f"evidence packet file not found: {packet_path}")
        return

    report = {
        "schema_version": "1.0.0",
        "report_type": "prototype-attestation",
        "passed": True,
        "profile_digest": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "ledger_head_digest": state.head_digest,
        "lane": "reference",
        "state": "internal-reference-prototype",
        "profile_id": profile_id,
        "revision": state.revision,
        "reference_bundle_id": reference_bundle_id,
        "source_quality_tier": source_quality_tier,
        "bundle_tier_record_digest": tier_record_digest,
        "evidence_packet": evidence_packet,
        "evidence_packet_digest": hashlib.sha256(packet_path.read_bytes()).hexdigest(),
        "adversarial_review": adversarial_review,
        "metrics_present": True,
        "rights_status": str(rights_status.value if hasattr(rights_status, "value") else rights_status),
        "technical_reviewer": technical_reviewer,
        "input_hashes": input_hashes,
        "verifier_version": f"optcg-promote/{PROMOTION_SCHEMA_VERSION}",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    console.print(
        f"prototype attestation written to [bold]{output}[/bold] "
        f"(profile {report['profile_digest'][:12]}, ledger head {state.head_digest[:12]})"
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
    console.print(f"lane: [bold]{state.lane}[/bold]")
    console.print(f"state: [bold]{state.state}[/bold]")
    console.print(f"fingerprint: {json.dumps(state.fingerprint, sort_keys=True)}")
    console.print(f"head digest: {state.head_digest}")
