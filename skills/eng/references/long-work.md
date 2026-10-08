# Long work

Read this when the work will take many turns and has a checkable finish line: a
performance target, a flaky test, a migration, a multi-step refactor.

Start a Codex Goal, or hand the user the exact line when you cannot set one
yourself:

```text
/goal <end state> verified by <evidence> while preserving <constraints>. Use <allowed files and tools>. Between iterations, record what changed, what the evidence showed, and the next best attempt. If blocked or no valid paths remain, stop with the attempted paths, the evidence, the blocker and the input needed.
```

Mark it complete only against that evidence; reaching a budget limit is not
completion. Skip Goals for small or vague work.

For multi-hour work, or work that spans sessions, keep an ExecPlan in the repo's
place for designs, following [execplan.md](execplan.md): a plan a fresh agent can
pick up with no other context, updated after each chunk, with observed evidence kept
apart from intentions. A plan that fits in a ticket needs no ExecPlan.
