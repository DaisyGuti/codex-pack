---
name: codex-usage
description: Use when asked what a Codex run, skill or period cost in tokens, credits or plan limits. Reports the 5-hour and weekly share by model and subagent, and exports usage for analysis. Reads Codex's own records; not for OpenAI API billing.
---

# Codex usage

Answer from Codex's own records with [scripts/codex_usage.py](scripts/codex_usage.py)
(run it with `python3`). It only reads; it changes nothing.

## Pick the call

- "What did that run take?": `--last 1`, then `--run <id>` for one row per thread.
- A period, a skill or an evaluation: `--since <date> --summary`, narrowed with
  `--skill <name>` when asked. The summary also splits usage by subagent role and by
  project (the root thread's folder).
- "Is a top-tier model doing mechanical work?": the same `--summary` ends with the
  frontier-tier subagent runs that wrote no patch, spawned nothing and returned a short
  answer (`--mech-output-max N` sets what counts as short; default 8000 output
  tokens).
- Data to aggregate elsewhere: `--csv <path>` (one row per thread). Write it where
  the user says; otherwise to `~/Documents/codex-usage-<since>.csv`, and give the
  path.

## Read the numbers

- A run is the thread the user started plus its subagents and any auto-review
  threads it triggered.
- Tokens are summed per thread. Cached input is the cheap part of a thread's
  context.
- Estimated credits apply Codex's Standard rate card per model and the 2.5x Fast
  multiplier. A model with no published rate (the auto-review approver) shows
  "n/a"; never estimate one.
- The 5-hour and weekly percentages are the plan's own meter. It is account-wide,
  so a run the script flags as overlapping other activity carries other sessions'
  usage too.
- A run started with `codex exec --ephemeral` leaves no record and cannot be
  reported. To measure a batch of test runs afterwards, leave `--ephemeral` off, or
  add `--json` and read `turn.completed.usage`
  ([references/testing-without-api-spend.md](references/testing-without-api-spend.md)
  has the test commands).
- Credits show "n/a" for a model the rate table lacks. Say so and point to the
  pricing page for the missing rate; never estimate one.

## Confirm each lead

The mechanical-looking list is a set of leads, not verdicts. For each one, read its
role and first message:

- Search, list, inventory, count or summarize work is a real candidate: recommend the
  `fast` or `workhorse` tier and the setting that applies it (the spawn names the model
  and effort; see [references/model-selection.md](references/model-selection.md)).
- Review, audit, design, security, root-cause or decision work is judgment: keep the
  tier and say why.
- A shell command can write files without a patch, so ask to see the commands before
  recommending a smaller tier.

## Report

Lead with the answer: tokens, estimated credits and plan percentage. Then the split
by model, subagent role and project, the biggest contributor, the confirmed leads with
their credits now and the tier you would move them to (approximate: another model may
use a different number of tokens), and any row the script marks partial or
overlapping. Quote no more of a conversation than the 40-character
preview the script prints.
