# Work types and the tier to start with

Tier names are the pack's: `fast`, `workhorse`, `frontier`. The model in each tier and its
slug come from `scripts/resolve_model.py` on the account at run time; the efforts below are
the starting points from [model-selection.md](model-selection.md), "Which tier".

## Contents

- Table of work types
- Signals to move up
- Signals to move down
- Patterns that waste tokens
- Sources

## Table of work types

| Work type | Examples | Start at | Effort to start | Check before trusting it |
|---|---|---|---|---|
| Mechanical | Extract fields, classify tickets, convert formats, list files that match a rule, summarize a short log, route a request, a rename or a config bump | `fast` | `high`; `low` only for a one-line edit or a single-file extraction | Exact match against 20 hand-labeled inputs |
| Implementation | Write a function to a spec, apply a refactor, write tests, fill a template from a design | `workhorse` | `medium`; `high` for longer or harder tasks | Tests pass and the diff stays in scope |
| Verification | Run and read a test suite, check a diff against a checklist, review for a known list of problems | `workhorse` | `medium`; `high` for reviewer, security and edge-case passes | It finds a known planted defect |
| Research with citations | Read several sources and report with links, compare vendor docs | `workhorse` | `medium`, then `high` | Every claim traces to a source |
| Judgment | Architecture or contract choices, a root cause across a large system, a decision that is costly to reverse | `frontier` | `medium`; `xhigh` for exacting analysis | A reviewer who knows the answer agrees on a sample |
| Concise rewriting that must keep every fact | Optimizing a prompt, adapting a document | `frontier` | `low`, then `medium` | A diff against the source shows no fact lost |
| High-volume or latency-bound | Chat replies, per-request routing, inline suggestions | `fast`, or `workhorse` at `low` | `high` on `fast`, `low` on `workhorse` | Latency and cost per request on real traffic |
| Long-horizon agentic | Multi-hour coding or migration runs with many tool calls | `frontier`, or `workhorse` at `high` after an eval | the models page's recommendation for that model | Tests, a reviewable diff and a spend cap |

## Signals to move up

- The check fails on real inputs after raising effort one level.
- Output is shallow on a task that needs several steps of reasoning.
- The unit makes a call that is costly to unwind (security design, a data deletion plan, a
  customer-facing commitment).
- Errors from this unit surface only downstream, far from where they were made.

## Signals to move down

- The output is correct on every sample and the model finishes in a few calls.
- The unit only reads and reports (no edits, no decisions).
- The same unit runs many times per day, so a small saving repeats.
- A lower effort on the same model passes the same check.

## Patterns that waste tokens

- Running every unit on the session's model. Name the model on each spawn.
- Spawning a subagent for a lookup that one search answers.
- Giving a reading-only helper `frontier` because the main session uses it.
- Building a multi-model cascade before sweeping effort on a single model: a cascade has to
  beat the single model's whole curve of quality against spend.
- Treating `frontier` as the default for knowledge work that `workhorse` already passes.
- Turning Fast mode on for work that is not waiting on a person: it costs 2.5 times as
  much.

## Sources

- Model selection: <https://developers.openai.com/api/docs/guides/model-selection.md>
- Reasoning effort: <https://developers.openai.com/api/docs/guides/reasoning.md>
- Codex models and pricing: <https://learn.chatgpt.com/docs/models.md>,
  <https://learn.chatgpt.com/docs/pricing.md>
- The table above is the pack's working rubric, adapted from the claude-pack one against
  those pages and [model-selection.md](model-selection.md); the tier-to-work mapping is a
  starting point to verify on real inputs.
