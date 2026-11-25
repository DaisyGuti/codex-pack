---
name: write-ticket
description: 'Files a bug, idea or request as a ticket the workers can build, or rewrites one. Checks the premise in the repo, then sets priority, model, run and lane. Use for "file a ticket", "rewrite ticket 42"; to plan one, $plan-ticket.'
---

# Write ticket

`$work-tickets` and `$ticket-worker` only work tickets written a particular way. This skill
writes them that way, from an idea or from a rough ticket. The words after the flags are the
description. Infer everything else, make reasonable assumptions instead of asking, and say
which ones you made in the report. To plan an existing ticket use `$plan-ticket`; to tidy
the board, `$daily-grooming`.

```text
$write-ticket <what you want, in your own words>
$write-ticket --repo my-app <...>        # skip repo inference
$write-ticket --ticket 42 --repo my-app  # rewrite an existing ticket in place
$write-ticket --ready <...>              # plan it too, and move it to ready once planned
$write-ticket --assignee me <...>        # assign it: a login, or "me" for the signed-in user
$write-ticket --dry-run <...>            # show the ticket and its labels, create nothing
```

Bundled scripts, run with stdin closed (`< /dev/null`): `scripts/registry.py`,
`scripts/check_ticket.py` and `scripts/resolve_model.py`, all under
`${CODEX_HOME:-~/.codex}/skills/write-ticket/`.

## 0. Set up

1. Run `python3 "${CODEX_HOME:-~/.codex}/skills/write-ticket/scripts/registry.py" ensure`.
   On the first run it creates the team's registry and exits 3; on an unfilled one it exits
   4. Follow [references/registry-rules.md](references/registry-rules.md) ("Where the
   registry lives"): show what it printed and stop. Do not guess registry values.
2. Run `python3 "${CODEX_HOME:-~/.codex}/skills/write-ticket/scripts/registry.py" show` for
   the tracker, board, lanes, priorities, labels, model labels and repos. No default lives in
   this skill. If a role this skill needs is missing (the backlog lane, say), stop and name
   the row to add.
3. Read the one tracker adapter for the registry's tracker, in full, once:
   [github.md](references/trackers/github.md) or
   [gitlab.md](references/trackers/gitlab.md). Every tracker action below is a named
   operation shown in bold; run each as the adapter writes it.
4. Read [references/ticket-labels.md](references/ticket-labels.md) for the judgment behind
   each label, and [references/model-selection.md](references/model-selection.md) for the
   tiers. When `registry.py show` prints a `batching` `mode` other than `off`, read
   [references/batches.md](references/batches.md) too.

## 1. Resolve the repo

`--repo`, or infer it from the description: a repo name from the registry's Repos table, a
file path, a product name, a symbol you can find with one search. **If it is not exactly one
repo, ask.** A ticket in the wrong repo aims the worker's closing keyword at the wrong tracker.
Read that repo's product brief from the registry; you need its audience.

## 2. Prove the premise before writing

Check in the repo's local clone with read-only commands, and run what proves a claim:

1. **Already built?** Search for the symbol, flag, route or config key; run the test file if
   there is one.
2. **Superseded?** Read the repo's `AGENTS.md`, README and decision records. A ticket against
   a deleted subsystem, a paused platform or a reversed decision is dead on filing.
3. **Already ticketed?** **search-issues** on the keywords, and **list-items** for board items
   on the same repo.
4. **Window passed?** A ticket tied to a date, campaign or season behind us is a decision about
   whether to bother: say so and file nothing.

**If the premise fails, stop and say so**, with the evidence: "this is already built, here is
the test that proves it" is the most valuable result this skill has.

## 3. Write it

Fill [assets/ticket-template.md](assets/ticket-template.md), every section in order, into a
temporary file (`mktemp`). Sections 1 to 3 and 5 of the Agent Instructions are boilerplate:
copy them exactly. In section 4's first bullet use the audience from the repo's brief.

- Write no dependency in the body. A dependency is a native blocked-by link: once the issue
  exists, link each one with **add-blocker** (step 4's **Blocked:**), checked first by
  plan-one-ticket.md, "Before linking a dependency".
- Omit Out of scope only when there is genuinely nothing a reader would include.
- **Never invent a concrete detail**: a price, a filename, an error string, a date, a metric, a
  version. Every specific is one you read. For a fact you do not have, write
  `- [ ] TBD: <the question>` and say so in the report.
- Split the ticket when the acceptance list runs past about seven bullets or the work spans
  more than two repos. Split it too when one ticket would change the database schema, the API
  and the UI together: one worker run cannot hold that much, and tickets of that size have
  ended with nothing committed. Cut by layer, one ticket each, and chain them with
  blocked-by links (**add-blocker**) once they are filed.

Then run `python3 "${CODEX_HOME:-~/.codex}/skills/write-ticket/scripts/check_ticket.py" <the file>`.
It prints the problems (a placeholder left in, edited boilerplate, a dependency written as a
body line, too many acceptance bullets) and exits 1 when there are any. Fix them and run it
again until it exits 0.

## 4. Assign the labels, priority and lane

- **Priority:** one role from the registry's Priority table, judged by its Meaning column.
- **Run label:** exactly one. The run-worker label when there is code or config a worker can
  build and prove, even if the last step is a live action no worker can take; the run-solo
  label only when there is nothing to build at all.
- **Model label:** the tier by difficulty, never urgency, `workhorse` when in doubt, written as
  the label the registry's Model labels table maps that tier to. Name the model the tier runs
  on today with `python3 "${CODEX_HOME:-~/.codex}/skills/write-ticket/scripts/resolve_model.py" <tier>`
  in the report; if it exits 3, say the account has none for that tier.
- **Other labels:** `project:<repo>`, and the repo's existing area labels (`web`, `bug`, ...)
  from **list-labels**. Never invent an area label.
- **Lane:** the backlog lane. Ready means planned, so `--ready` never files straight into the
  ready lane: step 5's **Plan it** moves the ticket there once it has a `### Final Plan`.
- **Assignee:** only with `--assignee`; `me` is **current-user**. Otherwise leave the ticket
  unassigned.
- **Blocked:** a dependency is a blocked-by link (**add-blocker**), never a `Depends on:` line
  in the body. When the ticket waits on an open issue (**issue-state**), link it, then the
  ticket gets the registry's blocked label and a `Blocked: dependency` comment naming each
  linked issue (shape in ticket-labels.md), and goes to the blocked lane: the label and the
  lane always agree. Link the issue that does the work, never a tracker, batch parent or
  review (a review's issue instead), and never one whose own blockers lead back here
  (plan-one-ticket.md, "Before linking a dependency").
  `$daily-grooming` frees it when the last dependency closes.

## 5. File it

`--dry-run` prints the ticket, its labels, lane and assignee and stops; read-only operations
are fine, nothing is created. Filing is this skill's whole job, and the person who typed the
command or asked for a ticket in chat has asked for it, so file without a further confirmation.

1. **ensure-label** for each label that may be missing (run, model, `project:<repo>`, blocked),
   with the registry's color and description for its own rows and the ones ticket-labels.md
   gives for `project:<repo>` ("Label colors and descriptions"). Area labels are never created.
2. **create-issue** with the title, body file and labels (this also adds it to the board).
3. **set-priority**, then **set-lane** (the blocked lane when the ticket is blocked). When
   it is blocked, **comment** with the `Blocked: dependency` comment.
4. **assign** when `--assignee` was given.
5. **Join a batch**, when batching is on and this is a new ticket (not `--ticket`): run
   **list-parents** for the repo and **attach-child** to an open parent that fits it, as
   batches.md says ("Joining a batch"; never create a parent). A ticket that joins belongs in
   the backlog lane even with `--ready`, since its parent's plan does not cover it yet:
   **set-lane** it there. No parent fits: it stays single until the next grooming pass.
   `--dry-run` names the parent it would join.
6. **Plan it**, only with `--ready` and only for a ticket that stayed single. Run
   [references/plan-one-ticket.md](references/plan-one-ticket.md) on the new ticket, on the
   `frontier` tier whatever the session's model: resolve
   `python3 "${CODEX_HOME:-~/.codex}/skills/write-ticket/scripts/resolve_model.py" frontier --effort medium`;
   when this session already runs on the printed `model`, read the file in full and follow it
   inline; otherwise, or when you cannot tell, spawn one planning subagent (the built-in
   `default` agent) with that model and reasoning effort, give it the ticket, the dry-run
   flag, the registry JSON, the adapter file's path and the path
   `${CODEX_HOME:-~/.codex}/skills/plan-ticket/references/plan-one-ticket.md`, and wait for
   its one line. A refused spawn (thread limit, multi-agent off) means planning inline and
   saying so. The procedure's step 4 moves the ticket from the backlog lane to the ready lane
   once its `### Final Plan` is posted. When it returns `held` or `could not plan`, the ticket
   stays in the backlog lane and the report says why. `--dry-run` passes the dry run through,
   so the plan is printed and nothing is posted.

`--ticket N`: run **read-issue** first and keep the old body. Stop and say so if the issue is
closed or its lane is in progress or done (find the lane with **list-items**). Otherwise
**edit-issue** with the new body, **remove-label** any run or model label that no longer
applies, add the new ones as in step 1, run **add-to-board** if it is not on the board, then
**set-priority** and **set-lane**, and the blocked label and comment if a dependency is still
open and the issue does not already carry both. Existing assignees stay unless `--assignee` was
given.

Finish every step above before you report. If a write fails, say which one and what is left
undone; never report a ticket as filed that is missing its labels, priority or lane. Delete the
temporary body file when you are done.

## 6. Report

In plain language, outcome first. If step 2 stopped the work, lead with that finding and its
evidence (already built, already ticketed, superseded, window passed). Otherwise lead with the
URL and title, then each assignment with a clause of reasoning, the assumptions you made, and
any `TBD:` bullets. If step 2 found something short of a stop, such as a related ticket, add
it. For `--ticket`, say what the old body held so nothing is lost silently. With batching on,
say which parent it joined, or that it stayed single. With `--ready`, give the planning
result line, the lane the ticket ended in, and the model the plan ran on when it was not the
frontier tier's. When the ticket is unassigned, say that `$work-tickets` will not pick it up
until someone is assigned.
