# OpenAI and Codex prompting sources behind the Codex pack

Read 2026-10-06, 2026-10-07 and 2026-10-08. Each entry says what the source established and where the pack applies it. Model
names in these pages change every few months; the pack resolves them at run time
(`scripts/resolve_model.py`) instead of quoting them.

## Model behavior and prompting

- **Prompt guidance / latest-model guide** —
  <https://developers.openai.com/api/docs/guides/prompt-guidance.md> (frontmatter
  `latestModelInfo.promptingGuide` points at
  `/api/docs/guides/latest-model/gpt-6-astra.md#prompting-best-practices`).
  GPT-6 Astra asks more clarifying questions and can stop early, so prompts should
  grant action on authorized work and ask for approval only after a concrete,
  reviewable result. It follows `AGENTS.md` and skill files closely, so conflicting
  guidance makes it pause; state that user instructions win and have it name the
  file and line behind a pause. It over-formats and repeats stock phrases unless a
  style is specified. It delegates less than wanted unless told when and how much.
  It over-tests small changes unless testing is calibrated. Applied in:
  `AGENTS.md` and the prompt optimizer's checklist.
- **Reasoning models** — <https://developers.openai.com/api/docs/guides/reasoning.md>.
  Effort levels `low` to `max` (plus `ultra` in Codex), model-dependent defaults
  (Sol and Luna default `medium`), "treat `reasoning.effort` as a tuning knob, not
  the primary way to recover quality", and "define what counts as done and how the
  model should verify its work". Applied in: `references/model-selection.md`,
  the optimizer's outcome-contract item.
- **Model selection** — <https://developers.openai.com/api/docs/guides/model-selection.md>
  and <https://learn.chatgpt.com/docs/model-selection.md>. Seven anchor settings:
  Luna low (fine edits, simple extraction), Luna xhigh (context across sources,
  prioritizing with clear constraints), Sol medium (complex technical work), Sol
  xhigh (decisions from conflicting evidence), Astra low (concise writing that
  preserves facts and nuance), Astra medium (ambitious broad-context work), Astra
  xhigh (exacting analysis). "Keep the lightest setting that meets your quality
  bar." Applied in: the tier table in `model-selection.md`.
- **Codex models** — <https://learn.chatgpt.com/docs/models.md>. GPT-6.1 Sol is the
  recommended workhorse where available (rolling out; it reached this account the
  evening of 2026-10-06, and the resolver's `--check` flagged the agent defaults
  within the hour), Luna for clear repeatable work, Astra for the hardest end-to-end
  work. Start Luna at High and Astra at Light (`low`). `max` for one hard problem;
  `ultra` spreads work over subagents. GPT-5.5 retires from Codex 2026-10-14.
  Applied in: the resolver's preference lists and default efforts.
- **Codex Prompting Guide** (cookbook, tuned on gpt-5.x Codex models) —
  <https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide.md>.
  Starter prompt sections: autonomy and persistence (finish in-turn, bias to action,
  stop when looping on the same files), code implementation (search for prior art,
  no broad catches or silent fallbacks, keep type safety, coherent edits), editing
  constraints (never revert others' changes, no amend, no destructive git), plan
  closure (every stated intention ends done, blocked or cancelled), review mode
  (findings first by severity with file and line; residual risks when none),
  final-answer rules. Prompting for an upfront plan or status messages can end a
  rollout early. Metaprompting: ask the model what in its instructions slowed it,
  repeat, keep the common suggestions. Three defaults clash with this user's setup
  and were overridden: stopping on unexpected changes (working trees are often shared),
  ASCII-only edits (match the file), a bold default visual style (keep an existing
  design system's look). Applied in: `skills/eng`, `AGENTS.md`, the
  optimizer's forward test and target guidance.

## Codex surfaces

- **AGENTS.md** — <https://learn.chatgpt.com/docs/agent-configuration/agents-md.md>.
  Global file from `~/.codex` (`AGENTS.override.md` first), then root to working
  directory, one file per directory, later files override, 32 KiB combined cap
  (`project_doc_max_bytes`), `## Code Review Rules` section read by GitHub review.
- **Skills** — <https://learn.chatgpt.com/docs/build-skills.md> and Codex's bundled
  `~/.codex/skills/.system/skill-creator/SKILL.md`. Folder with `SKILL.md` (`name`,
  `description`); progressive disclosure (name and description, then body, then
  references); descriptions front-load triggers because they get shortened when
  many skills are installed; symlinked skill folders are followed; no README inside
  a skill; scripts for deterministic logic; forward-test complex skills with a fresh
  subagent given no expected answer. Custom prompts are deprecated in favor of
  skills (<https://learn.chatgpt.com/docs/custom-prompts.md>).
- **Subagents** — <https://learn.chatgpt.com/docs/agent-configuration/subagents.md>.
  Custom agents are TOML files in `~/.codex/agents/` with `name`, `description`,
  `developer_instructions`, optional `model`, `model_reasoning_effort`,
  `sandbox_mode`. A subagent inherits the parent's model and effort unless the
  spawn or its file sets them, and inherits the sandbox. Parallelize read-heavy
  work; be careful with parallel writes. A good spawn prompt says how to divide the
  work, whether to wait, and what to return.
- **Non-interactive mode** — <https://learn.chatgpt.com/docs/non-interactive-mode.md>.
  `codex exec` (read-only sandbox by default, `-s workspace-write`, `-o` for the
  last message, `--output-schema`, `--json`, `--ephemeral`, `resume --last`).
- **Speed** — <https://learn.chatgpt.com/docs/agent-configuration/speed.md>. Fast mode
  uses included limits at 2.5x; the pack leaves the speed tier as configured.

- **Code review** — <https://learn.chatgpt.com/docs/code-review.md> and
  <https://learn.chatgpt.com/docs/third-party/github.md> (read 2026-10-08). Local review
  is the built-in `/review` command in the composer: a dedicated reviewer reads the
  selected diff and reports prioritized findings without changing the working tree.
  The CLI offers a base branch, uncommitted changes, a commit and custom instructions;
  the app and IDE offer a base branch and uncommitted changes. `review_model` in
  `config.toml` switches the reviewer model. Pull requests go through the Code Review
  plugin, which reads `## Code Review Rules` in the `AGENTS.md` closest to the code and
  flags only P0 and P1 issues; `@codex review` in a PR comment starts one. Reviewing in
  chat posts nothing. No page says a skill or subagent can start `/review`, so `$eng`
  never claims to have run it and tells the user the command instead. Applied in:
  `skills/eng` (step 8 and the report), `skills/codex-project-setup`.
- **Custom agents and config keys** — the Subagents page above plus
  <https://learn.chatgpt.com/docs/config-file/config-reference.md> (read 2026-10-08).
  The built-in agents are `default`, `worker` and `explorer`; `explorer` is described as
  read-heavy and a child inherits the parent's sandbox, so it can write in a
  workspace-write session. In the CLI a live `/permissions` change or `--yolo` is
  reapplied to children and beats the agent file's `sandbox_mode`. Keys used by the
  pack's model guide: `model`, `model_reasoning_effort`, `service_tier` (`fast` maps to
  the request value `priority`), `review_model`, `agents.default_subagent_model`,
  `agents.default_subagent_reasoning_effort`, `agents.max_concurrent_threads_per_session`
  (legacy alias `agents.max_threads`). Neither page documents a nesting depth for
  spawning. Applied in: `agents/reviewer.toml`, `agents/forward_tester.toml`,
  `agents/eng.toml`, `references/model-selection.md`.
- **Agent Skills specification** — <https://agentskills.io/specification>,
  <https://agentskills.io/skill-creation/best-practices>,
  <https://agentskills.io/skill-creation/optimizing-descriptions> and
  <https://agentskills.io/client-implementation/adding-skills-support> (read
  2026-10-08). `name`: 1 to 64 lowercase letters, digits and single hyphens, equal to
  the folder name; `description`: 1 to 1,024 characters, written as an instruction
  ("Use this skill when ...") from the user's intent, with boundaries against adjacent
  skills; SKILL.md under 500 lines and about 5,000 tokens; references one level deep;
  quote a description that has a colon and a space. Test a description with about 20
  labeled queries (8 to 10 should trigger, 8 to 10 near-misses should not), run each
  about three times, split roughly 60/40 into train and validation, and pick the best
  iteration by validation pass rate. Codex adds the catalog budget (2% of the context
  window, 8,000 characters when unknown, shortened descriptions first) and
  `agents/openai.yaml`. Applied in: the four core skills' descriptions and
  `evals/triggers/`.
- **Codex SDK and authentication** — <https://learn.chatgpt.com/docs/codex-sdk.md>,
  <https://learn.chatgpt.com/docs/non-interactive-mode.md>,
  <https://learn.chatgpt.com/docs/auth.md> and <https://learn.chatgpt.com/docs/pricing.md>
  (read 2026-10-08). The SDK and `codex exec` drive the local Codex agent and reuse the
  saved ChatGPT sign-in by default; an API key switches billing to API rates and is
  needed when the code under test calls OpenAI's API itself. Applied in:
  `references/testing-without-api-spend.md`, `skills/eng`, `skills/prompt-optimizer`.

## Codex cookbook recipes (topic page <https://developers.openai.com/cookbook/topic/codex.md>)

- **Using Goals in Codex** — `/cookbook/examples/codex/using_goals_in_codex.md`. A
  Goal is a thread-scoped completion contract: outcome, verification surface,
  constraints, boundaries, iteration policy, blocked stop condition. Completion is
  evidence-based; a budget stop is not completion; skip Goals for small or vague
  work; the model may start a Goal and may mark it complete only on evidence.
  Applied in: `eng` "Long work", `work-tickets`, the optimizer's Goal line.
- **Build iterative repair loops** — `/cookbook/examples/codex/build_iterative_repair_loops_with_codex.md`.
  Review, repair and validate as separate phases with structured outputs; the
  fixer never declares success; stop on pass, attempt cap, unchanged delta, or a
  needed human. Applied in: the optimizer's loop exit rule, the delegation note in
  `model-selection.md`.
- **Iterating development workflows** — `/cookbook/examples/codex/iterating-development-workflows-with-codex.md`.
  `AGENTS.md` holds durable rules with one owner per fact; unknown commands are
  marked unresolved; never claim a check passed without running it; prefer
  tightening an existing skill over adding one. Applied in: `codex-project-setup`,
  the evidence rules in `eng`, `ticket-worker` and `AGENTS.md`.
- **Agent improvement loop** — `/cookbook/examples/agents_sdk/agent_improvement_loop.md`.
  Treat human feedback as evidence; diagnose a failure as a missing requirement, a
  requirement present but not followed, or a defect; turn each correction into a
  regression eval; say which source wins in a conflict and report the conflict.
  Applied in: the optimizer's `--evidence` diagnosis and eval handoff,
  `AGENTS.md`'s conflict line.
- **Modernizing your codebase** — `/cookbook/examples/codex/code_modernization.md`.
  A living plan (progress, decisions, surprises, outcomes) for long work. Applied
  in: `eng` "Long work".
- **Code quality and security fixes on GitLab** — `/cookbook/examples/codex/secure_quality_gitlab.md`.
  Strict machine-readable output with markers and schema validation, an explicit
  empty result, and (from its update note) never treat a failed run or invalid
  output as an empty findings result. Applied in: the optimizer's machine-read
  output item, `AGENTS.md`'s failure line.
- **Build code review with the Codex SDK** — `examples/codex/build_code_review_with_codex_sdk.md`
  (openai/openai-cookbook at commit `0eac144`, MIT). A seven-line reviewer prompt (flag
  only actionable issues the change introduces, no nit-level comments, cite exact lines)
  and a strict findings schema: `findings[]` with `title`, `body`, `confidence_score`,
  `priority` 0 to 3 and `code_location`, then a verdict and a confidence score. The page
  carries an "Archived example" banner about its CI workflow's token and permission
  layout; only the prompt and the shape were used. Applied in: `agents/reviewer.toml`.
- **PLANS.md for multi-hour work** — `articles/codex_exec_plans.md`. A self-contained,
  living design document with behavior-based acceptance, a progress log, a decision
  log and a retrospective. Applied in: `skills/eng/references/execplan.md`.
- **GPT-5.1 prompting guide, metaprompting** — `examples/gpt-5/gpt-5-1_prompting_guide.ipynb`.
  Diagnose first (quote the prompt lines behind each failure, name contradictions), then
  patch with small edits; one group of related failures per call. Applied in:
  `skills/prompt-optimizer/references/diagnose-and-patch.md`.
- **GPT-5 troubleshooting guide and GPT-5.2 guide** —
  `examples/gpt-5/gpt-5_troubleshooting_guide.ipynb`, `examples/gpt-5/gpt-5-2_prompting_guide.ipynb`
  (sections 3.2 to 3.4 and 5). Symptom-to-remedy catalogue (overthinking, underthinking,
  deference, verbosity, tool overuse, malformed calls, scope drift, ambiguity). Its
  persistence block says never to ask the user to confirm assumptions, which conflicts
  with the approval gates in `AGENTS.md`, so the pack's version keeps the gates. Applied
  in: section 8 of `skills/prompt-optimizer/references/openai-prompting-guidance.md`.
- **Transparent image assets** — `/cookbook/examples/multimodal/transparent-image-assets-for-campaigns-and-presentations.md`.
  Image-generation specific (prompt text outranks the `background` parameter;
  verify generated charts against source data). Nothing in it changed the pack.
- **API libraries** — <https://developers.openai.com/api/docs/libraries.md>. SDK
  install pages; no prompting guidance.

## Ideas from other agent setups (read 2026-10-08)

- **jlaws/dotfiles** — <https://github.com/jlaws/dotfiles>. MIT for the author's own
  work; its `REFERENCES.md` says much of its agent material builds on other projects,
  so nothing was copied and every idea was rewritten in this pack's own words.
  Applied in: `scripts/check_pack.py` (agent-file and secret checks), the reviewer's
  "could not review" outcome and scope check, `$eng`'s docs line and covering-test
  check, the outside-text, two-failed-fixes, stdin, cleanup and attribution rules in
  `AGENTS.md`, the return contract in `references/model-selection.md`, and the
  bug-locating table and `SIMPLIFIED:` marker in the engineering standards.

## GitLab CLI and API (read 2026-10-08, run live 2026-10-08)

Behind `references/trackers/gitlab.md`. The commands were first written from the
documentation alone, with `glab` not installed. They were then run for real, every
operation in the adapter, with `glab` 1.121.0 signed in to gitlab.com (Free plan,
OAuth sign-in over HTTPS) against a throwaway private project in a personal namespace
with a project-scoped issue board named `Development` (lists for ready, in-progress,
in-review and blocked, plus the built-in Open and Closed). The run found and fixed:
`glab api` has no `--jq` flag and sends a `POST` once any field is present; label
colors need a leading `#`; `closes_issues` objects have a null `references`, so the
same-repo test uses `project_id`; the issue search does not reach comments, so model-fit
notes are found with the project notes search (`scope=notes`); any label name that does
not exist is created silently by create, edit and `--label`; a description or comment
line starting with `/` runs as a quick action; and scoped labels do not replace one
another on the Free plan (both stayed on one issue), so every lane or priority change
removes the others explicitly and `add-label` must not be used for them. Also measured:
the board's Open and Closed lists stand in for the backlog and done lanes; `Closes`,
`Fixes`, `Resolves` and `Implements` all closed on merge, from a description or from a
branch commit message alone, while `Refs` and a bare `#n` did not; and turning off
"Auto-close referenced issues" (`autoclose_referenced_issues`) left the issue open.

Not checkable on that account, and marked `UNVERIFIED:` in the adapter: group-scoped
boards, labels and subgroup issues (the only group had no boards, labels or subgroups;
its read endpoints answered 200 with empty lists), a self-managed host, a paid plan's
scoped-label replacement, a second assignee kept by `--assignee "+login"`, closing an
issue in another project, label inheritance from an ancestor group, the `locked`
merge request state, and the exit code after a real `glab auth logout` (a host with no
login and a rejected token both exit 1).

The documentation behind the first draft:

- **GitLab CLI** — <https://docs.gitlab.com/cli/> and its per-command pages:
  <https://docs.gitlab.com/cli/issue/list/>, `/cli/issue/view/`, `/cli/issue/note/`,
  `/cli/issue/update/`, `/cli/issue/close/`, `/cli/issue/create/`, `/cli/issue/`,
  `/cli/mr/create/`, `/cli/mr/list/`, `/cli/label/create/`, `/cli/label/list/`,
  `/cli/auth/status/`, `/cli/auth/login/`, `/cli/api/` and `/cli/configuration/`
  (`GITLAB_HOST`, `GITLAB_TOKEN`). `glab issue close` has no comment flag; `glab issue
  update` adds labels with `--label` and removes them with `--unlabel`; `glab api`
  reads a file into a field with `@<path>`. Applied in: the adapter's commands.
- **GitLab REST API** — <https://docs.gitlab.com/api/issues/> (list group and project
  issues, edit with `add_labels` and `remove_labels`, assignee fields and filters),
  <https://docs.gitlab.com/api/notes/> (issue comments),
  <https://docs.gitlab.com/api/labels/> and <https://docs.gitlab.com/api/group_labels/>
  (list, create), <https://docs.gitlab.com/api/boards/> and
  <https://docs.gitlab.com/api/group_boards/> (a board's lists and their labels),
  <https://docs.gitlab.com/api/users/> (the signed-in user),
  <https://docs.gitlab.com/api/search/> (the project `notes` search scope, used by
  `search-issues`). Applied in: `capture-board`, `list-items`, `read-issue`,
  `set-lane` and the label operations.
- **GitLab user guides** —
  <https://docs.gitlab.com/user/project/issues/managing_issues/> (closing keywords
  `Closes`, `Fixes`, `Resolves`, `Implements`; `#123` and `group/project#123`
  references; the close fires on the default branch),
  <https://docs.gitlab.com/user/project/labels/> (scoped labels `scope::value` replace
  one another on an issue; a paid feature), <https://docs.gitlab.com/user/project/issue_board/> (a
  board list is a label; moving a card swaps labels). Applied in: the adapter's lane
  and priority model and its closing-keyword section.

## Measured (2026-10-07, Codex CLI 0.158–0.160)

Each finding comes from a `codex exec` run whose thread rows are in
`~/.codex/state_5.sqlite` and whose events are in the thread's rollout file.

- **A symlinked custom agent file is refused.** `spawn_agent` returned "agent type
  is currently not available" for `~/.codex/agents/zz_probe_link.toml` (a symlink)
  and succeeded for a byte-identical real file. Symlinked skill folders and a
  symlinked `~/.codex/AGENTS.md` load normally. The docs say symlinks are followed
  for skills and say nothing about agent files.
- **A model in an agent file beats the model a spawn asks for.** A probe agent file
  pinning `gpt-6.1-sol` / `medium`, spawned with `model: gpt-6-luna`,
  `reasoning_effort: low`, ran on `gpt-6.1-sol` / `medium` (thread rows). This
  matches the Subagents page: "If a custom agent file sets `model` or
  `model_reasoning_effort`, the value in the file takes precedence."
- **Built-in agents take the spawn's model in any direction.** From a `gpt-6-luna`
  parent, `explorer` ran on `gpt-6-astra` and `worker` on `gpt-6.1-sol` as
  requested, and `explorer` on `gpt-6-luna` when that was requested.
- **Fixed cost of a subagent.** A child asked only to reply with one word used
  20,990–25,176 tokens (four runs, Luna, Astra and 6.1 Sol), most of it cached
  context. A Luna parent that spawned two or three such children used
  74,000–107,000 tokens. A plain desktop chat's first call carried 32,201 input
  tokens, 21,888 of them cached.
- **Where usage is recorded.** `threads` rows carry `model`, `reasoning_effort`,
  `tokens_used`, the parent link in `source`, and `agent_role`; rollout files carry
  per-call `token_count` events with input, cached, output and reasoning tokens
  and the plan's `rate_limits` (5-hour and weekly `used_percent`). Fast mode shows
  as `service_tier: "priority"` in `thread_settings_applied`. The auto-review
  approver runs as its own `codex-auto-review` threads. `codex exec --ephemeral`
  writes nothing. `scripts/codex_usage.py` reads all of this.
- **Credit rates** (credits per 1M tokens, Standard speed, input / cached / output,
  <https://learn.chatgpt.com/docs/pricing.md>): Astra 250 / 25 / 1,250; GPT-6.1 Sol
  50 / 2.5 / 250; GPT-6 Sol 50 / 5 / 250; Luna 2.5 / 0.25 / 12.5. Fast mode uses
  included limits at 2.5x. Plus plan estimate per 5 hours: Astra 5–45 local
  messages, 6.1 Sol 15–160, Luna 350–3,000.

## Trigger and end-to-end tests (2026-10-08, gpt-6-luna at low effort unless noted)

`scripts/eval_triggers.py`, 20 queries per skill, 3 runs each, connectors off. A query
passes when its trigger rate is on the right side of 0.5.

| Skill | Should trigger | Should not | Notes |
| --- | --- | --- | --- |
| plan-ticket | 10 / 10 | 10 / 10 | after adding "a teammate's" ticket to the description |
| ticket-worker | 10 / 10 | 10 / 10 | |
| work-tickets | 10 / 10 | 10 / 10 | |
| daily-grooming | 9 / 10 | 10 / 10 | misses a vague "what is the state of the board? fix anything off" |
| write-ticket | 8 / 10 | 10 / 10 | 6 / 10 before the description named bugs, ideas and issues |
| eng (in `evals/fixtures/small-repo`) | 7-8 / 10 | 9 / 10 | 2 / 10 before AGENTS.md routed code changes to it; code-review requests stay unreliable |

Run-to-run noise at 3 runs is about one query either way. A query that names a skill
(`$eng ...`) is detected through the session record, since Codex injects the skill
without a file read. Ordinary coding requests in a repo are done inline unless
AGENTS.md points them at `$eng`.

End to end on a throwaway private repo and board (gpt-6.1-sol at medium):
`$write-ticket` filed the ticket with priority, labels, lane and assignee;
`$plan-ticket` posted the plan and kept the labels; `$work-tickets` dispatched a
worker on the label's model, which fixed the bug with regression tests and opened a
pull request because the repo's CONTRIBUTING.md asked for one. That run held the pull
request with the blocked label, which led to the review-landing path in
`skills/ticket-worker/references/protocol.md` section 8. About 18 credits in all.
A re-run after that fix (a second bug, `$write-ticket` then `$work-tickets`) opened an
unlabelled pull request with `Fixes #3`, commented the link, moved the card to "In
review" and reported it as in review; merging it closed the issue. The board's
built-in close workflows were off (API-created board), so the card stayed in "In
review" until grooming. About 14 credits.

## Not yet measured

- **Nesting depth.** Whether a spawned `eng` agent can itself spawn an `explorer` is
  not documented (the Subagents and config pages name no depth setting) and the pack
  has no probe for it. `agents/eng.toml` and `$eng` therefore tell a spawned `eng`
  agent to ground the unit itself and say so when the spawn fails. A probe would spawn
  a custom agent from a built-in one and read the thread rows in
  `~/.codex/state_5.sqlite`, as the findings above do.
