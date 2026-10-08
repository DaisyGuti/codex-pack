---
name: plan-ticket
description: Use when the user wants a ticket planned before anyone works it, their own next one or a teammate's ("plan my next ticket", "plan ticket 73"). Picks the next Ready ticket, posts a plan of about 200 words on it and sets its model and run labels. Plans one ticket; for the whole board use $daily-grooming, for a new ticket $write-ticket.
---

# Plan ticket

`$work-tickets` and `$ticket-worker` build from a ticket that carries a plan, a model
label and a run label. This skill produces those for one ticket, right before it
ships, so the plan is fresh: plans written weeks ahead go stale when the brief
changes. To prepare a whole board's Ready lane in one pass, use `$daily-grooming`.

```text
$plan-ticket                       # plan the next Ready ticket assigned to you
$plan-ticket --all                 # pick from anyone's Ready tickets
$plan-ticket --ticket 73           # plan this ticket, wherever it is
$plan-ticket --ticket 73 --repo my-app   # when the number exists in several repos
$plan-ticket --dry-run             # print the plan and labels, change nothing
$plan-ticket --project 2 --owner my-group   # a different board (a pasted board URL works too)
$plan-ticket --context FILE        # use this brief instead of the repo's own (repeatable)
```

The tracker, board, lanes, priorities, labels, model labels and repos come from
[references/registry.md](references/registry.md); no default lives here. Its
"Resolving a project board argument" says how a pasted board URL and `--project` /
`--owner` resolve. Every tracker action below is a named operation shown in bold, with
its commands in `references/trackers/<tracker>.md` for the registry's tracker. Read
that one file once and run each operation as written. If a role this skill needs is
missing from the registry (the ready lane, say), stop and name the row to add. Bundled
script: `scripts/resolve_model.py` (see the report).

## 1. Pick the ticket

Run **auth-check**, then **current-user**: the person running this is whoever is signed
in to the tracker CLI.

**`--ticket N`:** run **list-items** and take the issue items numbered N. If they span
several repos and `--repo` did not settle it, stop and list them. No match, or a
closed issue, or one carrying the blocked label: say so and stop. A ticket in the
in-progress lane is planned anyway; the report says a worker may already have it.

**Otherwise:** run **list-items** on the ready lane and keep:

1. issues only (reviews and drafts are not planned);
2. those assigned to the signed-in login, compared case-insensitively, unless `--all`;
3. those without the registry's blocked label.

Sort by the Priority table's rank, highest first, unset last, stable. Walk that list:
resolve each ticket's repo per the registry (skip one that does not resolve, and name
it in the report), run **read-issue**, and the first ticket with no `### Final Plan`
comment is the pick. The model and run labels are not filters; this skill assigns
them.

When nothing is left, say so with the counts that explain it (how many Ready tickets
belong to others or to nobody, when `--all` would have found one), and point to
`$work-tickets --limit 1` for a ticket that already has a plan and `$daily-grooming`
for a board that needs tidying. Then stop.

## 2. Plan it

Follow [references/plan-one-ticket.md](references/plan-one-ticket.md) for the picked
ticket: load a lean context, write one terse plan, post it, set the labels (judged per
[references/ticket-labels.md](references/ticket-labels.md)). It holds the 200-word cap
and the list of what a plan may not contain. Do not add to either.
`--dry-run` means read-only operations only: print the pick, the plan and the labels
it would set, and change nothing. Carry the procedure through to its returned line
without stopping to ask; if a fact is missing, plan from the brief and say what you
assumed.

## 3. Report

In plain language, short, outcome first. When a ticket was planned:

> Planned `<repo>#<n>`: <title>. Run `$work-tickets --limit 1` to ship the top of your queue.

Then add only what applies:

- the model label and the run label set, each with a clause of reasoning, and the model
  the tier runs on today from `python3 scripts/resolve_model.py <tier>` (if it exits 3,
  say the account has none for that tier);
- the ticket is assigned to someone else, or to nobody: `$work-tickets` works only
  Ready tickets assigned to its own person, so it will not pick this one up until it is
  assigned to them;
- the ticket is not in the ready lane (`--ticket`): `$work-tickets` works only that
  lane;
- the run label is run-solo: `$work-tickets` never dispatches it, because it needs a
  person;
- the ticket was held instead of planned, and why, and what unblocks it;
- tickets skipped because their repo did not resolve.
