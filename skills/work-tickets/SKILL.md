---
name: work-tickets
description: Use when the user wants their Ready tickets built ("work the ready tickets", "run my queue", "work the P1s", a pasted board URL). Dispatches ticket_worker subagents in parallel waves, each on the model its ticket label calls for. Works the whole queue; for one issue use $ticket-worker.
---

# Work tickets

Read [references/orchestrator.md](references/orchestrator.md) in full before you
start. It holds the whole procedure: flags and defaults, the Ready gate, label
rules, model resolution, the state file, wave dispatch and reaping, and the report.

The tracker (GitHub or GitLab), board, lane names, labels, model labels and repo set
come from [references/registry.md](references/registry.md). Every tracker action in
the procedure is a named operation; its commands are in
`references/trackers/<tracker>.md` for the registry's tracker, so read only that file,
in full, before Phase 1. A ticket's model label resolves to a tier through the
registry's Model labels table, and the tier through
[scripts/resolve_model.py](scripts/resolve_model.py) (`fast`, `workhorse`, `frontier`).

`$work-tickets` with no arguments works the whole default board;
`$work-tickets --priority P1` narrows to one priority. Never ask the user for a
project number or a repo list.

- Only Ready tickets assigned to whoever is signed in to the tracker CLI are worked.
  Unassigned tickets and tickets assigned to others are counted in the report and
  never touched. There is no flag for someone else's tickets; that takes signing in
  as them.
- A Ready ticket carrying the registry's blocked label is held: never dispatched,
  never touched, and listed in the dry run and the report with the kind from its latest
  `Blocked:` comment. [references/ticket-labels.md](references/ticket-labels.md) defines
  the labels and the comment.
- Work the whole queue without checking in between waves, stopping only for the
  procedure's halt conditions. When Codex Goals are available, set one for a run that
  dispatches work, so it survives a turn ending between waves, and skip it for
  `--dry-run`: "Every ticket in this run's queue ends in completed[], blocked[] or
  skipped[], verified by the state file, without editing any ticket's code myself. If
  a reap finds an anomalous slot, stop with the slot, its step and the evidence."
- You orchestrate and the workers implement. Never edit a ticket's code yourself, and
  keep worker output out of the main thread: the state file holds the detail and each
  worker returns a one-paragraph summary.
- Every spawn names its model and reasoning effort, resolved from the ticket's label.
  Waves are capped at `--max-parallel` (3 by default) and at the Codex config's
  `agents.max_concurrent_threads_per_session` (older name `agents.max_threads`) when
  that is lower.
- Every worker lands its change by pull or merge request, whatever the repo's own rules
  say, and ends `review_opened`. That is finished work: reap it into `completed[]` with
  the review link, count it as "in review", and never treat it as blocked. Merging the
  review closes the issue and `$daily-grooming` settles it to done; no worker closes
  an issue or moves a card to done.
- Finish the queue, then report with the counts first: how many tickets are in review,
  blocked and skipped, and what needs the user.
- `--dry-run` has no side effects beyond capturing the board's fields. It prints each
  ticket's tier, resolved model and effort, the counts of Ready tickets left alone, and
  an "In review" line with the link for each earlier run's review that is still open.
