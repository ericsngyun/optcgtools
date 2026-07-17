# Claude Code adapter

`AGENTS.md` is the canonical constitution for this repository. Follow it exactly;
this file only adds Claude-Code-specific wiring and must stay thin.

- Before substantial work, identify the active task packet
  (`docs/agent-ops/task-packet.schema.json`). If none exists, draft one and get
  it confirmed before implementing.
- Use the project subagents in `.claude/agents/` for their owned roles:
  read-only reviewers (`repo-auditor`, `reference-researcher`,
  `registration-reviewer`, `adversarial-critic`, `release-gate`) and
  worktree-isolated implementers (`capture-operator`,
  `segmentation-specialist`, `material-forensics`, `renderer-fitter`).
- Respect the hooks in `.claude/settings.json`; they block private media,
  in-place approved-asset mutation, and generated artifacts. Do not work
  around a blocked call — fix the cause or stop and report.
- Run `scripts/agent-gates/run-quality-gates.sh` before claiming completion.
- Operational detail lives in `docs/agent-ops/`; start with its `README.md`.
