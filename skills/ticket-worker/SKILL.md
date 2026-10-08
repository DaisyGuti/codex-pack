---
name: ticket-worker
description: Use when the user asks to work one specific issue ("work issue 42 in my-app") or when $work-tickets dispatches a ticket payload. Takes the issue from plan to commit, push, close (or an open review, where the repo lands work by review) and board move in its own git worktree. For a whole Ready queue use $work-tickets.
---

# Ticket worker

Read [references/protocol.md](references/protocol.md) in full before your first
step. It holds the whole procedure for both ways work arrives: a JSON payload from
`$work-tickets` (you run as its `ticket_worker` subagent, and the payload names the
state file you update), or a direct request such as "work issue 42 in my-app".

The tracker, board, lane names, labels and repo set live in
[references/registry.md](references/registry.md). The only way a ticket or review is
held is the blocked label plus a comment saying what it is blocked on, as defined in
[references/ticket-labels.md](references/ticket-labels.md). A dispatched run receives them
through the state file; a direct run reads the registry itself. Every tracker action
in the protocol is a named operation; its commands are in
`references/trackers/<tracker>.md` for the registry's tracker (`github` or `gitlab`),
so read only that file, in full, before your first step.

- Run the pipeline without pausing. Stop only for the protocol's three cases: a
  blocker, a decision point, or manual-action-complete. Make reasonable assumptions on
  routine choices, and do not report until the run reached `ticket_closed`, `review_opened` or one of
  those stops, with the board and labels matching. Lead the report with the outcome.
  A repo whose rules require a pull or merge request lands by review: the run ends at
  `review_opened` with the review open, which is a finished ticket, not a stop.
- Work only tickets assigned to the signed-in user. A dispatched run checks the
  payload's `assignee` and stops with `blocked_not_assigned` when the issue is no
  longer theirs; a direct run compares the issue with the signed-in user, and when it
  is assigned to someone else or to nobody it stops and offers to assign it, never
  assigning without being told to.
- The request or dispatch authorizes every git and tracker action the protocol names:
  pushes, opening a review, issue comments, labels, closing the issue and board moves.
- Work only in your own worktree. A primary clone gets read-only git commands, plus
  the four writes the protocol lists for direct mode.
- Comments you post on the tracker are read by the user: short, plain language, and a
  concrete next step whenever you stop.
- Never switch models mid-run. The model you were spawned on is recorded, not
  chosen.
- A direct request ("work issue 42 in my-app") picks its model for itself. A skill
  cannot set the session's model, so once the assignment check passes, a ticket with a
  model label goes to a `ticket_worker` subagent spawned on that label's model and
  effort, and you relay its report. The protocol's section 1 has the exceptions (a
  model the user named, "work it here", a session already on that model, a run that was
  itself spawned) and what to do when the ticket has no model label. Bundled script:
  `scripts/resolve_model.py`, which turns a tier into a model and effort.
