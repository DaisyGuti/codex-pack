---
name: eng
description: Use when asked to fix a bug, build a feature, refactor, change architecture or review a diff in a code repo. Splits the work onto cheaper subagents. Not for judging how a screen looks (ux-review, web-design-guidelines) or questions with no code behind them.
---

# Engineering pass

Do the job end to end in the repo you were pointed at, and land it the way that
repo lands work. Invoking this skill is a request to verify: add the tests the
standards call for and run the gates in step 9.

Carry the work through to the landed change and the report in this turn. When a
detail is missing, pick the most reasonable assumption, write it in the report and
keep going. Stop to ask only for the cases step 3 names, for an approval the repo's
rules require (anything public, paid or production, deleting data), for a secret or
access you lack, or for a blocker you cannot clear; then say what you tried and what
would unblock you. When you notice you are re-reading or re-editing the same files
without progress, stop and report instead of looping.

## Read first

- **The repo's rules.** Codex has loaded the `AGENTS.md` chain. Read the rules
  files it points to (often `CONTRIBUTING.md` or a docs folder).
- **The craft standards:**
  [references/engineering-standards.md](references/engineering-standards.md). They
  apply to every engineer using this pack and bind you across every step
  below. If the file is missing, say so in your report and continue with this
  pass.
- **Model and effort:** [references/model-selection.md](references/model-selection.md),
  before you spawn anything. Inline work runs on whatever the user chose for this
  session.

When another session spawned you for one unit, read only what your brief names,
plus the standards when the unit writes code; skip the rest of this list.

## Handle the request

- **A review of existing code:** answer it directly and skip the build steps. Lead
  with findings ordered by severity, each with a `file:line`, then open questions.
  With no findings, say so plainly and name the residual risks and test gaps. When
  the target is a diff or a branch above the size step 8 gives, run it past the
  `reviewer` agent as step 8 describes, so the review comes from a fresh context.
  For any diff, tell the user that Codex's built-in `/review` gives another
  independent pass, and offer to write the criteria they want checked as custom
  review instructions for them to paste.
- **Several jobs in one message:** list them, then do all of them.
- **A repo, path or issue that does not exist:** say what you found and stop.

## The pass

1. **Name it.** Fix, feature, or both. A fix that needs a schema change first is
   both, and both halves get done.
2. **Ground in the real code.** Never describe or change code you have not opened.
   Read the modules involved and their tests. For a fix, reproduce it first with a
   failing test, a real run or exact log output; when you cannot reproduce it, list
   what you checked before proposing anything. For a feature, find the existing
   seam it belongs in. Read the repo's recorded decisions (ADRs, design docs) and
   stored measurements before measuring anything again: an evidenced answer is an
   answer, and a claim nobody measured is still open. When grounding spans more
   than one area of the repo, send explorers (see Split the work) and read their
   summaries instead of every file yourself.
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
   writing new code against a fast-moving library or API (OpenAI, Anthropic,
   LangGraph, MCP, any SDK released this year), fetch its current documentation;
   when it is unreachable, mark the line `UNVERIFIED:` with your assumption.
   While you iterate, run the cheap gates and only the tests that cover what you
   are touching.
7. **Consider the next version up,** once, when the simple version works. The
   standards document carries this rule.
8. **Review the diff adversarially, before the verification run.** With children,
   this is the combined diff after you integrate their work. The standards document
   says what to hunt for.
   - **Small diff:** review it yourself. Small means 150 changed lines or fewer
     (added plus removed, ignoring lockfiles, generated files and snapshots) across
     5 files or fewer, with none of the sensitive areas below.
   - **Larger diff, or any size that touches authentication, payments, personal
     data, migrations or deletion:** review it yourself and also send it to the
     `reviewer` agent, a read-only reader that did not write the code. Spawn it with
     `model` and `reasoning_effort` set from the model guide: `workhorse` / `high`,
     or `frontier` / `medium` for the sensitive areas. Its brief names the command
     that prints the diff (`git diff <base>...HEAD`, or `git diff HEAD` plus the
     untracked files `git status --short` lists for uncommitted work), what the
     change is meant to do, and the repo's rules files. It answers with one JSON object:
     `findings` (each with `title`, `body`, `priority` 0 to 3, `confidence_score`
     and `code_location`), then `overall_correctness` (`patch is correct`, `patch is
     incorrect` or `could not review`), `overall_explanation` and
     `overall_confidence_score`. Its scope check lists additions the brief did not ask
     for as findings titled `Unrequested:`.
   - **Weigh the findings.** Open the cited lines before you act on one. Fix what
     holds up, and report each one you decline with the reason. A reply that is not
     that JSON object, misses fields, or cites lines that do not exist is a failed
     review: run it once more, then fall back to your own review and say so. It is
     never an empty result. A `could not review` reply means the reviewer had no
     usable diff, brief or files: supply what it names as missing and run it once
     more; if it still cannot, review inline. Report it as "the reviewer could not
     review, because ...", never as "no findings" or a pass. When the `reviewer`
     agent is not installed, review inline and say so.
   - Fix what you find before step 9, so the tests run on the fixed state.
9. **Verify, then land.**
   - Find the landing rule in the repo's instruction files; failing that, read
     recent `git log` and `.github/workflows/` to see whether work arrives by direct
     commit or by pull request. When the repo names a push helper or a verification
     recipe, use it.
   - Commit by path. Never run `git add -A`, `git add .` or `git commit -a`. Run
     `git status --short` right before committing and confirm every staged path is
     yours. Never rebase in a shared tree, amend, or force-push unless the user
     asked. On a long run, commit as each piece works; documentation lands in the
     same commit as the code it describes.
   - Run the full gates once, on exactly what you will push, and push only after
     they pass: before the commit when the repo requires that, otherwise on the
     commit, from a clean checkout of it when `git status` still shows other
     changes. Beyond what the standards require each change to ship with, broaden
     or repeat test runs only when a new failure or concern justifies it.
   - The default `workspace-write` sandbox keeps `.git` read-only, so a commit may
     need approval or fail. When it is refused, say so in your report and leave the
     change ready to commit; never loop on it.
   - Confirm the test meant to cover the change ran the changed code path, since a
     green test that never reached it proves nothing. For a fix, watch it fail
     without the change (run it on the parent commit in a throwaway worktree, never
     by stashing or reverting in the shared tree); otherwise point to a name,
     assertion or output that only the new path produces. Say which in the report;
     when you cannot show it, report the test as unconfirmed.
   - Exercise the changed path where tests cannot reach it: a live run, a real
     request. A test that already drives that path end to end is enough.
   - Tests that touch OpenAI's API mock those calls by default. Spend an API key
     only on the few live-integration tests that must prove the real call, against a
     project with a spending limit. When the task is testing a prompt, a skill or an
     agent, run it with `codex exec` or the Codex SDK on the ChatGPT sign-in, which
     costs no API money.
     [references/testing-without-api-spend.md](references/testing-without-api-spend.md)
     has the commands and the checks to run before a batch.
   - For anything rendered, render it, screenshot it at the viewports that matter,
     and look at the images before you report.
   - Paste failures and say which are yours and which were already there. When a
     test looks wrong, say so instead of coding around it.

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
`$eng` owns the `reviewer` pass on the combined diff.

**When.** After grounding, list the units. For each, note what it finds or
changes, whether it reads or writes, the files it owns, its hardest call, and its
tier and effort from the model guide. Delegate a unit when it is self-contained and
its own work clearly outweighs a subagent's fixed cost: every Codex subagent starts
with about 21–25K tokens of context before doing anything (measured 2026-10-07),
mostly cached after its first call. Keep a unit inline when it is one search or one
edit, or when its brief would be longer than the change.

**Where each unit goes.**

| Unit | Agent | Tier / effort |
| --- | --- | --- |
| Grounding in another area of the repo, or more than about three unread files | built-in `explorer` (read-heavy; it inherits the session's sandbox, so its brief says not to edit), one per area, returning every `file:line` fact it finds | `fast` / `high` |
| Mechanical writes: renames, config, fixtures, docs, test scaffolding, one edit repeated across call sites | built-in `worker` | `fast` / `high` |
| Spec-driven code inside an existing seam | built-in `worker` | `workhorse` / `medium` |
| A sizable piece that needs its own grounding and review | the `eng` agent | `workhorse` / `medium`; `frontier` / `medium` only when its hardest call is in the guide's frontier row |
| The full gate run | built-in `worker` returning failing test ids with each one's first error line, or the commands run and "all passed" | `fast` / `high` |
| An independent review of a larger diff (step 8) | the `reviewer` agent | `workhorse` / `high`; `frontier` / `medium` for the sensitive areas |

Keep in this session the simpler-path check, every design decision, your own
review of the combined diff, and the report. A typical feature uses two to five children; a
one-file fix uses none.

**How.** Resolve every tier's model in one call with
[scripts/resolve_model.py](scripts/resolve_model.py) `--all`. Spawn all independent
units in one turn, each with `model` and `reasoning_effort` set explicitly; no
agent file in this pack pins a model, so the spawn decides. Give each child a brief
that stands alone: the goal, the exact files it may touch, the spec or interfaces,
the test command, how to commit (by path, on its own branch, never push), and what
to return, following the return contract in the model guide. Children do not read
the repo's rules files or the user's standing preferences, so put any rule that bears on the unit into its brief. Each write unit gets its
own git worktree (`git worktree add <path> -b <branch> origin/<default-branch>`)
unless it is the only writer. Wait for every child.

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
- `/review` is a command the user types. This skill cannot run it and must not claim
  to have.
- A skill cannot change the session's own model or effort; only the user's choice or
  `config.toml` does. Work that needs another setting goes to a subagent.

## Report

Done means the work is landed, the checks ran, and the real path was exercised.
Your final message is for the user:

- Lead with what changed and what it does for them now.
- Files touched, as clickable repo paths, and the commands you ran with their
  results, and how you confirmed the covering test ran the changed path.
- A docs line: "Docs: updated" with the files, or "Docs: not needed" with the
  reason. A missing docs line reads as docs nobody considered.
- What your adversarial review found: what you fixed, and what you left and why.
  Say whether the `reviewer` agent ran, what it found and what you did with each
  finding. The user can also run Codex's built-in `/review` ("Review against a base
  branch" or "Review uncommitted changes") for another independent pass; say so in
  one line, and never write that you ran it, because a skill cannot start it.
- The better version, if you saw one: built, or offered for the user to pick.
- Improvements you noticed outside the brief, one line each with a path.
- The split: each child, including the reviewer, with its tier and effort, and the
  units you kept inline with the reason. One line each.
- When the setting you ran on was wrong for the work: which axis (more effort on
  the same model, or a different tier) and the decision that needed it.
- Assumptions, deferrals and anything you could not verify.
- Every intention you stated along the way, closed out: done, blocked with the
  reason, or dropped with the reason.

Write short paragraphs in plain language, use lists only for parallel items, and
leave out the tool and subagent narration. Durable output (research with sources,
designs, audits) goes in the repo's own place for it and gets committed. Delete
throwaway files before you finish, and never hand back a temporary path.
