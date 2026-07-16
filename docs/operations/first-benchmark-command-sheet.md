# First benchmark — command sheet

Copy-paste commands for the Stage 1 benchmark session. Run everything from the
repository root. Fill the three variables first; keep the session outside the
repo.

```bash
# ---- fill these in -------------------------------------------------------
export SESSION_ID="op05-119-luffy-en-001"          # lowercase slug
export SESSION=~/GenkiStuff/optcg-reference-lab/$SESSION_ID
export CARD_ID="OP05-119"                          # official card ID
# ---------------------------------------------------------------------------
```

## 1. Initialize the session

```bash
uv run optcg-material init "$SESSION" \
  --session-id "$SESSION_ID" \
  --card-id "$CARD_ID" \
  --card-name "<Card Name>" \
  --set-code "<SET>" \
  --language EN \
  --operator "<your name>" \
  --rights-owner GenkiStuff
```

## 2. Ingest captures (repeat per file)

```bash
uv run optcg-material add "$SESSION" "$SESSION/incoming/albedo.png" --kind albedo

# tilt stills: angle in degrees, direction of the tilt axis
uv run optcg-material add "$SESSION" "$SESSION/incoming/tilt-x-m30.png" --kind tilt-x --angle -30
uv run optcg-material add "$SESSION" "$SESSION/incoming/tilt-y-p20.png" --kind tilt-y --angle 20

# moving light: label each position
uv run optcg-material add "$SESSION" "$SESSION/incoming/light-hard-01.png" --kind light-hard --light-label "hard led azimuth 10oclock elev 40"
uv run optcg-material add "$SESSION" "$SESSION/incoming/light-soft-02.png" --kind light-soft --light-label "softbox center elev 60"

# raking light: direction of the source
uv run optcg-material add "$SESSION" "$SESSION/incoming/rake-left.png" --kind rake --direction left

# macro details
uv run optcg-material add "$SESSION" "$SESSION/incoming/macro-title.png" --kind macro

# optional card back
uv run optcg-material add "$SESSION" "$SESSION/incoming/back.png" --kind back
```

Bulk-ingest a directory of tilt-x frames (example loop; adjust angles):

```bash
for A in -30 -20 -10 0 10 20 30; do
  N=$(printf '%s' "$A" | tr -d '-' ); S=$([ "${A#-}" != "$A" ] && echo m || echo p)
  uv run optcg-material add "$SESSION" "$SESSION/incoming/tilt-x-$S$N.png" --kind tilt-x --angle "$A"
done
```

## 3. Integrity-only check during acquisition (repeat freely)

```bash
uv run optcg-material validate "$SESSION" --integrity-only
```

Verifies hashes and paths without requiring the full capture set yet.

## 4. Human records authentication and rights (named human only)

```bash
uv run optcg-material verify-auth "$SESSION" \
  --method "physical inspection of owned inventory card" \
  --verifier "Eric Yun"

uv run optcg-material set-rights "$SESSION" \
  --status owned-capture \
  --public-derivatives-allowed \
  --no-public-albedo-allowed
```

## 5. Strict validation (full completeness + provenance)

```bash
uv run optcg-material validate "$SESSION" --strict
```

## 6. Quality preflight

```bash
uv run optcg-material quality "$SESSION"
# per-frame reports: $SESSION/diagnostics/quality/*.json, summary.json
```

Reshoot any rejected frame per the checklist, ingest replacements, re-run.

## 7. Rectification

```bash
uv run optcg-material rectify "$SESSION"
# rectified frames: $SESSION/processed/rectified/
```

If corner detection rejects frames, prepare a reviewed manual-quads JSON
(`{"<relative frame path>": [[x,y] x4 clockwise from top-left]}`) and re-run:

```bash
uv run optcg-material rectify "$SESSION" --manual-quads "$SESSION/review/manual-quads.json"
```

## 8. Residual registration

```bash
uv run optcg-material register "$SESSION"
# registered frames: $SESSION/processed/registered/
# metrics: $SESSION/diagnostics/registration/*.json, residual-summary.json
```

## 9. Diagnostic inspection

```bash
cat "$SESSION/diagnostics/quality/summary.json"
cat "$SESSION/diagnostics/registration/residual-summary.json"
open "$SESSION/processed/registered"   # flip through frames: text must not swim
```

Then request the read-only `registration-reviewer` agent verdict.

## 10. Ledgers (after registration passes review)

```bash
# open the session review
uv run optcg-review open "$SESSION" --reviewer "Eric Yun"

# promotion ledger: ingestion state (agent or operator may record this one)
CAPTURES_DIGEST=$(python3 - <<'EOF'
import json, pathlib, os
m = json.loads((pathlib.Path(os.environ["SESSION"]) / "capture-session.json").read_text())
import hashlib
h = hashlib.sha256("".join(sorted(f["blake3"] for f in m["files"])).encode()).hexdigest()
print(h)
EOF
)
uv run optcg-promote open-revision "$SESSION/review/promotion-log.jsonl" \
  --profile-id "$SESSION_ID" --revision 1 \
  --actor "<operator>" --actor-type agent \
  --to-state authenticated-capture-ingested \
  --source-session "$SESSION_ID" \
  --input-hash "$CAPTURES_DIGEST" \
  --fingerprint "{\"captures\": \"$CAPTURES_DIGEST\", \"renderer\": \"three-r185\"}"

# human-only transitions — Eric records these himself after inspecting evidence:
uv run optcg-promote promote "$SESSION/review/promotion-log.jsonl" \
  --profile-id "$SESSION_ID" --revision 1 \
  --from-state authenticated-capture-ingested --to-state quality-approved \
  --actor "Eric Yun" --actor-type human --technical-reviewer "Eric Yun" \
  --source-session "$SESSION_ID" --input-hash "$CAPTURES_DIGEST" \
  --evidence-packet "docs/agent-ops/evidence-packets/<packet>.json"

uv run optcg-promote promote "$SESSION/review/promotion-log.jsonl" \
  --profile-id "$SESSION_ID" --revision 1 \
  --from-state quality-approved --to-state registration-approved \
  --actor "Eric Yun" --actor-type human --technical-reviewer "Eric Yun" \
  --source-session "$SESSION_ID" --input-hash "$CAPTURES_DIGEST" \
  --evidence-packet "docs/agent-ops/evidence-packets/<packet>.json"

uv run optcg-review approve-item "$SESSION" --reviewer "Eric Yun" --item capture-quality
uv run optcg-review approve-item "$SESSION" --reviewer "Eric Yun" --item registration
```

**Stop here.** Segmentation, material extraction, and fitting wait for the
registered stack to pass human review, per the task packet.
