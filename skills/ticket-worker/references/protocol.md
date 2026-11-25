# Ticket worker protocol

One worker, one ticket, one run: plan, implement, test, commit on a branch, push the
branch, open a review into the default branch, and move the board card to review. Every
change lands by review. The worker never closes the issue: merging the review does. A
**review** is a pull request on GitHub and a merge request on GitLab. A dispatch message
that names a batch (a `parent` and its `children`) is one run too: the children in order,
one branch, one review (section 11).

Every run starts from a **dispatch message** (section 1): `$work-tickets` sends one to each
`ticket_worker` it spawns, and the `$ticket-worker` skill builds one for a direct request
and either hands it to a `ticket_worker` or follows this protocol with it in its own
session. If the message is missing, is not that JSON, or lacks an issue number, a repo or
an `assignee`, stop before touching the board and say which piece is missing. Do not hand
the ticket to another `ticket_worker`: the ticket, its design and its result stay yours.
The agents you start are sub-workers for parts of the change (section 6, **Split the
work**) and the read-only `reviewer` (section 7).

The standing rules:

- Run without pausing. Stop only for the three cases in section 4: a blocker, a decision
  point, or manual-action-complete. Make reasonable assumptions on routine choices.
- Work only tickets assigned to `assignee`. Never commit or push to the default branch,
  never merge, never close the issue, and never move a card to `done`.
- Your model is the one you were spawned on (or the session's, in a direct run worked in
  place). Name it in your report and never switch it mid-run.
- Comments you post on the tracker are read by people: short, plain language, and a
  concrete next step whenever you stop.
- Take every path from the dispatch message and never rebuild one. Work only in your own
  worktrees; a primary clone gets only the git commands section 3 lists.
- Never write the run record: `$work-tickets` records your `RESULT` line (section 10).

Codex behavior this protocol leans on (worktrees, sandbox, spawns, review) is in
[codex-ticket-notes.md](codex-ticket-notes.md).

## Contents

- 1. The dispatch message
- 2. Preflight and the assignment check
- 3. Where you work
- 4. Running, stopping and the board
- 5. Plan
- 6. Implement and test
- 7. Land the work
- 8. After the review opens
- 9. Needs manual action
- 10. Final report
- 11. Working a batch

## 1. The dispatch message

```json
{
  "mode": "dispatched",
  "slot_id": "slot-1",
  "ticket_number": 182,
  "ticket_repo": "shop-app",
  "repos": ["shop-app"],
  "item_ref": "<board item handle, null where the tracker needs none>",
  "assignee": "<login of the person this run works for>",
  "project": {
    "tracker": "github", "host": "github.com", "board": {},
    "tracker_ids": {}, "lanes": {}, "priorities": {}, "labels": {}, "model_labels": {}
  },
  "repo_map": { "shop-app": { "clone": "/abs/clone", "remote": "owner/shop-app", "brief": "/abs/README.md" } },
  "worktree_root": "/abs/state/ready-worktrees/<board key>-<login>",
  "worktree_paths": { "shop-app": "/abs/state/ready-worktrees/<board key>-<login>/slot-1/shop-app" },
  "files": {
    "adapter": "/abs/references/trackers/<tracker>.md",
    "labels": "/abs/references/ticket-labels.md",
    "ticket_template": "/abs/skills/write-ticket/assets/ticket-template.md",
    "check_ticket": "/abs/scripts/check_ticket.py"
  },
  "model": "<model slug you were spawned on>",
  "validate_plan_first": true,
  "context_files": ["/abs/brief.md"],
  "large_guides": ["backend/AGENTS.md"]
}
```

`mode` is `dispatched` (from `$work-tickets`) or `direct` (from `$ticket-worker`, one issue
the user named); a direct run uses `slot_id` `solo`. `project` carries the tracker, host,
board, `tracker_ids` (what **capture-board** returned), the lane and priority values by
role, the labels by role and the model labels by tier. `files.ticket_template` and
`files.check_ticket` are what section 7 uses to file follow-up tickets. There are no
fallback defaults: if any of it is missing, stop with `status=blocked_state_incomplete`,
`reason="the dispatch message is incomplete"`. `ticket_repo` is the owning repo; `repos`
lists every repo the ticket touches, owning repo first. `model` is informational.

`worktree_root` is the folder for this run's worktrees: `$STATE_ROOT/ready-worktrees/<board
key>-<login>` for a dispatched slot, `$STATE_ROOT/solo-worktrees/<repo>-<issue>` for a
direct run (`STATE_ROOT` is `${CODEX_HOME:-~/.codex}/state`). `worktree_paths` is optional:
the worktree the dispatcher already made for a repo, at `<worktree_root>/<slot_id>/<repo>`.
Codex has no worktree isolation of its own, so section 3 makes any worktree the message does
not name.

The rest is optional. `large_guides`: instruction files (repo paths) that `$work-tickets`
measured over the context budget for this slot; never read one whole, `grep` it for the
section the plan needs and read only that part. `resume_worktrees`: a map from repo to the
worktree of an earlier `blocked_sandbox` stop on a locked signing key (section 7); section 3
says how a run with it starts. `resumed`: `true` when the slot is dispatched again under the
`slot_id` it had before (an unfinished slot, or a resume after a locked signing key).
`parent` and `children` are present only for a batch (section 11): `parent` is `{"ref",
"number", "repo", "title", "area", "url"}` and `children` the children to work, in order,
each `{"ticket_number", "ticket_repo", "item_ref"}`, the first of them also named by
`ticket_number` and `ticket_repo`; a batch also carries `files.batches`, the pack's batch
rules. A single has none of the three.

**Tracker operations.** Every action on the tracker below is a named operation, shown in
bold (**set-lane**, **comment**, ...). Read `files.adapter` in full before your first step
and run each operation as written there; never improvise a command for one. Read
`files.labels` section "Blocked" before your first step; it defines the label and the
comment shape used when a ticket is held. Waiting on an ordinary review is not a hold: a
review that only needs its reviewer never carries the blocked label.

## 2. Preflight and the assignment check

1. `test -w` the folder `worktree_root` (create it with `mkdir -p` when missing), and each
   path in `worktree_paths` and `resume_worktrees`.
2. **auth-check**, then `git -C <clone> fetch origin --prune` for the owning repo's clone.
   Together they prove network, credentials and a writable Git directory. A failure is
   `status=blocked_sandbox` naming the failed check and the fix: sign in, or relaunch Codex
   with full access, because the default `workspace-write` sandbox keeps every `.git`
   read-only and no commit can happen inside it. When the tracker itself cannot be reached,
   record the status, skip the holding steps in section 4 (they need the tracker) and say
   so in your report.
3. **read-issue**. Confirm its `assignees` include `assignee` (compare logins
   case-insensitively). If not, stop with `status=blocked_not_assigned`, `reason="issue is
   assigned to <logins, or nobody>; this run works for <assignee>"`. This stop touches
   nothing on the ticket: no comment, no label, no board move, because the ticket is not
   this run's to change.
4. Confirm with **issue-state** that the issue is open; a closed issue is
   `blocked_ticket_closed`. Repeat this check at the start of each later section, since
   the issue may close outside this run.

**Default branch.** Each repo's default branch is `<default_branch>` below. Resolve it per
repo: `git -C <clone> symbolic-ref --short refs/remotes/origin/HEAD` with the leading
`origin/` removed. If that fails, run `git -C <clone> remote set-head origin --auto` once
and read it again. If it is still unknown, stop with `status=blocked_default_branch_unknown`
naming the repo. Never assume `main`.

## 3. Where you work

Never touch a primary clone's files. The only commands you run against one are `fetch`,
`worktree add`, `worktree remove`, `worktree prune`, `symbolic-ref`, `remote set-head` and
`branch -D`.

The branch is `<slot_id>-ticket-<n>` in every repo (a batch: section 11). For each repo in
`repos`, set `WT` (its working path):

1. **The dispatcher made it.** `WT` is `worktree_paths[<repo>]`. It must pass `test -d`, and
   `git rev-parse --path-format=absolute --git-common-dir` must print the same path there as
   in `repo_map[<repo>].clone`; otherwise stop with `status=blocked_worktree_missing`. When
   it is not already on the branch, make it there with `git -C $WT switch -c <branch>`.
2. **Otherwise make it** at `<worktree_root>/<slot_id>/<repo>` from the repo's clone:

   ```bash
   git -C <clone> fetch origin --prune
   git -C <clone> worktree add <worktree_root>/<slot_id>/<repo> -b <branch> origin/<default_branch>
   ```

   A worktree left over from a cut-off run at that path goes through the safe cleanup in
   [codex-ticket-notes.md](codex-ticket-notes.md) first, never `--force`; its branch keeps
   its commits. When the cleanup keeps it, stop with `status=blocked_worktree_create_failed`
   naming the kept path and the check it failed.

If git refuses the branch name because a leftover worktree from a cut-off run holds it
locally, append `-r2` (then `-r3`) and use that name everywhere below; the `RESULT` line
reports the name you used.

When the branch already exists on `origin` (a run that was cut off after pushing), start
from it instead of the default branch (a batch: only when `resumed` is true; section 11).
For a worktree you make, use `git -C <clone> worktree add <path> -b <branch>
origin/<branch>`; for one the dispatcher made, run `git -C $WT fetch origin <branch>` and
`git -C $WT switch -C <branch> origin/<branch>`. Then continue from what is there: look at
`git log`, `git status` and **list-open-reviews** to see which steps already happened, and do
only the ones that did not.

Run every git command as `git -C $WT`. Record `git -C $WT rev-parse origin/<default_branch>`
before any destructive step so a rollback has a reference.

**Sync.** `git -C $WT fetch origin --prune`, then `git -C $WT status --porcelain`: a dirty
tree on a fresh start is `status=blocked_dirty_tree`, naming the repo and files. Never
`git checkout <default_branch>` in a worktree; it may be checked out elsewhere. When there
are no local commits yet and `origin/<default_branch>` has moved since the worktree was
made, run `git -C $WT merge --ff-only origin/<default_branch>`. Past that, the default
branch is merged in once, when the change is ready (section 6).

**Resuming after a locked signing key.** When the dispatch message has `resume_worktrees`,
`WT` for each repo in it is that path, which holds the staged change. Skip sections 5 and 6,
check that `git -C $WT status --porcelain` shows only that change, and continue at section
7's **Commit**: the pre-commit review and the gates already ran.

## 4. Running, stopping and the board

Every step continues without a pause. A run that opens a review (section 7) ends normally
at `review_opened`; that is a finished run. You stop in exactly three cases, each with a
desktop notification (on macOS `osascript -e 'display notification "<reason>" with title
"Codex Ticket Worker"'`, on Linux `notify-send`; if neither works, say so in the reason and
stop anyway):

- **Blocker.** `status=blocked_<type>` with a `reason` that names what you tried, the
  evidence, the blocker and what would clear it. Hold kind: `failure`.
- **Decision point.** The ticket is ambiguous, its requirements conflict, or it forces a
  choice between meaningfully different approaches the ticket cannot settle.
  `status=needs_decision`. Stop only when a wrong guess would force a rewrite; routine
  implementation choices are yours. Hold kind: `decision`.
- **Manual action complete.** The code is done and tested, but the ticket cannot close
  without one live action no worker can take: creating a real object in a paid provider's
  dashboard, entering a real credential, sending a genuine outreach message, or spending
  real money. The plan is unambiguous and its last step is not yours to take. Hold kind:
  `live action`. Follow section 9.

When you re-read or re-edit the same files without progress, stop with
`status=blocked_no_progress`, listing what you tried, what you observed and the input that
would unblock the ticket.

**Board moves.** A move is **set-lane** with a lane role, using `project.lanes[<role>]`.

| Checkpoint | Lane role |
| --- | --- |
| Preflight, assignment check and sync passed (the run has started) | `in_progress` |
| `review_opened` | `review`, when `project.lanes` has that role with a value; otherwise no move |
| any `blocked_*`, `needs_decision`, `needs_manual_action` | `blocked` |

You never move a card to `done`: the merge closes the issue and `$daily-grooming` settles
the card. All three stops share the one blocked lane; the comment's kind says which it is.
A stopped ticket never goes to `in_progress`. When a lane value is missing from the board,
**set-lane** skips the move: log a warning and carry on. An issue that is not on the board
skips every board move; say so in the report.

**Holding the ticket.** Every stop except `blocked_not_assigned` runs these on the owning
repo, in this order:

1. **ensure-label** for `project.labels.blocked` (name, color, description), then
   **add-label**.
2. **set-lane** with role `blocked`.
3. **comment** once, in the shape of the Blocked section of `files.labels`, with the kind
   from the stop: `failure` quotes the exact error and what you tried; `decision` lists the
   options, each with its consequence, and recommends one; `live action` is section 9's
   comment. It goes before any filing, so a blocked label never sits without its comment.
4. When the follow-up list (section 6) is not empty and the tracker is reachable, file the
   items as section 7's **Review** step 4 describes, under the same cap, ending Context with
   `Found in <repo>#<n> (no review opened).` in place of a review link. A resumed run starts
   from the ticket's comments and the branch, so an item already filed is found by the
   search there. Then **comment** once more, short: `Follow-ups:` with the number and title
   of each ticket filed, and any items over the cap as one list for a person to file.

Always include an "Unblocks when:" line.

**Item handle.** Use `item_ref` from the dispatch message. If it is missing where the
tracker needs one, or **set-lane** reports the item not found, re-resolve it with
**list-items** by `(number, repo)`.

## 5. Plan

Posted plans go stale when the brief changes, so validate before replanning.

1. **read-issue** and read every `context_files` path end to end (the brief is the source
   of truth), except a file named in `large_guides`: `grep` it and read the part you need.
2. Find the latest `### Final Plan` comment. None: go to step 4.
3. Check it for drift: the files and symbols it names still exist (`find` or `grep`); key
   facts (flags, counts, providers, routes, libraries) still match the ticket body and each
   context file; the brief or the ticket body was not edited after the plan was posted (an
   edit counts as drift even with no visible contradiction; **read-issue** gives the issue's
   `updated` time and each comment's `created` time).
   - **No drift:** keep the plan as the contract. Post nothing.
   - **Drift:** replan in step 4, opening with `_Re-validated YYYY-MM-DD: <one-line drift
     summary>_`.
4. One pass, about 200 words, one paragraph per section at most: **Files to touch**,
   **Pattern to reuse**, **Acceptance** (the one or two checks that mean done), **Blockers /
   dependencies** (only if real), **Watch out for** (only non-obvious traps). No iteration
   loops, tradeoff tables, risk registers or restated briefs. If a section needs more than a
   paragraph, the ticket is too vague: **comment** asking for tightening instead of
   expanding the plan, and stop as a decision point. Post the plan with **comment**, the
   `### Final Plan` heading first and no iterations footer.

A resumed run uses the branch's state and the latest `### Final Plan` comment as the
contract. With no plan anywhere, stop with `blocked_missing_plan`: "no plan found; run
$daily-grooming or $plan-ticket to write one".

## 6. Implement and test

Read the repo's `AGENTS.md` (in a repo with no `AGENTS.md`, its root `CLAUDE.md`) and
`CONTRIBUTING.md`, whichever exist, at the root of `WT`, and the rules files they point to,
except a file in `large_guides`, which you `grep`. Codex loaded the `AGENTS.md` chain of the
session's own folder, not of your worktree, so this read is required. Then read the pack's
engineering standards,
`${CODEX_HOME:-~/.codex}/skills/eng/references/engineering-standards.md`, in full: they bind
this section and section 7, and the repo's rules win on house style. If the standards file
is missing, say so in the report and continue. One rule in the repo's files does not apply:
a rule to commit or push to the default branch gives way to section 7.

**Review before writing.** Read the dependency manifest, find the existing patterns for
state, navigation, styling, networking, caching, payment, auth and storage, and build with
what is there. If a needed library is missing, name the best-in-class option (well
maintained, widely used, officially supported) in the plan so it is visible before
implementation.

**Design.** Reuse the repo's code style and UI. Improve a pattern only where it falls below
the standard the repo itself sets, judged from its README, brand or design docs and
existing screens. Never import an aesthetic or audience from another product.

**Split the work.** Once the plan holds and before you build, list the units the change
falls into. Send every unit that is self-contained, needs no other unit's output and is
clearly larger than the cost of briefing one (a Codex subagent starts with about 21-25K
tokens of context) to a sub-worker. Keep a unit inline when it is one search or one edit.
Design decisions, merging, the review and the result stay with you.

1. When units share an interface (a type, a schema, a function signature), write it
   yourself first and commit it as section 7's **Commit** says, with `Refs #<n>` in place of
   a closing keyword, so every sub-worker builds against it.
2. Give each unit its own worktree, never a primary clone and never your own tree:
   `git -C $WT worktree add <worktree_root>/<slot_id>/<repo>-<unit> -b <branch>-<unit> HEAD`,
   `<unit>` a short lowercase slug. A leftover worktree or branch of that name from a
   cut-off run is removed first (`git -C $WT worktree remove --force <path>`, `git -C $WT
   branch -D <branch>-<unit>`): it was never pushed or merged, so the unit is built again.
3. Spawn every sub-worker in one turn, then wait for all of them: the built-in `worker`
   agent, its tier and effort chosen per unit by
   [model-selection.md](model-selection.md) (mechanical writes `fast` / `high`, spec-driven
   code inside an existing seam `workhorse` / `medium`), resolved with
   `python3 "${CODEX_HOME:-~/.codex}/skills/ticket-worker/scripts/resolve_model.py" --all`,
   and both set explicitly on the spawn. Each brief holds resolved values only: the worktree
   path, the unit and what done means, the interface and the files it owns, the rules files
   you read above, and the rules it shares with you. It commits on its own branch with
   `Refs #<n>` and no attribution lines, signed whenever the repo's git config signs; names
   any scratch file after its unit and deletes it; runs only its unit's tests with a temp
   folder inside its worktree; and never pushes, merges, opens a review, touches the tracker
   or spawns an agent. It never turns signing off: a locked key ends its run with that
   report.
4. Read each summary and its diff before trusting either. A unit whose sub-worker failed or
   returned without a commit is built inline; a locked key stops the run as section 7's
   **A locked signing key** says. Commit your own inline work first, then bring each unit in
   with `git -C $WT merge --squash <branch>-<unit>` and commit it as in step 1, settling any
   conflict yourself. Then remove each sub-worker's worktree and branch (`git -C $WT
   worktree remove --force <path>`, `git -C $WT branch -D <branch>-<unit>`). The change is
   now committed, so section 7's pre-commit review runs on `git diff <base SHA>`, and the
   closing keyword goes only in the review body.

A spawn the thread cap refuses (`agents.max_concurrent_threads_per_session`), or any other
refused spawn, is built inline; never retry it in a loop. The `split` field of the result
(section 10) names each sub-worker and its model, or says why the work stayed inline.

**Quality bar.** Zero console errors or warnings; update setup and run scripts when the
change affects build or dev workflow; file-level doc comments on new files, inline comments
on complex logic, `TODO` markers where future work shows (each one you leave is a follow-up,
below). Run a docs pass: fix the docs the change makes stale (READMEs, ADRs, `AGENTS.md`
guides, docstrings and comments in the diff, and the README of the area the change lives
in, including new dependencies, endpoints or env vars and changed run instructions), in
plain English. Every new environment variable lands in the repo's committed example env file
(`.env.example` or its equivalent) in the same change, with a one-line comment, its default
and a placeholder, a secret by name only; list in the result the names you leave out and why.

**Follow-ups.** Keep a running list from here to the review of every known gap the change
leaves: a `TODO` left in code, a path you did not test, an assumption that needs confirming,
and a pre-existing problem you noticed along the way. Section 7 adds every review finding
you do not fix. Never widen the change to avoid a ticket: a problem outside this ticket's
scope is listed, not fixed. Each item on the list becomes a follow-up ticket once the review
is open (section 7), up to that section's per-run cap, and the rest are listed in the
ticket comment for a person to file; a note in the review body or the report does not count.
A run that stops before a review opens files them when it holds the ticket (section 4) and
links the ticket in place of a review.

**Tests.** Write or update tests for every change, each checking behavior the change adds or
fixes, in the repo's existing location, naming and framework. A test stays only when it
proves needed behavior; list each test you delete or merge in the review body with its
reason. Keep tests that reach a model provider on the repo's mocks; a live API call in a test
costs money, so add one only where the repo's own rules already do. To check how a prompt,
skill or agent behaves, `codex exec` on the signed-in plan costs no API money: see
[testing-without-api-spend.md](testing-without-api-spend.md). Tests wait on a condition,
never on a fixed sleep; a real timeout is only a backstop against a hang.

**Gate command**, first match wins, per repo:

1. the test or check command the repo documents: `AGENTS.md`, a Makefile, justfile or
   Taskfile target, a test runner under `scripts/`, or the CI workflow's test step
2. `run-tests.sh` or `test.sh` at the repo root
3. `package.json` `scripts.test`, run with `npm test`
4. `pyproject.toml` or `pytest.ini`, run with `pytest`, adding `-n auto` when pytest-xdist
   is installed and the repo has not configured its own worker count
5. `pubspec.yaml`, run with `flutter test`
6. none: stop with `blocked_no_test_command`, "no test command detected"

Never hardcode a command. While you build, run only the one test or check you are working on.

**Merge the default branch, then run the gates the diff touches, once.** When the change
is ready, bring in the default branch first:
`git -C $WT fetch origin <default_branch> && git -C $WT merge --no-edit
origin/<default_branch>`. Never rebase. When git refuses the merge because your uncommitted
files overlap the incoming ones, commit the change to the slot branch first (section 7's
**Commit**), then merge, and run section 7's pre-commit review on `git diff <base SHA>`
instead of on the staged diff. A conflict you cannot settle without guessing at someone
else's intent is `blocked_merge_conflict`, naming the files.

After the merge, rerun the repo's setup step (dependency install, codegen, its worktree
setup target) and check that every test path you name exists. Then run, once, inside `WT`,
on the merged tree, the gates the diff touches: the tests that cover the changed code, the
lint and type checks for the languages in the diff, the build when it touches build inputs,
and any check the repo's rules require before a commit. Do not run the full suite locally
when CI runs it; with no CI, the full gates are the check. Never run the gates before the
merge and again after it. A later merge (a conflict fix) reruns the touched tests once on
the new head. Say in the review body and the report which gates ran, each one's wall time,
and which were left to CI.

**Parallelism.** Run tests through the repo's own runner at its default parallelism, never
lowering the worker count without a stated reason, and run independent gates at the same
time. When you call a test framework directly on a subset, give it a temp folder inside `WT`
(pytest `--basetemp`, a per-run `TMPDIR`) so runs in other slots cannot stall it.

**On failure.** A failed check starts diagnosis: read the failure and the code it
exercises, and decide whether the fault is in the implementation, the test or its setup,
or the environment. When it concerns behavior you are editing and is within the ticket's
scope, fix it in this run: the implementation when it violates the requirements, tests,
fixtures or mocks when they are wrong or stale against them. Never skip a failing test,
weaken an assertion or change the expected behavior merely to get a pass. After two failed
attempts at the same fix, change the approach and state which assumption was wrong. When a
failure needs work outside the ticket, unavailable access, or cannot be cleared in this run,
stop with `blocked_tests_failed` and a summary of the output; do not commit, and leave the
tree dirty. A test passed only if you ran it in `WT` and saw it pass; a timeout or
unreadable output is a failure.

**Waiting.** Wait on a process by its PID or by the background job you started it as, never
with a `pgrep -f` loop, which matches itself. Before you hand back, with any status, make
sure nothing you started is still running.

## 7. Land the work

Skip this section for a `needs_manual_action` ticket, except **Pre-commit review** and
**Codex review** and **Claude read**, which section 9 runs too; section 9 has its own rules for the rest.

**Every change lands by review.** Commit on the slot branch, push that branch and open a
review into `<default_branch>`. Never commit to or push `<default_branch>`, never merge,
never close the issue, even where the repo's own rules say to push straight to the default
branch: this overrides them. A rejected push to the slot branch is a blocker; do not push
anywhere else.

**What the repo's rules still decide.** They matter here only for what a review needs: a
pull or merge request template (build the body from it, keeping its required parts and
adding the content below), a title or label convention, a branch-name rule, and required
reviewers. The host requests code owners itself. A reviewer the rules name that the host
would not request: ask for them in the body and say in the report that **open-review** sets
none.

**Pre-commit review.** Once the gates in section 6 pass, review the change in at most two
rounds. Do this for every repo in `repos` before committing or pushing any of them, so a
stop here commits nothing beyond what section 6's split already committed:

1. Stage the change as **Commit** below describes (`git -C $WT add` the paths that belong
   to it), then compute the base SHA: `git -C $WT merge-base HEAD origin/<default_branch>`.
2. Round one: read the staged diff as an engineer who wants it rejected, against the
   standards' review checklist (correctness, concurrency, blast radius, design, tests and
   docs, authority, identifiers, trim), with a pass for anything said twice, and fix what
   you find. Then, when the diff is larger than 150 changed lines (added plus removed,
   ignoring lockfiles, generated files and snapshots) or 5 files, or touches authentication,
   security, payments, personal data, migrations or deletion, spawn the read-only `reviewer`
   agent once per repo on `workhorse` / `high` (`frontier` / `medium` for those sensitive
   areas), model and effort from `resolve_model.py`. Its brief carries resolved values,
   never variable names, because it starts with no history: the command that prints the
   change (`git -C <absolute worktree path> diff --cached <base SHA>`), what the change is
   meant to do (the ticket's title and acceptance criteria), and the repo's rules files you
   read in section 6. It reviews the whole change, every sub-worker's part included.
3. Open each line a finding cites before acting on it. Fix what holds up. A finding that is
   wrong gets a one-line reason in the review summary and no ticket. Every other finding you
   do not fix, declined or deferred, goes on the follow-up list with a one-line reason.
   After any fix, stage again and rerun the gates that cover the fixed files, a single run
   on the merged tree; a failure is `blocked_tests_failed`. Round two runs only when round
   one's fixes changed behavior: the `reviewer` once more per repo on the fixed staged diff,
   its brief adding round one's findings and what you did with each, handled the same way.
   After it, a finding still open goes on the follow-up list, except a P0 or P1, which
   step 4 covers.
4. A P0 or P1 finding you agree with but cannot fix stops the run with
   `status=blocked_review_findings`, naming the finding and what you tried. Commit nothing.
5. A reply that is not the reviewer's JSON object, misses fields, or cites lines that do not
   exist is a failed review: spawn it once more. A `could not review` reply: supply what it
   names as missing and spawn it once more. When it still cannot review, or the spawn is
   refused (the agent is not installed, the thread cap, multi-agent off), review the diff
   yourself for the same things and say in the review body that the `reviewer` did not run
   and why.

Keep a short review summary for the review body: who reviewed (you, the `reviewer`, and
Codex's review below, or why one did not run), what was fixed, each finding not fixed with
its reason (marked wrong, or follow-up), and the rest of the follow-up list, one line each.
The tickets do not exist yet; **Review** step 4 files them.

**Commit.** Run `git -C $WT status --porcelain`, read the list, and `git -C $WT add` the
paths that belong to the change. Then commit; the repo's git config decides signing, and you
never turn it off. The message describes the change itself and ends with a closing keyword
in the syntax the adapter lists under "Closing keywords for a commit message":

- Owning repo: `Closes #<n>`, or `Fixes #<n>` when the ticket has a `bug` label. When the
  change finishes only part of the ticket, `Refs #<n>` instead, in every commit and in the
  review body.
- Any other repo: `Refs <owning remote>#<n>`, which does not close.

The keyword is what closes the issue when the review merges, so it goes in the commit and in
the review body. When section 6's split already committed the work, it goes in the review
body alone. Record the commit SHA per repo.

**A locked signing key.** When a signed commit fails because the key is locked and no
terminal is available to unlock it, do not wait out retry windows and never turn signing
off. Keep the change staged in `WT` in every repo, stop with `status=blocked_sandbox` and
`reason="signing key locked"`, and hold the ticket as section 4 describes, saying in the
comment whether Codex's review already ran, with the line `Unblocks when: the signing key is
unlocked and the run resumed.` Put each `WT` in `worktree_paths` so the dispatcher can
resume this run in the same trees once the user has unlocked the key (`resume_worktrees`,
section 3). A resumed run commits the staged change and runs Codex's review unless that
comment says it already ran.

**Codex review.** After **Commit** and before the push, per repo, from `WT`, run Codex's
built-in review once over the whole branch: `codex review --base origin/<default_branch> <
/dev/null`. It reads everything the branch holds, section 6's sub-worker merges and any
conflict fix included. Keep the command, the reviewed commit, its exit status and its final
findings for the review summary. Handle the findings as **Pre-commit review** step 3 does:
fixes go in one more commit after the gates that cover them pass, and an agreed P0 or P1 you
cannot fix stops the run with `status=blocked_review_findings` before any push. Never run it
twice. When the CLI is missing, the run fails or times out, or it gives no final result, say
so in the review summary; it is never a pass. When neither the `reviewer` nor Codex's review
ran, put "no independent review ran" on the follow-up list.

**Claude read.** Then the standards file's Claude read, per repo, when the Claude CLI is
installed (`command -v claude`). Run it after the Codex review's fixes and before the push,
from `WT`, on the whole branch: `git -C $WT diff origin/<default_branch>...HEAD | claude -p
"<review prompt>" --tools "Read,Grep,Glob" --permission-mode dontAsk --strict-mcp-config
--no-session-persistence`, with the standards file's review prompt, so it reads section 6's
sub-worker merges and any conflict fix too. Handle its findings the same way; fixes go in one
more commit after the gates that cover them pass. Never run it twice. Without the CLI, or
when it fails or is not signed in, skip it and say so in the review summary.

**Review.** Per repo, in `repos` order, after the Codex review and the Claude read:

1. **Push the branch**: `git -C $WT push origin HEAD:<branch>`. Never force-push. A
   rejection is `blocked_push_rejected` with the exact remote error. There is no
   rebase-retry.
2. **open-review** from the branch into `<default_branch>` with **no label**. Do not run
   **ensure-label**, do not pass the blocked label, and leave out the adapter's label
   argument: the blocked label tells people and merge automation "do not merge", which is
   false here. Title: the ticket's title. Body: what was built, the gates run and their
   result (and the ones left to CI), the review summary, each test deleted or merged with
   its reason, and the closing keyword line. Write the body to a file in
   `<worktree_root>/<slot_id>/` named after the branch (`/` replaced by `-`, ending
   `-body.md`), and read the review back after you open or edit it to check its closing
   lines. Before opening, run **list-open-reviews** on the repo; if a review already closes
   `<n>` from this branch (a resumed run), reuse it. Record the URL per repo.

Rollback advisory when a later repo's push is rejected: close the reviews already opened
and delete their remote branches; nothing reached the default branch.

Then, on the owning repo:

3. **set-lane** with role `review` when the project defines that lane. Otherwise leave the
   card in `in_progress`. The issue stays open and unlabelled. The board moves before any
   filing, so a run cut off while filing still leaves the ticket in review.
4. **File the follow-ups**, one ticket per item on the follow-up list, in the repo the item
   concerns (the owning repo when it spans several), at most five new tickets per run, so
   filing cannot swamp the run. A comment on an existing ticket does not count toward it.
   Items past the cap are not filed: the comment in step 5 lists them for a person to file,
   and the result records each as `not_filed` with the reason `over the per-run cap`. For
   each item, in list order:
   - **search-issues** on its keywords for a ticket that already covers it, then
     **read-issue** on each match. When an open match already links this review, it is
     filed: say nothing more. When an open match does not, **comment** the new evidence and
     the review link there and file nothing new. A closed match covers the item only when
     its closing reason does; otherwise file a new ticket and link the closed one.
   - Otherwise fill `files.ticket_template` into a temporary file as `$write-ticket` does:
     the Agent Instructions sections 1 to 3 and 5 copied exactly and section 4's audience
     filled from the repo's brief (or "this repo's existing users"), the Agent Prompt,
     `Depends on: None`, concrete acceptance criteria, a `- [ ] TBD: <the question>` bullet
     for any fact you do not have, and no secret or controlled data. The last line of
     Context is `Found in <review link> (<repo>#<n>).`, with the link of the review that
     holds the code. Run `python3 <files.check_ticket> <file>` and fix what it prints; when
     it still fails on the second run, record the item as not filed with its output.
   - Labels and board, judged by `files.labels` (Priority, Run label, Model label):
     **ensure-label** for the run label, the model label and `project:<repo>` (its color and
     description from `files.labels`, "Label colors and descriptions"), then
     **create-issue**, **set-priority**, **set-lane** with role `backlog`, and **assign** to
     `assignee`, the source ticket's assignee. Never the blocked label and never the ready
     lane.
   - Delete the temporary file. A write that fails is not a stop: the review is open. Carry
     on with the other items, and record the item as not filed with the error.
5. **comment** once on the issue, plain and short and not in the `Blocked:` shape: the
   review link (every link, per repo, when multi-repo), one line on what was built, the
   tests run and that they passed, who reviewed the diff, the follow-ups (number and title
   each, or none), any items over the cap as one list headed `Not filed, for a person to
   file:`, and that merging closes #<n>. Section 8's model-fit note, when it applies, is a
   second comment right after this one.
6. Leave your worktrees: the branch is on the remote, and whoever started you removes them
   once your result is recorded (codex-ticket-notes.md, "Safe cleanup").

Report `status=review_opened` and stop.

Rollback advisories for any blocker, for the user to run after inspecting
`git -C $WT status` and `log`: local-only commits, `git -C $WT reset --hard <the SHA you
recorded>`. A commit already pushed is on the slot branch only, so nothing needs undoing on
the default branch; delete the remote branch. Never force-push.

## 8. After the review opens

**Model-fit note.** Post one only when the tier you ran on was visibly wrong: the ticket
needed several redo passes or you doubted the plan or the diff (too weak), or it was
mechanical work any cheaper tier would have finished the same (over-tiered). It changes
nothing about your run; it tells whoever assigns the model label next. Post it with
**comment** on the owning repo as a second short comment right after section 7's, and say
nothing when the tier fit:

```text
Model-fit note: <tier> (<model>) felt <too weak|over-tiered> for this ticket: <one line why>.
```

Name the tier (`fast`, `workhorse`, `frontier`) and the model slug you were spawned on. It
is found later with **search-issues** on the keywords `Model-fit note`.

**What you leave to the merge.** You do not close the issue, check that it closed, move the
card to `done`, or clear the `dependency` hold on a ticket that waited on this one. The
merge closes the issue through the closing keyword; the next `$daily-grooming` pass settles
it to done and removes the blocked label from a dependent whose dependencies are all closed
(`files.labels`, "Clearing it"). Conflicts and review comments that arrive later are picked
up by the board watcher's `CONFLICT` events and the next `$work-tickets` run, or by Codex
cloud's review when the team uses it; no local tool wakes a session for them.

## 9. Needs manual action

Triggers when the work is complete and tested and the ticket still cannot close without a
live action no worker can take (section 4). It lands by review like every ticket, and the
review is the one held review described here; no second, ordinary review is opened. You
usually know at planning time from the acceptance criteria; if it only becomes clear after
implementation, decide then. It is a whole-ticket decision: every repo in `repos` runs steps
1 to 3, then steps 4 to 8 run once, against the owning repo.

Per repo, with `WT`:

1. **Commit** on the slot branch: `git -C $WT commit -m "<what was built, plainly>.
   Progresses #<n>"`, after section 7's **Pre-commit review** has run for every repo and
   with the change staged as it describes. The message must not contain `Closes` or
   `Fixes`; the ticket is not done. A locked signing key stops the run as section 7
   describes. Then run section 7's **Codex review** and **Claude read**.
2. **Push the branch**, never the default branch: `git -C $WT push origin HEAD:<branch>`.
3. **Open a review on every repo**: it is the container that holds code back until the
   live step is done. Run **ensure-label** for the blocked label on the repo, then
   **open-review** from the branch into `<default_branch>` with the ticket's title, a body
   saying what was built, what tests pass, the review summary and exactly what must be done
   to finish (name the dashboard, the field, the action), and the blocked label's name as
   the label, so merge automation and people read it as "do not merge". Record the review
   URL per repo in `manual_action_refs`.

Then, on the owning repo:

4. **Label the issue** (not the review) with the blocked label: **ensure-label**, then
   **add-label**.
5. **set-lane** with role `blocked`.
6. **comment** once, in the `Blocked: live action` shape: what was built and verified (per
   repo when multi-repo), every review link, the exact live action as concretely as the
   acceptance criteria allow, and what done looks like:

   ```text
   **Blocked: live action**

   Implementation complete, tests passing. Review: <url>

   This needs one live step to finish: <exact action, e.g. "create the product for plan B in
   the payment dashboard and set its price ID as PRICE_ID_B in the hosting env vars">.

   Unblocks when: <what done looks like>.

   Once that is done: remove the blocked label from the review and from #<n>, merge the
   review, and close #<n>.
   ```

7. **File the follow-ups** as section 7's **Review** step 4 describes, under the same cap,
   with the held review's link as the found-in link, then, when the list is not empty, the
   short `Follow-ups:` comment section 4's step 4 describes.
8. Report `status=needs_manual_action` with a `reason` naming the live action.

Stop. Section 7's ordinary review and comment never run for this ticket, and section 8's
model-fit note is skipped: nothing was committed with a closing keyword, so merging the held
review closes nothing. Leave your worktrees in place.

## 10. Final report

**Clean up before you return,** whatever the status, so a long run does not pile up
leftovers:

- Stop every process you started: dev servers, watchers, compose stacks, background jobs.
  Close your own database connections.
- Drop the test databases and temporary data you created, through the repo's own mechanism
  where it has one (a test runner's cleanup or reclaim command, a documented teardown
  target), and delete the temporary files you wrote, the review body file included. Never
  terminate another session's connections, never stop or restart a shared database server,
  and never use `DROP DATABASE ... FORCE` on a database you did not create. A database you
  cannot show you created stays.
- Remove every sub-worker's worktree and branch (section 6); name a unit that was not
  merged.
- Leave your own worktrees alone. Whoever started you removes them once your result is
  recorded; a worktree with uncommitted files or unpushed commits stays, so push or say what
  is left.
- Name anything you could not clean up, and why, in the paragraph of the report.

Your final message goes to whoever dispatched you, or to the user in a direct run worked in
place. Before you write it, check that nothing you started is still running. It has three
parts.

First, one short paragraph that leads with the outcome (in review, blocked, or waiting on a
live step), then the ticket, its final step and status, who reviewed the diff and what that
changed, the review links and commit SHAs, the gates that ran and the ones left to CI, what
blocks it and what would clear it, and the model-fit note if you posted one. A ticket in
review is not closed: say that merging the review closes it.

Second, a **Follow-ups** heading and one line per ticket you filed or commented on:
`#<n> <title>` (with its repo when not the owning one), marked `(existing, commented)` when
it was not new. An item you could not file goes there too, as `not filed: <item>: <the
error, or over the per-run cap>`. Write `None` when the list is empty.

Third, as the last line, one machine-readable line the dispatcher records:

```text
RESULT {"slot_id": "slot-1", "ticket_number": 182, "ticket_repo": "shop-app", "status": "review_opened", "reason": null, "branch": "slot-1-ticket-182", "review_refs": {"shop-app": "https://..."}, "manual_action_refs": {}, "follow_up_refs": [{"repo": "shop-app", "number": 201, "title": "...", "url": "https://...", "action": "filed"}], "commit_sha": {"shop-app": "abc1234"}, "worktree_paths": {"shop-app": "/abs/path"}, "model": "<model slug>", "split": {"sub_workers": [{"unit": "scheduler", "model": "<model slug>"}], "kept_inline": "the shared interface and the route wiring: one edit each"}}
```

`status` is exactly one of `review_opened`, `needs_manual_action`, `needs_decision` or a
`blocked_<type>` value. `reason` is null on `review_opened` and a plain sentence otherwise.
`worktree_paths` names every worktree of yours still on disk, made by you or the dispatcher.
`follow_up_refs` is always present: `[]` when there are none, otherwise one object per item
with its `repo`, `number`, `title`, `url` and an `action` of `filed`, `commented` (on an
existing ticket) or `not_filed` (`number` and `url` null, and the error, or `over the
per-run cap`, in `reason`). `split` is always present: `sub_workers` lists one `{"unit",
"model"}` per sub-worker (section 6, **Split the work**), `[]` when none ran, and
`kept_inline` says in one sentence what you built yourself and why, or is null; the whole
field is null when the run stopped before section 6.

## 11. Working a batch

A dispatch message with `parent` and `children` is a batch: those children, in that order,
shipped on one branch in one review (`files.batches`, "Working a batch"). Sections 2 to 10
hold, with `<n>` read as each child in turn, except for what follows. A single has neither
field, and nothing here applies to it.

- **Checks.** Run section 2's assignment and open checks on each child. A child that fails
  one is left out: not worked, not touched, and named in the report. When every child
  fails, stop as section 2 says for the first.
- **Branch.** `batch/<parent.number>-<parent.area>-<slot_id>` in every repo, in place of
  `<slot_id>-ticket-<n>`, with the same `-r2` rule. Resume from `origin` only when the
  dispatch message has `resumed` true (this slot, under this `slot_id`, ran before).
  Without it, a branch of that name already on `origin` belongs to an earlier slot: never
  start from it, and take the next `-r2` (then `-r3`) name that `origin` does not have. A
  resumed batch reads which children are already done from `git log` and the tracker: a
  child is done only when a commit says `Refs #<child>`, no later commit reverts it (`This
  reverts commit <sha>` naming that commit), and **read-issue** shows no blocked label on
  it. It works every other child again, in order; after a locked signing key it commits the
  staged change first.
- **Plan.** The plan is on the parent: **read-parent-item**, and take each child's
  `### #<n>` section of the `### Final Plan`, or its `### Final Plan addendum: #<n>`.
  Section 5's drift check runs per section, and a replan goes on the parent with
  **comment-parent**. A child with no section is held with `blocked_missing_plan`.
- **Children in order.** For each child: **set-lane** it to `in_progress`, build and test it
  as section 6 says, stage it and commit it alone (section 7's **Commit**, with
  `Refs #<child>` in the message in place of a closing keyword: the keywords go only in the
  review body). Then the next child. When the last is done, merge the default branch once,
  run the gates once on the merged tree, and run section 7's **Pre-commit review** once over
  the whole branch (`git diff <base SHA>`, as section 6 allows), its brief carrying every
  child's title and acceptance, then **Codex review** and **Claude read** once. Fixes are one more commit.
- **Splitting children.** Children whose plan sections name no shared file may go to
  sub-workers by section 6's **Split the work**, a child per unit, moved to `in_progress`
  when its sub-worker starts. They share no interface, so no step 1 commit names a child.
  Each still lands as its own squash commit with `Refs #<child>`, in plan order.
- **A child that cannot finish.** A stop that belongs to one child (a section 4 blocker or
  decision, or a failing test or review finding only its change causes and you cannot fix)
  holds that child alone by section 4's **Holding the ticket**, and the batch goes on. Take
  its change out first: uncommitted, `git -C $WT add -A`, save
  `git -C $WT diff --cached HEAD` to `<worktree_root>/<slot_id>/<child>.patch` (name that
  path in its `Blocked:` comment), then `git -C $WT reset --hard HEAD`; committed,
  `git -C $WT revert --no-edit` its commits. Any other stop (preflight, the merge, a gate you
  cannot pin on one child, a locked signing key, a rejected push) stops the whole batch as
  section 4 says, holding every child not already held.
- **A live action.** A child whose last step is a live action makes the whole review
  section 9's held review, with no closing keyword for any child, and the status
  `needs_manual_action`. Its `Blocked: live action` comment goes on that child and names
  every child the merge finishes, for the person to close with it.
- **The review.** One per repo from the batch branch, titled with the parent's title. On
  the owning repo the body lists every child of the dispatch as a checklist, ticked for each
  one it closes, and has a closing line per finished child (`Closes #<child>`, or `Fixes`
  for a `bug` label) in the adapter's syntax. The parent line depends on what the parent is.
  An issue (GitHub, or `labels` mode on either tracker): `Refs #<parent.number>`, or
  `Closes #<parent.number>` when **list-parents** shows that every open child of the parent
  closes in this review and the parent is in this repo. A GitLab epic (`epics` mode):
  `Refs <parent.url>`, never a closing keyword; grooming closes it.
- **After it opens.** Section 7's step 3 moves each finished child to review first. Then
  file the follow-ups as for a single, under the same cap, and run step 5's comment on each
  finished child (it names the batch review). Then **comment-parent** once: the review link,
  the children it closes and each child held. A model-fit note goes on the parent with
  **comment-parent**.
- **The report.** The paragraph names the parent and each child's outcome. `status` is
  `review_opened` once the review is open (some children may be held),
  `needs_manual_action` for the held review, and otherwise the stop's (when no child
  finishes, no review opens and it is the first child's stop). `branch` is the batch branch,
  and the `RESULT` adds `"parent": {"ref", "number", "repo"}` and `"children_status"`: one
  `{"ticket_number", "ticket_repo", "status", "reason"}` per child of the dispatch, in
  order, with `review_opened` for each the review closes, the stop for each held, and
  `not_worked` for each the checks left out.
