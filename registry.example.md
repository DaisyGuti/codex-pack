# Ticket registry

This is your copy of the ticket registry, `registry.md` in the pack root. `install.sh` (or
the first `registry.py ensure` a ticket skill runs) created it from the pack's
`registry.example.md`, and the ticket skills read it on every run. It is untracked and one
per machine, so pulling a pack update never overwrites it. Keep `registry.example.md`
generic.

Fill in the rows below for your tracker. Every value is exact and case-sensitive: a lane or a
priority has to match the name the tracker shows. The skills read only the tables and the
`Key: value` lines; the prose is for you. The rules for reading it (a pasted board URL, which
repo a ticket belongs to, which brief to plan against) are in the pack's
`references/registry-rules.md`.

**A repo missing from the Repos table is invisible.** Its tickets are skipped with the
reason "no repo could be inferred" and named in the run summary. That is the intended
failure: loud, and never a guess.

**The person running a command is whoever is signed in to the tracker CLI on this
machine.** `$work-tickets` and `$ticket-worker` touch only tickets assigned to that
person.

## Tracker

- Tracker: `github`
- Host: `github.com`

`Tracker` is `github` or `gitlab`. `Host` is `github.com` or `gitlab.com`, or the host of
a GitHub Enterprise or self-managed GitLab server.

Optional: add ``- Works for: `your-login` `` to pin whose tickets `$work-tickets` and
`$ticket-worker` may work. Without it they work for whoever is signed in to the tracker CLI;
with it they halt when the CLI is signed in as anyone else, so a switched account
(`gh auth switch`, a second `glab` login) never works another person's tickets.

## Board

The default board, used when no `--project` or `--owner` is passed. Fill in the subsection
for your tracker and leave the other as it is.

### GitHub

A GitHub Projects (v2) board. The owner is a user or organization login.

- Owner: `your-github-login`
- Number: `1`
- Name: Engineering

### GitLab

An issue board. Its lists are either labels or the native work item Status.

- Scope: `group`
- Path: `your-group`
- Board: `Development`
- Lanes: `labels`

`Scope` is `group` or `project`. `Path` is the group or project path the board belongs
to. `Board` is the board's name or its numeric id. `Lanes` is `labels` when the board's
lists are labels (`status::ready`), or `status` when they are the work item Status
(Backlog, Ready, In progress and so on; a Premium or Ultimate feature). Without the line
the skills use `labels`.

## Lanes

Each lane as the tracker shows it: on GitHub a Status option name; on GitLab a label,
usually scoped (`status::ready`), or with `Lanes: status` the Status name (`Ready`). A
lane whose value is missing from the board is skipped with a warning when a ticket
moves, and a missing `ready` lane stops a run.

The `review` lane is optional: delete its row if the board has no such lane. A worker
that opens a review (every change lands by one) then leaves the card in `in_progress`.
A worker never moves a card to `done`: merging closes the issue and `$daily-grooming`
moves the card. Every other lane is required.

| Role | GitHub (Status option) | GitLab (label, or Status name) | Meaning |
| --- | --- | --- | --- |
| backlog | `Backlog` | `status::backlog` | Filed, not yet queued; where `$write-ticket` files by default |
| ready | `Ready` | `status::ready` | Groomed and queued; the only lane `$work-tickets` works |
| in_progress | `In progress` | `status::in-progress` | A worker has started |
| blocked | `Blocked` | `status::blocked` | Held; the issue's latest `Blocked:` comment says on what |
| review | `In review` | `status::in-review` | Optional. Work is built and a review is open; merging it closes the issue |
| done | `Done` | `status::done` | Shipped and closed |

## Priority

Each priority as the tracker shows it: on GitHub a Priority option name, on GitLab a
label. A GitHub board with no Priority field, or one with no options, carries priority
as a label instead: the GitHub value below is then the label's name (`P1`), and the
skills read and set that label. Row order is rank, highest first. `--priority P1` names
a role.

| Role | GitHub (Priority option) | GitLab (label) | Meaning |
| --- | --- | --- | --- |
| P0 | `P0` | `priority::0` | Active blocker; nothing ships until it is resolved |
| P1 | `P1` | `priority::1` | On the launch path or blocking infrastructure |
| P2 | `P2` | `priority::2` | Important; same release or shortly after |
| P3 | `P3` | `priority::3` | Nice to have, post-MVP, or deferred |

## Labels

| Role | Label | Color | Description |
| --- | --- | --- | --- |
| blocked | `blocked` | `b60205` | Held: a comment says what it is waiting for |
| run_worker | `run:worker` | `0e8a16` | A worker can finish this end to end |
| run_solo | `run:solo` | `fbca04` | Nothing to build; a person does the whole ticket |

Color and description are used only when a repo lacks the label and a skill creates it.
The name is what the skills match. Claude Code's ticket workers read the same run label
names on a shared board, so leave them alone while both are in use. Labels used without a
row here: `effort:<level>` (optional), `repo:<name>`, `project:<name>`, and `bug` (a
worker's commit then says `Fixes`).

## Model labels

The label that picks a ticket's worker model, one per tier. `$work-tickets` reads
whichever label here maps to a tier, and `$write-ticket` writes the mapped label. A tier
becomes a model and reasoning effort only through the pack's `resolve_model.py`, so no
model name is written here.

| Tier | Label | Color | Weight |
| --- | --- | --- | --- |
| fast | `model:fast` | `ededed` | 1 |
| workhorse | `model:workhorse` | `ededed` | 3 |
| frontier | `model:frontier` | `ededed` | 5 |

Weight is optional. When a tier has one, planning sets the issue's weight to it together with
the model label, so a milestone's burndown counts planned size. On GitLab it is the issue
weight. On GitHub it is a number issue field named `Weight` defined by the repo's owner, or,
without one, a number field named `Weight` on the board. Leave the column out to set no weight.

The labels `model:haiku`, `model:sonnet`, `model:opus` and the dated
`model:claude-haiku-*`, `model:claude-sonnet-*`, `model:claude-opus-*` forms resolve to
`fast`, `workhorse` and `frontier` when a ticket carries one the table does not list. A
board shared with Claude Code's ticket workers, which read only the `model:haiku`,
`model:sonnet` and `model:opus` forms, maps its tiers to those instead.

## Batches

A batch is one parent with a few child tickets that ship together: one worker, one
branch, one pull or merge request. It keeps the board from filling with small tickets
that each need their own review and CI run. `$daily-grooming` forms batches, and the plan
lives on the parent. The rules are in the pack's `references/batches.md`.

- Batching: `off`
- Batch size: `5`

`Batching` is `off` (every ticket is worked alone; the default without this section),
`epics` (GitLab: a group epic in the board's group is the parent), `sub-issues` (GitHub:
an issue whose sub-issues are the children) or `labels` (either tracker: the tickets
sharing a `batch:<area>` label, led by a parent issue titled `Batch: <area>`). In every mode
a batch parent's title starts with `Batch: `; other parents are left out of batching.
`Batch size` is the most children one parent holds.

## Repos

| Name | Remote | Local clone | Product brief | Focus |
| --- | --- | --- | --- | --- |
| `my-app` | `your-github-login/my-app` | `~/code/my-app` | `~/code/my-app/README.md` | active |

- **Remote** is `owner/repo` on GitHub and the project path
  (`group/subgroup/project`) on GitLab.
- **Local clone** is the primary clone. Workers never edit, check out or commit in it;
  they work in worktrees made from it.
- **Product brief** is the file a worker reads as the source of truth when it checks a
  ticket's plan. Repos that are components of one product may point at the same brief.
- **Focus** is `active`, `parked` or `unclassified`, the team's ruling on where
  attention goes. The skills read the other four columns and leave Focus to you.

Add a repo here before its tickets reach the board. Deadlines, release dates and other
facts that move are read at run time from the repos and their issues.
