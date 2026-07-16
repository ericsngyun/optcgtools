# ADR-0001: Visual-data control plane — FiftyOne + CVAT

Status: **accepted, phase-gated** (Phase B/C of `README.md`; do not implement
before the first authenticated session exists).

## Context

The pipeline produces registered frames, mask proposals with uncertainty,
measured material maps, and fit metrics that humans must browse, compare, and
correct. Building a bespoke annotation UI from scratch duplicates mature
tooling and steals effort from the physical pipeline.

## Decision

Adopt **FiftyOne** as the dataset browser/curation layer and **CVAT** as the
mask-correction annotation tool, integrated behind a thin repo-owned adapter
CLI (`optcg-dataset`) so neither becomes load-bearing for the core pipeline.

Planned surface (implemented only when the phase gate opens):

```bash
uv run optcg-dataset import-session <session-root>
uv run optcg-dataset launch
uv run optcg-dataset create-review-task <session-root>
uv run optcg-dataset sync-reviewed-labels <session-root>
uv run optcg-dataset export-approved-masks <session-root>
```

Dataset fields: session ID; card identity; print variant; capture kind; angle;
light state; quality result; registration metrics; semantic proposals;
reviewed masks; material proposals; fit metrics; approval state; source and
output hashes.

## Constraints

- FiftyOne must not become a required runtime dependency until the first
  authenticated session has validated the adapter's field requirements
  against real data.
- CVAT corrections flow back only as immutable review events
  (`MaskCorrection` in `semantic.py`); the adapter never overwrites proposals.
- Approval state remains owned by `optcg-review`/`promotion.py`; the dataset
  layer mirrors it read-only.
- Private media stays in private storage; the dataset backend must point at
  the private root, never copy media into the repository.

## Alternatives considered

- **Bespoke Svelte review UI only** — still needed for matched-render
  comparison (`review-ui-spec.md`), but rebuilding dataset browsing and mask
  editing in it is low-leverage.
- **Label Studio** — weaker video/frame-propagation review and mask-editing
  ergonomics for this use case.
- **CVAT alone** — annotation-centric; poor dataset-wide querying by metrics.
