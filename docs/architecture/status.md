# Current status

Superseded as a live tracker: the README's "Current implementation order"
section and GitHub issues are the source of truth for pipeline progress;
`docs/agent-ops/README.md` tracks the agent operating framework.

Snapshot (2026-07-17):

- capture/provenance, quality gates, rectification, registration — implemented and tested;
- semantic proposals (SAM 2.1 pinned; SAM 3.1 challenger pinned,
  checkpoint-gated), material-map extraction, physical renderer, deterministic
  render sequences, fit evaluation, bounded profile optimization — implemented;
  unvalidated on physical cards;
- review ledger, two-lane promotion state machine (ADR-0002), agent gates —
  implemented and tested (202 py + 7 web tests);
- Lane A reference tooling (bundle manifests/scoring/tiering, normalization,
  appearance envelope, cross-reference fitting) — implemented, tested, and
  exercised on the first two real bundles (EN + JP Perona OP06-093 alt-art);
  see `docs/agent-ops/evidence-packets/lane-a-first-execution-001.json` for
  outcomes (both bundles honestly Tier C pending more media; JP fit rejected
  by the acceptance gate; all rejection diagnostics recorded in private
  bundle storage);
- reference-lane publication — fail-closed by design until the bundle-review
  publication adapter is designed;
- review workspace UI, CSS profile compiler, GLB export — not implemented;
- first authenticated physical benchmark card — not yet processed (see
  `docs/agent-ops/first-benchmark-runbook.md`).
