---
name: eng
description: Use when asked to fix a bug, build a feature, refactor, change architecture or review a diff in a code repo. Splits the work onto cheaper subagents. Not for judging how a screen looks (ux-review, web-design-guidelines) or questions with no code behind them.
---

# Engineering pass

Do the job end to end in the repo you were pointed at, and land it by pull request
(a merge request on GitLab) into the default branch. Invoking this skill is a request
to verify: add the tests the standards call for and run the gates in step 9.

Carry the work through to the open review and the report in this turn. When a
detail is missing, pick the most reasonable assumption, write it in the report and
keep going. Stop to ask only for the cases step 3 names, for an approval the repo's
rules require (anything public, paid or production, deleting data), for a secret or
access you lack, or for a blocker you cannot clear; then say what you tried and what
would unblock you. When you notice you are re-reading or re-editing the same files
without progress, stop and report instead of looping.

## Read first

- **The repo's rules.** Codex has loaded the `AGENTS.md` chain. Read the rules
  files it points to (often `CONTRIBUTING.md` or a docs folder), the CI definitions
  (`.github/workflows/` or `.gitlab-ci.yml`), the pull or merge request template and
  `CODEOWNERS`. The repo's conventions win every fight over house style.
- **The craft standards:**
  [references/engineering-standards.md](references/engineering-standards.md). They
  bind every step below and are not repeated here. If the file is missing, say so in
  your report and continue with this pass.
- **Model and effort:** [references/model-selection.md](references/model-selection.md),
  before you spawn anything. Inline work runs on whatever the user chose for this
  session.

When another session spawned you for one unit, read only what your brief names,
plus the standards when the unit writes code; skip the rest of this list.

## Handle the request

- **A review of existing code:** answer it directly and skip the build steps. Lead
  with findings ordered by severity, each with a `file:line`, then open questions.
  With no findings, say so plainly and name the residual risks and test gaps. For a
  diff or a branch, also run it past the `reviewer` agent and Codex's built-in review
  as step 8 describes, preserving the requested target (`--base <branch>`,
  `--commit <SHA>` or `--uncommitted`). Inside a built-in review session, review
  directly and never launch another review.
- **Ambiguous:** when the readings lead to materially different work, ask one question
  with the readings side by side. When they lead to roughly the same work, pick the
  likelier, say which, and continue.
- **Several jobs in one message:** list them, then do all of them.
- **A repo, path or issue that does not exist:** say what you found and stop.

## The pass

1. **Name it.** Fix, feature, or both. A fix that needs a schema change first is
   both, and both halves get done.
2. **Ground in the real code.** Never describe or change code you have not opened.
   Read the modules involved and their tests. For a fix, reproduce it first with a
   failing test, a real run or exact log output; when you cannot reproduce it, list
   what you checked before proposing anything. For a feature, find the existing
   seam it belongs in. Read the repo's recorded decisions and stored measurements
   before measuring anything again: a claim nobody measured is still open. When
   grounding spans more than one area of the repo, send explorers (see Split the
   work) and read their summaries instead of every file yourself.
3. **Check for a simpler path.** What does the user see when this is done, and is
   the requested path the simplest way there? Watch for a new dependency where the
   stack already has one, generating what could be read or cached once, an
   abstraction with one caller, a second paid provider, or work a config change
   already covers. When a meaningfully simpler path exists, show a short tradeoff
   table (cost, latency, moving parts, failure modes, what each rules out) with
   your recommendation. Stop and ask only when the simpler path changes what gets
   built, part of the ask looks deferrable, the work needs money or a new provider,
   or a recorded decision would be overturned; then present the smaller and fuller
   versions, because deferring scope is the user's call. Decide mechanism yourself:
   serial or parallel, how many agents, branches, worktrees, test layout.
4. **Split the work** into units and send each delegable unit to a subagent on the
   cheapest adequate model, as the section below describes. Do this before
   building, every time; a one-file fix ends with "no split".
5. **Record architecture decisions.** When the change locks in a stack choice, a
   schema, an interface contract, an agent's authority or a data-flow direction,
   write it into the repo's decision log in its existing format and land it with
   the code. Bug fixes and additive features inside a seam need none.
6. **Build the smallest thing that fully does the job,** in the repo's idioms and
   the framework's documented ones. Search for prior art and reuse an existing
   helper before adding one. Surface errors: no broad catches, silent defaults or
   success-shaped fallbacks, and no casts that only quiet the type checker. Read
   enough of a file to make all your changes to it in one coherent edit. Before
   writing new code against a fast-moving library or API, fetch its current
   documentation; when it is unreachable, mark the line `UNVERIFIED:`.
   While you iterate, run only the test or check you are touching; the gates run
   once, in step 9.
   - **The design rules bind every line you write.** The standards' rules from
     "Follow the codebase's patterns" through "Keep hashed and exported bytes stable"
     cover patterns, loops and string literals, typed models, DRY, fixing by design,
     refactors, dead code, tests, quality counts, guidance and exported bytes. Each
     loop or literal you keep, and each pattern you chose not to use, gets one line of
     why in the report.
   - **Run the docs pass** from the standards over every doc and comment the change
     touches, and over its area's README and guide, before the review. A change to an
     `AGENTS.md` also gets the standards' context-budget check.
7. **Consider the next version up,** once, when the simple version works. The
   standards carry this rule.
8. **Review the diff adversarially, in at most two rounds, before the verification
   run.** With children, this is the combined diff after you integrate their work.
   The standards' review rule sets the rounds, the stop on an unfixable P0 or P1 and
   the fallback when the reviewer cannot run, whatever the diff's size.
   - **Round one.** Run the standards' review checklist in full on your own diff, its
     DRY pass and docs pass included, and spawn the `reviewer` agent with `model` and
     `reasoning_effort` set from the model guide: `workhorse` / `high`, or
     `frontier` / `medium` when the diff touches authentication, authorization,
     payments, personal data, secrets, migrations or deletion. Its brief names the
     command that prints the diff (`git diff <base>...HEAD`, or `git diff HEAD` plus
     the untracked files `git status --short` lists for uncommitted work), what the
     change is meant to do, and the repo's rules files. It answers with one JSON
     object: `findings` (each with `title`, `body`, `priority` 0 to 3,
     `confidence_score` and `code_location`), then `overall_correctness`
     (`patch is correct`, `patch is incorrect` or `could not review`),
     `overall_explanation` and `overall_confidence_score`.
   - **Weigh the findings.** Open the cited lines before you act on one. Fix what
     holds up. A wrong finding gets a one-line reason in the report; every other
     finding you do not fix, declined or deferred, is a follow-up (see Report). An
     agreed P0 or P1 you cannot fix stops the run before step 9: commit, push and open
     nothing, and report it with what you tried. A reply that is not that JSON object,
     misses fields, or cites lines that do not exist is a failed review: run it once
     more, then fall back to your own review and say so. A `could not review` reply
     is not a pass: supply what it names as missing and run it once more. When the
     `reviewer` agent is not installed, review inline and say so.
   - **Round two,** only when round one's fixes changed behaviour: the `reviewer` reads
     the fixed diff, its brief adding round one's findings and what you did with each.
     There is no third round.
   - Fix what you find before step 9, so the checks run on the fixed state.
9. **Verify, then land.** Branch, commit and open the review as
   [references/landing.md](references/landing.md) says; its last section is how to
   write the review body.
   - **Every change lands by review.** Work on a branch named for the change, from
     the latest `origin/<default-branch>`, never on the default branch, whatever the
     repo's files allow. Commit by path.
   - **Merge the base, then run Codex's built-in review.** Commit, merge the base
     branch into yours (`git fetch origin <base> && git merge origin/<base>`, never a
     rebase), rerun the repo's setup step, then run
     `codex review --base origin/<default-branch> < /dev/null` from the worktree, on
     the ChatGPT sign-in
     ([references/testing-without-api-spend.md](references/testing-without-api-spend.md)).
     Confirm it covered every changed file. Handle its findings as the standards'
     review rule says: fix what holds up, commit, and run it once more when the fixes
     changed code; there is no third run. Save the command, the reviewed commit, the
     exit status and the final findings. A missing CLI, a failed run, a timeout or no
     final result blocks completion: report the evidence and what would unblock it,
     never a pass. Then, when `command -v claude` finds the Claude CLI, run the
     standards' Claude read once on the branch's diff and handle it as they say; skip it
     with a one-line note when the CLI is missing, fails or is not signed in.
   - **Run only the gates the diff touches, once,** together and at the repo's full
     parallelism, on that merged and reviewed tree, as the standards' merge and
     parallelism rules say. Read real exit codes; never pipe a test runner through
     `tail` or `grep` and call the result a pass. Note what ran, what was left to CI,
     and each gate's wall time.
   - Confirm the test meant to cover the change ran the changed code path. For a fix,
     watch it fail without the change (run it on the parent commit in a throwaway
     worktree, never by stashing or reverting in the shared tree); otherwise point to
     a name, assertion or output only the new path produces. When you cannot show it,
     report the test as unconfirmed.
   - **Exercise the changed path where tests cannot reach it.** One command you run
     yourself. A run of more than one or two commands (a compose stack, a seeded
     end-to-end flow, a server you start and poll) goes to a built-in `worker` briefed
     with [references/run-the-change.md](references/run-the-change.md), the commands,
     what should happen and the evidence to bring back; fix what it reports and send
     it again. For anything rendered, render it, screenshot it at the viewports that
     matter, and look at the images before you report.
   - Tests that touch a paid model API mock those calls by default; an API key is
     only for the few live-integration tests. Test a prompt, skill or agent with
     `codex exec` on the ChatGPT sign-in, as testing-without-api-spend.md says.
   - **Push the branch and open the review** by default; it needs no extra go. Open it
     as a draft when the brief says so. Never merge it, never enable auto-merge, never
     push to the default branch and never force-push. A brief that says "do not push"
     or "leave it local" wins; then leave the commit on the branch and put the branch,
     the filled-in push and create commands and a drafted title and body in the report.
   - Paste failures and say which are yours and which were already there. When a
     test looks wrong, say so; never code around it.

For work that will take many turns toward a checkable finish line, also read
[references/long-work.md](references/long-work.md). For multi-hour work that spans
sessions, also read [references/execplan.md](references/execplan.md).

## Split the work

You run on the session's model, usually the most expensive one in play. Spend it
on decisions, and send every unit with a crisp spec to a cheaper subagent. This
section is for the session that ran `$eng`. A spawned `eng` agent does its own
brief and may use only the built-in `explorer`, and only if it can spawn at all (the
Codex docs do not say how deep spawning nests); when it cannot, it grounds the unit
itself and says so. Any other spawned unit spawns nothing. The session that ran
`$eng` owns the `reviewer` pass and the built-in review on the combined diff.

**When.** After grounding, list the units. For each, note what it finds or
changes, whether it reads or writes, the files it owns, its hardest call, and its
tier and effort from the model guide. Delegate a unit when it is self-contained and
its own work clearly outweighs a subagent's fixed cost: every Codex subagent starts
with about 21–25K tokens of context before doing anything (measured 2026-10-07),
mostly cached after its first call. Keep a unit inline when it is one search or one
edit, or when its brief would be longer than the change. When the brief holds more
than three or four separable units, write the split down before building and send
out every unit whose interface you can fix first.

**Where each unit goes.**

| Unit | Agent | Tier / effort |
| --- | --- | --- |
| Grounding in another area of the repo, or more than about three unread files | built-in `explorer` (read-heavy; it inherits the session's sandbox, so its brief says not to edit), one per area, returning every `file:line` fact it finds | `fast` / `high` |
| Mechanical writes: renames, config, fixtures, docs, test scaffolding, one edit repeated across call sites | built-in `worker` | `fast` / `high` |
| Spec-driven code inside an existing seam | built-in `worker` | `workhorse` / `medium` |
| A sizable piece that needs its own grounding and review | the `eng` agent | `frontier` / `medium` by default; a model and effort named for the unit (a ticket's labels, say) win |
| Running the change end to end (step 9) | built-in `worker` briefed with run-the-change.md | `workhorse` / `medium` |
| The gate run | built-in `worker` returning failing test ids with each one's first error line, or the commands run, each wall time and "all passed" | `fast` / `high` |
| The adversarial review of every diff (step 8) | the `reviewer` agent | `workhorse` / `high`; `frontier` / `medium` for the sensitive areas |

Keep in this session the simpler-path check, every design decision, your own
review of the combined diff, and the report. A typical feature uses two to five
children; a one-file fix uses only the reviewer.

**How.** Resolve every tier's model in one call with
[scripts/resolve_model.py](scripts/resolve_model.py) `--all`. Spawn all independent
units in one turn, each with `model` and `reasoning_effort` set explicitly; no
agent file in this pack pins a model, so the spawn decides. Give each child a brief
that stands alone: the goal, the exact files it may touch, the spec or interfaces,
the test command, how to commit (by path, on its own branch, never push), and what
to return, following the return contract in the model guide. Children do not read
the repo's rules files or the user's standing preferences, so put any rule that
bears on the unit into its brief, and name the standards file for any unit that
writes code. Each write unit gets its own git worktree
(`git worktree add <path> -b <branch> origin/<default-branch>`) unless it is the
only writer. Wait for every child.

**After.** Read each child's summary and its diff before trusting it. Bring the
branches into your tree yourself (cherry-pick or merge), then review and verify the
combined change. Remove each worktree and its throwaway branch once its commits
are in. Ending your turn is final, so never end it while a child you depend on is
still running. When the sandbox refuses `git worktree add` or a child's commit, run
the write units one at a time in this tree and say so in the report.

## Gotchas

- A custom agent file that sets `model` or `model_reasoning_effort` overrides the
  spawn's values. No agent file in this pack sets either, so every spawn passes both.
- A spawn that names only a model gets that model's default effort. Name both.
- `/review` is interactive; use the `codex review` CLI.
- A skill cannot change the session's own model or effort; only the user's choice or
  `config.toml` does. Work that needs another setting goes to a subagent.

## Report

Done means the change is committed on a branch with its review open, the `reviewer`
rounds and Codex's built-in review ran on the final diff and their findings were
addressed, the touched gates ran once on the merged tree, and the real path was
exercised. Your final message is for the user:

- Lead with what changed and what it does for them now, then the branch and the
  review link (or, when no review could be opened, why not and where the branch is).
  Say plainly that nothing was merged.
- Files touched, as clickable repo paths; the commands you ran with their results;
  which gates ran, which were left to CI, and each gate's wall time; and how you
  confirmed the covering test ran the changed path. Each test you deleted or merged,
  with its reason, as the review body lists it.
- A docs line: "Docs: updated" with the files, or "Docs: not needed" with the
  reason. A missing docs line reads as docs nobody considered.
- What the review found: what you fixed, what was wrong (with the reason), and what
  you left (each also a follow-up). Say whether the `reviewer` agent ran, in how many
  rounds, and what you did with each finding. Include the built-in `codex review`
  command, the reviewed commit and its result, or what blocked it, and the Claude read's
  result or the one line saying why it was skipped.
- Each loop or string literal you kept and each pattern you chose not to use, one
  line of why.
- The better version, if you saw one: built, or offered for the user to pick.
- The split: each child, including the reviewer, with its tier and effort, and the
  units you kept inline with the reason. One line each.
- When the setting you ran on was wrong for the work: which axis (more effort on
  the same model, or a different tier) and the decision that needed it.
- Assumptions, deferrals and anything you could not verify. A choice a standing rule
  made for you (an `AGENTS.md` rule, the pack's landing rule, a preference in
  `config.toml`) is not an assumption; leave it out.
- Every intention you stated along the way, closed out: done, blocked with the
  reason, or dropped with the reason.
- **Follow-ups**, last: one line each, with `file:line` where it applies, for every
  review finding you did not fix (declined or deferred; not one that was wrong) and
  every known gap the change leaves: a `TODO` left in code, a path with no test, an
  assumption that needs confirming, a deferral, an improvement outside the brief, and
  a pre-existing problem you noticed. Write `None` when there are none.

A follow-up needs a ticket; a line in the report is not enough. When the repo or the
brief gives you a ticket workflow (the pack's ticket registry, or a tracker the brief
names), file each one once the review is open: follow `$write-ticket` for the ticket
shape and commands, check that no existing ticket already covers it (comment the new
evidence there instead), end the body with `Found in <review link>`, and put the
ticket number on its line. With no such workflow, say so and leave the list for the
user to file. Never invent a tracker, and put no secret or customer data in a ticket.

Write short paragraphs in plain language, lists only for parallel items, and no tool
narration. Durable output (research, designs, audits) goes in the repo's own place
for it, committed. Delete throwaway files; never hand back a temporary path.
