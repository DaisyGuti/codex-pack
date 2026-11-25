---
name: ticket-worker
description: Use to work one GitHub or GitLab issue ("work issue 42 in my-app") from plan to an open pull or merge request in its own worktree. Also runs what $work-tickets dispatches; for a queue use $work-tickets.
---

# Ticket worker

Takes one issue assigned to the signed-in user from plan to an open review (a pull request,
or a merge request on GitLab) in its own git worktree, and moves the board card. Merging
the review closes the issue. The whole procedure is
[references/protocol.md](references/protocol.md); read it in full before your first step.
Codex behavior it leans on is in [references/codex-ticket-notes.md](references/codex-ticket-notes.md).

**A dispatched run** (you are the `ticket_worker` agent and your message is a dispatch
message from `$work-tickets`, or from a `$ticket-worker` session that handed a ticket
over): skip the steps below and follow the protocol from its section 1. The run record is
`$work-tickets`' (`scripts/ticket_state.py`); a worker never writes it.

**A direct request** ("work issue 42 in my-app", "take #42 to a PR"): run the steps below.
They build the dispatch message the protocol starts from, then work the ticket here or hand
it to a `ticket_worker` on the model its label calls for.

Paths used below: `<scripts>` is `${CODEX_HOME:-~/.codex}/skills/ticket-worker/scripts`,
and `STATE_ROOT` is `${CODEX_HOME:-~/.codex}/state`.

## Standing rules

- Run without pausing. Stop only for the protocol's three cases (a blocker, a decision
  point, manual-action-complete), and do not report until the run reached `review_opened`
  or one of them, with the board and labels matching. Lead the report with the outcome.
- Every change lands by review, whatever the repo's own rules say. The worker never commits
  or pushes to the default branch, never merges, never closes the issue and never moves its
  card to done; merging closes it and `$daily-grooming` settles the card.
- Work only tickets assigned to the signed-in user. The request authorizes every git and
  tracker action the protocol names: pushes of the run's own branch, opening a review, issue
  comments, follow-up tickets, labels and board moves (never to done).
- Work only in the run's own worktrees. A primary clone gets only the git commands the
  protocol's section 3 lists.
- Comments on the tracker are read by people: short, plain language, and a concrete next
  step whenever you stop.
- Never switch models mid-run. A skill cannot set the session's model; only a spawned
  subagent runs on a chosen model and effort.

## 1. Set up

1. Run `python3 <scripts>/registry.py ensure`. Exit 3 means it just created the team's
   registry and exit 4 means it is unfilled: follow
   [references/registry-rules.md](references/registry-rules.md) ("Where the registry
   lives"), show what it printed and stop. Then `python3 <scripts>/registry.py show` gives
   the tracker, board, lanes, priorities, labels, model labels, batching and repos.
2. Read the one tracker adapter for the registry's tracker, in full:
   `references/trackers/github.md` or `references/trackers/gitlab.md`. Every tracker action
   below is a named operation shown in bold.
3. Read [references/model-selection.md](references/model-selection.md) and the protocol,
   whose section 1 is the dispatch message you build.

## 2. Find the ticket and check it is the user's

1. **Repo.** The repo the request names, else the registry repo whose clone contains the
   current folder. When neither settles it, ask which repo and stop. The issue number is the
   one in the request.
2. Run **auth-check** and **current-user**. If the registry sets `works_for` and it differs
   from the signed-in login (case-insensitively), stop: "Signed in as <login>, but this
   registry works only for <works_for>." Then run **capture-board** and **list-items** and
   match the item on `(number, repo)`; keep its `item_ref`. An issue that is not on the
   board skips every board move: say so in the report.
3. **read-issue**. If it is assigned to someone else, or to nobody, stop before anything
   else: change nothing on the ticket and say who it is assigned to (or that it is
   unassigned). For an unassigned ticket, offer to assign it to the current user with
   **assign**, and run **assign** only when the user says to. Never offer to take a ticket
   assigned to someone else; that person reassigns it. A closed issue or one carrying the
   blocked label also stops here, with that fact, except a resume after a locked signing
   key (section 5).
4. **Batch**, when the registry's `batching` `mode` is not `off` (read
   [references/batches.md](references/batches.md), "Working a batch"): run **read-parent**.
   An issue with a batch parent (`batch` true: its title starts with `Batch: `) is worked
   with its whole batch, and the report says so: **list-parents** gives the parent's
   children and **read-parent-item** its plan, and the batch is every open child assigned to
   the current user, without the blocked label, that the plan covers, in the plan's order,
   at most the registry's Batch size of them and all in the first child's repo (the issue
   named is one of them, or this step stops and says why). Children left out are named in
   the report. There is no flag for one child alone: to work it by itself, detach it from
   its parent first. An issue with no parent, or a parent with `batch` false, is a single. A
   direct run never sets `resumed`, so a batch never starts from a branch already on the
   remote, except after a locked signing key (section 5).

## 3. Choose the model

1. A model the user named outranks the label. If it differs from the session's, it runs on
   a spawned `ticket_worker` (section 4).
2. Otherwise take the issue's model label. The registry's Model labels table maps each label
   to `fast`, `workhorse` or `frontier`; without that table the labels are `model:fast`,
   `model:workhorse` and `model:frontier`, and `model:haiku`, `model:sonnet` and
   `model:opus` mean the same three tiers. The effort is the `effort:<level>` label when the
   issue has one, otherwise `high` for `fast` and `medium` for the other two. Run
   `python3 <scripts>/resolve_model.py <tier> --effort <effort>` and use the `model` and
   `effort` it prints, passing any `notes` on in the report.
3. No model label, several, one that maps to no tier, or a resolver exit that is not 0: use
   the `workhorse` tier at `medium` and say in the report which of those it was. Do not
   guess another tier.
4. A batch resolves every child this way and runs on the strongest tier among them
   (frontier over workhorse over fast) at the highest effort (`low` < `medium` < `high` <
   `xhigh` < `max`), unless the user named a model.

## 4. Build the dispatch message and run it

Build the dispatch message exactly as the protocol's section 1 describes, with `mode`
`direct`, `slot_id` `solo`, `ticket_number`, `ticket_repo` and `repos` (the repo, plus any
other registry repo the issue body names), `item_ref`, `assignee` (the current user),
`project` (from the registry and **capture-board**), `repo_map`, `worktree_root`
`$STATE_ROOT/solo-worktrees/<ticket_repo>-<n>`, `model`, `validate_plan_first` `true`,
`context_files` (the repo's product brief), and `files`: `adapter` (the tracker file read in
step 1), `labels` (`references/ticket-labels.md`), `ticket_template`
(`${CODEX_HOME:-~/.codex}/skills/write-ticket/assets/ticket-template.md`) and `check_ticket`
(`<scripts>/check_ticket.py`). Every path is absolute: expand `${CODEX_HOME:-~/.codex}` and
resolve symlinked folders (`cd <dir> && pwd -P`). A batch also sends `parent`, the ordered
`children` and `files.batches` (`references/batches.md`), with `ticket_number` and
`ticket_repo` naming the first child; a single sends none of them.

Then decide where it runs:

1. **Work it in this session**, following the protocol with this message, when any of
   these holds: you are already a spawned `ticket_worker` (a spawned run never delegates
   again, which prevents a loop); the user said to work it here (a named model that differs
   from the session's: say in the report that the session cannot switch models); or the
   session already runs on the chosen model at that effort.
2. **Otherwise hand it off.** Spawn one `ticket_worker` with `spawn_agent`, setting the
   chosen model and reasoning effort explicitly (the agent file sets neither), with the
   dispatch message as the whole message. Wait for it, then close its thread. If the spawn
   fails for lack of a free thread (`agents.max_concurrent_threads_per_session`, older name
   `agents.max_threads`), wait for a thread and try once more. Any other spawn error, for
   example "agent type is currently not available" (the agent file is missing or installed
   as a symlink): work the ticket in this session, say what failed, and tell the user to
   rerun the pack's `install.sh`. Never retry in a loop.

## 5. A locked signing key

The worker signs its commits whenever the repo's git config does. When the key is locked
and no terminal can unlock it, the worker never turns signing off: it keeps the change
staged in its worktrees, holds the ticket with the blocked label and a `Blocked: failure`
comment, and ends with `status` `blocked_sandbox`, the `reason` `signing key locked`, and
the trees in `worktree_paths`. Keep those worktrees (section 6 leaves them), and ask the
user to unlock the key in their own terminal, for example by signing one test message so
the agent caches the passphrase. When they say it is unlocked, that clears the hold:
**remove-label** the blocked label, **comment** `Unblocked: signing key unlocked.`, and run
the same dispatch message again (section 4) with `resume_worktrees` set from the result's
`worktree_paths` and `resumed` `true`. The resumed worker commits the staged change and
carries on from the protocol's section 7.

In a later session, the user runs this skill on the issue again and says the key is
unlocked. Then the blocked label does not stop section 2 when the ticket's latest
`Blocked:` comment is the signing-key stop: find each repo's worktree with
`git -C <clone> worktree list` (the one on `solo-ticket-<n>`, or its `-r2` or `-r3` form),
and resume the same way. When any repo in `repos` has none, the staged change is gone:
resume nothing, say so, and the user removes the blocked label and runs the ticket again
from the start. A batch resumes only in the session that started it; in a later session the
user clears the blocked label on each held child and runs the batch again.

## 6. Clean up and report

**Clean up first.** Once the result is in hand, remove the run's worktrees by the safe
cleanup in [references/codex-ticket-notes.md](references/codex-ticket-notes.md) ("Safe
cleanup"): only when nothing in them is uncommitted or unpushed, never with `--force`. A
`review_opened` result is the case it covers; keep the worktrees of any other status and
say where they are.

Relay the worker's report as yours, its Follow-ups list included. Put one line before it
saying which model and effort ran and why (the label, the user's choice, or the fallback in
section 3), and one line saying that Codex has no local Auto-fix: a conflict shows up in the
board watcher's `CONFLICT` events and the next `$work-tickets` run, and Codex cloud's review
runs on the review when someone mentions `@codex` or the team turned on automatic reviews.
The worker's last line is a `RESULT` line; read it for the status and the review links, and
keep it out of your own summary. A ticket in review is not closed: say that merging the
review closes it. For a batch, name the parent, the children the review closes and each
child left out or held, from the `RESULT`'s `children_status`.
