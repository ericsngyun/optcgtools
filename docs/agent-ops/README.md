# Agent operations

Operational detail behind the constitution in `/AGENTS.md`. Policy lives there;
this directory holds the machinery.

| File | Purpose |
| --- | --- |
| `task-packet.schema.json` | Contract every substantial implementation task starts from |
| `evidence-packet.schema.json` | Contract every completed material/rendering task emits |
| `approval-state-machine.md` | The 13-state profile lifecycle and its coded enforcement |
| `concurrency-policy.md` + `ownership.json` | Path ownership and parallel-work rules |
| `toolchain-validation.md` | How to verify Claude Code and Codex load the framework |
| `first-benchmark-runbook.md` | Exact procedure for the first authenticated card |
| `adr-0001-visual-data-control-plane.md` | FiftyOne + CVAT decision, phase-gated |

## Enforcement points

| Gate | Where it runs |
| --- | --- |
| `scripts/agent-gates/check-private-media.py` | Claude hooks, pre-commit, CI repo scan |
| `scripts/agent-gates/check-approved-assets.py` | Claude hooks, pre-commit, CI |
| `scripts/agent-gates/check-generated-artifacts.py` | Claude hooks, pre-commit, CI |
| `scripts/agent-gates/check-profile-promotion.py` | Release gate, CI (when ledgers change) |
| `scripts/agent-gates/check-evidence-packet.py` | Release gate, PR review |
| `scripts/agent-gates/run-quality-gates.sh` | Before any completion claim |
| `src/optcg_material/review.py` (`optcg-review`) | Per-session human review and publication |
| `src/optcg_material/promotion.py` | Profile promotion transitions |

## Infrastructure phase gates

- **Phase A (now):** Git, private external capture dirs, hashed manifests, the
  existing CLI pipeline, GitHub Actions, task/evidence packets. Goal: one
  authenticated benchmark card end to end.
- **Phase B (after the first complete card):** local MLflow tracking of
  session/profile IDs, algorithm versions, parameters, metrics, and renders.
  Local only; no shared server until multiple operators need it.
- **Phase C (after multiple large capture sessions):** evaluate DVC for large
  private capture/derived data. Git keeps code, manifests, schemas, and small
  approved web assets.
- **Phase D (after ≥3 repeated end-to-end sessions):** evaluate Prefect for
  queued GPU jobs, retries, review pauses, and batch processing.

Adding a platform before its gate is a constitution violation
("infrastructure ahead of its phase gate").
