# Testing without API spend: Codex SDK, `codex exec`, or an API key

Codex can be driven from a script and run on the ChatGPT plan you are signed in with,
with no API bill. An OpenAI API key is needed only when the code under test calls
OpenAI's API itself. Sources were read 2026-10-08; a line marked UNVERIFIED is one the
docs do not settle.

## Which one to use

1. **Testing a prompt, a skill, an `AGENTS.md`, or how a Codex agent behaves:** run it
   with `codex exec` on your ChatGPT sign-in. "`codex exec` reuses saved CLI
   authentication by default"
   ([non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode.md)).
   It uses the plan's Codex limits and costs no API money.
2. **The same test driven from code** (threads, streaming, typed results, a loop over
   many cases): the Codex SDK. It runs the local Codex agent with the same sign-in
   ([Codex SDK](https://learn.chatgpt.com/docs/codex-sdk.md)). TypeScript:
   `npm install @openai/codex-sdk`. Python: `pip install openai-codex`.
3. **Code that itself calls the OpenAI API** (the Responses API, Evals, Batch,
   Embeddings, an app's own model calls): an API key is required, billed per token at
   API rates ([API overview](https://developers.openai.com/api/reference/overview.md),
   [authentication](https://learn.chatgpt.com/docs/auth.md)). Prefer tests that mock
   those calls; spend a key only on the few tests that must prove the live
   integration, against a project with a spending limit. Fine-tuning, Realtime and the
   Agents SDK follow the same rule as far as the docs show (UNVERIFIED).
4. **CI where nobody can sign in:** the docs recommend an API key for "programmatic
   Codex CLI workflows, such as CI/CD jobs" ([authentication](https://learn.chatgpt.com/docs/auth.md)).
   A ChatGPT login can be copied onto a trusted private runner, never a public one
   ([CI/CD auth](https://learn.chatgpt.com/docs/auth/ci-cd-auth.md)).

Never reach for an API key to test a prompt or an agent: that turns a test that is
free on the plan into metered spend.

## Before a batch of test runs

- `codex login status` must report a ChatGPT login. `CODEX_API_KEY` switches one run
  to API billing; keep it, and `OPENAI_API_KEY`, out of the shell you test from
  (whether `OPENAI_API_KEY` alone overrides the ChatGPT login is UNVERIFIED).
- Turn Fast mode off for tests: it draws on plan limits at 2.5 times the standard rate
  ([speed](https://learn.chatgpt.com/docs/agent-configuration/speed.md)).
- Run one case first, then small batches, on the cheapest tier that answers the
  question (`python3 scripts/resolve_model.py fast`). The plan has a five-hour window
  and weekly limits may also apply ([pricing](https://learn.chatgpt.com/docs/pricing.md));
  many parallel runs on the frontier tier can use up the window for every session on
  the account.
- No single page states that SDK runs count against plan limits; it follows from the
  pages above (UNVERIFIED). Assume `--ephemeral` runs count too.

## Commands

```bash
# One read-only test with a structured answer and no saved session
codex exec --ephemeral --sandbox read-only -m <model> \
  -c model_reasoning_effort=<effort> --output-schema ./schema.json -o ./out.json "<prompt>"

# Token counts for the run: add --json and read turn.completed.usage
# Ignore your personal config and rules for a repeatable run
codex exec --ignore-user-config --ignore-rules ...
# Outside a git repository
codex exec --skip-git-repo-check ...
# Continue the last run
codex exec resume --last "<follow-up>"
```

TypeScript SDK:

```ts
import { Codex } from "@openai/codex-sdk";
const thread = new Codex().startThread({ workingDirectory, sandboxMode: "read-only", modelReasoningEffort: "low" });
const result = await thread.run(prompt, { outputSchema });
```

Runs that keep a session record can be measured afterwards with `$codex-usage`;
`--ephemeral` runs leave no record to measure.
