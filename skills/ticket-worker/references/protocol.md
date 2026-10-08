# Ticket worker protocol

One worker, one issue, one run: plan, implement, test, commit, push, then land the work
the way the repo lands work (a direct push that closes the issue, or an open review that
closes it on merge), and move the board card. The tracker (GitHub or GitLab), board, lanes, labels and repo set come
from [registry.md](registry.md); a dispatched worker receives them through the state
file, a direct one reads the registry itself.

**Tracker operations.** Every action on the tracker below is a named operation, shown
in bold (**set-lane**, **comment**, ...). The exact commands for each are in
`references/trackers/<tracker>.md` for the registry's tracker. Read that one file in
full before your first step and run each operation as written there; never improvise a
command for one. A **review** is a pull request on GitHub and a merge request on
GitLab. `<remote>` is the repo's registry Remote and `<n>` the issue number.

**Holding a ticket.** The only way a ticket or a review is held is the registry's
blocked label plus a comment saying what it is blocked on, in the shape defined in the
"Blocked" section of [ticket-labels.md](ticket-labels.md). Read that section before
your first step; this protocol says when to hold a ticket and which kind of comment to
post, and the shape lives there. Waiting on an ordinary review is not a hold: a review
that only needs its reviewer never carries the blocked label (section 8).

**Default branch.** Each repo's default branch is `default_branch[<repo>]`, written
`<default_branch>` below. A dispatched run reads it from `state.project.repo_map`;
a direct run resolves it from the primary clone:
`git -C <primary_clone> symbolic-ref --short refs/remotes/origin/HEAD` with the leading
`origin/` removed. If that fails, run `git -C <primary_clone> remote set-head origin
--auto` once and read it again. If it is still unknown, stop with
`status=blocked_default_branch_unknown` naming the repo. Never assume `main`.

## 1. How work arrives

**Dispatched.** `$work-tickets` spawns you with a JSON payload as the message:

```json
{
  "slot_id": "slot-1",
  "ticket_number": 182,
  "repos": ["<repo>"],
  "item_ref": "<tracker handle for the board item, null where the tracker needs none>",
  "assignee": "<login of the person this run works for>",
  "worktree_paths": { "<repo>": "<absolute worktree path>" },
  "state_file": "<absolute path to the state JSON>",
  "state_lock": "<absolute path to the lock file>",
  "model": "<slug you were spawned on>",
  "validate_plan_first": true,
  "context_files": ["<absolute path to the product brief>"]
}
```

`assignee` is the signed-in login the orchestrator resolved; this run exists for that
person only. `model` is informational: log it in your slot and never switch models
mid-run. Take every path from the payload; never rebuild one. Your slot is the entry in
`state.active[]` with your `slot_id`. The branch in each worktree is
`<slot_id>-ticket-<ticket_number>`, created at `origin/<default_branch>`.

**Direct** ("work issue 42 in my-app"). There is no state file and no slot.
Resolve the owning repo from the registry (when the request names no repo and the
current directory is not one of the registry's clones, ask which and stop), then
build what a dispatch would have given you. Run **auth-check** first; the lookups
below need a signed-in CLI.

- The tracker, host and board, the lanes, priorities, labels, model labels and
  `repo_map` from the registry; `tracker_ids` from **capture-board**; the board item
  from **list-items**, matched on `(number, repo)`, whose `item_ref` you keep. An
  issue that is not on the board skips every board move; say so in the report.
- `assignee` from **current-user**. If **read-issue** shows the issue assigned to
  someone else, or to nobody, stop before anything else: change nothing on the
  ticket, say who it is assigned to (or that it is unassigned), and offer to assign it
  to the current user with **assign**. Run **assign** only when the user says to.

**Choosing the model (direct runs).** A skill cannot set the session's model; only a
spawned subagent can run on a chosen model and effort. So after the assignment check
and before creating anything, decide whether to hand the whole ticket to a
`ticket_worker` subagent on the model its label calls for.

1. **Work it in this session**, with no handoff, when any of these holds:
   - you are already a spawned run: you run as the `ticket_worker` agent, or the
     message says it is a handoff from a `$ticket-worker` session. A spawned run never
     delegates again, which prevents a loop;
   - the user named a model, or said to work it here. A named model outranks the label;
     if it differs from the session's, say in the report that the session cannot switch
     models;
   - you can see that the session already runs on the label's model at its effort.
2. **Find the tier.** Take the issue's model label from **read-issue**. The registry's
   Model labels table maps each label to `fast`, `workhorse` or `frontier`; without that
   table the labels are `model:fast`, `model:workhorse` and `model:frontier`, and
   `model:haiku`, `model:sonnet` and `model:opus` mean the same three tiers. The effort
   is the `effort:<level>` label when the issue has one, otherwise `high` for `fast` and
   `medium` for the other two. Run `python3 scripts/resolve_model.py <tier> --effort
   <effort>` and use the `model` and `effort` it prints, passing any `notes` it prints on
   in the report.
3. **No usable label.** No model label, several, one that maps to no tier, or a resolver
   exit of 3 (no model for the tier) or anything else non-zero: work the ticket in this
   session and say in the report which of these it was. Do not guess a tier.
4. **Hand off.** Spawn one `ticket_worker` with `spawn_agent`, setting the resolved
   model and reasoning effort explicitly (the agent file sets neither). The message is
   the user's request as they wrote it, followed by: "Handoff from a $ticket-worker
   session. You are the spawned run: work this ticket yourself and do not spawn another
   ticket_worker. Return one short paragraph: the outcome first, then the final step,
   commit or review links, and what blocks it." Then wait for it, relay its report as
   yours with one line before it saying which model and effort it ran on and why, close
   its thread, and stop. The worker repeats the lookups and the assignment check, so the
   rest of this protocol is its job. If the spawn fails for lack of a free thread (see
   the Codex config's `agents.max_concurrent_threads_per_session`, older name
   `agents.max_threads`), wait for a thread and try once more. Any other spawn error,
   for example "agent type is currently not available" (the agent file is missing or
   installed as a symlink): work the ticket in this session, say what failed, and tell
   the user to rerun the pack's `install.sh`. Never retry in a loop.

When this session works the ticket, continue:

- Slot id `solo`, so the branch is `solo-ticket-<issue>`. Create one worktree per
  repo from `origin/<default_branch>` under `${CODEX_HOME:-$HOME/.codex}/state/solo-worktrees/<repo>-<issue>/`
  with `git -C <primary_clone> fetch origin --prune` and `git -C <primary_clone>
  worktree add <path> -b solo-ticket-<issue> origin/<default_branch>`. Those two commands,
  `worktree remove` and `branch -D` are the only writes you make against a primary
  clone.
- The brief from the registry is `context_files`.

Then run every step below, board moves and terminal states included, skipping only
the state-file writes. Keep the slot's fields in your head and put them in the report.
After `ticket_closed` or `review_opened`, remove your worktree and local branch (a
review's branch is on the remote); after any stop, leave both for inspection.

**Anything else** (invalid JSON, no issue number, or a payload with no `assignee`):
stop before touching the board and say what is missing.

## 2. Preflight

Before the first step, confirm the sandbox lets you do the job: `test -w` each
worktree path (direct mode: the `solo-worktrees` folder, created if missing),
**auth-check**, and `git -C <worktree> fetch origin --prune` (direct mode:
against the primary clone), which proves network, credentials and a writable Git
directory. When a check fails, stop with `status=blocked_sandbox`, naming the failed
check and the fix: relaunch Codex with full access. The default `workspace-write`
sandbox keeps every `.git` read-only, so commits cannot happen inside it, even with
extra writable directories.

**Assignment check.** Dispatched runs: run **read-issue** and confirm its `assignees`
include the payload's `assignee` (logins compare case-insensitively). If not, stop with
`status=blocked_not_assigned`, `reason="issue is assigned to <logins, or nobody>, not
<assignee>"`. This stop touches nothing on the ticket: no comment, no label, no board
move, because the ticket is not this run's to change. Direct runs did the equivalent
check in section 1.

## 3. State

Dispatched runs only. The orchestrator wrote `state.project`:
`tracker`, `host`, `board` (the registry's board identity), `tracker_ids` (what
**capture-board** returned; only the adapter reads inside it), `repo_map`
(`{ "<name>": { "primary_clone", "remote": "<Remote>", "brief", "default_branch" } }`), `lanes` (role to
lane value), `priorities` (role to priority value), `labels` (role to
`{name, color, description}`), `model_labels` (tier to label), `assignee`. There are no fallback
defaults: if any of them is missing, stop with `status=blocked_state_incomplete`,
`reason="state.project is incomplete: the orchestrator did not run its capture"`.
You are told the board and the repos and never guess them. If a path in
`worktree_paths` fails `test -d`, stop with `status=blocked_worktree_missing`.

**Every read-modify-write of the state file takes the exclusive advisory lock on
the payload's `state_lock`:**

```bash
(
  flock -x 200
  # read "$STATE_FILE", mutate YOUR slot in state.active[], write back
) 200>"$STATE_LOCK"
```

Where `flock` is not installed, Python's `fcntl.flock(fd, fcntl.LOCK_EX)` on the
same lock file takes the same lock. Locate your slot strictly by `slot_id`. Never
touch other slots or `state.completed[]`, `state.blocked[]`, `state.skipped[]`;
those belong to the orchestrator.

At every checkpoint update your slot's `step`, `status`, `reason` and whatever else
changed, and move the board card as section 4 says. Fields you maintain:
`pre_step_sha`, `changed_files`, `commit_sha`, `plan`, `ticket_repo`, `model`,
`close_method`, `closed_at`, `manual_action_refs`, `landing` (`direct` or `review`,
set in section 8), `review_refs` (`{ "<repo>": "<review URL>" }`), `unblock_skipped`,
`unblock_check_error`.

Steps: `fetched`, `synced`, `planned`, `implemented_<repo>`, `tested_<repo>`,
`committed_<repo>`, `pushed_<repo>`, `ticket_closed`, `downstream_unblocked`,
`review_opened` (terminal) or `needs_manual_action` (terminal).

```
fetched > synced > planned > implemented_<repo> > tested_<repo> -+-> committed_<repo> > pushed_<repo> > ticket_closed > downstream_unblocked   (landing: direct)
                                                                  +-> committed_<repo> > pushed_<repo> > review_opened (terminal)          (landing: review)
                                                                  +-> needs_manual_action (terminal, section 11)
```

A multi-repo ticket repeats implement, test, commit and push per repo in `repos[]`
order, committing and pushing one repo before starting the next. For
`needs_manual_action`, implement and test repeat per repo, then section 11 runs.

## 4. Running, stopping, and the board

Every checkpoint continues without a pause. A run that opens a review (section 8) ends
normally at `review_opened`; that is a finished run, not a stop. You stop in exactly three cases, each
with a desktop notification (on macOS `osascript -e 'display notification "<reason>" with title "Codex Ticket Worker"'`, on Linux `notify-send`; if none works, say so in the reason and stop anyway):

- **Blocker.** `status=blocked_<type>` with a `reason` that names what you tried,
  the evidence, the blocker and what would clear it. Add the advisory rollback from
  section 8 when it applies. Hold kind: `failure`.
- **Decision point.** The ticket is ambiguous, its requirements conflict, or it
  forces a choice between meaningfully different approaches the ticket cannot
  settle. `status=needs_decision`. Only stop when a wrong guess would force a
  rewrite; routine implementation choices are yours. Hold kind: `decision`.
- **Manual action complete.** The code is done and tested, but the ticket cannot
  close without one live action no worker can take: creating a real object in a paid
  provider's dashboard, entering a real credential, sending a genuine outreach
  message, or spending real money. This is not a decision point; the plan is
  unambiguous and its last step is not yours to take. Hold kind: `live action`.
  Follow section 11.

When you re-read or re-edit the same files without progress, stop with
`status=blocked_no_progress`, listing what you tried, what you observed and the
input that would unblock the ticket.

**Board moves.** A move is **set-lane** with the lane role, which looks the lane value
up in `lanes[<role>]` and applies it.

| Checkpoint | Lane role |
| --- | --- |
| `synced`, `planned` | `in_progress` |
| last `pushed_<repo>` (landing `direct`, ticket about to close) | `done` |
| `review_opened` | `review` if the registry defines that lane, otherwise no move |
| any `blocked_*`, `needs_decision`, `needs_manual_action` | `blocked` |

A ticket whose review is open stays out of `done` until the merge closes it. All three stops share the one blocked lane. The `status` values stay distinct in the
state file, and the comment's kind says which it is. A stopped ticket never goes to
`in_progress`.

If a lane value is missing from the board, **set-lane** skips the move and you log a
warning; never block on it.

**Holding the ticket.** Every stop except `blocked_not_assigned` (which touches
nothing: no label, no comment, no move) runs these, on the owning repo, in this order:

1. **ensure-label** for `labels.blocked` (its name, color and description), then
   **add-label**.
2. **comment** once, in the shape of ticket-labels.md's "Blocked" section, with the
   kind from the stop: `failure` quotes the exact error and what you tried;
   `decision` lists the options, each with its consequence, and recommends one;
   `live action` is section 11's comment.
3. **set-lane** with role `blocked`.

Plain language, and always an "Unblocks when:" line. A preflight stop that happens
because the tracker itself cannot be reached (`blocked_sandbox` from a failed
**auth-check**) cannot run these: record the status in the state file, say so in the
report, and skip them.

**Item handle.** Use your slot's `item_ref` over the payload's, because state came from
the authoritative **list-items**. If it is missing where the tracker needs one, or
**set-lane** reports the item not found, re-resolve it with **list-items** by
`(number, repo)` and write it back to your slot under the lock.

## 5. Sync

Per repo, with `WT=worktree_paths[<repo>]`; run every git command as `git -C $WT`.

1. `git -C $WT fetch origin --prune`.
2. `git -C $WT status --porcelain`. On a fresh start (step `fetched`, `synced` or
   earlier), dirty output means `blocked_dirty_tree`, naming the repo and files. On
   a resume at `implemented_<repo>` before tests, dirty files must match your slot's
   `changed_files[<repo>]`; a mismatch is `blocked_dirty_tree_unexpected`.
3. Never `git checkout <default_branch>` in the worktree; it may be checked out elsewhere. If
   no local commits exist yet and `origin/<default_branch>` has advanced since the worktree was
   made, run `git -C $WT merge --ff-only origin/<default_branch>`. After your first
   commit, section 8's rebase-retry does the reconciling.

Set `fetched` once all repos are fetched, then `synced`.

At the start of every step, verify with **issue-state** that the issue is open; if it was closed outside this run, stop with
`blocked_ticket_closed`. Do not trust state alone.

Before any destructive step, record `git -C $WT rev-parse origin/<default_branch>` in
`pre_step_sha[<repo>]`.

## 6. Plan

Posted plans rot when the brief changes, so validate before replanning.

1. Run **read-issue** and read every `context_files` path end to end (the brief is
   the source of truth).
2. Find the latest `### Final Plan` comment. None: go to step 4.
3. Check it for drift: files and symbols it names still exist (`find` or `grep`);
   key facts (flags, counts, providers, routes, libraries) still match the ticket
   body and each context file; the brief or the ticket body was not edited after the
   plan was posted (an edit is a drift signal even with no visible contradiction;
   **read-issue** gives the issue's `updated` time and each comment's `created` time).
   - **No drift:** write the plan to your slot's `plan`, set `planned`, and go to
     implementation. Post nothing.
   - **Drift:** replan in step 4, opening with
     `_Re-validated YYYY-MM-DD: <one-line drift summary>_`.
4. One pass, about 200 words, one paragraph per section at most: **Files to touch**,
   **Pattern to reuse**, **Acceptance** (the one or two checks that mean done),
   **Blockers / dependencies** (only if real), **Watch out for** (only non-obvious
   traps). No iteration loops, tradeoff tables, risk registers or restated briefs.
   If a section needs more than a paragraph, the ticket is too vague: comment asking
   for tightening instead of expanding the plan. Post it with
   **comment**, the `### Final Plan` heading first and no iterations footer.
5. Write the full plan text to your slot's `plan`, set `step=planned`,
   `status=running`, move the card to `in_progress`, and continue.

On resume past `planned`, the slot's `plan` is the contract. If it is null, use the
ticket's latest `### Final Plan` comment. With neither, stop with
`blocked_missing_plan`, "no plan found in slot state or ticket comments; re-run
`$work-tickets` to groom one".

## 7. Implement and test

Read the repo's `AGENTS.md` (or `CONTRIBUTING.md` and the other rules files at its
root when it has none) and the rules files those point to, and follow them with the
standards below.

**Review before writing.** Read the dependency manifest, find the existing patterns
for state, navigation, styling, networking, caching, payment, auth and storage, and
build with what is there. If a needed library is missing, name the best-in-class
option (well maintained, widely used, officially supported) in the plan so it is
visible before implementation.

**Design.** Reuse the repo's code style and UI. Improve a pattern only where it
falls below the standard the repo itself sets, judged from its README, brand or
design docs and existing screens. Never import an aesthetic or audience from another
product.

**Quality bar.** Zero console errors or warnings; update `run.sh`, `setup.sh` and
similar when the change affects build or dev workflow; file-level doc comments on new
files, inline comments on complex logic, `TODO` markers where future work shows; a
README update when the change adds dependencies, endpoints or env vars or alters run
instructions.

**Tests.** Write or update tests for every change, each checking behavior the change
adds or fixes, in the repo's existing location, naming and framework. Keep tests that
reach a model provider on the repo's mocks; a live API call in a test costs money, so
add one only where the repo's own rules already do. To check how a prompt, skill or
agent behaves, `codex exec` on the signed-in plan costs no API money: see the pack's
[testing-without-api-spend.md](testing-without-api-spend.md).

After implementing, record the changed paths from `git -C $WT status --porcelain` in
`changed_files[<repo>]` and set `implemented_<repo>`. If `changed_files[<repo>]` is
null on a resume, stop with `blocked_state_incomplete`: check `git -C <worktree>
status` and `diff`; if the changes look right, re-run `$work-tickets` with the same
flags to retry; if wrong, `git -C <worktree> restore :/` and re-run from the
previous checkpoint.

**Test command**, first match wins, per repo:

1. `run-tests.sh` or `test.sh` at the repo root
2. `package.json` `scripts.test`, run with `npm test`
3. `pyproject.toml` or `pytest.ini`, run with `pytest`
4. `pubspec.yaml`, run with `flutter test`
5. none: stop with `blocked_no_test_command`, "no test command detected"

Never hardcode a command. Run it inside the worktree, together with any check the
repo's rules require before a commit. On failure stop with `blocked_tests_failed`,
with a summary of the output, do not commit, and leave the tree dirty. Advisory:
`git -C $WT restore :/` discards the changes. Set `tested_<repo>` on success. A test
passed only if you ran it in the worktree and saw it pass; a timeout or unreadable
output is a failure.

## 8. Land the work: commit, push, and review when the repo asks for one

Skip this section and section 9 for a `needs_manual_action` ticket; section 11 has
its own rules.

**Landing rule.** Before committing, decide per repo how it lands work, from its own
words first:

1. **Rules files.** The repo's `AGENTS.md` chain, `CLAUDE.md`, `CONTRIBUTING*` and the
   files those point to (section 7 already read them). A rule that requires a pull or
   merge request, or a reviewer, means `review`. A rule that says to commit or push to
   the default branch means `direct`.
2. **History, only when the files are silent.** Read the last 20 commits on
   `origin/<default_branch>` (`git -C $WT log --first-parent -20 --format=%s%n%P
   origin/<default_branch>`). Mostly merge commits, `Merge pull request` / `Merge branch`
   subjects or `(#123)` suffixes means `review`; mostly plain commits, or too little
   history to tell, means `direct`.
3. **Conflicting or unclear signals mean `review`.** It is the safer choice: a review
   can always be merged, a push cannot be taken back.

A multi-repo ticket lands as one: if any repo in `repos[]` lands by `review`, every
repo does, so the code arrives together. Record the result in `landing` and say in the
report which rule decided it (the file and the sentence, or "recent history").

**Commit** on the slot branch (never on `<default_branch>` directly):

```bash
git -C $WT add -A
git -C $WT commit -m "<msg>"
```

The message describes the change itself and ends with a closing keyword in
the syntax of the tracker adapter's **close-issue** section:

- Owning repo: `Closes #<n>`, or `Fixes #<n>` when the ticket has a `bug` label.
- Any other repo: `Refs <owning remote>#<n>`, which does not close.

The owning repo is the board item's `repo`, else the first entry of
`repos[]`; store its name in `ticket_repo`. Record the SHA in `commit_sha[<repo>]`.
The keyword is the same for both landings; with `review` it fires when the review
merges, with `direct` when the push lands.

**Push (landing `direct`)**, per repo: `git -C $WT push origin HEAD:<default_branch>`. Never force-push. On a
non-fast-forward or branch-protection rejection, try one rebase-retry, which is
normal when another worker pushed first:

1. `LOCAL_SHA=$(git -C $WT rev-parse HEAD)` for diagnostics.
2. `git -C $WT fetch origin --prune`.
3. `git -C $WT rebase origin/<default_branch>`; on conflict `git -C $WT rebase --abort` and go
   to the block path.
4. Re-run the test command; on failure go to the block path.
5. `git -C $WT push origin HEAD:<default_branch>`; on success update `commit_sha[<repo>]` (the
   rebase rewrote it) and continue; on failure go to the block path.

**Protected branch.** When the remote rejects the push because the default branch is
protected (it requires a pull or merge request, a review or passing checks), the repo
lands by review even though its rules files did not say so: switch to review landing
for this ticket, record why in the slot, and continue from there.

**Block path:** `blocked_push_rejected`, with the exact remote error and whether the
retry ran and why it failed (`rebase-conflict`, `tests-failed-after-rebase` or
`push-still-rejected`).

**Rollback advisories** for any blocker, for the user to run after inspecting
`git -C $WT status` and `log`: local-only commits, `git -C $WT reset --hard
<pre_step_sha>` (or `origin/<default_branch>` after a rejected push); pushed commits, `git -C $WT
revert <sha> && git -C $WT push origin HEAD:<default_branch>`. Never force-push.

Set `committed_<repo>` and `pushed_<repo>` as they complete. Before the last push,
move the card to `done` per section 4.

**Review landing.** A review is a normal, successful end for a ticket, never a hold.
Per repo, in `repos[]` order, after the commit:

1. **Push the branch**, not `<default_branch>`: `git -C $WT push origin
   HEAD:<slot_branch>`. Never force-push; a rejection is `blocked_push_rejected` with
   the exact remote error. There is no rebase-retry here: the review absorbs a moved
   default branch when it merges. Set `pushed_<repo>`.
2. **open-review** from `<slot_branch>` into `<default_branch>` with **no label**. Do
   not run **ensure-label**, do not pass `labels.blocked`, and leave out the adapter's
   label argument; the blocked label tells people and merge automation "do not merge",
   which is false here. Title: the ticket's title. Body: what was built, the tests
   run and their result, and the closing keyword line from the commit (`Closes #<n>`,
   `Fixes #<n>` or `Refs <owning remote>#<n>`, as in the commit). Before opening, run
   **list-open-reviews** on the repo; if a review already closes `<n>` from this
   branch (a resumed run), reuse it instead of opening a second. Record the URL in
   `review_refs[<repo>]` under the lock.

Rollback advisory for a blocker partway through (a later repo's push is rejected, say):
close the reviews already opened and delete their remote branches; nothing reached
`<default_branch>`.

Then, on the owning repo:

3. **comment** once on the issue, plain and short, not in the `Blocked:` shape: the
   review link (every link, per repo, when multi-repo), one line on what was built, the
   tests run and that they passed, and that merging closes #<n>.
4. **set-lane** with role `review` when the registry defines that lane. Otherwise
   leave the card where it is, in `in_progress`. The issue stays open and unlabelled.
5. **Set the slot** `step=review_opened`, `status=review_opened` (terminal) and
   `landing=review`. Stop.

Section 9 never runs for this ticket: the merge closes the issue, `$daily-grooming`
settles closed issues to done. No close verification, no model-fit note, no downstream
unblock now, so a dependent ticket's `dependency` hold stays on until a person clears it
(nothing else clears one when a merge, not a worker, closes the issue). If the ticket also needs a live step, section 11
applies instead: its review is held with the blocked label because both facts are true.

## 9. Close, model fit, downstream

Also skipped for a `needs_manual_action` ticket (no closing keyword was committed) and
for landing `review` (the merge closes the issue, section 8).

**Verify the close** after the owning repo's push lands with **verify-closed**. Still
open: **close-issue** with the comment "Auto-closed by ticket worker (keyword did not
fire; commit <sha>)". If that fails too, stop with
`blocked_close_failed` and do not report the ticket completed. Record
`close_method` as `keyword`, `fallback` or `blocked_close_failed`. Pushes to
non-owning repos need no verification. Set `ticket_closed` and `closed_at`
(ISO 8601), leave `status=running`; the orchestrator reaps the slot.

**Model-fit note.** Post one only when the tier you ran on was visibly wrong: the
ticket needed several redo passes or you doubted the plan or the diff (too weak), or
it was pure mechanical work any cheaper tier would have finished the same (over-tiered).
It changes nothing about your run; it tells whoever assigns the `model:` label next.
Post it with **comment** on the owning repo, even after an auto-close (both trackers
allow comments on closed issues), and say nothing when the tier fit:

```text
Model-fit note: <tier> (<slug>) felt <too weak|over-tiered> for this ticket: <one line why>.
```

Name the tier (`fast`, `workhorse`, `frontier`) and the slug you were spawned on. It
is found later with **search-issues** on the keywords `Model-fit note`.

**Clear downstream blocked labels**, on the owning repo only, once the issue is
confirmed closed, and only for a dependent whose hold is a dependency hold:

1. **list-blocked** on the owning repo, with `labels.blocked`'s name.
2. For each, match case-insensitively a `Depends on:`, `Blocked by:` or `Blocked on:`
   line containing `#<n>` or `<repo>#<n>`, or a `#<n>` under a heading containing
   "depend" or "block". A blocked issue with no such block is skipped; only a person
   can clear a reason the issue never states.
3. Run **read-issue** on it. Its most recent `**Blocked:` comment must have the kind
   `dependency`. Any other kind, or no such comment, is skipped with that reason
   (`kind <kind>` or `no Blocked comment`): append `{downstream: d, reason: "..."}` to
   `unblock_skipped[]` and leave the label.
4. Parse every ticket number in the dependency block; check each other one with
   **issue-state**.
5. All others closed: **remove-label** `labels.blocked`'s name from `<d>`, then
   **comment** on it: "Unblocked by #<n> (last remaining dependency closed)."
6. Any other still open: leave the label and append `{downstream: d, reason: "still
   blocked by #M"}` to `unblock_skipped[]`.

Failures here (rate limit, network, a failed label edit) go in
`unblock_check_error` and never block a ticket that has shipped. Set
`downstream_unblocked`. Cross-repo chains are out of scope.

## 10. Report

Your final message goes to whoever dispatched you, or to the user in direct mode:
one short paragraph that leads with the outcome (closed, in review, blocked or waiting
on a live step), then the ticket, its final step and status, commit SHAs or review links, how it
closed (or, for a ticket in review, the landing rule that decided it), what blocks it and what would clear it, and the model-fit note if you posted
one. In direct mode, if you worked the ticket in the session because of the model rules
above, say why in one clause (for example "the ticket had no model label"). With a state
file, the file is the record and this is the summary.

## 11. `needs_manual_action`

Triggers when the work is complete and tested and the ticket still cannot close
without a live action no worker can take (section 4). It applies whatever the repo's
landing rule says, and a repo that lands by review gets the one held review described
here, not a second ordinary one. You usually know at
planning time from the acceptance criteria; if it only becomes clear after
implementation, decide then. It is a whole-ticket decision: every repo in `repos[]`
runs steps 1 to 3, then steps 4 to 7 run once, against the owning repo.

Per repo, with `WT`:

1. **Commit** on the slot branch:
   `git -C $WT add -A` then `git -C $WT commit -m "<what was built, plainly>.
   Progresses #<n>"`. The message must not contain `Closes` or `Fixes`; the ticket is
   not done.
2. **Push the branch**, not `<default_branch>`: `git -C $WT push origin HEAD:<slot_branch>`.
3. **Open a review on every repo**, including one whose own rules say to commit
   straight to the default branch: a review is the only container that holds code back
   until the live step is done. Run **ensure-label** for `labels.blocked` on the repo,
   then **open-review** from `<slot_branch>` into `<default_branch>` with the ticket's
   title, a body saying what was built, what tests pass, and exactly what must be done
   to finish (name the dashboard, the field, the action), and `labels.blocked`'s name as
   the label, so merge automation and people read it as "do not merge". Record the
   review URL in `manual_action_refs[<repo>]` under the lock.

Then, on the owning repo:

4. **Label the issue** (not the review) with `labels.blocked`: **ensure-label**, then
   **add-label**.
5. **Comment once** on the ticket with **comment**, in the `Blocked: live action` shape
   of ticket-labels.md: what was built and verified (per repo when multi-repo), every
   review link, the exact live action as concretely as the acceptance criteria allow,
   and what done looks like:
   ```
   **Blocked: live action**

   Implementation complete, tests passing. Review: <url>

   This needs one live step to finish: <exact action, e.g. "create the product for
   plan B ($99/mo) in the payment dashboard and set its price ID as PRICE_ID_B in
   the hosting env vars">.

   Unblocks when: <what done looks like>.

   Once that is done: remove the blocked label from the review and from #<n>, merge the review, and close #<n>.
   ```
6. **Move the card** to the `blocked` lane with **set-lane**.
7. **Set the slot** `status=needs_manual_action` (its own value, neither `blocked_*`
   nor `needs_decision`) with a `reason` naming the live action.

Stop. Section 9's close verification and downstream unblock never run: nothing was
committed with a closing keyword, so there is nothing to verify and nothing to
unblock yet.
