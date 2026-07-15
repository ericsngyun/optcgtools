from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from .models import (
    AuthenticationStatus,
    CaptureDirection,
    CaptureKind,
    Language,
    RightsStatus,
)
from .provenance import (
    ProvenanceError,
    add_capture_file,
    load_manifest,
    save_manifest,
    write_schema,
)
from .quality import QualityThresholds
from .session import (
    SessionError,
    initialize_session,
    rectify_session,
    register_rectified_session,
    run_quality_preflight,
    validate_session,
)

app = typer.Typer(
    name="optcg-material",
    help="Authenticated physical-card capture ingestion and registration tools.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()


def _fail(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@app.command("init")
def init_command(
    session_root: Annotated[Path, typer.Argument(help="New private capture-session directory")],
    session_id: Annotated[str, typer.Option("--session-id")],
    card_id: Annotated[str, typer.Option("--card-id")],
    card_name: Annotated[str, typer.Option("--card-name")],
    set_code: Annotated[str, typer.Option("--set-code")],
    operator: Annotated[str, typer.Option("--operator")],
    rights_owner: Annotated[str, typer.Option("--rights-owner")],
    language: Annotated[Language, typer.Option("--language")] = Language.EN,
) -> None:
    """Initialize an immutable-identity capture session."""
    try:
        session = initialize_session(
            session_root,
            session_id=session_id,
            card_id=card_id,
            card_name=card_name,
            set_code=set_code,
            language=language,
            operator=operator,
            rights_owner=rights_owner,
        )
    except (SessionError, ValidationError) as exc:
        _fail(str(exc))
    console.print(f"created [bold]{session.session_id}[/bold] at {session_root}")


@app.command("add")
def add_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    kind: Annotated[CaptureKind, typer.Option("--kind")],
    angle: Annotated[float | None, typer.Option("--angle")] = None,
    direction: Annotated[CaptureDirection, typer.Option("--direction")] = CaptureDirection.NONE,
    light_label: Annotated[str | None, typer.Option("--light-label")] = None,
    captured_at: Annotated[str | None, typer.Option("--captured-at")] = None,
) -> None:
    """Hash and copy one capture into the private session."""
    try:
        record = add_capture_file(
            session_root,
            source,
            kind,
            angle_degrees=angle,
            direction=direction,
            light_label=light_label,
            captured_at=_parse_datetime(captured_at),
        )
    except (ProvenanceError, ValidationError, ValueError) as exc:
        _fail(str(exc))
    console.print(f"added {record.path}  blake3={record.blake3}")


@app.command("verify-auth")
def verify_auth_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    method: Annotated[str, typer.Option("--method")],
    verifier: Annotated[str, typer.Option("--verifier")],
    evidence_reference: Annotated[str | None, typer.Option("--evidence-reference")] = None,
) -> None:
    """Record authenticated-card verification; no visual model can self-approve this state."""
    try:
        session = load_manifest(session_root)
        session.authentication.status = AuthenticationStatus.VERIFIED
        session.authentication.method = method
        session.authentication.verifier = verifier
        session.authentication.evidence_reference = evidence_reference
        session.authentication.verified_at = datetime.now(UTC)
        save_manifest(session_root, session)
    except (ProvenanceError, ValidationError) as exc:
        _fail(str(exc))
    console.print("authentication marked [bold green]verified[/bold green]")


@app.command("set-rights")
def set_rights_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    status: Annotated[RightsStatus, typer.Option("--status")],
    owner: Annotated[str | None, typer.Option("--owner")] = None,
    public_derivatives_allowed: Annotated[
        bool, typer.Option("--public-derivatives-allowed/--no-public-derivatives-allowed")
    ] = False,
    public_albedo_allowed: Annotated[
        bool, typer.Option("--public-albedo-allowed/--no-public-albedo-allowed")
    ] = False,
    license_reference: Annotated[str | None, typer.Option("--license-reference")] = None,
) -> None:
    """Record source rights separately from technical approval."""
    try:
        session = load_manifest(session_root)
        session.rights.status = status
        session.rights.owner = owner or session.rights.owner
        session.rights.public_derivatives_allowed = public_derivatives_allowed
        session.rights.public_albedo_allowed = public_albedo_allowed
        session.rights.license_reference = license_reference
        save_manifest(session_root, session)
    except (ProvenanceError, ValidationError) as exc:
        _fail(str(exc))
    console.print(f"rights status set to [bold]{status.value}[/bold]")


@app.command("validate")
def validate_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    strict: Annotated[bool, typer.Option("--strict/--integrity-only")] = True,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Verify hashes, paths, authentication, rights, and capture completeness."""
    try:
        result = validate_session(session_root, strict_capture_set=strict)
    except (ProvenanceError, ValidationError) as exc:
        _fail(str(exc))

    if json_output:
        console.print_json(json.dumps(result))
    else:
        console.print(f"session: [bold]{result['session_id']}[/bold]")
        console.print(f"files: {result['files']}")
        for error in result["errors"]:
            console.print(f"[red]• {error}[/red]")
        if result["valid"]:
            console.print("[bold green]valid[/bold green]")
    if not result["valid"]:
        raise typer.Exit(code=2)


@app.command("quality")
def quality_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    minimum_laplacian_variance: Annotated[
        float, typer.Option("--min-laplacian-variance")
    ] = 70.0,
) -> None:
    """Run deterministic blur, resolution, exposure, and clipping gates."""
    reports = run_quality_preflight(
        session_root,
        thresholds=QualityThresholds(min_laplacian_variance=minimum_laplacian_variance),
    )
    table = Table("Frame", "Resolution", "Blur", "Accepted", "Reasons")
    for report in reports:
        resolution = f"{report.width}x{report.height}" if report.width and report.height else "n/a"
        blur = f"{report.laplacian_variance:.1f}" if report.laplacian_variance else "n/a"
        table.add_row(
            Path(report.path).name,
            resolution,
            blur,
            "yes" if report.accepted else "no",
            "; ".join(report.reasons),
        )
    console.print(table)
    if any(not report.accepted for report in reports):
        raise typer.Exit(code=2)


@app.command("rectify")
def rectify_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    manual_quads: Annotated[
        Path | None, typer.Option("--manual-quads", exists=True, dir_okay=False)
    ] = None,
    require_quality_pass: Annotated[
        bool, typer.Option("--require-quality-pass/--allow-quality-failures")
    ] = True,
) -> None:
    """Detect the card boundary and warp stills to the canonical card canvas."""
    try:
        results = rectify_session(
            session_root,
            manual_quads_path=manual_quads,
            require_quality_pass=require_quality_pass,
        )
    except (SessionError, ProvenanceError, ValidationError, json.JSONDecodeError) as exc:
        _fail(str(exc))
    console.print_json(json.dumps(results))
    if any(result["status"].startswith("rejected") for result in results):
        raise typer.Exit(code=2)


@app.command("register")
def register_command(
    session_root: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    stable_mask: Annotated[
        Path | None, typer.Option("--stable-mask", exists=True, dir_okay=False)
    ] = None,
) -> None:
    """Residual-register rectified frames against the first albedo capture."""
    try:
        results = register_rectified_session(session_root, stable_mask_path=stable_mask)
    except (SessionError, ProvenanceError, ValidationError) as exc:
        _fail(str(exc))
    console.print_json(json.dumps(results))
    if any(result["status"].startswith("rejected") for result in results):
        raise typer.Exit(code=2)


@app.command("write-schema")
def schema_command(
    output: Annotated[Path, typer.Argument()] = Path("schemas/capture-session.schema.json"),
) -> None:
    """Emit the canonical JSON Schema from the validated Pydantic contract."""
    write_schema(output)
    console.print(f"wrote {output}")


if __name__ == "__main__":
    app()
