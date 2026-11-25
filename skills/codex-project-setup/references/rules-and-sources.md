# Why each rule is in the template, and where it comes from

Read this when a repo pushes back on a rule or asks where it came from. Fetch the page
again before quoting a number or a flag.

## Contents

- How Codex treats an AGENTS.md
- The Security rules section, rule by rule
- How a rule becomes enforced
- Judgment calls in the skill

## How Codex treats an AGENTS.md

Source: Codex manual, "Custom instructions with AGENTS.md" and "Project instructions
discovery" (<https://learn.chatgpt.com/docs/agent-configuration/agents-md.md>).

- Codex builds one instruction chain per run. It reads the global file in `CODEX_HOME`
  (`AGENTS.override.md` when non-empty, otherwise `AGENTS.md`), then walks from the
  project root (the folder holding `.git`, or the `project_root_markers` in
  `config.toml`) down to the working folder. In each folder it takes the first non-empty
  file of `AGENTS.override.md`, `AGENTS.md` and the names in
  `project_doc_fallback_filenames`, at most one file per folder.
- Files join root first, so a file closer to the working folder wins where two disagree.
- Codex skips empty files and stops adding project files once their combined size reaches
  `project_doc_max_bytes` (32 KiB by default). Text past that cap never reaches the model.
  `check_context_budget.py` measures the chain against that cap and a tighter budget.
- An `AGENTS.md` is guidance the model reads, not configuration Codex enforces.
- `AGENTS.override.md` is for a temporary or local override; Codex copies an ignored one
  into local managed worktrees. The team's rules belong in `AGENTS.md`.
- Codex's GitHub code review reads the `## Code Review Rules` section of the `AGENTS.md`
  closest to the code a rule governs.

## The Security rules section, rule by rule

| Rule in the template | Why | Source |
| --- | --- | --- |
| No secrets in code, config, tests, fixtures, logs, commits, tickets or prompts | A committed or prompted secret has to be treated as leaked; history keeps it | Team policy for government products |
| No customer, personal or controlled government data in prompts, fixtures or test output | Prompts and fixtures leave the boundary the data was approved for | Team policy for government products |
| Respect the lockfile; pin base images by digest | A tag is mutable; pinning to a digest keeps the same image even when a publisher replaces the tag | Docker build best practices, "Pin base image versions", <https://docs.docker.com/build/building/best-practices/> |
| Pin CI actions to a commit SHA | A bad actor would need a SHA-1 collision to slip a change into a pinned action | GitHub, Security hardening for GitHub Actions, <https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions> |
| Human review for authentication, authorization, payments, personal data, secrets | A wrong call here is expensive to unwind and is not caught by tests alone | Team policy for government products |
| Signed commits only when the repo already uses them | The scan reports `commit.gpgsign` and how many of the last commits carry a signature; the skill never turns signing on | Repo's own settings |

GitLab has no `uses:` line to pin. The nearest equivalent is pinning `include:` entries and
job images to a fixed ref or digest.

## How a rule becomes enforced

`AGENTS.md` text is advice. A rule that must hold every time belongs in a Codex hook
(`[[hooks.PreToolUse]]` in `config.toml` or `hooks.json`, user-level or in a trusted
project's `.codex/`; manual, "Hooks") or in a CI check. The template's Enforcement line
says so, so a reader knows which rules are enforced and which are guidance.

## Judgment calls in the skill

- **UNKNOWN over a guess.** A command the repo does not state is written as `UNKNOWN`,
  because a plausible wrong command costs every later session.
- **Lines the scan cannot support are deleted.** A signed-commits line in a repo that does
  not sign commits tells Codex to do something the repo does not ask for.
- **Landing line is fixed.** Branch, then pull or merge request, never the default branch.
  A repo whose files say "commit to main" gets the review-only line anyway, and the conflict
  is listed in the report for a person to settle.
