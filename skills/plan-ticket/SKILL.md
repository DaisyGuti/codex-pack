---
name: plan-ticket
description: 'Plans one ticket before it is worked. Picks the next Ready ticket (or a numbered one), posts a build plan of about 200 words, sets model and run labels. Use for "plan my next ticket", "plan ticket 73"; for the board, $daily-grooming.'
---

# Plan ticket

`$work-tickets` and `$ticket-worker` build from a ticket that carries a plan, a model label
and a run label. This skill produces those for one ticket, right before it ships, so the plan
is fresh: plans written weeks ahead go stale when the brief changes. To prepare a whole
board's Ready lane in one pass, use `$daily-grooming`; to file a new ticket, `$write-ticket`.

```text
$plan-ticket                       # plan the next Ready ticket assigned to you
$plan-ticket --all                 # pick from anyone's Ready tickets
$plan-ticket --ticket 73           # plan this ticket, wherever it is
$plan-ticket --ticket 73 --repo my-app   # when the number exists in several repos
$plan-ticket --dry-run             # print the plan and labels, change nothing
$plan-ticket --project 2 --owner my-group   # a different board (a pasted board URL works too)
$plan-ticket --context FILE        # use this brief instead of the repo's own (repeatable)
```

Bundled scripts, run with stdin closed (`< /dev/null`): `scripts/registry.py`,
`scripts/resolve_model.py` and `scripts/deps.py` (the dependency check
[references/plan-one-ticket.md](references/plan-one-ticket.md) step 2 uses), all under
`${CODEX_HOME:-~/.codex}/skills/plan-ticket/`.

## 0. Set up

1. Run `python3 "${CODEX_HOME:-~/.codex}/skills/plan-ticket/scripts/registry.py" ensure`.
   Exit 3 means it just created the team's registry and exit 4 means it is unfilled: follow
   [references/registry-rules.md](references/registry-rules.md) ("Where the registry
   lives"), show what it printed and stop.
2. Run `python3 "${CODEX_HOME:-~/.codex}/skills/plan-ticket/scripts/registry.py" show` for
   the tracker, board, lanes, priorities, labels, model labels and repos. No default lives in
   this skill. `registry-rules.md` ("Resolving a project board argument") says how a pasted
   board URL and `--project` / `--owner` resolve. If a role this skill needs is missing (the
   ready lane, say), stop and name the row to add.
3. Read the one tracker adapter for the registry's tracker, in full, once:
   [github.md](references/trackers/github.md) or
   [gitlab.md](references/trackers/gitlab.md). Every tracker action below is a named
   operation shown in bold; run each as the adapter writes it.
4. Read [references/plan-one-ticket.md](references/plan-one-ticket.md) and
   [references/ticket-labels.md](references/ticket-labels.md). When `registry.py show`
   prints a `batching` `mode` other than `off`, read
   [references/batches.md](references/batches.md) too.

## 1. Pick the ticket

Run **auth-check**, then **current-user**: the person running this is whoever is signed in to
the tracker CLI.

**`--ticket N`:** run **list-items** and take the issue items numbered N. If they span several
repos and `--repo` did not settle it, stop and list them. No match, or a closed issue, or one
carrying the blocked label: say so and stop. A ticket in the in-progress lane is planned
anyway; the report says a worker may already have it.

**Otherwise:** run **list-items** on the ready lane and keep:

1. issues only (reviews and drafts are not planned);
2. those assigned to the signed-in login, compared case-insensitively, unless `--all`;
3. those without the registry's blocked label.

Sort by the Priority table's rank, highest first, unset last, stable. Walk that list: resolve
each ticket's repo per the registry rules (skip one that does not resolve, and name it in the
report), run **read-issue**, and the first ticket with no `### Final Plan` comment is the
pick. When batching is on, run **read-parent** too: a child of a batch parent (`batch` true)
counts as planned when its parent's plan or an addendum has a section for it; a ticket under
any other parent is a single. The model and run labels are not filters; this skill assigns
them.

When nothing is left, say so with the counts that explain it (how many Ready tickets belong to
others or to nobody, when `--all` would have found one), and point to
`$work-tickets --limit 1` for a ticket that already has a plan and `$daily-grooming` for a
board that needs tidying. Then stop.

## 2. Plan it

Planning runs on the `frontier` tier whatever the session's model
([references/model-selection.md](references/model-selection.md), "Ticket work"). Run
`python3 "${CODEX_HOME:-~/.codex}/skills/plan-ticket/scripts/resolve_model.py" frontier --effort medium`.
When this session already runs on the printed `model`, plan inline. Otherwise, or when you
cannot tell, spawn one planning subagent (the built-in `default` agent) with that `model` and
reasoning effort, and wait for it. Its message names the ticket (Remote and number), whether
this is a dry run, any `--context FILE`, the batching mode and that it may join a parent, the
registry JSON from step 0, the adapter file's path, and the path
`${CODEX_HOME:-~/.codex}/skills/plan-ticket/references/plan-one-ticket.md`; it follows that
file and returns its one line. When the spawn is refused (thread limit, multi-agent off), plan
inline and say in the report that the plan ran on the session's model.

Either way, follow `plan-one-ticket.md` for the picked ticket: load a lean context, write one
terse plan, post it, set the labels and weight (judged per `ticket-labels.md`) and move a
planned ticket with no open blocker to the ready lane. It holds the 200-word cap and the list
of what a plan may not contain. Do not add to either. When batching is on: a ticket with a
parent is planned with its whole batch, on the parent, and a ticket without one is planned
with **Joining a parent**; both are in that file's "Batches" section. `--dry-run` means
read-only operations only: print the pick, the plan and the labels it would set, and change
nothing. Carry the procedure through to its returned line without stopping to ask; if a fact
is missing, plan from the brief and say what you assumed.

## 3. Report

In plain language, short, outcome first. When a ticket was planned:

> Planned `<repo>#<n>`: <title>. Run `$work-tickets --limit 1` to ship the top of your queue.

Then add only what applies:

- the model label and the run label set, each with a clause of reasoning, the weight set,
  and the model the tier runs on today from
  `python3 "${CODEX_HOME:-~/.codex}/skills/plan-ticket/scripts/resolve_model.py" <tier>` (if
  it exits 3, say the account has none for that tier);
- the model the plan ran on, when it was not the frontier tier's;
- the ticket is assigned to someone else, or to nobody: `$work-tickets` works only Ready
  tickets assigned to its own person, so it will not pick this one up until it is assigned to
  them;
- the ticket moved to the ready lane because it is planned and nothing blocks it, or stayed in
  another lane (in progress, blocked, done) that a worker or a person put it in;
- the run label is run-solo: `$work-tickets` never dispatches it, because it needs a person;
- the ticket was held instead of planned, and why, and what unblocks it;
- with batching on, the parent it was planned under and every child the plan covers, a new
  batch it proposes, or that it stayed single;
- the notes on the returned line: the parent attached or suggested, duplicates and close
  candidates (for a person to close), the milestone set from the parent or a mismatch with
  it, no assignee;
- tickets skipped because their repo did not resolve.
