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
