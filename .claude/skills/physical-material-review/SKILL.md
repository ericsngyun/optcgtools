---
name: physical-material-review
description: Run the three-part anti-slop review for a card's masks, material maps, and matched renders — deterministic engineering review, material-forensics review, and adversarial visual review — then record human approvals via optcg-review. Use before any approval or publication.
---

# Physical material review

Follow `AGENTS.md`. Every card needs all three evaluations; none may be
skipped, and no agent may convert its own verdict into an approval.

## 1. Deterministic engineering review

```bash
uv run optcg-material validate <session-root>
uv run optcg-material quality <session-root>
uv run optcg-fit validate-request <fit-request.json>
scripts/agent-gates/run-quality-gates.sh
uv run python scripts/agent-gates/check-profile-promotion.py <promotion-ledger>
uv run python scripts/agent-gates/check-evidence-packet.py <evidence-packet.json>
```

Verify hashes, manifest validity, image quality, geometry, registration,
schema compliance, reproducibility, tests, and performance.

## 2. Material-forensics review

Inspect the measured maps and fit report for: foil occupancy vs the physical
card; metallic (brightness-only) vs diffractive (hue-traveling) response; ink
suppression; gloss independence from foil; hue order and direction; highlight
movement; texture frequency vs artwork linework; anisotropy; under-sampled or
clipped regions. Every claim must cite a measurement or a registered frame.

## 3. Adversarial visual review

Delegate to the `adversarial-critic` subagent with the candidate renders,
matched reference frames, and fit report. It returns
`PASS | REVISE | REJECT | INSUFFICIENT_EVIDENCE` with numbered findings.

## 4. Human approval

Only after all three reviews, a named human records decisions:

```bash
uv run optcg-review approve-item <session-root> --reviewer "<human>" --item semantic-masks
uv run optcg-review approve-item <session-root> --reviewer "<human>" --item material-maps
uv run optcg-review approve-item <session-root> --reviewer "<human>" --item matched-renders
# ... remaining checklist items, then:
uv run optcg-review approve-technical <session-root> --reviewer "<human>"
uv run optcg-review approve-rights <session-root> --reviewer "<human>"
uv run optcg-review approve-production <session-root> --reviewer "<human>"
uv run optcg-review check-publish <session-root> --profile <profile.json>
```

Rejections use `reject-item` with an explanation; blocking issues use
`comment --blocking` and must be resolved before approval. Corresponding
promotion-ledger transitions (`masks-reviewed`, `material-maps-reviewed`,
`render-reviewed`, `capture-validated`) are recorded with the human as actor.

## Rejection triggers

Reject on: full-card rainbow on selective foil; pointer-centered color wheels;
noise-as-texture; uniform effects across materially different cards; yellow-
rainbow gold; equal manga foil on foreground and background; luminous dark
ink; clearcoat baked into foil; texture ignoring linework; wrong hue order;
unstable registration; mask halos; unbounded saturation; excessive tilt;
mobile jank; or renders that only match at one privileged angle.
