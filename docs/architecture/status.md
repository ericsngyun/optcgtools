# Current status

Superseded as a live tracker: the README's "Current implementation order"
section and GitHub issues are the source of truth for pipeline progress;
`docs/agent-ops/README.md` tracks the agent operating framework.

Snapshot (2026-07-15):

- capture/provenance, quality gates, rectification, registration — implemented and tested;
- semantic proposals (SAM 2.1 pinned), material-map extraction, physical
  renderer, deterministic render sequences, fit evaluation, bounded profile
  optimization — implemented; unvalidated on physical cards;
- review ledger, promotion state machine, agent gates — implemented and tested;
- review workspace UI, CSS profile compiler, GLB export — not implemented;
- first authenticated benchmark card — not yet processed (see
  `docs/agent-ops/first-benchmark-runbook.md`).
