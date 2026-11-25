# Plan one ticket

The one procedure for writing a ticket's plan, shared by `$plan-ticket` (one ticket) and
`$daily-grooming` (every unplanned Ready ticket, possibly through subagents). Keep it
here and nowhere else.

A worker reads the plan before it builds, checks it for drift, and re-plans only when
it has drifted. So the plan is a short brief for the worker: a
short plan that is 80% right and gets re-checked at build time beats a long one that
is stale by next week.

**Inputs.** The ticket (its repo's Remote and number), and whether this is a dry run.
Optional: `--context FILE`. The registry and the tracker adapter file for the
registry's tracker are already read; if you were handed this file in a subagent
brief, read both before the first step. Tracker actions are the named operations in
bold; run them as the adapter file writes them.

## 1. Load the context, lean

1. **read-issue** for the ticket: title, body, labels, comments, state.
2. Stop, and return `could not plan: <reason>`, when the issue is closed or carries
   the registry's blocked label. Nothing is written.
3. The owning repo and its brief come from the registry's "Resolving a ticket to its
   repo" and "Resolving a ticket's product brief". An explicit `--context FILE`
   replaces the brief. A brief missing on disk: plan without it and say so in your
   result. A repo with no local clone on this machine: stop with
   `could not plan: no local clone of <repo>`.
4. Read, in the repo's local clone and with read-only commands only:
   - the brief, end to end (it is the source of truth);
   - the top of the repo's dependency manifest (`package.json`, `pyproject.toml`,
     `requirements.txt`, `go.mod`, `Cargo.toml`: whichever exists);
   - **one** targeted search for the primary symbol or file the ticket names.

   That is all. Do not survey the repo, and do not research other tickets.
5. For each issue the body names on a `Depends on:`, `Blocked by:` or `Blocked on:` line,
   run **issue-state**, and check each open one by step 2's "Before naming a dependency".

## 2. Hold it instead, when there is nothing sound to plan

**Before naming a dependency.** A hold that waits on something that waits on it never clears,
so check every issue before it goes on a `Depends on:` line or in a `Blocked: dependency`
comment, whether this ticket's body named it or the plan adds it:

1. **read-issue** it and each open issue on its own `Depends on:`, `Blocked by:` or `Blocked
   on:` lines, two levels down. A chain that leads back to this ticket, or to a ticket this
   one was cut from, is a cycle: do not name that issue. Name the one link in the chain that
   does the work this ticket needs, or hold with kind `decision` when none does, and say which
   chain it was.
2. **A tracker or a batch parent closes last**, so never name one. An issue is a tracker when
   it was cut into parts (its parts' bodies say `Part <N> of <M>` and name it) and a batch
   parent when it lists other tickets as its children. Name the open part or child whose work
   this ticket needs instead.
3. **Work already merged frees nothing.** Run **merged-reviews** on each open issue. One that
   prints a review has its work on the default branch (a review that only said `Refs` leaves
   its issue open): do not name it, and say in the returned line that it may be ready to close.

On a grooming pass, `scripts/deps.py` (relative to this skill folder; its docstring holds the
input) does all three for the whole board at once; use its report rather than reading the
chains again.

**Cutting a ticket into parts.** When a person accepts a cut (or asks for one) and the parts
are filed, each part's body opens with `Part <N> of <M>, cut by layer from <ref>`, so
`deps.py` and the next planner see the family. In the same step, run **list-open-issues** and
read each body for the cut ticket's ref, and re-point every open ticket that names it on a
`Depends on:` line, or in the latest `Blocked: dependency` comment, to the specific part it
needs (**edit-issue** the line, then **comment** the change). A part never names the ticket it
was cut from.

Do not write a plan, and hold the ticket, in two cases:

- **A dependency is still open** (step 1.5) and passes "Before naming a dependency" above:
  kind `dependency`, naming each open issue.
- **The ticket is too vague to plan.** A section would need more than a paragraph, or
  you cannot state what done looks like. Expanding the plan is the wrong response:
  kind `decision`, listing the missing facts as questions, each with your recommended
  answer.

Holding follows [ticket-labels.md](ticket-labels.md), "Blocked": **ensure-label** and
**add-label** for the registry's blocked label, then **comment** in the `Blocked:` shape,
then **set-lane** with role `blocked` from whatever lane it sits in. The label and the
blocked lane always agree: a held ticket never waits in the backlog or ready lane. Return
`held: <kind>`. In a dry run, print what you would post and write nothing.

## 3. Write the plan, one pass

About 200 words and about five minutes of work. One paragraph per section at most:

- **Files to touch**: concrete paths, in each affected repo.
- **Pattern to reuse**: the existing file or function the work should mirror.
- **Acceptance**: the one or two checks that mean done.
- **Blockers / dependencies**: only if real and current.
- **Watch out for**: only the non-obvious traps.

The comment starts with the heading `### Final Plan` on a line of its own, exactly,
because workers look for that heading. When the ticket already has a `### Final Plan`
comment (you were asked to re-plan it), put one line under the heading first:
`_Re-planned YYYY-MM-DD: <reason>_`, using today's date.

**Forbidden:**

- iteration loops or an iterations footer ("Iterations: 2, round 1 added X");
- tradeoff tables;
- risk registers;
- "cross-ticket coordination" sections that re-list other tickets;
- restating the brief: link to it.

A fourth section, a table or a third paragraph in one section means stop and cut. If
the plan will not fit in 200 words, the ticket is too vague: go to step 2.

## 4. Post it and set the labels

In a dry run, print the plan and the labels below, run no write operation, and
return.

1. **comment** with the plan. Keep the comment's URL if the operation printed one.
2. **Model label.** Judge the tier from the plan you just wrote: its files, its traps.
   [ticket-labels.md](ticket-labels.md), "Model label", holds the rubric, and the
   registry's Model labels table gives the label for the tier. A model label already
   on the ticket stays as it is, in any form the registry resolves, and so does a
   ticket that has several (report that; do not pick). Otherwise **ensure-label**,
   then **add-label**.
3. **Run label.** Judge it from the acceptance criteria you just wrote, per
   [ticket-labels.md](ticket-labels.md), "Run label". None on the ticket: **ensure-label**
   and **add-label** the right one. The wrong one: **remove-label** it and add the
   right one. Both on the ticket: a contradiction only a person can settle, so report
   it and change nothing.

**ensure-label** can lose a race when several planners run at once. A failure to
create a label that now exists is success: run it again to confirm, and carry on.

## 5. Return one line

```text
planned <repo>#<n>: <model label>, <run label>, <comment URL, when printed>, <word count> words
replanned <repo>#<n>: <same fields>
held <repo>#<n>: <kind>: <what it waits on>
could not plan <repo>#<n>: <reason>
```

The caller reads this line and nothing else; it does not need the plan text back.

## Labels only, when the plan already exists

`$daily-grooming` also uses this procedure on a Ready ticket that already has a
`### Final Plan` comment but lacks a model or run label, since `$work-tickets` will not
dispatch it that way. Do step 4's labels (2 and 3) judging from the existing plan,
post nothing, and return `labelled <repo>#<n>: <labels added>`.
