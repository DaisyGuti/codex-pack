---
name: write-ticket
description: "Use to get a bug, idea or request onto the team's tracker as a ticket or issue, or to turn a rough note into a proper one. Also rewrites an existing ticket. Checks it isn't already built or ticketed, then files it with priority, model and run labels. To plan one use $plan-ticket; to tidy the board, $daily-grooming."
---

# Write ticket

`$work-tickets` and `$ticket-worker` only work tickets written a particular way. This
skill writes them that way, from an idea or from a rough ticket. The words after the
flags are the description; infer everything else, make reasonable assumptions instead of
asking, and say which ones you made in the report.

```text
$write-ticket <what you want, in your own words>
$write-ticket --repo my-app <...>        # skip repo inference
$write-ticket --ticket 42 --repo my-app  # rewrite an existing ticket in place
$write-ticket --ready <...>              # file into the ready lane instead of backlog
$write-ticket --assignee me <...>        # assign it: a login, or "me" for the signed-in user
$write-ticket --dry-run <...>            # show the ticket and its labels, create nothing
```

The tracker, board, lanes, priorities, labels, model labels and repos come from
[references/registry.md](references/registry.md); no default lives here. If a role this
skill needs is missing from the registry (the backlog lane, say), stop and name the row
to add. Every tracker action below is a named operation shown in bold, with its
commands in `references/trackers/<tracker>.md` for the registry's tracker. Read that
one file once and run each operation as written. Bundled script:
`scripts/resolve_model.py` (see the model label in step 4).

## 1. Resolve the repo

`--repo`, or infer it from the description: a repo name from the registry's table, a
file path, a product name, a symbol you can find with one search. **If it is not
exactly one repo, ask.** A ticket in the wrong repo aims the worker's closing keyword
at the wrong tracker. Read that repo's brief from the registry; you need its audience.

## 2. Prove the premise before writing

Check in the repo's local clone with read-only commands and run what proves a claim:

1. **Already built?** Search for the symbol, flag, route or config key; run the test
   file if there is one.
2. **Superseded?** Read the repo's `AGENTS.md`, README and decision records. A ticket
   against a deleted subsystem, a paused platform or a reversed decision is dead on
   filing.
3. **Already ticketed?** **search-issues** on the keywords, and **list-items** for
   board items on the same repo.
4. **Window passed?** A ticket tied to a date, campaign or season behind us is a
   decision about whether to bother: say so and file nothing.

**If the premise fails, stop and say so**, with the evidence: "this is already built,
here is the test that proves it" is the most valuable result this skill has.

## 3. Write it

Fill [assets/ticket-template.md](assets/ticket-template.md), every section in order.
Sections 1 to 3 and 5 of the Agent Instructions are boilerplate: copy them exactly. In
section 4's first bullet use the audience from the repo's brief.

- Write `None` under Dependencies rather than dropping the heading. A dependency goes
  on a `Depends on:` line, since the workers' unblock step matches `Depends on:` and
  `Blocked by:`.
- Omit Out of scope only when there is genuinely nothing a reader would include.
- **Never invent a concrete detail**: a price, a filename, an error string, a date, a
  metric, a version. Every specific is one you read. For a fact you do not have, write
  `- [ ] TBD: <the question>` and say so in the report.
- Split the ticket when the acceptance list runs past about seven bullets or the work
  spans more than two repos.

## 4. Assign the labels, priority and lane

[references/ticket-labels.md](references/ticket-labels.md) holds the judgment for each
label; apply it rather than restating it here.

- **Priority:** one role from the registry's Priority table, judged by its Meaning
  column.
- **Run label:** exactly one. The run-worker label when there is code or config a
  worker can build and prove, even if the last step is a live action no worker can
  take; the run-solo label only when there is nothing to build at all.
- **Model label:** the tier by difficulty, never urgency, `workhorse` when in doubt,
  written as the label the registry's Model labels table maps that tier to
  ([references/model-selection.md](references/model-selection.md) has the rows). Name
  the model the tier runs on today with `python3 scripts/resolve_model.py <tier>` in the
  report; if it exits 3, say the account has none for that tier.
- **Other labels:** `project:<repo>`, and the repo's existing area labels (`web`,
  `bug`, ...) from **list-labels**. Never invent an area label.
- **Lane:** the backlog lane, or the ready lane with `--ready`.
- **Assignee:** only with `--assignee`; `me` is **current-user**. Otherwise leave the
  ticket unassigned.
- **Blocked:** when a `Depends on:` issue is still open (**issue-state**), the ticket
  gets the registry's blocked label and a `Blocked: dependency` comment naming each open
  dependency (shape in ticket-labels.md). It keeps the lane it was filed in. The
  workers' unblock step frees it when the last dependency closes.

## 5. File it

`--dry-run` prints the ticket, its labels, lane and assignee and stops; read-only
operations are fine, nothing is created.

1. **ensure-label** for each label that may be missing (run, model, `project:<repo>`,
   blocked), using the registry's color and description; `project:` labels get color
   `ededed` and the description "Product: <repo>". Area labels are never created.
2. **create-issue** with the title, body and labels (this also adds it to the board).
3. **set-priority**, then **set-lane**. When the ticket is blocked, **comment** with the
   `Blocked: dependency` comment.
4. **assign** when `--assignee` was given.

`--ticket N`: run **read-issue** first and keep the old body. Stop and say so if the
issue is closed or its lane is in progress or done (find the lane with **list-items**).
Otherwise **edit-issue** with the new body, **remove-label** any run or model label
that no longer applies, add the new ones as in step 1, run **add-to-board** if it is
not on the board, then **set-priority** and **set-lane**, and the blocked label and
comment if a dependency is still open and the issue does not already carry both.
Existing assignees stay unless `--assignee` was given.

Finish every step above before you report. If a write fails, say which one and what is
left undone; never report a ticket as filed that is missing its labels, priority or
lane.

## 6. Report

In plain language, outcome first. If step 2 stopped the work, lead with that finding
and its evidence (already built, already ticketed, superseded, window passed). Otherwise
lead with the URL and title, then each assignment with a clause of reasoning, the
assumptions you made, and any `TBD:` bullets. If step 2 found something short of a
stop, such as a related ticket, add it. For `--ticket`, say what the old body held so
nothing is lost silently. When the ticket is unassigned, say that `$work-tickets` will
not pick it up until someone is assigned.
