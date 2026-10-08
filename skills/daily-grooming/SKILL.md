---
name: daily-grooming
description: Use when the user wants the whole ticket board tidied ("groom the board", "clean up my backlog", "get Ready in shape"). Settles closed work, flags duplicates, syncs priorities, promotes tickets to Ready and plans and labels each one, for every person's tickets. For one ticket use $plan-ticket. Try --dry-run first.
---

# Daily grooming

Keeps a GitHub Project board or GitLab issue board honest so that "Ready" means "safe
to dispatch": a plan, a priority, a model label and a run label on every ready ticket.
It covers the whole board, every person's tickets.

```text
$daily-grooming                            # the whole default board, every repo in the registry
$daily-grooming --dry-run                  # print every change and plan, change nothing
$daily-grooming --project 2 --owner my-group   # a different board (a pasted board URL works too)
$daily-grooming --repo my-app              # only these registry repos; repeatable
$daily-grooming --context FILE             # one brief for the whole run; repeatable
```

Never ask for a project number or a repo list. The tracker, board, lanes, priorities,
labels, model labels and repos come from [references/registry.md](references/registry.md),
including how a pasted board URL resolves; nothing is defaulted here. `--context FILE`
is right only for a single-product board: otherwise each ticket is judged against its own
repo's brief, per the registry.

Read [references/grooming.md](references/grooming.md) in full before you start. It holds
the steps, in order:

1. set up and capture the board;
2. fetch the items and settle closed or merged work to done, before anything else looks
   at it;
3. flag duplicates;
4. audit each open ticket, with the priority sync;
5. triage lanes, and order the Ready lane;
6. apply the changes;
7. make every Ready ticket dispatchable, planning each unplanned one with
   [references/plan-one-ticket.md](references/plan-one-ticket.md), the same procedure
   `$plan-ticket` uses, in parallel subagents when there are more than a few;
8. print the summary.

Every tracker action is a named operation; its commands are in
`references/trackers/<tracker>.md` for the registry's tracker. Read that one file once.
Priority, run, model and blocked labels mean what [references/ticket-labels.md](references/ticket-labels.md)
says. Planning subagents take their model and effort from
[references/model-selection.md](references/model-selection.md) through the bundled
`scripts/resolve_model.py`.

The standing rules:

- **Settle closed work first.** A closed issue or merged review goes to done and is never
  audited, prioritised, triaged or planned.
- **Never touch a ticket a worker or a person put somewhere.** A ticket in progress, in
  the blocked lane, carrying the blocked label, or with an open linked review keeps its
  lane and is never planned. Grooming only flags the ones that look wrong: a blocked label
  with no `Blocked:` comment, and a ticket in the blocked lane without the label.
- **Never change an assignee.** A Ready ticket with no assignee is listed under Needs
  Attention, because `$work-tickets` works only tickets assigned to its person.
- **Preserve labels.** Remove only a priority label being replaced; add rather than remove
  when unsure.
- **No check-ins.** Finish the pass, then report. Failed writes go in the summary, and the
  pass continues. Before the summary, confirm each of the eight steps ran or was skipped
  for a reason you can state, and that every Ready ticket is planned, labelled or listed
  under Needs Attention. The summary opens with what changed on the board.
- **`--dry-run` runs read operations only.** It prints every planned change and every
  ticket it would plan, and writes nothing, creates no label and spawns nothing.
