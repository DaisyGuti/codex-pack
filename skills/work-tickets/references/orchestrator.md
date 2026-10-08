# Ready-ticket orchestrator

Process the **Ready** tickets of a project board, on GitHub or GitLab, that are
assigned to the person running this command, by dispatching `ticket_worker` subagents
in parallel waves. The tracker, board, lane names, labels and repos come from
[registry.md](registry.md), which is the only place any of them is written down.

**Whose tickets.** The person running the command is whoever is signed in to the
tracker CLI on this machine (**current-user**, resolved once in Phase 1). Only Ready
tickets assigned to that login are worked. Unassigned tickets and tickets assigned
only to others are left exactly as they are and counted in the report. There is no
flag for working someone else's tickets: to do that, sign in as them.

**Tracker operations.** Every action on the tracker below is a named operation, shown
in bold (**list-items**, **set-lane**, ...). The exact commands for each are in
`references/trackers/<tracker>.md` for the registry's tracker. Read that one file in
full before Phase 1 and run each operation as written there; never improvise a
command for one. A **review** is a pull request on GitHub and a merge request on
GitLab.

## Invocation

```text
$work-tickets                          # every Ready ticket across the default board
$work-tickets --dry-run                # the queue and nothing else
$work-tickets --priority P1            # only P1 tickets
$work-tickets --project 2 --owner me   # a different board (a pasted board URL works too)
$work-tickets --max-parallel 5         # wider waves
```

No arguments are needed, and you never ask the user for a project number or a repo
list. Defaults, applied when the flag is absent:

- **tracker, host, board:** the registry's Tracker and Board sections
- **repos:** every repo in the registry's table; keep no list here
- **priority:** no filter; any priority, and none, is eligible
- **max-parallel:** 3. **limit:** 30

Overrides:

- `--priority P0|P1|P2|P3`, repeatable: priority roles from the registry's Priority
  table. It narrows within Ready and never replaces it.
- `--project N` / `--owner OWNER`, or a pasted board URL of either tracker, per the
  registry's "Resolving a project board argument".
- `--repo NAME:PATH[:REMOTE]`, repeatable, restricting the run to those repos (REMOTE
  defaults to `<owner or board path>/<NAME>`).
- `--context FILE`, repeatable: the brief used for plan validation. Absent, each
  worker gets its own repo's brief from the registry.
- `--max-parallel N`, `--limit N` (each minimum 1), `--dry-run`, `--clear-skipped`.

A ticket's lane equal to the registry's ready lane value, and the signed-in login among
its assignees, are always the gate.

## Labels a ticket must carry

A ticket missing either set was never groomed and is not dispatched.

**A model label** picks the worker's model. The registry's Model labels table maps
each tier (`fast`, `workhorse`, `frontier`) to the label that means it; a ticket's
tier is the tier whose label it carries. Labels the table does not list still resolve
when they are `model:haiku`, `model:sonnet` or `model:opus` (the same three tiers) or
the legacy `model:claude-haiku-*`, `model:claude-sonnet-*` or `model:claude-opus-*`
forms; map those to a tier name before calling the resolver, which does not know the
dated names. A registry with no Model labels table means `model:fast`,
`model:workhorse` and `model:frontier`. No model label: `blocked[]`,
`reason="no model label"`. A label that starts with `model:` and maps to no tier:
`blocked[]`, `reason="unrecognized model label: <value>"`. Several model labels:
`blocked[]`, `reason="conflicting model labels: <values>"`.

**`effort:<level>`** (optional) sets the reasoning effort.

**The run-worker label or the run-solo label** (registry Labels roles `run_worker` and
`run_solo`; `run:worker` and `run:solo` by default), exactly one.

- run-worker: a worker can finish it end to end, and it is self-contained. That is
  what makes it safe in a parallel wave. It keeps the label even when its last step is
  a live action no worker can take; the worker builds the rest and stops at
  `needs_manual_action`.
- run-solo: nothing to build at all. Skipped, never dispatched.
- Neither: `blocked[]`, `reason="no run label: ticket has not been groomed"`.

[ticket-labels.md](ticket-labels.md) has the full rule for both labels. Concurrency
safety is a per-ticket property decided when the ticket is groomed
(the run-worker label means self-contained), so there is no pairwise conflict check here.

## Mechanics

- **Roots.** Let `STATE_ROOT=${CODEX_HOME:-$HOME/.codex}/state`, expanded to an
  absolute path everywhere it is written, payloads included. The **board key** is
  `<owner>-<number>` on GitHub, and on GitLab the board's group or project path with
  each `/` written `-`, then `-` and the board id (or the board name lower-cased with
  runs of other characters written `-`, when the registry gives only a name). `<login>`
  is the signed-in login from **current-user**.
  - State file: `$STATE_ROOT/ready-worker-<board key>-<login>.json`
  - Lock: the same path plus `.lock`
  - Worktrees: `$STATE_ROOT/ready-worktrees/<board key>-<login>/<slot_id>/<repo>`

  Each `(board, login)` pair gets its own state file and worktree root, so runs
  against different boards cannot collide, and two people on one machine never share
  a slot table. Run one orchestrator per board and login at a time:
  a worker moves its card out of Ready as soon as it starts, but two orchestrators
  would queue the same Ready tickets until then.
- **Pushes.** Each worker decides how its repo lands work, from the repo's own rules
  (protocol section 8). A repo that lands directly gets a push to the default branch
  with no review, and the worker's one-shot rebase-retry absorbs push races. A repo
  that lands by pull or merge request gets its branch pushed and a review opened with
  no blocked label; the ticket ends `review_opened`, a successful end, and merging the
  review closes the issue. A ticket that ends in `needs_manual_action` pushes its own
  branch and opens a review carrying the registry's blocked label, on every repo, so
  nobody merges it before the live step.
- **Blocker isolation.** A blocked ticket halts only its own slot; the rest of the
  wave finishes and the next wave dispatches.
- **Preflight**, before the first slot is created: you can write under `STATE_ROOT`,
  **auth-check** passes, and `git -C <one primary clone> fetch origin --prune`
  succeeds (network, credentials, a writable Git directory). When a check fails,
  stop before touching the board and tell the user to relaunch Codex with full
  access. The default `workspace-write` sandbox cannot run this skill, even with
  extra writable directories, because it keeps every `.git` read-only and both
  `git worktree add` and each worker's commits write there.
- **Notifications.** One desktop notification where the platform has a command for
  it: `osascript -e 'display notification "<text>" with title "Codex Ready Worker"'`
  on macOS, `notify-send` on Linux. If none works, say so in the report.
- **Locking.** Every read-modify-write of the state file takes the exclusive
  advisory lock:

  ```bash
  (
    flock -x 200
    # read state, mutate, write back
  ) 200>"$STATE_LOCK"
  ```

  Where `flock` is not installed, Python's `fcntl.flock(fd, fcntl.LOCK_EX)` on the
  same lock file takes the same lock.

## State file

If the file does not exist, create it:

```json
{ "schema_version": 3, "project": {}, "active": [], "completed": [], "blocked": [], "skipped": [] }
```

If `schema_version` is not `3`, halt with "State schema version <N> is not
supported. Delete or migrate <state_file>." The orchestrator owns inserts into
`active[]`, moves to `completed[]` and `blocked[]`, `skipped[]` inserts, and the
worktree lifecycle. A worker mutates only its own slot in `active[]`, found by
`slot_id`.

Slot record in `active[]`:

```json
{
  "slot_id": "slot-1",
  "ticket_number": 182,
  "repos": ["<repo>"],
  "ticket_repo": "<repo>",
  "item_ref": "<tracker handle for the board item, null where the tracker needs none>",
  "worktree_paths": { "<repo>": "<abs worktree path>" },
  "slot_branch": "slot-1-ticket-182",
  "resolved_tier": "workhorse",
  "resolved_model": "<slug>",
  "resolved_effort": "medium",
  "step": "synced",
  "status": "running",
  "reason": null,
  "pre_step_sha": {},
  "changed_files": {},
  "commit_sha": {},
  "plan": null,
  "started_at": "<ISO 8601>"
}
```

## Phase 1: capture the board

At the start of every run, so a renamed lane or an edited registry takes effect:

1. **current-user** gives the login this run works for. If it cannot be read, halt:
   "Cannot tell who is signed in to the tracker CLI."
2. **capture-board** with the registry's board, lanes and priorities gives
   `tracker_ids`, `missing_lanes`, `missing_priorities` and `has_priority`. Without
   priority support the run is fine unless `--priority` was passed, then halt:
   "Priority filter requested but board <board key> has no priority support."
3. From the registry take `lanes` (role to lane value for the configured tracker),
   `priorities` (role to priority value, in rank order), `labels` (role to
   `{name, color, description}`) and `model_labels` (tier to label). The ready lane
   must not be in `missing_lanes`, or halt and print the raw output of
   **capture-board**. Any other missing lane: warn, and workers will skip that move.
4. Build `repo_map` from the registry, or from `--repo` flags when passed:
   `{ "<name>": { "primary_clone": "<abs path>", "remote": "<Remote>", "brief": "<abs path>", "default_branch": null } }`.
   `default_branch` is filled in lazily, per repo, the first time a slot needs it
   (section 7a).
5. Write `state.project` under lock: `tracker`, `host`, `board` (the resolved board
   identity: owner and number, or scope, path and id), `board_key`, `assignee` (the
   login), `tracker_ids`, `repo_map`, `lanes`, `priorities`, `labels`, `model_labels`,
   `captured_at`.

If an existing `state.project` has a different board or assignee than the resolved
ones, halt: two boards or two people have been pointed at one state file.

## Orchestration

### 1. Parse arguments

Apply the defaults above. On `--clear-skipped`, empty `state.skipped[]` under lock.

### 2. Resume crashed workers

A non-empty `state.active[]` is a run that did not finish cleanly. Treat those slots
as the first wave and re-dispatch each from its stored record, after re-resolving its
model (section 4). Check each worktree path still exists; if not, move the slot to
`blocked[]` with `blocked_worktree_missing`. This first wave may exceed
`--max-parallel`; log a warning.

### 3. Fetch and filter the queue

Run **list-items** on the ready lane. Each item carries `item_ref`, `number`, `repo`,
`type`, `title`, `lane`, `priority`, `labels` and `assignees`. Keep items whose `lane`
equals the ready lane's value, then drop:

- `type != "issue"` to `skipped[]`, `reason="not an issue: reviews are merged, not
  worked"`. Handed a pull request or merge request, a worker would open a second
  branch for a change that already has one.
- a null `number` to `skipped[]`, `reason="null content number"`.

Then split what is left by assignee, with logins compared case-insensitively. An item
whose `assignees` include `state.project.assignee` stays. An item with no assignees
adds one to the **unassigned** count; an item assigned only to other people adds one
to the **assigned to others** count. Both are left exactly as they are: not
dispatched, not in `skipped[]`, not in `blocked[]`, and nothing written to the ticket.
Keep the two counts for the dry run and the completion report. Then take out the
**held** tickets: any remaining item whose `labels` include `labels.blocked`'s name is
somebody's open hold (a dependency, a decision, a live action or a failure; see
[ticket-labels.md](ticket-labels.md)). Never dispatch it, never put it in `blocked[]`, never touch it.
Count it as held, keeping its number and `repo` for the report. Then drop:

- anything already in `completed[]`, `blocked[]` or `active[]`, matched on the pair
  `(ticket_number, ticket_repo)` and never on the number alone: issue numbers are
  per repo, so two repos routinely reuse one number. `ticket_repo` here is the last
  part of the item's `repo`, which is available before section 4.
- the run-solo label to `skipped[]`, `reason="run:solo label: human-in-loop required"`.
- neither run label to `blocked[]`, `reason="no run label: ticket has not been
  groomed"`.
- with `--priority`, any item whose `priority` is not the registry value of a
  requested role to `skipped[]`, `reason="priority <X> not in filter"`.

### 4. Resolve repos and the model

**Repos** follow the registry's "Resolving a ticket to its repo": parent repo, then
`repo:<name>`, then `project:<name>`, then a body keyword scan; no match skips with
`reason="no repo could be inferred"`, never a guess. The repo the issue lives in is
the owning repo; a ticket may resolve to several.

**Model.** Find the ticket's model label as in "Labels a ticket must carry", turn it into a tier
name (`fast`, `workhorse` or `frontier`), and run the skill's
`scripts/resolve_model.py <tier> --effort <effort>`,
with the effort from the ticket's `effort:<level>` label when present, otherwise
`high` for `fast`, `medium` for `workhorse` and `medium` for `frontier`. Store the
printed `tier`, `model` and `effort` as `resolved_tier`, `resolved_model` and
`resolved_effort`. A slot resumed from an earlier run is resolved again from its
`resolved_tier` and `resolved_effort`, so a retired slug never reaches a spawn.

- Exit 3: `blocked[]`, `reason="no model available for tier <tier>"`.
- Any other non-zero exit: `blocked[]` with the script's error as the reason.
- A missing or unrecognized label: blocked as in "Labels a ticket must carry".

Show any `notes` the script prints (a fallback slug, a clamped effort) on that
ticket's dry-run and report lines. Blocked tickets are not enqueued.

### 5. Sort, then cap

Sort by priority in the rank order of the registry's Priority table (P0 first by default), then unset, stable within a priority, then keep
the first `--limit`.

### 6. Dry run

With `--dry-run`, print the queue, the skipped list and the existing `blocked[]`,
then exit. The only side effects are Phase 1 capture and `--clear-skipped`. The "In
review" lines come from `completed[]` entries marked `landed: "review"`, each checked
with **review-state** on its first `review_refs` entry; list only those still `open`,
with their links. A review that merged or closed drops out of the line.

```text
Ready queue: board <board key> for <login> (max-parallel=<M>, limit=<L>, to-process=<K>)
  #182 "title" repos=[<repo>] owning=<repo> workhorse <slug> medium P1
Left alone: <A> Ready tickets assigned to others, <U> unassigned
Held (carry the blocked label, not dispatched): <H>
  #71 <repo>: Blocked: dependency
In review (opened by earlier runs, still open): <R>
  #120 <repo>: <review URL>
Skipped this run:
  #60 "title": run:solo label: human-in-loop required
Blocked (not enqueued):
  #64 "title": no run label: ticket has not been groomed
```

### 6.5. Plan validation

Every payload carries `validate_plan_first: true`. The worker reads the ticket's
existing `### Final Plan`, checks it for drift, uses it as is when clean, and
otherwise re-plans in one pass. Pass the owning repo's brief from the registry as
`context_files`, or the `--context` files when given.

### 7. Wave dispatch loop

While the queue or `state.active[]` is non-empty:

**7a. Assign slots.** If this is the first wave and `active[]` was non-empty at
invocation, the wave is those slots; go to 7b. Otherwise take up to `--max-parallel`
tickets from the front of the queue and, for each:

1. `slot_id` = `slot-<i>`, the smallest positive integer not used by any slot in
   `active[]` or `blocked[]` (blocked slots keep their worktrees, so their ids stay
   taken). Assign the whole wave's ids up front.
2. Worktree path per repo: `$STATE_ROOT/ready-worktrees/<board key>-<login>/<slot_id>/<repo>`.
3. Create it from the repo's `primary_clone`:
   ```bash
   git -C <primary_clone> worktree remove --force <wt-path> 2>/dev/null || true
   git -C <primary_clone> worktree prune
   git -C <primary_clone> fetch origin --prune
   git -C <primary_clone> worktree add <wt-path> -b <slot_id>-ticket-<n> origin/<default_branch>
   ```
   `<default_branch>` is the repo's `repo_map[<repo>].default_branch`. When it is null,
   read it from the primary clone before the commands above:
   `git -C <primary_clone> symbolic-ref --short refs/remotes/origin/HEAD` with the
   leading `origin/` removed. If that fails, run `git -C <primary_clone> remote
   set-head origin --auto` once and read it again. If it is still unknown, the slot is
   `blocked_default_branch_unknown` with the repo named; append it to `blocked[]` and
   continue with the rest of the wave. Store what you read in `repo_map` under lock.
4. Append the slot record to `active[]` under lock with `step="synced"`,
   `status="running"`.

If worktree creation fails for a repo, mark the slot `blocked_worktree_create_failed`
with the error, append it to `blocked[]`, and continue with the rest of the wave.

**7b. Dispatch in parallel.** In one turn, spawn one `ticket_worker` subagent per
slot with `spawn_agent`, setting the model to the slot's `resolved_model` and the
reasoning effort to `resolved_effort`. The agent file sets neither, so the spawn's
values are the ones that run. The message is this payload:

```json
{
  "slot_id": "<id>",
  "ticket_number": 182,
  "repos": ["..."],
  "item_ref": "<item_ref>",
  "assignee": "<login>",
  "worktree_paths": { "<repo>": "<wt-path>" },
  "state_file": "<absolute state file path>",
  "state_lock": "<absolute lock path>",
  "model": "<resolved_model>",
  "validate_plan_first": true,
  "context_files": ["<owning repo's brief>"]
}
```

The worker reads the tracker, board, lanes, labels and `repo_map` from `state.project`
and hardcodes none of them. Each worker returns one short paragraph (ticket, final step
and status, commit or review links, what blocks it); the slot in the state file is the
record, so do not ask for logs. Wait for every worker in the wave before reaping.

- **Thread limit.** If the Codex config sets `agents.max_concurrent_threads_per_session`
  (older name `agents.max_threads`) below `--max-parallel`, use it as the wave size and
  say so in the report. If a spawn still fails for lack of a free thread, spawn that
  slot again as soon as a worker in the wave returns, and reap only after it finishes
  too. After reaping a wave, close its worker threads, since open threads count against
  the limit.
- **Any other spawn error** (for example "agent type is currently not available",
  meaning the agent file is missing or installed as a symlink) puts that slot in
  `blocked[]` with the error text, and the report tells the user to rerun the pack's
  `install.sh`. Never retry it in a loop.

**7c. Reap.** For each slot, under lock, re-read its entry:

- `status` starts with `blocked_`, or equals `needs_decision` or `needs_manual_action`:
  copy the full record into `blocked[]` (keep `worktree_paths`), remove it from
  `active[]`, leave the worktree (the branch and reviews may still need it),
  print the reason and paths, and send one notification. `needs_manual_action` lands
  in `blocked[]` like the others, told apart by its `status` and by the
  `manual_action_refs` (review URLs) in its record. A `blocked_not_assigned` slot means
  the ticket was reassigned after the queue was built: it is reported, nothing on the
  ticket was touched, and it will not be dispatched again until it is assigned back.
- `status == "review_opened"`: the worker built and tested the ticket and opened a
  review; this is successful work, not a block. Copy `{ticket_number, repos,
  ticket_repo, commit_sha, review_refs, landed: "review", started_at, resolved_tier,
  resolved_model, resolved_effort}` into `completed[]`, remove it from `active[]`, then
  remove the worktree and branch exactly as for a closed ticket below. The branch is
  on the remote, so nothing is lost; the report says the worktree was removed. The
  issue is still open until the review merges.
- `step == "ticket_closed"` and `status == "running"`: copy `{ticket_number, repos,
  ticket_repo, commit_sha, close_method, closed_at, started_at, resolved_tier,
  resolved_model, resolved_effort}` into `completed[]`, remove it from `active[]`, then
  ```bash
  git -C <primary_clone> worktree remove --force <wt-path>
  git -C <primary_clone> worktree prune
  git -C <primary_clone> branch -D <slot_branch> 2>/dev/null || true
  ```
- `status == "running"` at an intermediate step (the worker returned without finishing
  or blocking): anomalous. Leave it in `active[]` to resume next run, log a warning,
  and dispatch no further waves this run.

**7d.** Repeat from 7a until the queue and `active[]` are empty.

### 8. Completion

```text
=== work-tickets complete: board <board key> for <login> ===
Completed: <N>
  #182 <repo>: keyword close, commit abc1234 (slot-1, workhorse <slug> medium, 12m)
In review: <R>
  #190 <repo>: <review URL> (slot-2, workhorse <slug> medium, 9m; merging closes the issue)
Blocked: <M>
  #50 <repo>: blocked_push_rejected: non-fast-forward (worktree: ...)
  #189 <repo>: needs_manual_action: create the product for plan B and set PRICE_ID_B
    in the hosting env vars. Review https://... (worktree: ...)
Skipped: <K>
  #60 "title": run:solo label: human-in-loop required
Pre-existing blocked[] (carried over): <L>
Left alone: <A> Ready tickets assigned to others, <U> unassigned
Held (carry the blocked label, not dispatched): <H>
  #71 <repo>: Blocked: dependency
```

An "In review" line is not a problem to fix: the ticket is built and tested and waits
for its reviewer, so the sentence on what needs the user says which reviews are open to
merge, with their links. A `needs_manual_action` line's reason names the live action and the review
links from `manual_action_refs`; that tells the user at a glance which Blocked items
are a bug to fix and which are a click to make. Follow the block with one plain
sentence on what needs the user: the held tickets and the blocked tickets of this run,
each with the kind of its most recent `Blocked:` comment (**read-issue**; a run's own
`blocked_*` is a `failure`, `needs_decision` a `decision`, `needs_manual_action` a
`live action`, and a blocked label with no such comment is "no Blocked comment"), and
the manual actions with their links, and say that the "left alone" tickets are not this
person's to work (the unassigned ones need an assignee before `$work-tickets` will
pick them up). Then send the notification:
`Ready worker complete: N done, R in review, M blocked, K skipped (board <board key>, <login>)`.
In review counts only this run's `review_opened` tickets, apart from Completed.

## Notes

- **Full restart for one board and login:** delete its state file, then per repo in
  `repo_map` run `git -C <primary_clone> worktree prune`, then remove
  `$STATE_ROOT/ready-worktrees/<board key>-<login>/`.
- **Retry** a completed or blocked ticket by removing its entry from `completed[]` or
  `blocked[]`. The orchestrator never auto-retries a blocker.
- `skipped[]` persists across runs; `--clear-skipped` empties it.
