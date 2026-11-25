---
name: model-recommender
description: "Use to pick the OpenAI model tier and reasoning effort for a kind of Codex work: a task, subagent, pipeline stage or feature. Reads the live model catalog. Not for rewriting a prompt ($prompt-optimizer), past spend ($codex-usage) or auditing a product's model calls ($model-usage-audit)."
---

# Model recommender

Pick the cheapest model tier and effort that does the job, say how to check that it does,
and say what to change when it does not. The lineup, prices and defaults move with each
release, so read them at run time (step 2) and never from memory.

Input: a description of the work, or `--file PATH` to a prompt or plan. `--context "..."`
can add volume, latency needs, where it runs and how sensitive the data is. If the work is
too vague to classify, ask one question.

This skill recommends OpenAI models for Codex's own work (the session, its subagents,
`codex exec` runs, the Codex SDK) and for a product that calls the OpenAI API. The tier
vocabulary and starting efforts are the pack's guide,
[references/model-selection.md](references/model-selection.md); read it before step 3.

## Steps

1. **Split the work into units and classify each.** A unit is a piece that could run on its
   own model. Use the types in [references/work-types.md](references/work-types.md):
   mechanical, implementation, verification, research, judgment, high-volume or
   latency-bound, and long-horizon agentic. One request that mixes types becomes several
   units.

2. **Read the current lineup.** Run the resolver, then fetch the pages it cannot answer:
   - `python3 ${CODEX_HOME:-~/.codex}/skills/model-recommender/scripts/resolve_model.py --all`
     prints the slug and a starting effort for each tier on this account, and `--list`
     prints the whole catalog with descriptions. Pass on any `notes` it prints.
   - <https://learn.chatgpt.com/docs/models.md>: which model each tier is for, retirement
     dates, and what Codex recommends starting on.
   - <https://learn.chatgpt.com/docs/pricing.md>: credits per million tokens and the Fast
     mode multiplier.
   - <https://developers.openai.com/api/docs/guides/model-selection.md> and
     <https://developers.openai.com/api/docs/guides/reasoning.md#reasoning-effort>: the
     selection matrix and the effort levels each model supports. For OpenAI API questions
     use the `openai-docs` skill when it is installed.
   Fetch with the web tool or `curl -fsSL`; if the sandbox refuses the network, retry two or
   three times, then ask once to run it outside the sandbox. If a fetch still fails, say
   which and what the recommendation leaves unchecked.

3. **Choose tier and effort per unit.** Apply the rules below and the table in
   `model-selection.md`, then cross-check the effort against the models page for that model.

4. **Say how to verify.** A recommendation is a hypothesis. For each unit give a small
   sample of real inputs to run at the proposed setting, the pass check, and the escalation
   step if it fails. For a recurring workload, point to `$codex-usage` to see what the
   setting costs afterward.

5. **Say how to apply it.** Give the exact setting for each unit from
   [references/codex-settings.md](references/codex-settings.md): a spawn's model and effort,
   a `codex exec` flag, a `config.toml` key, or an SDK field. Never write a slug from
   memory: use the resolver's.

## Rules

- **Start cheap and move up on evidence.** `fast` for mechanical work, `workhorse` for
  implementation and most verification, `frontier` for genuinely hard judgment. Move up one
  step after a weak result on real inputs.
- **Raise effort before raising the tier.** OpenAI describes effort as a tuning knob within
  one model, not the main way to recover quality, so define what done means and how the
  model verifies it first. Raise the tier when a higher effort still fails the check.
- **Reserve `frontier` for what the lower tiers cannot do.** Use it for judgment that is
  expensive to unwind, after evals on `workhorse` at high effort fall short.
- **Subagents get their own model.** A spawn that names nothing takes the `config.toml`
  `[agents]` default, then the parent's model, so a session on `frontier` quietly runs every
  helper there. Name the model and effort of every spawn. Spawn a subagent only for
  independent work of real size: each starts with about 21 to 25 thousand tokens of
  context.
- **A skill cannot change the session's own model.** Say so when the work the session
  runs inline needs another setting, and hand that work to a subagent or a `codex exec`
  call.
- **Never request `ultra` for a subagent,** and treat `max` as a last step after `xhigh`.
  Leave Fast mode as the user configured it: it multiplies usage by 2.5.
- **Combine models only after one model's effort has been swept.** A cheap executor that
  escalates hard decisions, or a `frontier` orchestrator that hands bulk work to cheaper
  workers, is worth it only when the single-model curve of quality against spend leaves
  room, and the recommendation says what to measure.
- **Stay with OpenAI.** This skill compares OpenAI tiers. For a task OpenAI models cannot
  do or a request to compare other providers, say so and stop: the choice for another
  provider's model in a product's code is `$model-usage-audit`'s to inventory and that
  provider's own docs to settle.
- **Do not quote prices from memory.** Quote the fetched pricing page with its date.

## Output

One table, then short notes. Use exactly these columns:

| Unit | Work type | Tier and model (slug from the resolver) | Effort | Why this tier | Move up if |
|---|---|---|---|---|---|

Then:
- **Cost note**: credits per million tokens for each model used, from the fetched pricing
  page, and the relative cost of the plan against running every unit on `frontier`.
- **How to verify**: the sample, the pass check and the escalation step per unit.
- **How to apply**: the spawn parameters, `codex exec` flags, `config.toml` keys or SDK
  fields.
- **Not checked**: anything a failed fetch or missing information left open.

If the user supplied volume, estimate monthly cost as tokens times price and show the
arithmetic with its assumptions; otherwise skip the estimate.
