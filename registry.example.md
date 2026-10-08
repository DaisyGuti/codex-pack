# The ticket registry

This is the template for the machine's registry. The installer copies it to
`registry.md` in the pack root (untracked, one per machine) when none exists; edit
that copy, and keep this one generic. The `ticket-worker`, `work-tickets` and
`write-ticket` skills read the registry through their `references/registry.md` links.

**One list.** Every ticket command reads this file for the tracker, the board, its
lanes, its labels and the repo set. None of them keeps its own copy of any of these or
takes a hardcoded scope list. A change to scope is a change here and nowhere else.

**A repo missing from the table is invisible.** Its tickets are skipped with
`reason="no repo could be inferred"` and named in the run summary. That is the
intended failure: loud, never a guess.

Priority, run and model labels, and how a ticket is held, follow
[references/ticket-labels.md](references/ticket-labels.md); this file holds only the
names the tracker sees.

**The person running a command is whoever is signed in to the tracker CLI on this
machine.** The commands that work tickets (`$work-tickets`, `$ticket-worker`) touch
only tickets assigned to that person.

A registry written before trackers existed has no Tracker section; read it as a
GitHub registry. A missing Model labels table means its defaults.

## Tracker

- Tracker: `github` (`github` or `gitlab`)
- Host: `github.com` (a self-managed GitLab such as `gitlab.example.com`, or a GitHub
  Enterprise host, goes here)

The ticket commands run the tracker's operations from one adapter file, read only for
the tracker named here: `references/trackers/github.md` or
`references/trackers/gitlab.md`.

## Board

The default board, used when no `--project` or `--owner` is passed. Fill in the block
for the tracker above and ignore the other.

GitHub (a Projects v2 board):

- Owner: `your-github-login`
- Number: `1`
- Name: Engineering

GitLab (an issue board, which is a set of label lists):

- Scope: `group` (`group` or `project`)
- Path: `your-group` (the group or project path the board belongs to)
- Board: `Development` (the board's name, or its numeric id)

## Lanes

Each lane as the tracker sees it: on GitHub a Status option name, on GitLab a label,
typically scoped (`status::ready`). Exact and case-sensitive. A lane whose value is
missing from the board is skipped with a warning when a ticket moves, and `ready`
missing stops a run. Only the column for the tracker above is read.

The `review` lane is optional: delete its row if the board has no such lane. A worker
that opens a review (every change lands by one) then leaves the card in `in_progress`
instead of moving it. A worker never moves a card to `done`: merging closes the issue and
`$daily-grooming` moves it. The other lanes are required as before.

| Role | GitHub (Status option) | GitLab (label) | Meaning |
| --- | --- | --- | --- |
| backlog | `Backlog` | `status::backlog` | Filed, not yet queued; where `$write-ticket` files by default |
| ready | `Ready` | `status::ready` | Groomed and queued; the only lane a run works |
| in_progress | `In progress` | `status::in-progress` | A worker has started |
| blocked | `Blocked` | `status::blocked` | Held; the issue's latest `Blocked:` comment says on what |
| review | `In review` | `status::in-review` | Optional. Work is built and a review is open; merging it closes the issue |
| done | `Done` | `status::done` | Shipped and closed |

## Priority

Each priority as the tracker sees it: on GitHub a Priority option name, on GitLab a
label. The row order is the rank, highest first. `--priority P1` names a role.

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

- **blocked** is the one way a ticket or a review is held, on its own or on a review
  that must not merge yet. It always comes with a comment saying what it is blocked
  on; [references/ticket-labels.md](references/ticket-labels.md) has the comment's shape
  and the four kinds. Merge automation on the machine should refuse a review carrying
  it. No label names a person. A review that is only waiting for its reviewer is not
  held and never carries it.
- **run_worker** and **run_solo** are the pair every ticket carries exactly one of;
  ticket-labels.md says which to choose. Claude Code's workers read the same two names
  on a shared board, so leave them alone while both are in use.
- Color and description are used only when a repo lacks the label and a command
  creates it; the name is what matters.
- Labels the ticket commands use without a row here: `effort:<level>` (optional),
  `repo:<name>`, `project:<name>`, and `bug` (a worker's commit then says `Fixes`).

## Model labels

The label that picks a ticket's worker model, one per tier. `$work-tickets` reads
whichever label here maps to a tier; `$write-ticket` writes the mapped label. The
defaults are tier names. A board shared with Claude Code's workers, which only
understand `model:haiku`, `model:sonnet` and `model:opus`, maps its tiers to those
instead.

| Tier | Label | Color |
| --- | --- | --- |
| fast | `model:fast` | `ededed` |
| workhorse | `model:workhorse` | `ededed` |
| frontier | `model:frontier` | `ededed` |

`model:haiku`, `model:sonnet`, `model:opus` and the older `model:claude-haiku-*`,
`model:claude-sonnet-*`, `model:claude-opus-*` forms still resolve to `fast`,
`workhorse` and `frontier` when a ticket carries one the table does not list, so
tickets labelled before this table existed keep working.

## Repos

| Name | Remote | Local clone | Product brief | Focus |
| --- | --- | --- | --- | --- |
| `my-app` | `your-github-login/my-app` | `~/code/my-app` | `~/code/my-app/README.md` | active |

- **Remote** is `owner/repo` on GitHub and the project path
  (`group/subgroup/project`) on GitLab.
- **Local clone** is the primary clone. Workers never edit, check out or commit in
  it; they work in worktrees made from it.
- **Product brief** is the file a worker reads as the source of truth when it
  validates a ticket's plan. Repos that are components of one product may point at
  the same brief.
- **Focus** is `active`, `parked` or `unclassified`, the team's ruling on where
  attention goes. The ticket commands read the other four columns and leave Focus to
  you and to any prioritising you do by hand.

## Resolving a project board argument

Every ticket command takes one optional positional argument alongside its
`--project N` / `--owner OWNER` flags. On GitHub they are the board's number and
owner. On GitLab `--owner` is the group or project path and `--project` is the board's
numeric id. Two shapes reach the argument, and both resolve here:

- **Empty.** The normal invocation: the default board above and every repo in the
  table.
- **A pasted board URL.** Parse the owner or path and the board and treat the result
  exactly as if `--project` and `--owner` had been typed. This narrows the run to that
  single board. Recognized shapes, matched through the board number or id:
  - GitHub: `https://github.com/users/<owner>/projects/<N>` and
    `https://github.com/orgs/<owner>/projects/<N>`, either followed by `/views/<V>`
    (the view suffix is ignored, because dispatch works on the whole
    board). A GitHub Enterprise host takes the same paths.
  - GitLab group board: `https://<host>/groups/<group path>/-/boards/<id>`
  - GitLab project board: `https://<host>/<project path>/-/boards/<id>`
    Anything after the id (a query string such as `?label_name[]=...`) is ignored.

  The host in a URL must equal the Tracker section's host; a mismatch stops the run
  and says so.

Other flags present (`--dry-run`, `--priority P1`, and so on) apply as written.
When the resolved board equals the default board, the URL changes nothing: say so in
the run's output so it does not look like the scope narrowed.

## Resolving a ticket to its repo

Use these rules in order; the first match wins.

1. **Parent repo.** The board item's `repo` (the Remote form; the name is the last
   part of the path). It is the repo the issue lives in and is correct for nearly
   every ticket.
2. **Explicit label.** A `repo:<name>` label naming a table row.
3. **Project label.** A `project:<name>` label naming a table row.
4. **Body keyword scan.** A case-insensitive search of the ticket body for each
   table name; every hit is a target repo.
5. **No match.** Do not guess. Skip the ticket with
   `reason="no repo could be inferred"` and surface it in the run summary.

A ticket may resolve to several repos. The repo it lives in (rule 1) is the
**owning repo**: labels, plan comments and the auto-close keyword go there.

## Resolving a ticket's product brief

Look up the owning repo in the table and read its brief. Never pass one board-wide
`--context` on a board that spans several products: a ticket planned against
another product's brief is worse than one planned against none. An explicit
`--context FILE` still wins, for single-product runs where one brief covers the
whole board.

## Keeping this file true

Add a repo here before its tickets reach the board. Deadlines, release dates and
anything else that moves are read at runtime from the repos and their issues, and
are never copied into this file, where they go stale the day they change.
