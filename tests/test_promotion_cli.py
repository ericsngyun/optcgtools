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


# --- reference-lane tier binding (--bundle-tier-record) ---------------------


def _tier_record_json(tmp_path: Path, **overrides) -> Path:
    import json

    score = {
        "source_id": "ebay-001",
        "exact_variant_match": 1.0,
        "english_confirmation": 1.0,
        "surface_visibility": 0.8,
        "angles_score": 0.6,
        "macro_score": 0.5,
        "lighting_diversity": 0.5,
        "resolution_score": 0.8,
        "compression_penalty": 0.1,
        "editing_risk_penalty": 0.0,
        "proxy_risk_penalty": 0.0,
        "alignment_success": 0.9,
        "weights": {},
        "composite_score": 0.85,
        "tier": "A",
        "tier_rationale": "synthetic",
        "computed_at": "2026-07-16T00:00:00Z",
    }
    record = {
        "bundle_id": "op06-093-perona-v2-en-b001",
        "tier": "B",
        "source_scores": [score],
        "human_reviewed_tier_b": True,
        "reviewer": "Eric Yun",
        "eligible_for_profile": True,
    }
    record.update(overrides)
    path = tmp_path / "tier-record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _reference_ladder_to_supported(ledger: Path) -> None:
    result = runner.invoke(
        app,
        [
            "open-revision", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--actor", "capture-operator", "--actor-type", "agent",
            "--revision", "1", "--lane", "reference",
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "promote", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--from-state", "hypothesis", "--to-state", "exact-variant-verified",
            "--actor", "Eric Yun", "--actor-type", "human",
            "--technical-reviewer", "Eric Yun",
            "--revision", "1", "--lane", "reference",
            "--reference-bundle-id", "op06-093-perona-v2-en-b001",
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "promote", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--from-state", "exact-variant-verified",
            "--to-state", "public-reference-supported",
            "--actor", "capture-operator", "--actor-type", "agent",
            "--revision", "1", "--lane", "reference",
            "--reference-bundle-id", "op06-093-perona-v2-en-b001",
            "--input-hash", HASH,
        ],
    )
    assert result.exit_code == 0, result.output


def _promote_to_assets_proposed(ledger: Path, extra: list[str]) -> object:
    return runner.invoke(
        app,
        [
            "promote", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--from-state", "public-reference-supported",
            "--to-state", "reference-assets-proposed",
            "--actor", "capture-operator", "--actor-type", "agent",
            "--revision", "1", "--lane", "reference",
            "--reference-bundle-id", "op06-093-perona-v2-en-b001",
            "--input-hash", HASH,
            "--source-quality-tier", "B",
            "--evidence-packet", "docs/agent-ops/evidence-packets/synthetic.json",
            "--rights-status", "restricted-research",
            *extra,
        ],
    )


def test_reference_tier_requires_bundle_tier_record(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    _reference_ladder_to_supported(ledger)
    result = _promote_to_assets_proposed(ledger, [])
    assert result.exit_code == 1
    assert "--bundle-tier-record is required" in result.output


def test_reference_tier_record_binds_declaration(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    _reference_ladder_to_supported(ledger)
    record = _tier_record_json(tmp_path)
    result = _promote_to_assets_proposed(ledger, ["--bundle-tier-record", str(record)])
    assert result.exit_code == 0, result.output


def test_reference_tier_record_mismatch_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    _reference_ladder_to_supported(ledger)
    record = _tier_record_json(tmp_path, tier="A", human_reviewed_tier_b=False, reviewer=None)
    result = _promote_to_assets_proposed(ledger, ["--bundle-tier-record", str(record)])
    assert result.exit_code == 1
    assert "does not match computed tier" in result.output


def test_reference_tier_b_without_review_is_invalid_record(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    _reference_ladder_to_supported(ledger)
    record = _tier_record_json(tmp_path, human_reviewed_tier_b=False, reviewer=None)
    result = _promote_to_assets_proposed(ledger, ["--bundle-tier-record", str(record)])
    assert result.exit_code == 1
    assert "invalid bundle tier record" in result.output
