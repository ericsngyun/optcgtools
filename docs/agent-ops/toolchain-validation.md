# Toolchain validation

How to verify that both agent toolchains actually load this framework.
Re-run after any change to `AGENTS.md`, `.claude/`, or `.codex/`.

## Claude Code

```bash
claude
```

Ask:

```text
List the canonical instruction files, available project subagents,
their permissions, and the hooks that will block invalid publication.
Do not modify files.
```

Expected: `AGENTS.md` named as canonical with `CLAUDE.md` as a thin adapter;
nine subagents (five read-only, four worktree-isolated write agents); the
PreToolUse file guard and git-commit guard from `.claude/settings.json`; the
two skills (`authenticated-card-session`, `physical-material-review`).

## Codex

```bash
codex --ask-for-approval never \
  "List the active instruction sources and summarize the repository's evidence and approval gates. Do not modify files."
```

Expected: `AGENTS.md` identified as the instruction source; the same approval
state machine and gates described.

**Schema caveat:** `.codex/config.toml` and `.codex/agents/*.toml` were written
against the Codex CLI config schema current at authoring time
(`approval_policy`, `sandbox_mode`, `[agents.*]`). Codex evolves quickly —
verify key names against `codex --help` / the installed version's config
reference before relying on them for enforcement. Policy enforcement never
depends on Codex config alone: the gate scripts and CI enforce independently.

## Hook verification

```bash
# forbidden media fixture is blocked
printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' \
  "$(git rev-parse --show-toplevel)/private-references/x/raw.png" \
  | python3 scripts/agent-gates/hook-file-guard.py; echo "exit=$?"   # expect 2

# invalid promotion is blocked
uv run python scripts/agent-gates/check-profile-promotion.py <forged-ledger>  # expect exit 2

# legitimate generated test assets are NOT blocked
printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' \
  "$(git rev-parse --show-toplevel)/tests-web/fixtures/synthetic.png" \
  | python3 scripts/agent-gates/hook-file-guard.py; echo "exit=$?"   # expect 0
```

Automated equivalents run in `tests/test_agent_gates.py`.

## Cross-tool consistency check

Both toolchains must answer identically on: canonical file (AGENTS.md), the
13-state approval ladder, human-only transitions, and the two-card family
rule. A divergent answer means an adapter drifted — fix the adapter, never by
forking policy.
