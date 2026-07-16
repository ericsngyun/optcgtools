from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

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
