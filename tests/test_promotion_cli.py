from __future__ import annotations

from pathlib import Path

import pytest
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


# --- `internal-reference-prototype` (ADR-0002 amendment) --------------------


def test_internal_reference_prototype_state_string_passes_through(tmp_path: Path) -> None:
    """The `--to-state internal-reference-prototype` string is accepted end
    to end by the existing `--adversarial-review`/`--evidence-packet` flags —
    no new CLI flags are needed for this state."""
    ledger = tmp_path / "promotions.jsonl"
    _reference_ladder_to_supported(ledger)
    record = _tier_record_json(tmp_path)
    result = _promote_to_assets_proposed(ledger, ["--bundle-tier-record", str(record)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "promote", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--from-state", "reference-assets-proposed",
            "--to-state", "reference-profile-fitted",
            "--actor", "capture-operator", "--actor-type", "agent",
            "--revision", "1", "--lane", "reference",
            "--reference-bundle-id", "op06-093-perona-v2-en-b001",
            "--input-hash", HASH,
            "--source-quality-tier", "B",
            "--evidence-packet", "docs/agent-ops/evidence-packets/synthetic.json",
            "--rights-status", "restricted-research",
            "--metrics", '{"cross_reference_consistency_score": 0.8}',
            "--bundle-tier-record", str(record),
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "promote", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--from-state", "reference-profile-fitted",
            "--to-state", "adversarial-review-passed",
            "--actor", "Eric Yun", "--actor-type", "human",
            "--technical-reviewer", "Eric Yun",
            "--revision", "1", "--lane", "reference",
            "--reference-bundle-id", "op06-093-perona-v2-en-b001",
            "--input-hash", HASH,
            "--source-quality-tier", "B",
            "--evidence-packet", "docs/agent-ops/evidence-packets/synthetic.json",
            "--rights-status", "restricted-research",
            "--metrics", '{"cross_reference_consistency_score": 0.8}',
            "--bundle-tier-record", str(record),
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "promote", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--from-state", "adversarial-review-passed",
            "--to-state", "internal-reference-prototype",
            "--actor", "Eric Yun", "--actor-type", "human",
            "--technical-reviewer", "Eric Yun",
            "--revision", "1", "--lane", "reference",
            "--reference-bundle-id", "op06-093-perona-v2-en-b001",
            "--input-hash", HASH,
            "--source-quality-tier", "B",
            "--evidence-packet", "docs/agent-ops/evidence-packets/synthetic.json",
            "--rights-status", "restricted-research",
            "--metrics", '{"cross_reference_consistency_score": 0.8}',
            "--adversarial-review", "review/critic/op06-093-perona-v2.json",
            "--bundle-tier-record", str(record),
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["status", str(ledger), "--profile-id", "op06-093-perona-v2"])
    assert result.exit_code == 0, result.output
    assert "internal-reference-prototype" in result.output


# --- prototype-attestation (PR #16 blocking finding) ------------------------


def _ladder_to(ledger: Path, tmp_path: Path, stop_after: str) -> Path:
    """Walk the Lane A ladder one state at a time up to and including
    `stop_after`, returning the tier-record path used for binding."""
    record = _tier_record_json(tmp_path)
    _reference_ladder_to_supported(ledger)
    if stop_after == "public-reference-supported":
        return record
    result = _promote_to_assets_proposed(ledger, ["--bundle-tier-record", str(record)])
    assert result.exit_code == 0, result.output
    if stop_after == "reference-assets-proposed":
        return record
    steps = [
        ("reference-assets-proposed", "reference-profile-fitted", []),
        ("reference-profile-fitted", "adversarial-review-passed",
         ["--actor", "Eric Yun", "--actor-type", "human",
          "--technical-reviewer", "Eric Yun",
          "--adversarial-review", "review/critic-verdict.md"]),
        ("adversarial-review-passed", "internal-reference-prototype",
         ["--actor", "Eric Yun", "--actor-type", "human",
          "--technical-reviewer", "Eric Yun",
          "--adversarial-review", "review/critic-verdict.md"]),
    ]
    for from_state, to_state, extra in steps:
        result = runner.invoke(app, [
            "promote", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--from-state", from_state, "--to-state", to_state,
            "--actor", "capture-operator", "--actor-type", "agent",
            "--revision", "1", "--lane", "reference",
            "--reference-bundle-id", "op06-093-perona-v2-en-b001",
            "--input-hash", HASH,
            "--source-quality-tier", "B",
            "--bundle-tier-record", str(record),
            "--metrics", '{"consistency": 0.81}',
            "--evidence-packet", "docs/agent-ops/evidence-packets/synthetic.json",
            "--rights-status", "restricted-research",
            *extra,
        ])
        assert result.exit_code == 0, (to_state, result.output)
        if stop_after == to_state:
            return record
    return record


def _attest(ledger: Path, tmp_path: Path, profile_id: str = "op06-093-perona-v2"):
    profile = tmp_path / "profile.json"
    profile.write_text('{"card": {"id": "OP06-093"}}', encoding="utf-8")
    packet = tmp_path / "evidence.json"
    packet.write_text('{"synthetic": true}', encoding="utf-8")
    out = tmp_path / "prototype-attestation.json"
    result = runner.invoke(app, [
        "prototype-attestation", str(ledger),
        "--profile-id", profile_id,
        "--profile", str(profile),
        "--evidence-packet-file", str(packet),
        "--output", str(out),
    ])
    return result, out, profile, packet


def test_prototype_attestation_full_ladder_positive(tmp_path: Path) -> None:
    import hashlib
    import json as jsonlib

    ledger = tmp_path / "promotions.jsonl"
    _ladder_to(ledger, tmp_path, "internal-reference-prototype")
    result, out, profile, packet = _attest(ledger, tmp_path)
    assert result.exit_code == 0, result.output
    report = jsonlib.loads(out.read_text())
    expected_keys = {
        "schema_version", "report_type", "passed", "profile_digest",
        "ledger_head_digest", "lane", "state", "profile_id", "revision",
        "reference_bundle_id", "source_quality_tier", "bundle_tier_record_digest",
        "evidence_packet", "evidence_packet_digest", "adversarial_review",
        "metrics_present", "rights_status", "technical_reviewer",
        "input_hashes", "verifier_version",
    }
    assert set(report) == expected_keys
    assert report["passed"] is True
    assert report["report_type"] == "prototype-attestation"
    assert report["lane"] == "reference"
    assert report["state"] == "internal-reference-prototype"
    assert report["profile_id"] == "op06-093-perona-v2"
    assert report["source_quality_tier"] == "B"
    assert report["bundle_tier_record_digest"] and len(report["bundle_tier_record_digest"]) == 64
    assert report["profile_digest"] == hashlib.sha256(profile.read_bytes()).hexdigest()
    assert report["evidence_packet_digest"] == hashlib.sha256(packet.read_bytes()).hexdigest()
    assert report["technical_reviewer"] == "Eric Yun"
    assert report["adversarial_review"] == "review/critic-verdict.md"
    assert report["rights_status"] == "restricted-research"
    assert report["metrics_present"] is True
    assert report["input_hashes"] == [HASH]
    assert report["verifier_version"].startswith("optcg-promote/")


@pytest.mark.parametrize("stop_after", [
    "hypothesis-only",
    "public-reference-supported",
    "reference-profile-fitted",
    "adversarial-review-passed",
])
def test_prototype_attestation_refuses_early_states(tmp_path: Path, stop_after: str) -> None:
    ledger = tmp_path / "promotions.jsonl"
    if stop_after == "hypothesis-only":
        result = runner.invoke(app, [
            "open-revision", str(ledger),
            "--profile-id", "op06-093-perona-v2",
            "--actor", "capture-operator", "--actor-type", "agent",
            "--revision", "1", "--lane", "reference",
        ])
        assert result.exit_code == 0, result.output
    else:
        _ladder_to(ledger, tmp_path, stop_after)
    result, out, _, _ = _attest(ledger, tmp_path)
    assert result.exit_code == 1
    assert "no attestation can be issued" in result.output
    assert not out.exists()


def test_prototype_attestation_refuses_wrong_profile_and_physical_lane(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    _ladder_to(ledger, tmp_path, "internal-reference-prototype")
    result, _out, _, _ = _attest(ledger, tmp_path, profile_id="some-other-profile")
    assert result.exit_code == 1
    assert "no events" in result.output

    physical = tmp_path / "physical.jsonl"
    open_revision(physical)
    result2, _out2, _, _ = _attest(physical, tmp_path, profile_id="op05-119-luffy")
    assert result2.exit_code == 1
    assert "lane" in result2.output


def test_prototype_attestation_refuses_tampered_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "promotions.jsonl"
    _ladder_to(ledger, tmp_path, "internal-reference-prototype")
    lines = ledger.read_text().splitlines()
    lines[1] = lines[1].replace("Eric Yun", "Someone Else")
    ledger.write_text("\n".join(lines) + "\n")
    result, _out, _, _ = _attest(ledger, tmp_path)
    assert result.exit_code == 1
    assert "ledger failed verification" in result.output
