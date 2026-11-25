# Codex facts the ticket skills rely on

When a fact changes, this file is the one place to correct; the ticket skills and the
`ticket_worker` agent point here instead of restating it. Measured facts carry their date;
[docs/sources.md](../docs/sources.md) has the pages behind the rest.

## Contents

- Pack paths, the registry and state
- Worktrees for workers
- Checked on Linux and macOS
- Sandbox, approvals and signing
- Model and effort at spawn
- Instruction files a worker sees
- Review
- What does not port from Claude Code

## Pack paths, the registry and state

- `install.sh` links each skill folder into `${CODEX_HOME:-~/.codex}/skills/` and copies
  each file in `agents/` into the Codex agents folder. Codex refuses a symlinked agent file:
  `spawn_agent` answers "agent type is currently not available" (measured 2026-10-07). After
  any change in `agents/`, rerun `install.sh`.
- Codex substitutes nothing in a skill's text. A path written `${CODEX_HOME:-~/.codex}/...`
  is expanded by the shell when a command runs it, so anything handed to another agent (a
  dispatch message, a brief) carries absolute paths, never that form.
- The team's registry is `registry.md` in the pack root, created from `registry.example.md`
  by `install.sh` and reached from each skill as `references/registry.md`. Scripts live in
  the pack's `scripts/` and are reached from a skill through its `scripts/` symlinks.
- `STATE_ROOT` is `${CODEX_HOME:-~/.codex}/state`. It holds the run record
  (`ready-worker-<board key>-<login>.json`), the board watcher's memory, the worktrees of
  dispatched slots (`ready-worktrees/<board key>-<login>/<slot_id>/<repo>`) and those of
  direct runs (`solo-worktrees/<repo>-<issue>/`).

## Worktrees for workers

- Codex has no per-subagent worktree isolation. Whoever starts a ticket makes its worktrees
  with `git worktree add` from the registry's clone: `$work-tickets` for a dispatched slot,
  the `$ticket-worker` skill or the worker itself for the rest, sub-worker worktrees
  included. A subagent works in whatever path its brief names; nothing stops it writing
  elsewhere, so the rule to stay in its worktrees is the worker's own.
- Codex does not lock a worktree it did not make. A worktree that `git worktree list
  --porcelain` shows as `locked` was locked by someone else: leave it and report it kept.
- **Safe cleanup**, run by whoever started the worker, once its result is recorded, for each
  path in the result's `worktree_paths` (skip one already gone). Write `<path>` the way
  `git worktree list --porcelain` prints it: resolved, no trailing slash (`/private/tmp/...`
  on macOS; `cd <path> && pwd -P` gives that form). Remove it only when every check passes:
  1. `git -C <path> status --porcelain --untracked-files=all` prints nothing.
  2. `git -C <path> symbolic-ref -q HEAD` succeeds: it is on a branch.
  3. `git -C <path> fetch origin <branch>` and `git -C <path> merge-base --is-ancestor HEAD
     FETCH_HEAD` succeed: every commit is on the remote branch. When the fetch fails with
     `couldn't find remote ref` (the branch was deleted after its review merged), the check
     passes only when **review-state** reads `merged` or `closed`.
  4. No process has its working directory inside it: `lsof -d cwd -Fn` exits 0, writes
     nothing to stderr and lists no `n` line equal to `<path>` or starting with `<path>/`.
     Any non-zero exit (127 for a missing `lsof`) or stderr warning fails the check.
  5. It is not locked (above).

  Then, with `<clone>` the registry clone of that repo: `git -C <clone> worktree remove
  <path>` without `--force`, then `git -C <clone> worktree prune`. The branch keeps the
  commits. Run one removal per worktree at a time. A remove that fails with `could not open
  directory` or `is not a working tree` is read as another removal of the same path: check
  the worktree list and the directory again before reporting it kept. A remove that fails
  partway (`failed to delete`) has already unregistered the worktree, so the leftover
  directory is kept and reported, never `rm -rf`'d. A worktree that fails a check is kept and
  named in the report with the check it failed.

## Checked on Linux and macOS

Run 2026-11-20 for the Claude Code version of this pack, on macOS and Debian 12 (lsof 4.95.0,
git 2.39.5); the commands are the same here.

- `lsof -d cwd -Fn` exits 0 with empty stderr and one `n<path>` line per process directory,
  and exits 0 with no match. A missing `lsof` exits 127. As a non-root Linux user it does not
  list a root-owned process's cwd and prints no warning, so the check covers only processes of
  the cleaning user, which is who runs a worker's shell. A process that writes into a worktree
  from a cwd outside it (a file watcher, a Docker bind mount) is invisible too, so the worker's
  own cleanup (stop what you started) is the guard.
- Two concurrent `git worktree remove` runs on one worktree left a half-deleted `.venv` in a
  live run; a Linux reproduction did not trigger the race. The one-removal-at-a-time rule
  above is the guard.

## Sandbox, approvals and signing

- The default `workspace-write` sandbox keeps every `.git` read-only, even with extra
  writable directories, so a commit cannot happen inside it. A ticket worker needs Codex
  launched with full access; its preflight proves it with a `fetch` and a write test.
- A subagent runs under its parent's sandbox and approval settings. A live `/permissions`
  change or `--yolo` in the CLI is reapplied to children, even over an agent file's
  `sandbox_mode` (see `agents/reviewer.toml`).
- A worker cannot unlock a locked GPG or SSH signing key: there is no terminal for the
  passphrase. It never turns signing off; it stops with `blocked_sandbox`,
  `reason="signing key locked"`, keeps the change staged, and the run resumes in the same
  worktrees once the user has unlocked the key in their own terminal (for example by signing
  one test message so the agent caches the passphrase).

## Model and effort at spawn

- A subagent takes its model and effort from the spawn, then the `[agents]` defaults in
  `config.toml`, then the parent. An agent file that sets either overrides all of them
  (measured 2026-10-07), so no agent file in this pack sets one, and every spawn names both,
  from `resolve_model.py` ([model-selection.md](model-selection.md)).
- A skill cannot change the session's own model or effort. Work that needs another setting
  goes to a spawned subagent.
- Running threads are capped by `agents.max_concurrent_threads_per_session` in
  `config.toml` (older name `agents.max_threads`). A spawn over the cap is refused; never
  retry it in a loop.
- Codex documents no depth limit for a subagent spawning its own. A ticket worker spawns
  the read-only `reviewer` agent and sub-workers (the built-in `worker` agent); when a spawn
  is refused (the thread cap, multi-agent off, the agent not installed) it does that unit
  inline and says so.
- Each subagent starts with about 21-25K tokens of context before any work (measured
  2026-10-07), mostly cached after its first call.

## Instruction files a worker sees

- Codex loads the `AGENTS.md` files from the session's project root down to its working
  folder when the session starts, and truncates the combined text past
  `project_doc_max_bytes`. A worker's worktree is not that folder, so the worker reads the
  worktree's `AGENTS.md` (or a root `CLAUDE.md` in a repo with no `AGENTS.md`) and
  `CONTRIBUTING.md` itself.
- An oversized guide costs every worker that reads it. `$work-tickets` measures them with
  `${CODEX_HOME:-~/.codex}/skills/codex-project-setup/scripts/check_context_budget.py` and
  names the large ones in a dispatch message's `large_guides`; a worker greps those and
  reads only the part it needs.

## Review

- `codex review` is Codex's built-in review, run non-interactively from the CLI:
  `codex review --base origin/<default_branch> < /dev/null` for a committed branch,
  `--uncommitted` for pending files. `/review` is the interactive form; skills never use it.
  It spends the ChatGPT plan, not an API key
  ([testing-without-api-spend.md](testing-without-api-spend.md)).
- A session that is itself a built-in review never launches another review.
- After Codex's rounds, a worker runs one read-only Claude read when `command -v claude`
  finds the Claude CLI: the diff on stdin to `claude -p` with only the Read, Grep and Glob
  tools (the standards file's review rule has the command and prompt). It spends the user's
  Claude allowance and is skipped, with a note, when the CLI is missing or not signed in.
- The `reviewer` agent is read-only (`sandbox_mode = "read-only"`) and answers with one JSON
  object of findings and a verdict, or `could not review`.
- After a review opens, Codex cloud's GitHub or GitLab integration can review it when someone
  mentions `@codex` or the team turns on automatic reviews. That is a team setting; the skills
  never change it.

## What does not port from Claude Code

- **Worktree isolation and locks.** Claude Code's `isolation: worktree` and its per-session
  worktree locks have no Codex counterpart; the cleanup above drops the unlock and re-lock
  steps.
- **Turn cap.** Codex custom agents have no `maxTurns`. The per-run cap on follow-up tickets
  stays, so filing cannot swamp a run.
- **Auto-fix.** Codex has no local tool that binds a review and wakes a session on a CI
  failure, a conflict or a comment. The board watcher's `CONFLICT` events and the next
  `$work-tickets` run pick up conflicts; Codex cloud's review (above) covers comments on
  request.
- **A Monitor tool.** `$work-tickets` runs `watch_board.py --once` as its poll tick, or a
  long-running `watch_board.py` in a background terminal when the client offers one.
- **Questions to the user** go in the reply; there is no question tool.
