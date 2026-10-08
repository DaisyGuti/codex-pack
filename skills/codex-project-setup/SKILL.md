---
name: codex-project-setup
description: Use when asked to set up, onboard or prepare a repository for Codex, or to create, refresh or audit that repo's AGENTS.md from its real files. Not for rewording an existing prompt or agent file (prompt-optimizer), and not for the global ~/.codex/AGENTS.md.
---

# Codex project setup

Give a repository an `AGENTS.md` that tells Codex what it cannot infer from the
code: where the rules live, the real commands, what done means, how work lands, and
what needs approval. Ask a question only after the draft exists, and only where a
step below says the choice is the user's (steps 3 and 5).

## Boundaries

- Read anything in the repo and every instruction file Codex will load.
- Write only the repo's `AGENTS.md`, at the repo root unless the user names another
  directory. An existing `AGENTS.md` that is empty or holds only placeholders counts
  as absent.
- When neither the working directory nor a path the user gave is inside a git
  repository, ask for the repo path and stop.
- This skill fixes facts (commands, paths, landing rule, approvals). Sharpening the
  wording of an `AGENTS.md` for the model that reads it is `$prompt-optimizer`'s job.

## Steps

1. **Read what exists.** Any `AGENTS.md` or `AGENTS.override.md` from the repo root
   down to the working directory, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`, the
   dependency manifests, `Makefile` or `package.json` scripts,
   `.github/workflows/`, any pull or merge request template and `CODEOWNERS`, and the
   last 30 commits (`git log --oneline -30`) to see how the repo reviews work.
2. **Fill the template** at [assets/AGENTS.template.md](assets/AGENTS.template.md).
   - Link to existing rules files and copy nothing from them. When `CLAUDE.md` holds
     the project's rules, `AGENTS.md` names it and adds only what Codex needs on
     top.
   - Every command must appear in the repo: in a manifest, a script, CI or the
     README. Never guess one.
   - Write `UNKNOWN` for a fact that applies here and that the repo does not state,
     such as a command or a required reviewer. Delete any line or section that does not
     apply to this repo or that the repo has nothing for.
   - The landing line always reads: branch, then open a pull request (merge request
     on GitLab) into the default branch, never a commit to it. Add the repo's own
     review requirements after it, each from a file that states it: required
     reviewers or code owners, the pull or merge request template to fill, title or
     label conventions, and what must pass before a merge. Never write "commit
     straight to main", whatever the history shows.
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
3. **Audit for conflicts.** Compare the draft against the other instruction files
   Codex will load, including `~/.codex/AGENTS.md` and any `AGENTS.md` between the
   repo root and the working directory (the closest file wins). Fix each conflict by
   changing the draft so the file that owns the fact stays its only copy, and leave
   every other file unchanged. List a conflict for the user when the right answer is
   theirs to choose. A rule in any of those files that says to commit or push to the
   default branch always goes in the report as a conflict with the pack's review-only
   rule: the draft keeps the review-only landing line, and the file holding the old
   rule stays as it is for the user to change.
4. **Check it.** Run both checks and see them pass:
   - `grep -nE '\{\{|<!--' AGENTS.md` returns nothing, apart from comments that were
     already in an existing file you kept.
   - The combined size of `~/.codex/AGENTS.md` and every `AGENTS.md` from the repo
     root to the working directory stays under 32 KiB (32768 bytes), measured with
     `wc -c`. When it is over, shorten the draft by linking to the document that owns
     the detail.
5. **Land it** by review: a branch, a commit of only `AGENTS.md` by path so another
   session's staged changes stay out, a push of the branch, and a pull request (merge
   request on GitLab) opened with the CLI of the remote's host, filling the repo's
   template when it has one. Never commit or push to the default branch. With no
   remote, or a CLI that is missing or not signed in, leave the commit on the branch
   and say so. Retry a transient network failure up to twice, then stop and report
   with the file committed on the branch locally or left in the working tree.

When an `AGENTS.md` already exists, refresh it in place: keep rules that are still
true, correct stale commands and paths, and say in your report what you removed and
why.

## Report

The file path, the review link, a few lines on what it now tells Codex, every `UNKNOWN`
left for the user to fill, and any conflict you resolved or left for them, including any
existing rule that says to commit to the default branch.
