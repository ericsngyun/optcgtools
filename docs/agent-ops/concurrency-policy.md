# Concurrency and ownership policy

Machine-readable table: `ownership.json`. One write-capable agent owns a path
group at a time; ownership transfers are explicit (update `ownership.json` in
the same PR that hands the work over).

## Rules

1. **Parallelize read-heavy work first.** Audits, research, registration
   review, adversarial critique, and release gating are read-only and may run
   concurrently without coordination.
2. **Write work is serialized per path group.** Two agents never edit the same
   owned files. If a task spans two groups, either split it or transfer
   ownership explicitly.
3. **Isolation.** Write-capable Claude subagents run in Git worktrees
   (`isolation: worktree`); Codex runs `workspace-write` on its own branch.
   Claude Code and Codex never edit the same branch simultaneously.
4. **Independent verification.** When Claude Code authors a material-pipeline
   change, Codex reviews it, and vice versa. The author never verifies alone.
5. **Integration.** Parallel write branches merge only after independent
   review, and the complete quality suite
   (`scripts/agent-gates/run-quality-gates.sh`) runs again after the merge.
6. **Agent teams** are reserved for independent literature research, competing
   material hypotheses, parallel read-only review, and adversarial evaluation.
   Never for concurrent edits to one subsystem. The lead agent synthesizes.
7. **Stop condition.** If two agents would touch the same owned files, stop
   and report — do not race.
