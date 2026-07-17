from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from optcg_material.promotion import (
    ActorType,
    ProfileState,
    PromotionAction,
    PromotionEvent,
    append_promotion,
    new_event_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GATES_DIR = REPO_ROOT / "scripts" / "agent-gates"
AGENT_OPS_DIR = REPO_ROOT / "docs" / "agent-ops"

spec = importlib.util.spec_from_file_location("gate_common", GATES_DIR / "gate_common.py")
assert spec and spec.loader
gate_common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_common)


def run_gate(script: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATES_DIR / script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


class TestPrivateMediaRules:
    def test_private_directories_blocked(self) -> None:
        assert gate_common.private_media_violation("private-references/op01/albedo.png", 100)
        assert gate_common.private_media_violation("marketplace-references/listing.jpg", 100)

    def test_raw_video_and_checkpoints_blocked(self) -> None:
        assert gate_common.private_media_violation("captures/card.cr2", 100)
        assert gate_common.private_media_violation("clips/tilt.mp4", 100)
        assert gate_common.private_media_violation("models/sam2.1.pt", 100)

    def test_raster_outside_fixture_paths_blocked(self) -> None:
        assert gate_common.private_media_violation("src/lib/sneaky.png", 10_000)

    def test_small_fixture_raster_allowed(self) -> None:
        assert gate_common.private_media_violation("public/img/demo/card.png", 10_000) is None

    def test_oversized_fixture_raster_blocked(self) -> None:
        assert gate_common.private_media_violation("public/img/demo/card.png", 2_000_000)

    def test_vector_fixtures_unrestricted(self) -> None:
        assert gate_common.private_media_violation("public/img/demo/card.svg", 2_000_000) is None


class TestApprovedAssetRules:
    def test_modify_delete_rename_blocked(self) -> None:
        for status in ("M", "D", "R"):
            assert gate_common.approved_asset_violation(status, "sessions/x/semantic/approved/mask.png")

    def test_additions_allowed(self) -> None:
        assert gate_common.approved_asset_violation("A", "sessions/x/semantic/approved/mask-v2.png") is None

    def test_non_approved_paths_ignored(self) -> None:
        assert gate_common.approved_asset_violation("M", "src/optcg_material/review.py") is None


class TestGeneratedArtifactRules:
    def test_build_output_blocked(self) -> None:
        assert gate_common.generated_artifact_violation("dist/assets/index.js")
        assert gate_common.generated_artifact_violation("src/__pycache__/x.pyc")
        assert gate_common.generated_artifact_violation("test-results/trace.zip")

    def test_source_files_allowed(self) -> None:
        assert gate_common.generated_artifact_violation("src/optcg_material/review.py") is None


def make_packet(**overrides) -> dict:
    packet = {
        "task_id": "demo-task",
        "run_id": "run-001",
        "repository_commit": "a" * 40,
        "agent": "material-forensics",
        "agent_tool": "claude-code",
        "environment": {"platform": "darwin"},
        "commands_run": ["uv run pytest"],
        "tests": [{"command": "uv run pytest", "result": "pass"}],
        "observations": [
            {
                "statement": "Foil occupancy is selective; the background stays diffuse.",
                "evidence_state": "measured",
            }
        ],
        "recommended_state_transition": {"to_state": "material-maps-proposed"},
        "human_approval_required": True,
    }
    packet.update(overrides)
    return packet


class TestEvidencePacketGate:
    def test_valid_packet_passes(self, tmp_path: Path) -> None:
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(make_packet()), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 0, result.stderr

    def test_misleading_claim_without_measurement_blocked(self, tmp_path: Path) -> None:
        packet = make_packet(
            observations=[
                {
                    "statement": "The render is accurate and production-ready.",
                    "evidence_state": "inferred",
                }
            ]
        )
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 2
        assert "evidence state is 'inferred'" in result.stderr

    def test_human_only_transition_requires_approval_flag(self, tmp_path: Path) -> None:
        packet = make_packet(
            recommended_state_transition={"to_state": "capture-validated"},
            human_approval_required=False,
        )
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 2
        assert "human-only" in result.stderr

    def test_schema_violation_blocked(self, tmp_path: Path) -> None:
        packet = make_packet()
        del packet["observations"]
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 2
        assert "schema violation" in result.stderr

    def test_reference_lane_packet_passes(self, tmp_path: Path) -> None:
        packet = make_packet(
            lane="reference",
            recommended_state_transition={"to_state": "reference-assets-proposed"},
            observations=[
                {
                    "statement": "Foil occupancy is source-supported across three bundle sources.",
                    "evidence_state": "source-supported",
                }
            ],
        )
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 0, result.stderr

    def test_reference_lane_forbids_measured_evidence_state(self, tmp_path: Path) -> None:
        packet = make_packet(
            lane="reference",
            observations=[
                {
                    "statement": "Specular highlight position is consistent across sources.",
                    "evidence_state": "measured",
                }
            ],
        )
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 2
        assert "never mark appearance/material claims as physically measured" in result.stderr

    @pytest.mark.parametrize(
        "phrase",
        ["capture-validated", "physically measured", "physically exact"],
    )
    def test_reference_lane_forbids_physical_claim_phrases(
        self, tmp_path: Path, phrase: str
    ) -> None:
        packet = make_packet(
            lane="reference",
            known_failures=[f"The result looks {phrase} but is not."],
        )
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 2
        assert "forbidden reference-lane phrase" in result.stderr

    def test_physical_lane_packet_unaffected_by_reference_phrase_ban(self, tmp_path: Path) -> None:
        packet = make_packet(known_failures=["Result is capture-validated pending review."])
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 0, result.stderr

    def test_reference_lane_state_names_not_flagged_as_misleading(self, tmp_path: Path) -> None:
        packet = make_packet(
            lane="reference",
            observations=[
                {
                    "statement": "The bundle reached adversarial-review-passed after two reviewers agreed.",
                    "evidence_state": "human-reviewed",
                }
            ],
            recommended_state_transition={"to_state": "reference-assets-proposed"},
        )
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 0, result.stderr

    def test_reference_lane_packet_rejects_physical_transition_target(self, tmp_path: Path) -> None:
        packet = make_packet(
            lane="reference",
            observations=[
                {
                    "statement": "Envelope proposals recorded for review.",
                    "evidence_state": "source-supported",
                }
            ],
            recommended_state_transition={"to_state": "material-maps-proposed"},
        )
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode != 0
        assert "not a reference-lane state" in result.stderr + result.stdout

    def test_reference_lane_packet_accepts_internal_reference_prototype(
        self, tmp_path: Path
    ) -> None:
        """ADR-0002 amendment: `internal-reference-prototype` is a legitimate
        reference-lane `to_state` recommendation, and its state name is not
        itself flagged as a misleading claim."""
        packet = make_packet(
            lane="reference",
            observations=[
                {
                    "statement": (
                        "Critic review passed; recommending internal-reference-prototype "
                        "for a private renderer preview."
                    ),
                    "evidence_state": "human-reviewed",
                }
            ],
            recommended_state_transition={"to_state": "internal-reference-prototype"},
        )
        path = tmp_path / "packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        result = run_gate("check-evidence-packet.py", str(path))
        assert result.returncode == 0, result.stderr


class TestPromotionGate:
    def test_valid_ledger_passes(self, tmp_path: Path) -> None:
        ledger = tmp_path / "promotions.jsonl"
        append_promotion(
            ledger,
            PromotionEvent(
                event_id=new_event_id(),
                sequence=0,
                profile_id="op05-119-luffy",
                revision=1,
                action=PromotionAction.OPEN_REVISION,
                to_state=ProfileState.AUTHENTICATED_CAPTURE_INGESTED,
                actor="capture-operator",
                actor_type=ActorType.AGENT,
                source_session="op05-119-luffy-en-001",
                input_hashes=["a" * 64],
            ),
        )
        result = run_gate("check-profile-promotion.py", str(ledger))
        assert result.returncode == 0, result.stderr

    def test_hand_forged_promotion_blocked(self, tmp_path: Path) -> None:
        # An agent forging a jump straight to production-validated, bypassing
        # append_promotion's guards, must be caught by the replay.
        forged = PromotionEvent(
            event_id=new_event_id(),
            sequence=0,
            profile_id="op05-119-luffy",
            revision=1,
            action=PromotionAction.OPEN_REVISION,
            to_state=ProfileState.PRODUCTION_VALIDATED,
            actor="rogue-agent",
            actor_type=ActorType.AGENT,
        )
        forged.event_digest = forged.content_digest()
        ledger = tmp_path / "promotions.jsonl"
        ledger.write_text(forged.model_dump_json(exclude_none=True) + "\n", encoding="utf-8")
        result = run_gate("check-profile-promotion.py", str(ledger))
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr


class TestHookFileGuard:
    def test_private_media_write_blocked(self) -> None:
        payload = json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(REPO_ROOT / "private-references/op01/raw.png")},
            }
        )
        result = run_gate("hook-file-guard.py", stdin=payload)
        assert result.returncode == 2
        assert "private capture directory" in result.stderr

    def test_normal_source_write_allowed(self) -> None:
        payload = json.dumps(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(REPO_ROOT / "src/optcg_material/review.py")},
            }
        )
        result = run_gate("hook-file-guard.py", stdin=payload)
        assert result.returncode == 0, result.stderr

    def test_outside_repo_paths_ignored(self) -> None:
        payload = json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": "/tmp/scratch/notes.md"}}
        )
        result = run_gate("hook-file-guard.py", stdin=payload)
        assert result.returncode == 0, result.stderr


class TestStagedInvocations:
    @pytest.mark.parametrize(
        "script",
        ["check-private-media.py", "check-approved-assets.py", "check-generated-artifacts.py"],
    )
    def test_staged_mode_runs(self, script: str) -> None:
        result = run_gate(script, "--staged")
        assert result.returncode in (0, 2)


class TestCheckPrivateMediaReferenceLanePaths:
    @pytest.mark.parametrize(
        "path",
        [
            "public-reference-bundles/op05-119-luffy-en-bundle-001/private-media/front.jpg",
            "public-reference-bundles/op05-119-luffy-en-bundle-001/normalized/front.png",
            "public-reference-bundles/op05-119-luffy-en-bundle-001/registered/front.png",
            # Non-raster manifest under a private bundle root: only the new
            # reference-lane rule (not the pre-existing raster rule) blocks this.
            "public-reference-bundles/op05-119-luffy-en-bundle-001/private-media/manifest.json",
        ],
    )
    def test_reference_bundle_private_roots_blocked(self, path: str) -> None:
        result = run_gate("check-private-media.py", path)
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_reference_bundle_public_manifest_allowed(self) -> None:
        result = run_gate(
            "check-private-media.py",
            "docs/agent-ops/reference-bundle.schema.json",
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# New agent-ops schemas (ADR-0002) — each validates a synthetic fixture and
# rejects a deliberately invalid one.
# ---------------------------------------------------------------------------


def _validate(schema_name: str, instance: dict) -> list[str]:
    schema = json.loads((AGENT_OPS_DIR / schema_name).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [issue.message for issue in validator.iter_errors(instance)]


REFERENCE_BUNDLE_FIXTURE = {
    "schema_version": "1.0.0",
    "bundle_id": "op05-119-luffy-en-bundle-001",
    "card_id": "OP05-119",
    "set_code": "OP05",
    "language": "EN",
    "exact_print_variant": "1st edition English base print",
    "region_release": "NA",
    "created_at": "2026-07-01T00:00:00Z",
    "updated_at": "2026-07-02T00:00:00Z",
    "variant_verification": {
        "verified": True,
        "verifier": "GenkiStuff reviewer",
        "method": "print-run marking comparison",
        "confidence": 0.95,
        "notes": "Matches confirmed English SR foil print run.",
    },
    "rights_status": "licensed",
    "rights_reviewer": "GenkiStuff rights reviewer",
    "tier": "A",
    "source_ids": ["ebay-listing-0001", "collector-video-0002"],
    "sources": [
        {
            "source_id": "ebay-listing-0001",
            "source_url": "https://example.com/listing/1",
            "source_type": "ebay-listing",
            "retrieval_date": "2026-06-30T00:00:00Z",
            "card_id": "OP05-119",
            "language": "EN",
            "exact_print_variant": "1st edition English base print",
            "region_release": "NA",
            "protection": "sleeved",
            "media_form": "still",
            "resolution": {"width": 2400, "height": 3360},
            "useful_angles": 3,
            "macro_available": True,
            "lighting_usefulness": "high",
            "compression_level": "low",
            "editing_likelihood": "low",
            "variant_confidence": 0.9,
            "proxy_counterfeit_risk": "low",
            "rights_status": "licensed",
            "retrieval_status": "retrieved",
        }
    ],
    "private_media_root": "~/GenkiStuff/optcg-reference-lab/public-reference-bundles/op05-119-luffy-en-bundle-001/",
    "manifest_digest": "a" * 64,
}


def test_reference_bundle_fixture_valid() -> None:
    assert _validate("reference-bundle.schema.json", REFERENCE_BUNDLE_FIXTURE) == []


def test_reference_bundle_fixture_invalid_missing_manifest_digest() -> None:
    invalid = {k: v for k, v in REFERENCE_BUNDLE_FIXTURE.items() if k != "manifest_digest"}
    assert _validate("reference-bundle.schema.json", invalid) != []


REFERENCE_SOURCE_QUALITY_FIXTURE = {
    "source_score": {
        "source_id": "ebay-listing-0001",
        "exact_variant_match": 0.95,
        "english_confirmation": 1.0,
        "surface_visibility": 0.8,
        "angles_score": 0.6,
        "macro_score": 0.7,
        "lighting_diversity": 0.5,
        "resolution_score": 0.9,
        "compression_penalty": 0.1,
        "editing_risk_penalty": 0.05,
        "proxy_risk_penalty": 0.05,
        "alignment_success": 0.85,
        "weights": {"exact_variant_match": 2.0, "surface_visibility": 1.5},
        "composite_score": 0.82,
        "tier": "A",
        "tier_rationale": "High-resolution, low-compression macro stills of the exact print.",
        "computed_at": "2026-07-02T00:00:00Z",
    },
    "bundle_tier": {
        "bundle_id": "op05-119-luffy-en-bundle-001",
        "tier": "A",
        "source_scores": [
            {
                "source_id": "ebay-listing-0001",
                "exact_variant_match": 0.95,
                "english_confirmation": 1.0,
                "surface_visibility": 0.8,
                "angles_score": 0.6,
                "macro_score": 0.7,
                "lighting_diversity": 0.5,
                "resolution_score": 0.9,
                "compression_penalty": 0.1,
                "editing_risk_penalty": 0.05,
                "proxy_risk_penalty": 0.05,
                "alignment_success": 0.85,
                "weights": {"exact_variant_match": 2.0},
                "composite_score": 0.82,
                "tier": "A",
                "tier_rationale": "High-resolution, low-compression macro stills of the exact print.",
                "computed_at": "2026-07-02T00:00:00Z",
            }
        ],
        "human_reviewed_tier_b": False,
        "reviewer": None,
        "eligible_for_profile": True,
    },
}


def test_reference_source_quality_fixture_valid() -> None:
    assert _validate("reference-source-quality.schema.json", REFERENCE_SOURCE_QUALITY_FIXTURE) == []


def test_reference_source_quality_fixture_invalid_tier() -> None:
    invalid = json.loads(json.dumps(REFERENCE_SOURCE_QUALITY_FIXTURE))
    invalid["bundle_tier"]["tier"] = "D"
    assert _validate("reference-source-quality.schema.json", invalid) != []


ACQUISITION_TASK_FIXTURE = {
    "task_id": "acq-op05-119-0001",
    "bundle_id": "op05-119-luffy-en-bundle-001",
    "source_url": "https://example.com/listing/blocked",
    "reason_blocked": "anti-bot",
    "detected_at": "2026-07-03T00:00:00Z",
    "requested_media": "front and back stills at native resolution",
    "status": "open",
    "assignee": None,
    "resolution_notes": "",
}


def test_acquisition_task_fixture_valid() -> None:
    assert _validate("acquisition-task.schema.json", ACQUISITION_TASK_FIXTURE) == []


def test_acquisition_task_fixture_invalid_no_credential_fields_allowed() -> None:
    invalid = {**ACQUISITION_TASK_FIXTURE, "bypass_token": "should-never-exist"}
    assert _validate("acquisition-task.schema.json", invalid) != []


APPEARANCE_ENVELOPE_FIXTURE = {
    "schema_version": "1.0.0",
    "bundle_id": "op05-119-luffy-en-bundle-001",
    "card_id": "OP05-119",
    "region_id": "character-art",
    "source_count": 3,
    "contributing_source_ids": ["ebay-listing-0001", "collector-video-0002"],
    "brightness": {"min": 0.1, "max": 0.9, "variance": 0.02, "median": 0.5},
    "chroma_variance": 0.01,
    "hue_range": {"min_deg": 10.0, "max_deg": 40.0, "dominant_hue_axis_deg": 25.0},
    "specular_activation_frequency": 0.4,
    "proposals": {
        "metallic": 0.3,
        "foil": 0.7,
        "clearcoat": 0.2,
        "black_ink_suppression": 0.1,
        "texture_frequency": 12.0,
        "texture_direction_deg": 45.0,
        "confidence": {"metallic": 0.6, "foil": 0.8},
    },
    "per_pixel_confidence_map": "appearance/confidence-map.png",
    "robust_method": "median-of-sources with MAD outlier rejection",
    "outlier_sources_excluded": [],
    "label": "observed-appearance-proposal",
    "evidence_state": "source-supported",
    "generated_at": "2026-07-04T00:00:00Z",
}


def test_appearance_envelope_fixture_valid() -> None:
    assert _validate("appearance-envelope.schema.json", APPEARANCE_ENVELOPE_FIXTURE) == []


def test_appearance_envelope_fixture_invalid_label() -> None:
    invalid = {**APPEARANCE_ENVELOPE_FIXTURE, "label": "physically-measured"}
    assert _validate("appearance-envelope.schema.json", invalid) != []


REFERENCE_FITTING_REPORT_FIXTURE = {
    "schema_version": "1.0.0",
    "run_id": "fit-run-0001",
    "bundle_id": "op05-119-luffy-en-bundle-001",
    "profile_path": "profiles/op05-119-luffy.json",
    "profile_blake3": "b" * 64,
    "per_source": [
        {
            "source_id": "ebay-listing-0001",
            "estimated_pose": {"yaw_deg": 2.0, "pitch_deg": -1.0},
            "light_direction": {"azimuth_deg": 210.0, "elevation_deg": 35.0},
            "glare_center": {"x": 0.42, "y": 0.61},
            "light_hardness": 0.6,
            "exposure_scale": 1.02,
            "confidence_weight": 0.8,
            "candidate_render_path": "renders/ebay-listing-0001.png",
            "difference_image_path": "diagnostics/ebay-listing-0001-diff.png",
            "regional_error": {"foil-band": 0.03, "background": 0.01},
            "highlight_trajectory": None,
        }
    ],
    "cross_reference_consistency_score": 0.78,
    "single_reference_overfit_flag": False,
    "privileged_reference_ids": [],
    "outlier_report": [],
    "aggregate_loss": 0.045,
    "generated_at": "2026-07-05T00:00:00Z",
}


def test_reference_fitting_report_fixture_valid() -> None:
    assert _validate("reference-fitting-report.schema.json", REFERENCE_FITTING_REPORT_FIXTURE) == []


def test_reference_fitting_report_fixture_invalid_missing_per_source() -> None:
    invalid = {k: v for k, v in REFERENCE_FITTING_REPORT_FIXTURE.items() if k != "per_source"}
    assert _validate("reference-fitting-report.schema.json", invalid) != []
