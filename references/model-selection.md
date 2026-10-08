# Choosing a model and reasoning effort in Codex

Shared by every skill and custom agent in this pack. Sources: OpenAI's Codex
[Models](https://learn.chatgpt.com/docs/models.md),
[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md) and
[Model selection](https://developers.openai.com/api/docs/guides/model-selection.md)
pages and the [reasoning effort table](https://developers.openai.com/api/docs/guides/reasoning.md#reasoning-effort),
read 2026-10-06.

## The rule

Size each unit of work by the hardest judgment it contains. A long job made of
easy calls stays on a cheap tier. Start at the cheapest setting that should clear
the quality bar, and when one unit comes back weak, rerun that unit one step up.
Everything starting high is the failure this guide exists to prevent. A model or
effort the user names outranks this guide.

The gaps are large. Per token, `frontier` costs about 5 times `workhorse` and about
100 times `fast`, and Fast mode multiplies any tier by 2.5 against the plan's
included usage ([pricing](https://learn.chatgpt.com/docs/pricing.md), read
2026-10-07). A `fast` unit that comes back weak and is redone one tier up still
costs far less than running it high from the start.

## Get the slug from the resolver

Model names change every few months, so no prompt in this pack spells one out.
Pick a tier and a starting effort from the table below, then resolve them:

```bash
python3 scripts/resolve_model.py <fast|workhorse|frontier> --effort <start effort>
```

The path is relative to the skill folder that linked this guide; outside a skill,
the script is at `${CODEX_HOME:-~/.codex}/skills/eng/scripts/resolve_model.py`.
Without `--effort`, the script uses OpenAI's generic starting point for the tier
(`fast` high, `workhorse` medium, `frontier` low); pass `--effort` from the table
below. When you will spawn several tiers, `--all` resolves all three in one call.

The script reads this account's live model catalog and picks the newest listed
model for each tier, so nobody edits a prompt, a table or a model name when OpenAI
ships a new model. When its pick differs from the script's built-in fallback list,
it prints a note saying so; pass that note on to the user. The built-in list only
answers when the catalog cannot classify a tier or cannot be read.

The catalog comes first from the Codex CLI (`codex debug models`) and then from
`$CODEX_HOME/models_cache.json`. The script prints JSON with `model`, `effort`,
`supported_efforts`, `source` and `notes`. It finds the CLI on `PATH`, in
`$CODEX_CLI_PATH`, or bundled inside the ChatGPT desktop app; a `source` of
`models_cache` means none of those answered, and the cache file, shared by every
Codex client on the machine, can list only an older client's models. Use `model` and
`effort` exactly as printed. Pass any `notes` on to the user when they
change what happened, for example a clamped effort or `"source": "fallback"` (the
catalog could not be read, so the slug is unverified). Exit 3 means the account has
no model for that tier: say so and use the nearest tier that resolves. Exit 2 means
a bad tier or flag: fix the call and rerun it once.

The script also accepts the ticket-label forms `model:haiku`, `model:sonnet` and
`model:opus`, which this portfolio uses as tier names: haiku is `fast`, sonnet is
`workhorse`, opus is `frontier`.

If the script is missing, list the catalog with
`python3 -c "import json,os;[print(m['slug'],'|',m['description']) for m in json.load(open(os.path.expanduser('~/.codex/models_cache.json')))['models']]"`
and pick by description: "frontier" means `frontier`, "workhorse" means
`workhorse`, "fast and affordable" means `fast`. Prefer the newest generation.

## Which tier

| The unit's hardest call | Tier | Start | Raise to |
| --- | --- | --- | --- |
| Mechanical work with a crisp rubric: file inventories, scans, extraction, classification, format conversion, a rename, a config bump, wiring an existing checker into an existing pipeline | `fast` | `high`; `low` only for a one-line edit or a single-file extraction | `xhigh` |
| Spec-driven implementation inside an existing seam, most bug fixes, research with citations, most verification and review | `workhorse` | `medium` | `high` for debugging, security or reviewer passes and edge-case tracing; `xhigh` for decisions built from conflicting evidence |
| Judgment where a wrong call is expensive to unwind: an architecture or contract choice, ambiguous multi-step work across a large context, subtle domain math, what a guard does when it cannot resolve, whether a contradiction is real, direction-setting synthesis | `frontier` | `medium` | `xhigh` for exacting analysis |
| Concise rewriting that must keep every fact and nuance, such as optimizing a prompt or adapting a document | `frontier` | `low` | `medium` |

`max` gives one hard problem more time; use it only after `xhigh` came back weak.
`ultra` makes the model spread work across its own subagents. This pack delegates
explicitly with right-sized children, so never request `ultra` for a subagent.
In the desktop app's picker, `low` shows as Light and `xhigh` as Extra High.

Leave the speed tier (Fast, Ultrafast) as the user configured it.

## What a skill can choose, and what only the user can

A Codex skill cannot choose the session's own model or effort. The session runs on
what the user picked or what `config.toml` says, and a skill's inline steps run on
that. Only these can set a model and effort: a spawned subagent (the spawn names
both), a custom agent file, `codex exec -m <model> -c model_reasoning_effort=<effort>`,
and the Codex SDK (`model`, `modelReasoningEffort`). A skill that needs a specific
setting hands that work to one of them, and says in its report when the session's own
setting was wrong for the work.

## Recommended team default

Set the session default once in `~/.codex/config.toml`, so inline work starts on the
workhorse tier at the interactive default of the Codex prompting guide:

```toml
model = "<the workhorse slug from: python3 scripts/resolve_model.py workhorse>"
model_reasoning_effort = "medium"
```

Leave `service_tier` unset. Setting `service_tier = "fast"` turns Fast mode on for new
turns, and Fast mode uses the plan's included limits at 2.5 times the standard rate,
so turn it on only when the speed is worth that
([speed](https://learn.chatgpt.com/docs/agent-configuration/speed.md)). Three
optional keys: `agents.default_subagent_model` and
`agents.default_subagent_reasoning_effort` set what a spawn gets when it names
nothing (a spawn's own values still win), and `review_model` sets the model that
Codex's built-in `/review` uses. Key names are from the
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference.md),
read 2026-10-08. The slug is the one thing in that file that goes stale; rerun the
resolver when a new model ships.

## Escalating

Name which axis a weak result needs, in your report:

- **More depth on the same model.** You redid an analysis and only trusted a later
  pass, you held more call sites than you could track, or you know of an edge case
  you did not chase. Raise the effort one step, or go straight to the level the
  table names when the unit's work matches that row's description.
- **A different kind of call.** The unit turned out to hold one of the frontier
  judgments in the table. Move up a tier.

## Delegating

A subagent takes its model and effort from the spawn, then the `[agents]` defaults
in `config.toml`, then the parent. A custom agent file that sets either value
overrides all of them (measured 2026-10-07: a spawn that asked for `fast` ran on the
file's `workhorse` model), so no agent file in this pack sets one and every spawn
names both, resolved from the table above.

Each subagent starts with about 21–25K tokens of context before it does any work
(measured 2026-10-07 on one-word tasks), most of it cached after its first call.
Delegate a unit when its own work clearly outweighs that, or when it can run a
tier or more below the parent.

- Parallelize read-heavy units freely: exploration, scans, test runs, log triage,
  review lenses.
- Run write-heavy units in parallel only when each has its own git worktree.
- Each spawn message states the unit, its inputs, what to return and what "done"
  means, plus any rule that bears on it, so the child needs no rules files of its
  own. Wait for every subagent before you synthesize.
- **Return contract.** A child cuts narration and process talk and never cuts
  findings, error text, `file:line` evidence or numbers. It quotes errors and exit
  codes as printed, keeps every finding with its location, and has no length cap on
  substance. When it finds nothing, it says so in one line that names what it
  checked, so silence cannot pass for success.
- When one unit fixes and another validates, keep them separate. Only the
  validator's result counts as validation.
- Write messages to other agents so a person can read them: full sentences, proper
  spacing.
