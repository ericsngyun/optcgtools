from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from optcg_material.promotion_cli import app

runner = CliRunner()
HASH = "a" * 64


def open_revision(ledger: Path) -> None:
    result = runner.invoke(
        app,
        [
            "open-revision",
            str(ledger),
            "--profile-id", "op05-119-luffy",
            "--actor", "capture-operator",
            "--actor-type", "agent",
            "--revision", "1",
            "--source-session", "op05-119-luffy-en-001",
            "--input-hash", HASH,
            "--fingerprint", '{"captures": "' + HASH + '"}',
        ],
    )
    assert result.exit_code == 0, result.output


def test_open_revision_and_status(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    result = runner.invoke(app, ["status", str(ledger), "--profile-id", "op05-119-luffy"])
    assert result.exit_code == 0, result.output
    assert "authenticated-capture-ingested" in result.output
    assert "revision: 1" in result.output


def test_agent_cannot_promote_to_human_only_state(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    result = runner.invoke(
        app,
        [
            "promote",
            str(ledger),
            "--profile-id", "op05-119-luffy",
            "--from-state", "authenticated-capture-ingested",
            "--to-state", "quality-approved",
            "--actor", "capture-operator",
            "--actor-type", "agent",
            "--revision", "1",
            "--source-session", "op05-119-luffy-en-001",
            "--input-hash", HASH,
            "--evidence-packet", "review/evidence/quality.json",
        ],
    )
    assert result.exit_code == 1
    assert "human-only" in result.output


def test_human_promotion_and_demotion(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    result = runner.invoke(
        app,
        [
            "promote",
            str(ledger),
            "--profile-id", "op05-119-luffy",
            "--from-state", "authenticated-capture-ingested",
            "--to-state", "quality-approved",
            "--actor", "Eric Yun",
            "--actor-type", "human",
            "--technical-reviewer", "Eric Yun",
            "--revision", "1",
            "--source-session", "op05-119-luffy-en-001",
            "--input-hash", HASH,
            "--evidence-packet", "review/evidence/quality.json",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "demote",
            str(ledger),
            "--profile-id", "op05-119-luffy",
            "--from-state", "quality-approved",
            "--to-state", "authenticated-capture-ingested",
            "--actor", "quality-gate",
            "--actor-type", "ci",
            "--revision", "1",
            "--reason", "re-registration required after frame swim",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["status", str(ledger), "--profile-id", "op05-119-luffy"])
    assert "authenticated-capture-ingested" in result.output


def test_bad_metrics_json_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    open_revision(ledger)
    result = runner.invoke(
        app,
        [
            "promote",
            str(ledger),
            "--profile-id", "op05-119-luffy",
            "--from-state", "authenticated-capture-ingested",
            "--to-state", "quality-approved",
            "--actor", "Eric Yun",
            "--actor-type", "human",
            "--technical-reviewer", "Eric Yun",
            "--revision", "1",
            "--source-session", "op05-119-luffy-en-001",
            "--input-hash", HASH,
            "--evidence-packet", "review/evidence/quality.json",
            "--metrics", "not-json",
        ],
    )
    assert result.exit_code == 1
    assert "JSON object" in result.output
