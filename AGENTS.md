# OPTCG Physical Material Lab — Agent Constitution

This file is the canonical cross-agent policy for this repository. Tool-specific
adapters (`CLAUDE.md`, `.claude/`, `.codex/`) implement it; they never override it.
When policy changes: update this file first, then the adapters, then re-test
instruction discovery (`docs/agent-ops/toolchain-validation.md`).

## Mission

Convert authenticated physical One Piece Card Game evidence into: registered
capture sequences → reviewed semantic masks → measured material maps →
versioned renderer profiles → quantitatively evaluated renders → approved CSS,
WebGL, and GLB deliverables. The standard is material fidelity to the physical
card — never a decorative rainbow parody.

## Source-of-truth hierarchy

Resolve conflicting information in this order. Lower ranks never override higher:

1. authenticated controlled physical capture;
2. human-reviewed derived evidence;
3. official card metadata;
4. multiple independent real-card photographs or videos;
5. manufacturer or printing references;
6. agent inference;
7. aesthetic preference.

## Non-negotiable prohibitions

Agents must never:

- mark a card authentic (only a named human records authentication);
- self-approve a mask, material map, or renderer profile;
- treat rarity as a complete material specification;
- publish raw private card photography or commit marketplace imagery;
- present a synthetic fixture as a physical extraction;
- promote an asset because it "looks convincing";
- replace missing evidence with an invented texture;
- implement gold as a yellow-tinted rainbow;
- apply uniform foil to a selectively foiled card;
- hide local errors inside whole-card averages;
- overwrite approved assets in place (append-only; new revisions only);
- bypass a failed registration, rights, or quality gate;
- alter the pinned Pokémon reference source (`npm run check:source-pin`);
- add infrastructure ahead of its phase gate (`docs/agent-ops/README.md`).

## Required uncertainty language

Label every conclusion as exactly one of:

`measured` · `human-reviewed` · `source-supported` · `inferred` · `hypothesis` · `unknown`

Never write "accurate", "validated", "matched", "faithful", "production-ready",
or "approved" without the corresponding approval state and named reviewer.
`scripts/agent-gates/check-evidence-packet.py` enforces this.

## Approval state machine

Profile lifecycle (enforced in code by `src/optcg_material/promotion.py`;
details in `docs/agent-ops/approval-state-machine.md`):

```text
hypothesis → public-reference-supported → authenticated-capture-ingested
→ quality-approved → registration-approved → masks-proposed → masks-reviewed
→ material-maps-proposed → material-maps-reviewed → profile-fitted
→ render-reviewed → capture-validated → production-validated
```

- Transitions are append-only, hash-chained promotion events.
- Review/validation transitions are human-only; agents propose, ingest, and fit.
- A failed earlier gate demotes the profile; later automatic outputs are invalid.
- New captures, checkpoints, extraction algorithms, or major renderer versions
  open a new profile revision — never mutate the current one.
- `production-validated` requires named technical and rights reviewers.
- A reusable finish family requires at least two authenticated,
  capture-validated cards with materially similar measured behavior.

Per-session human review (checklist, blocking comments, technical/rights
approval, publication gate) is enforced by `optcg-review`
(`src/optcg_material/review.py`).

## Task and evidence packets

- No substantial implementation work without a task packet
  (`docs/agent-ops/task-packet.schema.json`): objective, allowed/forbidden
  paths, acceptance criteria, required tests, stop conditions, reviewer.
- Every completed material/rendering task emits an evidence packet
  (`docs/agent-ops/evidence-packet.schema.json`) separating facts,
  measurements, inferences, and subjective judgments.
- A PR that changes capture processing, geometry, segmentation, material
  extraction, fitting, CSS/WebGL behavior, GLB generation, or approval logic
  is incomplete without an evidence packet.

## Stop conditions

Stop and report — do not improvise — when: authenticated evidence is required
but unavailable; frames cannot be registered reliably; rights are unknown; the
output would overwrite an approved asset; two agents would edit the same owned
files; a checkpoint or dependency cannot be reproduced; the observed material
exceeds the renderer's model; a quantitative threshold is uncalibrated; or the
task would require inventing card-specific evidence. When blocked, improve
tooling, diagnostics, schemas, or synthetic fixtures instead.

## Ownership and concurrency

One write-capable agent owns a path group at a time
(`docs/agent-ops/concurrency-policy.md`, machine-readable
`docs/agent-ops/ownership.json`). Parallelize read-only work freely; parallel
write work requires separate branches/worktrees, non-overlapping ownership,
independent integration review, and a full quality-suite run after merge.

## Quality gates

Before reporting completion of integration-ready work:

```bash
scripts/agent-gates/run-quality-gates.sh
```

(equivalent to `git diff --check`, staged agent gates, `npm run
check:source-pin`, `npm run build`, `npm run test:web`, `uv run ruff check src
tests`, `uv run pytest`). Rendering or material milestones additionally
require real visual evidence — unit tests alone are insufficient.

## Review protocol

Every card requires three distinct evaluations before human approval:
deterministic engineering review, material-forensics review, and adversarial
visual review returning `PASS | REVISE | REJECT | INSUFFICIENT_EVIDENCE`.
Only a named human converts a critic PASS into a state transition. See
`.claude/skills/physical-material-review/SKILL.md`.

## Rights boundary

Raw captures live in private storage outside this repository
(`~/GenkiStuff/optcg-reference-lab/`). Public code may contain synthetic
fixtures, source URLs and observations, approved manifests, and legally
approved derived assets only. `docs/architecture/security-and-rights.md` governs.
