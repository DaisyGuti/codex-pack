---
name: work-tickets
description: Use when the user wants their Ready tickets built ("work my ready tickets", "run my queue", "work the P1s", a board URL). Runs a rolling pool of ticket_worker agents, each on its label's model. For one issue use $ticket-worker.
---

# Work tickets

Read [references/orchestrator.md](references/orchestrator.md) in full before you start. It
holds the whole procedure: flags and defaults, the Ready gate, label rules, model resolution,
the run record, pool dispatch and reaping, worktree cleanup, and the report.

`$work-tickets` with no arguments works the whole default board; `$work-tickets --priority P1`
narrows to one priority. Flags: `--dry-run`, `--priority`, `--max-parallel N`, `--limit N`,
`--repo NAME`, `--project N --owner OWNER` (or a pasted board URL), `--context FILE`,
`--clear-skipped`.

## Before Phase 1

1. Run `python3 "${CODEX_HOME:-~/.codex}/skills/work-tickets/scripts/registry.py" ensure`. Exit
   3 means it just created the team's registry and exit 4 means it is unfilled: follow
   [references/registry-rules.md](references/registry-rules.md) ("Where the registry lives"),
   show what it printed and stop. Never ask the user for a project number or a repo list: they
   come from the registry ([references/registry.md](references/registry.md)).
2. Read the one tracker adapter for the registry's tracker, in full:
   [references/trackers/github.md](references/trackers/github.md) or
   [references/trackers/gitlab.md](references/trackers/gitlab.md).
3. Read [references/ticket-labels.md](references/ticket-labels.md) (the labels and the Blocked
   comment), [references/model-selection.md](references/model-selection.md) (how a model label
   becomes a spawn) and the worker's contract, the `$ticket-worker` skill's protocol, whose
   dispatch message section is the payload you send. The Codex behaviour the procedure leans
   on (worktrees and their cleanup, model and effort at spawn, the thread limit, sandbox and
   approvals) is in [references/codex-ticket-notes.md](references/codex-ticket-notes.md).

## The standing rules

- Only Ready tickets assigned to whoever is signed in to the tracker CLI are worked.
  Unassigned tickets and tickets assigned to others are counted in the report and never
  touched. There is no flag for someone else's tickets; that takes signing in as them. When
  the registry's Tracker section sets `Works for`, a run signed in as any other login halts
  before reading the board.
- A Ready ticket carrying the registry's blocked label is held: never dispatched, never
  touched, and listed in the dry run and the report with the kind from its latest `Blocked:`
  comment.
- Work the whole queue without checking in, stopping only for the procedure's halt
  conditions. When Codex Goals are available, set one for a run that dispatches work, so it
  survives a turn ending while workers run, and skip it for `--dry-run`: "Every ticket in this
  run's queue ends in the run record's completed, blocked or skipped list, or is reported
  Unfinished after a halt, checked with ticket_state.py show; every worker I started has
  returned before the report; and I edit no ticket's code myself."
- You orchestrate and the workers implement. Never edit a ticket's code yourself, and keep
  worker output out of the main thread: the run record holds the detail and each worker
  returns one paragraph, its Follow-ups and a `RESULT` line.
- Every spawn is the `ticket_worker` custom agent and names its model and reasoning effort,
  resolved from the ticket's label with `scripts/resolve_model.py`. Run a rolling pool capped
  at `--max-parallel` (5 by default) and at the Codex config's
  `agents.max_concurrent_threads_per_session` (older name `agents.max_threads`) when that is
  lower: start that many workers at once, and the moment one returns start the next ticket
  instead of waiting for the rest.
- Every worker lands its change by pull or merge request, whatever the repo's own rules say,
  and ends `review_opened`. That is finished work: record it with its review link, count it as
  "in review", and never treat it as blocked. Merging the review closes the issue and
  `$daily-grooming` settles it to done; no worker closes an issue or moves a card to done.
- A worker moves its card to In progress when it starts and to the review lane when its review
  opens (if the board has one).
- **Batches, when batching is on** (`registry.py show` prints a `batching` `mode` other than
  `off`; read [references/batches.md](references/batches.md)): Ready tickets are grouped by
  parent, and each parent with Ready children is one slot and one worker, on the strongest
  model and highest effort its children resolve to, working them in the plan's order on one
  branch with one review. A ticket with no parent is a single slot, as before.
- Before any slot dispatches, and in `--dry-run`, measure the instruction files each slot's
  workers will load (the procedure's step 5a): a slot over budget is warned about, never
  halted, and its worker is told to `grep` the big file; the report lists those files on their
  own line.
- The board watcher (`scripts/watch_board.py`;
  [references/board-watcher.md](references/board-watcher.md)) is the only thing that polls the
  tracker; never start a polling loop per review or per worker. Workers file follow-up tickets
  with `scripts/check_ticket.py`, whose path the dispatch message carries.
- Clean up each worker's worktree as soon as its result is recorded, and sweep merged reviews'
  worktrees at the end, with the safe checks in the procedure; never `--force`, never `rm -rf`.
- Finish the queue and wait for every running worker, then report with the counts first: how
  many tickets are in review, blocked and not dispatched, and what needs the user.
- `--dry-run` has no side effects beyond capturing the board's fields. It prints each ticket's
  tier, resolved model and effort, its context estimate, the counts of Ready tickets left
  alone, and an "In review" line with the link for each earlier run's review that is still
  open.
