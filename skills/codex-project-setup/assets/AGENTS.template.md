# AGENTS.md — {{project name}}

<!--
Template from codex/skills/codex-project-setup; its SKILL.md says how to fill it.
Delete this comment. Keep the file a short router: durable rules, one owner per
fact, links in place of copies. Codex follows it closely, so a stale line becomes a
wrong instruction. The whole AGENTS.md chain stays under 32 KiB.
-->

## What this repo is

{{One paragraph: what the product does, who uses it, and what "working" means
for it.}}

## Where the rules live

{{List each file that owns project rules and what it owns, for example
"`CONTRIBUTING.md`: conventions and landing rule" or "`docs/decisions/`: accepted
decisions". Read these before changing code. Delete this section when this file is
the only rules file.}}

## Commands

- Setup: `{{command}}`
- Run locally: `{{command}}`
- Tests, narrow: `{{command for one file or test}}`
- Tests, full: `{{command}}`
- Lint, format, typecheck: `{{command}}`

## Definition of done

- {{The checks that must pass before work counts as done.}}
- {{How to exercise the real path: a dev server URL, a CLI invocation, a fixture.}}
- {{For visible changes: the viewports to screenshot and look at before reporting.}}

## Landing changes

- {{"Commit straight to `main` and push" or "Branch and open a pull request; merge
  when CI is green unless it carries label X".}}
- Commit messages: {{style, for example Conventional Commits}}.
- {{Push helper or release script, if the repo has one.}}

## Conventions

- {{Language, framework and version pins; the idioms this repo follows.}}
- {{Layout: where new modules, tests and assets go.}}
- Durable output: research with sources in `{{path}}`, designs in `{{path}}`,
  decisions in `{{path}}`.

## Ask before

- {{Repo-specific actions that need the user's approval: deploys, migrations,
  paid services, production data, secrets, public posts.}}

## Models and delegation

- Routine changes here: `{{tier}}` tier at `{{effort}}` effort (tiers and the
  resolver are in `${CODEX_HOME:-~/.codex}/skills/eng/references/model-selection.md`).
- Escalate to `frontier` for {{the areas where a wrong call is expensive}}.
- Safe to parallelize: {{read-heavy units, or independent packages}}. Parallel
  writes only in separate git worktrees.
- For a complex feature or a significant refactor, write an ExecPlan first and keep
  it current (`${CODEX_HOME:-~/.codex}/skills/eng/references/execplan.md`).

## Code Review Rules

<!-- Read by Codex code review on GitHub. One rule per bullet: the behavior to flag,
then the safe path. Leave formatting and lint to CI. Delete the section if empty. -->

- {{Behavior to flag.}} Safe path: {{what to do instead}}.
