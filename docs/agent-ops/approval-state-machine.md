# Approval state machine

Coded enforcement: `src/optcg_material/promotion.py` (unit tests in
`tests/test_promotion.py`; ledger replay gate in
`scripts/agent-gates/check-profile-promotion.py`). Prompts remind; code enforces.

## States

```text
hypothesis
→ public-reference-supported
→ authenticated-capture-ingested
→ quality-approved                (human-only)
→ registration-approved           (human-only)
→ masks-proposed
→ masks-reviewed                  (human-only)
→ material-maps-proposed
→ material-maps-reviewed          (human-only)
→ profile-fitted
→ render-reviewed                 (human-only)
→ capture-validated               (human-only)
→ production-validated            (human-only; technical + rights reviewers)
```

## Rules (all enforced in code)

- **Append-only events.** Promotions are hash-chained JSONL events
  (`PromotionEvent`); editing history breaks the chain and the gate.
- **One state at a time.** A `promote` event must advance exactly one state.
- **Human-only transitions.** Events targeting a `(human-only)` state require
  `actor_type: human` and a named `technical_reviewer`.
- **Demotion on failed gates.** Any actor (including CI) may `demote` with a
  stated reason; later automatic outputs of the old state are invalid.
- **Evidence requirements.** From `authenticated-capture-ingested`: a
  `source_session` and input content hashes. From `quality-approved`: an
  evidence packet reference. From `profile-fitted`: quantitative metrics.
  `capture-validated`+ requires a resolved rights status.
  `production-validated` additionally requires a named `rights_reviewer`.
- **Revisions, not mutations.** A new capture, model checkpoint, extraction
  algorithm, or major renderer version changes the revision fingerprint;
  changing a fingerprint component mid-revision is rejected — open a new
  revision (which restarts at an entry state).
- **Family rule.** `validate_family_proposal` rejects any finish family with
  fewer than two distinct, capture-validated authenticated cards. Shared
  family behavior must still preserve card-specific masks and artwork-specific
  texture where the evidence requires it.

## Known limitations and threat model

An independent adversarial review (2026-07-15) of the enforcement code
established the following. The gates are designed to keep honest-but-fallible
agents from sloppy or premature promotion; they are **not** a cryptographic
defense against a deliberately malicious actor with repository write access:

- `actor_type`, `actor`, and reviewer names are self-declared strings. A
  malicious writer could forge `actor_type: human`. Mitigation today: human
  reviewers verify the ledger names them before acting on any approval; PR
  review is the identity boundary. Planned upgrade: reviewer-held signing keys
  (Ed25519/HMAC) so `verify_ledger` requires signatures, not just digests.
- The hash chain is tamper-*evident* against accidental edits, not against an
  attacker who recomputes the whole chain. Same signature upgrade closes this.
- The approved-asset gate keys on an `approved` path segment. Delivery
  directories must therefore live under an `approved/` segment (e.g.
  `public/approved/…`); a digest manifest of approved assets is the planned
  stronger replacement.
- `source_quality_tier` on a promotion event is self-declared at the library
  layer, like `actor_type`. Hardening after the PR #15 independent review:
  a tier-`B` reference event is rejected unless its `fingerprint` carries
  `bundle-tier-record` — the digest of the fail-closed, human-reviewed
  `BundleTierRecord` — so the binding is auditable in-ledger; `optcg-promote
  --bundle-tier-record` verifies the record's content and injects that digest.
  A direct library caller can still fabricate a digest (CI replays ledgers
  without access to private bundles); the bracketing human-only gates and PR
  review remain the containment for that residual.
- `verify_promotion_ledger` performs a full semantic replay (PR #15
  independent-review hardening): a hash-valid but semantically malformed
  ledger — lane laundering, human-only bypass, rank jumps — fails closed at
  load, not only at append.
- The misleading-language gate is a lint, not a proof: it matches word stems
  and can be evaded by paraphrase. The human review ladder is the real gate.
- Client-side hooks (`.claude/settings.json`) are advisory for indirect
  commits (scripts that shell out to git); CI re-runs the media/artifact/
  approved-asset gates server-side as the backstop.

## Lane A (`reference`) — public-reference synthesis

ADR-0002 (`adr-0002-two-lane-reference-synthesis.md`) adds a second lane for
cards without an authenticated physical capture, on the same coded engine.

```text
hypothesis
→ exact-variant-verified           (human-only)
→ public-reference-supported
→ reference-assets-proposed
→ reference-profile-fitted
→ adversarial-review-passed        (human-only)
→ internal-reference-prototype     (human-only; requires an adversarial_review reference)
→ production-reference-derived     (human-only; technical + rights reviewers)
```

- **Human-only set:** `exact-variant-verified`, `adversarial-review-passed`,
  `internal-reference-prototype`, `production-reference-derived`.
- **`internal-reference-prototype` (ADR-0002 amendment).** Sits between the
  critic gate and production derivation. It requires everything
  `adversarial-review-passed` requires (evidence packet, `A`/reviewed-`B`
  source tier, resolved rights, quantitative metrics) plus a non-empty
  `adversarial_review` reference and a named `technical_reviewer`. What it
  **permits**: private renderer/CSS previews only, for internal review after
  exact-variant verification, minimum evidence review, manually reviewed
  masks, and critic review. What it **forbids** (unchanged from every other
  Lane A state): production publication, capture-validated claims, rights
  bypass, and approved-asset overwrite — enforced structurally (no Lane A
  state is a physical-validation state) and by the publication gate below,
  which rejects it with an explicit "internal preview only, non-publishable"
  error. `production-reference-derived` remains the only state one rank
  closer to a publication label, and reaching it still requires passing
  through `internal-reference-prototype` one state at a time, per the
  approval ladder's non-negotiable one-hop-per-promotion rule.
- **Entry states:** a Lane A revision may only enter (and re-enter) at
  `hypothesis` — every new reference bundle re-passes the human variant gate.
  Lane B keeps its original three entry states unchanged.
- **Thresholds:** `reference_bundle_id` required from `exact-variant-verified`;
  `input_hashes` and `reference_bundle_id` (which stands in for
  `source_session` — the reference lane has no capture session) from
  `public-reference-supported`; `source_quality_tier` in `{A, B}` (`C` is
  rejected at any rank), an evidence packet, and a resolved `rights_status`
  from `reference-assets-proposed`; quantitative `metrics` from
  `reference-profile-fitted`; a non-empty `adversarial_review` reference from
  `internal-reference-prototype`; a named `technical_reviewer` on every
  human-only target; a named `rights_reviewer` additionally at
  `production-reference-derived`. The tier-B human-review requirement lives in
  the bundle's `BundleTierRecord` (fail-closed in
  `reference_bundle.py`); `optcg-promote promote` binds the declared ledger
  tier to that record via `--bundle-tier-record` (required whenever a
  reference-lane event declares a tier). The promotion *library* verifies only
  the letter — see the threat-model note below.
- **Lane immutability.** `lane` is fixed at `open-revision` and is part of
  revision identity. Every later event on that revision — including a
  demotion — must match it; a differing lane is rejected. Cross-lane
  demotion is therefore impossible.
- **Reference family analog.** `validate_reference_family_proposal` requires
  at least two distinct `card_id`s **and** two distinct
  `reference_bundle_id`s, each at reference-state rank ≥
  `adversarial-review-passed`. Rarity or illustrator similarity alone can
  never establish a family; each card keeps its own foil/metallic/
  suppression/composition/art-texture masks.
- **Schema versions.** `PromotionEvent` gained a nullable `lane` field plus
  nullable `reference_bundle_id`, `source_quality_tier`, `adversarial_review`,
  and `linked_reference_revision` fields, all defaulting to `None`. Because
  `content_digest()` serializes with `exclude_none=True`, a physical event
  that never sets these fields is byte-identical to its pre-ADR-0002 form and
  its digest is unchanged. The ledger schema version is now `1.1.0`; `1.0.0`
  events remain loadable and verifiable, but reference-lane events require
  `1.1.0` or later.
- **Cross-lane calibration.** A Lane A profile later calibrated physically
  opens a new revision of the same `profile_id` with `lane: physical`,
  entering at `authenticated-capture-ingested`; `linked_reference_revision`
  records the provenance link as metadata only.
- **Labeling.** Lane A output must never carry `capture-validated`,
  "physically measured", or "physically exact". The only valid publication
  labels are `reference-derived`, `source-supported simulation`, and
  `visually fitted across real-card references` — enforced structurally (no
  Lane A state is a physical-validation state), by the publication gate
  (`review.py check_publication`), and by the evidence-packet lint
  (`check-evidence-packet.py`).

## Relationship to session review states

`optcg-review` (`src/optcg_material/review.py`) governs the *per-session human
checklist*: `unreviewed → needs-revision → technically-approved →
rights-approved → production-approved`, with blocking comments and the
`check-publish` gate. The promotion machine governs the *profile lifecycle*.
Mapping: a profile may only reach `capture-validated` when its session review
is at least `technically-approved`, and `production-validated` requires the
session review at `production-approved` (both reviewers named in both ledgers).
The profile schema's `provenance.reviewStatus: approved` corresponds to
session `production-approved`.
