# Bundle coverage scoring

Bundle-level coverage scores what a reference bundle proves **as a whole**,
alongside — never instead of — per-source quality scoring
(`docs/agent-ops/reference-source-quality.schema.json`, frozen). It exists to
close a real gap from the first Lane A execution: three well-registered
viewing angles of one card each scored ~0.499 (single-angle penalty) and the
bundle stayed tier C even though the cross-source angle diversity was real.

Implementation: `compute_bundle_coverage` / `coverage_bundle` in
`src/optcg_material/reference_bundle.py`; CLI verb
`optcg-reference coverage <bundle-root>`.

## Artifact

`coverage_bundle` persists `review/bundle-coverage.json` inside the private
bundle root. This is a **new** documented artifact — it is not one of the
frozen ADR-0002 schemas, and the frozen `bundle_tier` record is unchanged
(schema formalization can follow later). Structure:

```json
{
  "record_version": "1.0.0",
  "bundle_id": "<slug>",
  "computed_at": "<ISO 8601>",
  "accepted_source_ids": ["..."],
  "independent_family_count": 1,
  "distinct_angle_count": 3,
  "axes": {
    "<axis>": { "score": 0.0, "rationale": "..." }
  },
  "weights": { "<axis>": 0.0 },
  "composite": 0.0,
  "multi_angle_route": {
    "qualifying_source_ids": ["..."],
    "distinct_angles": 3,
    "minimum_variant_confidence": 0.9,
    "composite_floor": 0.55,
    "satisfied": true,
    "rationale": "PASS/FAIL per condition; excluded weak sources; review note"
  }
}
```

Only **accepted** sources count toward any axis: `retrieval_status:
retrieved`, media ingested (BLAKE3-recorded), and a normalization diagnostics
record with `status: accepted`. Everything else contributes nothing (fail
closed).

## The seven axes (each 0–1, with a per-axis rationale)

| Axis | Weight | Derivation |
| --- | --- | --- |
| `temporal_sequence` | 0.10 | 1.0 if any accepted source is `media_form: video` (a registered continuous sequence), else 0.0. |
| `angle_span` | 0.20 | `min(distinct_angles / 3, 1.0)`. Angle labels come from diagnostics pose metadata (`pose.angle_label`) when available; else a documented proxy: a human `ANGLE: <label>` marker in `review_notes`. All unlabeled sources collapse into ONE bucket — unproven diversity is not diversity. |
| `lighting_consistency` | 0.15 | (fraction of accepted sources with `lighting_usefulness` medium/high) × same-session factor: 1.0 when ≥2 accepted sources share a named, provenance-known seller (same capture session evidence), else 0.6. |
| `macro_coverage` | 0.10 | 1.0 if any accepted source has `macro_available`, else 0.0. |
| `independent_sources` | 0.15 | `min(families / 3, 1.0)` where families derive from seller/listing **attribution**, never `source_id` count: named seller → one family per seller; no seller → one family per listing URL; and every source whose `review_notes` contain the `PROVENANCE UNKNOWN` marker collapses into ONE shared family (unattributed listings could all be the same actor). |
| `variant_confidence` | 0.20 | `(min + median) / 2` of `variant_confidence` across accepted sources; the rationale reports both min and median. |
| `interference_diversity` | 0.10 | Variety of clean vs interference-flagged views (from diagnostics `interference.flagged`; missing report = flagged, fail closed): both kinds present → 1.0; all clean → 0.8; all flagged/unreported → 0.3. |

Weights sum to 1.0. `composite = clip(Σ weight × score, 0, 1)`, rounded to 4
decimals. Identical inputs always produce identical output
(`computed_at` is injectable for determinism).

## Tier integration: the multi-angle reviewed-B route

`compute_bundle_tier(..., coverage=...)` accepts the coverage record
(`tier_bundle` computes and persists it automatically). Tier B eligibility
may now be satisfied by **either**:

- the existing per-source route (≥1 tier-A source, or ≥2 tier-B-or-better
  sources), **or**
- the multi-angle route: **≥3 qualifying accepted-registration sources
  spanning ≥3 distinct angles**, minimum `variant_confidence` **≥ 0.9**
  across qualifying sources, **and** coverage composite **≥ 0.55**
  (`COVERAGE_ROUTE_COMPOSITE_FLOOR`).

Per-source route floors (a source failing any of these is excluded from the
qualifying set and its angle does not count):

- registration accepted in diagnostics and media ingested,
- `variant_confidence >= 0.9`,
- `proxy_counterfeit_risk` not high,
- `editing_likelihood` not high.

Unchanged, fail-closed properties:

- **Tier A is unchanged**: coverage can only ever lift C to B, never to A.
- **Tier B still requires a recorded human review by a named reviewer**
  before the bundle is eligible for a profile; the route only establishes
  eligibility *for* that review.
- A coverage record for a different `bundle_id` is refused outright.

## Guardrails (both directions)

1. **No weak-source promotion.** Coverage never modifies any
   `SourceQualityScore`; every individual source is still gated by the
   per-source floors, and a weak source (failed registration, low variant
   confidence, high proxy risk, high editing likelihood) contributes nothing
   to the route — not even its viewing angle. Proven by
   `test_weak_source_contributes_nothing_to_the_coverage_route`.
2. **No single-view-only rejection.** A coherent bundle of ≥3 registered
   single-view sources spanning ≥3 distinct angles at variant confidence
   ≥0.9 reaches the reviewed-B eligibility path even though each frame alone
   carries the single-angle penalty (the ~0.499 scenario). Proven by
   `test_multi_angle_bundle_reaches_reviewed_b_eligibility`.

## Review-note markers

- `PROVENANCE UNKNOWN` — placed by a human reviewer when seller/listing
  attribution cannot be established; collapses the source into the single
  shared provenance-unknown family.
- `ANGLE: <label>` — human-recorded viewing angle (e.g. `ANGLE: tilt-left`);
  used only when diagnostics pose metadata is absent. Semicolon or newline
  ends the label.
