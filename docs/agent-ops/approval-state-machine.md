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
- The misleading-language gate is a lint, not a proof: it matches word stems
  and can be evaded by paraphrase. The human review ladder is the real gate.
- Client-side hooks (`.claude/settings.json`) are advisory for indirect
  commits (scripts that shell out to git); CI re-runs the media/artifact/
  approved-asset gates server-side as the backstop.

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
