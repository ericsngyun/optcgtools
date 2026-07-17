# ADR-0002 — Two-lane evidence system (public-reference synthesis)

- Status: accepted (2026-07-16)
- Deciders: Eric Yun (lead reviewer), lead operator session
- Supersedes: nothing; extends ADR-0001

## Context

The lab's original pipeline required an authenticated physical card before any
profile could progress past `public-reference-supported`. That gate is correct
for physical-measurement claims, but it prevents building production-quality,
honestly-labeled card simulations for cards GenkiStuff does not own. Public
real-card photographs and videos (marketplace listings, collector videos) carry
usable appearance evidence when their exact English print variant is verified
and their limitations are recorded.

## Decision

Add a second promotion lane. The existing physical ladder is retained
unchanged as **Lane B (`physical`)**. A new **Lane A (`reference`)** ladder is
added:

```text
hypothesis
→ exact-variant-verified           (human-only)
→ public-reference-supported
→ reference-assets-proposed
→ reference-profile-fitted
→ adversarial-review-passed        (human-only)
→ production-reference-derived     (human-only; technical + rights reviewers)
```

### Encoding

- `PromotionEvent` gains a nullable `lane` field (`None` ⇒ `physical`) plus
  nullable `reference_bundle_id`, `source_quality_tier`, `adversarial_review`,
  and `linked_reference_revision` fields. All new fields default to `None` so
  `content_digest()` (`exclude_none=True`) reproduces historical 1.0.0 digests
  byte-for-byte. Ledger schema version becomes 1.1.0; 1.0.0 events remain
  loadable and verifiable.
- Lane state ladders are namespaced enums with lane-local rank maps; the
  global physical `ProfileState`/`STATE_RANK`/`HUMAN_ONLY_TARGETS` and the
  physical family rule stay byte-for-byte unchanged.
- `lane` is fixed at `open-revision` and is part of revision identity; events
  on a revision must match its lane. Lane A revisions may enter only at
  `hypothesis` — every new bundle re-passes the human variant gate.
- Demotion compares rank within the revision's lane; cross-lane demotion is
  impossible.

### Lane A requirement thresholds

- `reference_bundle_id` required from `exact-variant-verified`;
- `input_hashes` (must include the bundle manifest digest) from
  `public-reference-supported`;
- `source_quality_tier` (`A`, or `B` with human review) and an evidence packet
  and a resolved `rights_status` from `reference-assets-proposed`;
- quantitative `metrics` from `reference-profile-fitted`;
- named `technical_reviewer` on all human-only targets; named
  `rights_reviewer` additionally at `production-reference-derived`.

### Labeling (defense in depth)

Lane A output must never carry `capture-validated`, "physically measured", or
"physically exact". Allowed publication labels: `reference-derived`,
`source-supported simulation`, `visually fitted across real-card references`.

1. Structural: the reference lane's state set contains no physical-validation
   states — a Lane A revision cannot reach them.
2. Publication gate (`review.py check_publication`): lane-aware; reference
   profiles must declare `lane: "reference"`, carry a reference-lane
   confidence label, and are rejected if they contain a forbidden
   physical-claim phrase.
3. Evidence-packet lint (`check-evidence-packet.py`): lane-scoped; reference
   packets may not mark physical claims `measured`/`human-reviewed` and the
   forbidden phrases are added to the block list. The lint remains a lint —
   the human ladder and the structural guarantee are the real gate.

### Cross-lane calibration

A Lane A profile later calibrated physically opens a **new revision** of the
same `profile_id` with `lane: physical` entering at
`authenticated-capture-ingested`; `linked_reference_revision` records the
provenance link (metadata only). Publication label derives from the HEAD
revision's lane; physical outranks reference for the same profile.

### Finish families

`validate_reference_family_proposal` requires ≥2 distinct `card_id` AND ≥2
distinct `reference_bundle_id`, each at reference-state ≥
`adversarial-review-passed`, with materially similar observed response.
Rarity or illustrator similarity alone can never establish a family. Each card
retains its own foil/metallic/suppression/composition/art-texture masks.

### Reference bundles

Private bundle root (never committed):
`~/GenkiStuff/optcg-reference-lab/public-reference-bundles/<bundle-id>/` with
`manifest.json`, `sources/` (urls.json, source-notes/), `private-media/`,
`normalized/`, `registered/`, `appearance/`, `semantic/`, `profiles/`,
`renders/`, `diagnostics/`, `review/`. The public repo holds only schemas,
code, source URLs and permitted textual observations, hashes, rights-permitted
derived masks, synthetic fixtures, and approved web assets. Normalized
reference images are private-only. Blocked retrievals record an acquisition
task for a human; agents never automate around anti-bot controls.

Appearance-envelope outputs are labeled observed appearance proposals — never
physical BRDF measurements. Robust statistics prevent any single source from
dominating. Fitting must reject profiles that match only one privileged
reference. 3D output uses deterministic planar card geometry; normal or
displacement maps derived from public imagery are labeled `inferred`.

## Rejected alternatives

- **Shared-prefix DAG in one state enum** — `hypothesis` and
  `public-reference-supported` exist in both ladders, so a single global rank
  map collides; a successor-set rewrite of the core engine risks Lane B.
- **Separate per-lane profile registries** — splits identity of one card
  profile across ledgers and breaks the hash-chain audit trail.
- **Reusing physical states behind a "synthetic" flag** — labeling by flag is
  exactly the laundering risk this ADR exists to prevent.

## Amendment (2026-07-16) — `internal-reference-prototype`

- Status: accepted.

Insert a new Lane A rank, `internal-reference-prototype`, between
`adversarial-review-passed` and `production-reference-derived`:

```text
...
→ adversarial-review-passed        (human-only)
→ internal-reference-prototype     (human-only; requires adversarial_review)
→ production-reference-derived     (human-only; technical + rights reviewers)
```

**Purpose.** A state for private renderer/CSS previews after exact-variant
verification, minimum evidence review, manually reviewed masks, and critic
review, that is structurally incapable of being mistaken for a publication
label. It permits private previews only; it never permits production
publication, capture-validated claims, rights bypass, or approved-asset
overwrite.

**Encoding.** `ReferenceState.INTERNAL_REFERENCE_PROTOTYPE =
"internal-reference-prototype"` is declared between
`ADVERSARIAL_REVIEW_PASSED` and `PRODUCTION_REFERENCE_DERIVED`; enum
declaration order derives `REFERENCE_STATE_ORDER`/`REFERENCE_STATE_RANK`, so
the new member is automatically ranked correctly with no other code change to
the rank derivation. It is added to `LANE_HUMAN_ONLY[Lane.REFERENCE]`. It
inherits every `reference-assets-proposed`-and-later requirement (bundle id,
hashes, tier/evidence/rights, metrics) and additionally requires a non-empty
`adversarial_review` reference from this rank forward (a new
`REFERENCE_ADVERSARIAL_REVIEW_REQUIRED_FROM` threshold), plus the named
`technical_reviewer` every human-only target requires.

**Rank-shift safety.** Inserting a rank in the middle of a linear, ordinal
StrEnum shifts the rank of every state after it (here, only
`production-reference-derived`, by one). This is safe today because no
reference-lane promotion ledger is committed to this repository: reference
bundles and their promotion history live only in the private bundle root
(`~/GenkiStuff/optcg-reference-lab/public-reference-bundles/...`), and, per
the two-lane evidence system's own operational state at the time of this
amendment, every such private ledger is still at `hypothesis` or earlier — no
private ledger has recorded a `promote` event past `hypothesis` yet. A rank
shift is only unsafe for a ledger that has already recorded a `promote` to
`production-reference-derived` (or any state after the insertion point) under
the old rank numbering, because `validate_transition`'s one-hop check
re-derives ranks from current code on every replay; no such ledger exists.
Any future rank insertion into either ladder must re-verify this precondition
against the private bundle roots before merging.

**Publication gate.** `review.py check_publication` explicitly rejects a
profile whose `classification.confidence` is
`internal-reference-prototype` with an "internal preview only,
non-publishable" error, distinct from (and in addition to) the existing
fail-closed rejection of all reference-lane publication pending the
bundle-review adapter. `production-reference-derived` remains the only
publication-eligible state.

**Evidence-packet lint.** `check-evidence-packet.py` gains
`internal-reference-prototype` in `STATE_NAME_TOKENS` (so the state name is
not itself flagged as a misleading claim), `HUMAN_ONLY_STATES`, and
`REFERENCE_LADDER_STATES` (so it is a legal `to_state` recommendation for a
reference-lane packet).

**Digest compatibility.** No serialized field changed; `PromotionEvent`
already carries `adversarial_review` (added in the original ADR-0002 change)
and no new field was introduced. The physical lane and the 1.0.0 golden
digest pin are untouched.

**Pre-existing test extension (lead-authorized).** Inserting a mandatory rank
between `adversarial-review-passed` and `production-reference-derived` turns
the old direct one-hop promotion between them into a two-rank jump, which the
unweakened one-state-at-a-time rule correctly rejects. Three pre-existing
tests in `tests/test_promotion.py` (`test_reference_lane_happy_path`,
`test_agent_cannot_perform_reference_human_only_transition`,
`test_reference_production_requires_rights_reviewer`) were mechanically
extended to walk the now-longer ladder through `internal-reference-prototype`
instead of skipping it; no assertion's intent changed. This was flagged as a
stop condition and explicitly authorized by the lead reviewer before merging.

## Consequences

- Lane A work may begin immediately from verified-English dossiers, without a
  physical card (unlike Lane B and unlike ADR-0001's original phase gate).
- New ownership group `reference-synthesis` (owner: capture-operator):
  `reference_bundle.py`, `reference_bundle_cli.py`, `reference_normalize.py`,
  `reference_normalize_cli.py`. Appearance envelope joins material-extraction;
  reference fitting joins fitting; SAM 3.1 challenger joins segmentation.
- Five new agent-ops schemas: bundle manifest + source record, quality
  score/tier, acquisition task, appearance envelope, cross-reference fitting
  report. They are the frozen interface contract for the parallel Phase-1
  implementations.
