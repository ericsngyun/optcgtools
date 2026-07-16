# First benchmark runbook

The next pipeline action is processing **one** authenticated physical card —
Stage 1 of the benchmark order: a standard rare holo or basic SR foil.
No speculative shader tuning happens before this card has a registered,
human-reviewed frame stack.

## Prerequisites

- A physical card in hand, authenticity recordable by a named human.
- Capture rig per `docs/research/reference-capture-protocol.md`: fixed camera,
  fixed card center, locked focus/exposure/white balance, no HDR/portrait/filters.
- Private storage root, e.g. `~/GenkiStuff/optcg-reference-lab/`.
- Green suite: `scripts/agent-gates/run-quality-gates.sh`.

## Procedure

1. **Task packet.** Draft one from `task-packet.schema.json`
   (`task_id: first-benchmark-<card>`); reviewer = the named human.
2. **Session.** Follow the `authenticated-card-session` skill:
   `init → add` (1 albedo, 7 tilt-x, 7 tilt-y, 7 light-hard, 3 light-soft,
   4 rake, 4 macro) `→ verify-auth → set-rights → validate → quality →
   rectify → register`.
3. **Promotion.** Open the promotion ledger: `open-revision` to
   `authenticated-capture-ingested` with session reference, capture hashes,
   and fingerprint (captures digest, renderer version).
4. **Human gates.** The reviewer inspects the quality report and registration
   diagnostics, then records `quality-approved` and `registration-approved`
   (human-only transitions) plus `optcg-review approve-item` for
   `capture-quality` and `registration`. If printed detail swims between
   frames: demote, fix capture or manual corners, re-register.
5. **Masks.** Run `optcg-semantic` with documented prompts →
   `masks-proposed`. Human reviews/corrects (immutable correction events) →
   `masks-reviewed`.
6. **Material maps.** `optcg-maps extract` with approved masks as soft
   priors → `material-maps-proposed`; review each channel independently →
   `material-maps-reviewed`.
7. **Fit.** Deterministic render sequence + `optcg-fit evaluate` +
   bounded optimization (`docs/operations/profile-optimization.md`) →
   `profile-fitted` with metrics in the evidence packet.
8. **Three-part review.** Run the `physical-material-review` skill
   (engineering, forensics, adversarial-critic). On critic PASS the human may
   record `render-reviewed`, then `capture-validated`.
9. **Evidence packet.** Emit and validate
   (`check-evidence-packet.py`); attach fit metrics, difference images, and
   known limitations.

## Explicit non-goals for card one

- No finish-family generalization (two-card rule).
- No production CSS/GLB publication (`production-validated` needs the
  delivery compiler milestone plus rights review).
- No new shader families before the registered stack passes visual review.

## Stop conditions

Missing authentication, unknown rights, failed quality gate, unregistrable
frames, or a material response the renderer cannot represent → stop, record
the diagnostic, improve tooling or capture protocol. Never substitute
invented data.
