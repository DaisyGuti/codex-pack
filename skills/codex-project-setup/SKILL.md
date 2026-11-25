---
name: codex-project-setup
description: Use when asked to set up, onboard or prepare a repository for Codex, or to create, refresh or audit that repo's AGENTS.md from its real files. Not for rewording an existing prompt or agent file (prompt-optimizer), and not for the global ~/.codex/AGENTS.md.
---

# Codex project setup

Give a repository an `AGENTS.md` that tells Codex what it cannot infer from the
code: where the rules live, the real commands, what done means, how work lands, the
team's security rules, and what needs approval. Every fact comes from a file in the
repo. Ask a question only after the draft exists, and only where a step below says
the choice is the user's (steps 4 and 7).

## Boundaries

- Read anything in the repo and every instruction file Codex will load.
- Write only the repo's `AGENTS.md`, at the repo root unless the user names another
  directory. An existing `AGENTS.md` that is empty or holds only placeholders counts
  as absent. Step 7's context-budget guard adds a copy of the check script,
  `.context-budget.toml` and one check entry, and only after the user says yes.
- When neither the working directory nor a path the user gave is inside a git
  repository, ask for the repo path and stop.
- This skill fixes facts (commands, paths, landing rule, security rules, approvals).
  Sharpening the wording of an `AGENTS.md` for the model that reads it is
  `$prompt-optimizer`'s job.

## Steps

1. **Scan.** Run `python3 scripts/scan_repo.py <repo path> < /dev/null` (execute it; do
   not read it). It prints JSON: host (GitHub or GitLab), default branch, the
   instruction files present (`AGENTS.md`, `AGENTS.override.md`, `CLAUDE.md` and
   others), package scripts, Makefile targets, CI files with their `run:` and `script:`
   commands, lockfiles, Dockerfile base images and whether each is pinned by digest,
   GitHub Actions pinned or not, the review templates and `CODEOWNERS`, and how many of
   the last 30 commits are signed or follow Conventional Commits. It needs Python 3.12
   or later and `git`.
2. **Read what exists.** Any `AGENTS.md` or `AGENTS.override.md` from the repo root
   down to the working directory, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`, the CI
   files the scan lists and the pull or merge request template.
3. **Fill the template** at [assets/AGENTS.template.md](assets/AGENTS.template.md).
   - Link to existing rules files and copy nothing from them. When `CLAUDE.md` holds
     the project's rules, `AGENTS.md` names it and adds only what Codex needs on
     top.
   - **Commands.** Take each from a manifest script, a Makefile target or a CI step
     the scan lists, and name the source in parentheses. Write `UNKNOWN` for a fact
     that applies here and that the repo does not state, such as a command or a
     required reviewer; never guess one. Delete any line or section that does not
     apply to this repo or that the repo has nothing for.
   - **Landing changes.** The first line always reads: branch, then open a pull
     request (merge request on GitLab) into the default branch, never a commit to it.
     Use the host the scan reports. Add the repo's own review requirements after it,
     each from a file that states it: code owners, the template to fill, title or
     label conventions, what must pass before a merge. Never write "commit straight
     to main", whatever the history shows. Name Conventional Commits only when most
     sampled commits follow it or a file says so. Keep the signed-commits line only
     when `gpgsign_config` is `true` or most sampled commits carry a signature;
     this skill never turns signing on.
   - **Security rules.** Keep the section as written. Fill the secret mechanism, the
     example env file and the lockfile from the scan; delete a clause the repo has no
     answer for. Add a repo-specific rule only when a repo file states it. When the
     scan shows unpinned base images or unpinned Actions, add one line under
     Dependencies naming them as a known gap for a person to fix; do not rewrite the
     Dockerfile or workflow here.
   - Include only facts that change how an agent works in this repo. Leave out
     history, progress notes and anything the code already makes obvious.
   - For Models and delegation, take the tier and effort from the table in
     [references/model-selection.md](references/model-selection.md) (routine work is
     usually `workhorse` at `medium`). Write tier names only; the resolver supplies
     slugs at run time.
   - Code Review Rules come only from rules the repo already states, each as the
     behavior to flag plus the safe path. The heading is exactly `## Code Review
     Rules`: GitHub review reads the one in the `AGENTS.md` closest to the code the
     rule governs, and it reports only the top two severities, so write each rule as a
     behavior that deserves one. Delete the section when there are none.
   - When the repo's tests call a model API, record under Commands which tests need a
     real key and how the others run without one, if the repo's files say so;
     otherwise write `UNKNOWN`.
   - Remove every template comment and `{{placeholder}}`.
4. **Audit for conflicts.** Compare the draft against the other instruction files
   Codex will load, including `~/.codex/AGENTS.md` (or `AGENTS.override.md` there) and
   every `AGENTS.override.md` or `AGENTS.md` between the repo root and the working
   directory (the closest file wins). Fix each conflict by changing the draft so the
   file that owns the fact stays its only copy, and leave every other file unchanged.
   List a conflict for the user when the right answer is theirs to choose. A rule in
   any of those files that says to commit or push to the default branch always goes
   in the report as a conflict with the pack's review-only rule: the draft keeps the
   review-only landing line, and the file holding the old rule stays as it is for the
   user to change.
5. **Check it.** Run `python3 scripts/check_agents_md.py <path to the AGENTS.md>
   < /dev/null`. It fails on a leftover placeholder or template comment, a file past
   Codex's 32 KiB read cap, a missing Commands, Landing or Security section, a landing
   rule with no pull or merge request, a secret-shaped string, a machine-specific path,
   a `make` target or package script that does not exist, and a relative link to a
   missing file. Fix each failure and rerun until it exits 0, then confirm every
   `UNKNOWN` it counts is in your report. Then run
   `python3 scripts/check_context_budget.py <repo> --path <working folder> < /dev/null`:
   it measures the chain Codex loads (the global file plus one file per folder from
   the root down) against 16 KiB per file and 32 KiB in total, and fails when the
   project chain passes `project_doc_max_bytes`, because Codex never reads text past
   that cap. When it is over, shorten the draft by linking to the document that owns
   the detail, or move area detail into a nested `AGENTS.md`.
6. **Land it** by review: a branch, a commit of only `AGENTS.md` by path so another
   session's staged changes stay out, a push of the branch, and a pull request (merge
   request on GitLab) opened with the CLI of the remote's host, filling the repo's
   template when it has one. Never commit or push to the default branch. With no
   remote, or a CLI that is missing or not signed in, leave the commit on the branch
   and say so. Retry a transient network failure up to twice, then stop and report
   with the file committed on the branch locally or left in the working tree.
7. **Offer the context-budget guard.** Run
   `python3 scripts/check_context_budget.py <repo> --all --json < /dev/null` and report
   each instruction file's size and whether any is over the per-file limit. Then ask in
   your reply whether to add the guard, which fails CI when an instruction file grows
   past its limit; write nothing for it unasked. On a yes, follow
   [references/context-budget-guard.md](references/context-budget-guard.md) and push
   the guard to the same review branch. On a no, leave the repo as it is.

When an `AGENTS.md` already exists, refresh it in place: keep rules that are still
true, correct stale commands and paths, and say in your report what you removed and
why. Background on each security rule and its source is in
[references/rules-and-sources.md](references/rules-and-sources.md).

## Report

The file path, the review link, a few lines on what it now tells Codex, every `UNKNOWN`
left for the user to fill, any conflict you resolved or left for them (including any
existing rule that says to commit to the default branch), the known gaps from the scan
(unpinned images or actions), the context-budget result, and the guard question.
