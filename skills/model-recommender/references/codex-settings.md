# Applying a model and effort recommendation in Codex

Settings are from [model-selection.md](model-selection.md) ("What a skill can choose" and
"Recommended team default") and the Codex configuration reference,
<https://learn.chatgpt.com/docs/config-file/config-reference.md>. Re-fetch that page before
quoting a key the user will paste into a config file: names change between versions.

## Contents

- The main session
- Subagents
- A one-off run
- Where cost shows up afterward

## The main session

The session runs on the model the user picked in the app's or CLI's model picker, or on
`~/.codex/config.toml`:

```toml
model = "<workhorse slug from: python3 scripts/resolve_model.py workhorse>"
model_reasoning_effort = "medium"
```

A skill cannot change either one for the turn it runs in. Leave `service_tier` unset:
`service_tier = "fast"` turns Fast mode on, at 2.5 times the standard usage rate.

## Subagents

A subagent takes its model and effort from the spawn, then from `config.toml`, then from the
parent:

```toml
[agents]
default_subagent_model = "<slug>"
default_subagent_reasoning_effort = "medium"
```

- Every spawn should name its own model and effort, resolved with
  `python3 scripts/resolve_model.py <fast|workhorse|frontier> --effort <level>`.
- A custom agent file (`agents/*.toml`) that sets `model` or `model_reasoning_effort`
  overrides all of them (measured 2026-10-07), so this pack's agent files set neither.
- `review_model` sets the model Codex's built-in `/review` uses.
- `ultra` makes a model spread work over its own subagents; never use it for a subagent.

## A one-off run

```bash
codex exec -m <slug> -c model_reasoning_effort=<effort> "<prompt>"
```

The Codex SDK takes `model` and `modelReasoningEffort`. For tests that call models, read
[testing-without-api-spend.md](testing-without-api-spend.md) first: run them on the ChatGPT
sign-in, not an API key.

## Where cost shows up afterward

`$codex-usage` reports tokens, estimated credits and the plan's percentage per run, split
by model and by subagent role, and lists frontier-tier subagent runs that look mechanical.
