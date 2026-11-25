---
name: daily-grooming
description: Use when the user wants the whole ticket board tidied ("groom the board", "clean up my backlog", "get Ready in shape"). Settles done work, syncs priorities, batches and plans every Ready ticket. For one ticket use $plan-ticket.
---

# Daily grooming

Keeps a GitHub Project board or GitLab issue board honest so that "Ready" means "safe to
dispatch": a plan, a priority, a model label and a run label on every ready ticket. It covers
the whole board, every person's tickets.

```text
$daily-grooming                            # the whole default board, every repo in the registry
$daily-grooming --dry-run                  # print every change and plan, change nothing
$daily-grooming --project 2 --owner my-group   # a different board (a pasted board URL works too)
$daily-grooming --repo my-app              # only these registry repos; repeatable
$daily-grooming --context FILE             # one brief for the whole run; repeatable
$daily-grooming --convert-batch-labels     # once: turn batch:<area> labels into batch parents
```

Never ask for a project number or a repo list. `--context FILE` is right only for a
single-product board: otherwise each ticket is judged against its own repo's brief.

`<scripts>` below is `${CODEX_HOME:-~/.codex}/skills/daily-grooming/scripts`.

## Before the pass

1. Run `python3 <scripts>/registry.py ensure`. Exit 3 means it just created the team's
   registry and exit 4 means it is unfilled: follow
   [references/registry-rules.md](references/registry-rules.md) ("Where the registry lives"),
   show what it printed and stop. The same file says how a pasted board URL resolves. The
   registry itself is [references/registry.md](references/registry.md).
2. Read the one tracker adapter for the registry's tracker, in full, once:
   [references/trackers/github.md](references/trackers/github.md) or
   [references/trackers/gitlab.md](references/trackers/gitlab.md). Every tracker action is a
   named operation shown in bold in the procedure.
3. Read [references/grooming.md](references/grooming.md) in full. It holds the steps, in
   order: set up and capture the board; fetch the items and settle closed or merged work to
   done before anything else looks at it; flag duplicates; audit each open ticket, with the
   priority sync; group related tickets under batch and epic parents; triage lanes and order
   the Ready lane; apply the changes; make every Ready ticket dispatchable; print the summary,
   with the Ready lane cut into waves by `<scripts>/waves.py`. The batch steps run only when
   batching is on (`registry.py show` prints `batching`, and its `mode` is not `off`); they
   follow [references/batches.md](references/batches.md), which you then read in full too.
4. Planning follows [references/plan-one-ticket.md](references/plan-one-ticket.md), the same
   procedure `$plan-ticket` uses, with its parent, batch, duplicate and grooming checks.
   Planning runs on the `frontier` tier whatever the session's model
   ([references/model-selection.md](references/model-selection.md)): each ticket is planned in
   a subagent spawned on the frontier model and effort `scripts/resolve_model.py` prints, in
   parallel when there are several, or inline when this session already runs on that model.
   Priority, run, model and blocked labels mean what
   [references/ticket-labels.md](references/ticket-labels.md) says. Codex facts the pass leans
   on (subagents, the thread limit, model and effort at spawn) are in
   [references/codex-ticket-notes.md](references/codex-ticket-notes.md).

## The standing rules

- **Settle closed work first.** A closed issue or merged review goes to done and is never
  audited, prioritised, triaged or planned.
- **Never touch a ticket a worker or a person put somewhere.** A ticket in progress, in the
  blocked lane, carrying the blocked label, or with an open linked review keeps its lane and
  is never planned. Grooming only flags the ones that look wrong: a blocked label with no
  `Blocked:` comment, and a ticket in the blocked lane without the label.
- **Never change an assignee.** A Ready ticket with no assignee is listed under Needs
  Attention, because `$work-tickets` works only tickets assigned to its person.
- **Preserve labels.** Remove only a priority label being replaced; add rather than remove
  when unsure.
- **No check-ins.** Finish the pass, then report. Failed writes go in the summary, and the
  pass continues. Before the summary, confirm each step ran or was skipped for a reason you
  can state, and that every Ready ticket is planned, labelled or listed under Needs Attention.
  The summary opens with what changed on the board.
- **`--dry-run` runs read operations only.** It prints every planned change and every ticket
  it would plan, and writes nothing on the tracker, creates no label and spawns nothing.
- **Batches, when batching is on.** A parent is never a ticket: it is dropped from triage and
  counted apart. Grooming forms and joins batches and closes finished parents without asking,
  moves a batch's children between lanes together, plans a batch on its parent, and lists
  every attach and created parent under **Batches** in the summary. With batching off none of
  this runs and the pass is exactly as above.
- **Ready means planned.** A ticket goes to the ready lane only with a `### Final Plan` and no
  open blocker, and a planned, unblocked ticket goes there in the same pass, never left in the
  backlog.
- **Duplicates and lane order are reported.** Duplicates and close candidates are listed for a
  person and never closed or merged. The Ready order goes in the summary, in the waves
  `<scripts>/waves.py` cuts after related tickets are grouped, for someone to apply, since no
  tracker operation reorders a lane.
