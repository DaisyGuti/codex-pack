---
name: prompt-optimizer
description: Use when asked to optimize, tighten or upgrade an existing prompt, developer message, AGENTS.md, SKILL.md or agent file for the model that runs it. Also picks the model and effort. Not for creating a repo's AGENTS.md from its files (codex-project-setup) or writing a prompt from nothing.
---

# Prompt Optimizer

Turn an existing prompt into the strongest version of itself for the model that
will run it, through a capped revise-and-review loop, and state exactly how to run
the result.

## Inputs

```text
$prompt-optimizer [--file PATH ...] [--context "..."] [--target PROVIDER] [--portable] [--refresh-guidance] [--evidence PATH ...] [--write]
```

- `--file PATH`: the prompt to optimize; repeat for several. Without it, the text
  after the invocation is the prompt.
- `--context "..."`: any of audience, use case, success metric, tone to keep,
  one-shot or repeated workflow, and the runtime it will run in.
- `--target PROVIDER`: `openai`, `claude`, `gemini`, `llama` or `heygen`; see
  Resolve the target.
- `--portable`: cross-model portability matters (turns on that checklist item).
- `--refresh-guidance`: refresh the target's guidance snapshot before starting.
- `--evidence PATH`: optional; a transcript, an output or a list of corrections
  showing where the prompt fell short. Repeatable.
- `--write`: after the report, overwrite each file with its Final version. Without
  it, change no files except a guidance snapshot the target guidance says to
  refresh.

Classify the input before anything else:

- **A prompt** (instructions aimed at a model): proceed.
- **Empty**, or a `--file` that cannot be read: ask for the prompt or a readable
  path, and stop. With several files, optimize the readable ones and name the rest.
- **Not a prompt** (raw data, a bare question, a spec or notes with no model-directed
  instructions): say what it looks like and ask the user to confirm or rewrite.
- **Several distinct prompts pasted together**: list them and ask which to optimize.
  Separate `--file` arguments are already explicit; optimize each one.
- **A prompt mixed with notes or critique**: extract the prompt, state that
  assumption in the iteration log, and proceed.

Missing context fields are fine; ask only when one blocks a P0 or P1 decision.
When the prompt and `--context` disagree, the prompt wins.

## Resolve the target

Stop at the first match:

1. `--target` was passed. It wins even when the prompt's style suggests another
   provider; flag that mismatch as a P1 so the structure changes to fit the target.
2. The prompt, its location or `--context` names a provider: a model string, a
   provider or SDK name, or a product-specific ask. A `CLAUDE.md` or any file under
   a `.claude/` folder is `claude`. An `AGENTS.md`, a Codex agent `.toml`, or a
   `SKILL.md` outside `.claude/` is `openai`.
3. Otherwise `openai`.

`heygen` is not an LLM target. Skip the reasoning, autonomy and tool-use checks and
apply the HeyGen checklist from its guidance file instead.

Then read [references/target-guidance.md](references/target-guidance.md) and follow
only the section for the resolved target. It names the live source, the fallback
snapshot and the refresh rule.

## Objective, in priority order

1. Intent preservation: it still solves the original problem.
2. Correctness: it produces accurate, on-task output.
3. Determinism: the same input yields stable output.
4. Clarity: unambiguous to the model and to a human reviewer.
5. Robustness: edge cases and failures handled.
6. Brevity: minimal structure, no redundancy.

A higher item beats a lower one; never trade 1 or 2 for 6. A revision may grow
only to fix a P0 or P1.

## The loop

Tag every issue **P0** (breaks the prompt or causes wrong behavior), **P1**
(materially weakens the output) or **P2** (polish). When unsure, call it P1.
Reclassify every open issue each round.

With `--evidence`, work in two steps, following
[references/diagnose-and-patch.md](references/diagnose-and-patch.md), one group of
related failures at a time. First diagnose, with no fixes: for each failure, quote the
prompt lines that drive it, name any contradictions between lines, and classify the
cause as one of: the instruction is missing, it is present but unclear, it is
present but was not followed, or the cause lies outside the prompt (a tool, the
harness, the input). Then patch: make the smallest edits that address the first three
causes (resolve conflicts, delete contradicting lines, keep the length about the
same), report the fourth under Handoff items, and turn each failure into an eval
case. Re-run the failing inputs after the patch.

- **Rounds 1–4:** evaluate the current version against the checklist, then fix
  every P0 and P1; fix a P2 only when the fix is trivial. End these rounds early,
  and go to round 5, once only P2s remain or a round leaves the issue list
  unchanged.
- **Round 5:** apply anything in the target guidance the draft still misses. Then
  review through three lenses, writing each finding as `[P0|P1] issue — why it
  matters`: a hostile QA reviewer (malformed input, contradictions, undefined
  boundaries), a non-expert user (jargon, unclear placeholders, assumed context),
  and a senior engineer shipping it to production (determinism, hidden state,
  bloat, regressions under a model update). Run the forward test.
- **Round 6:** only when round 5 found a P0 or P1. Revise and recheck.

After round 6, any open P0 or P1 goes to Unresolved issues. Before output, run the
checklist once more on the final version and confirm the three failure-mode cases
are covered.

### Checklist

- **Clarity.** Task, inputs, outputs and constraints are unambiguous.
- **Target conventions.** Follows the target's guidance: its structuring mechanism
  (Markdown sections for OpenAI; XML tags only where the target prescribes them),
  a role only when the target recommends one, and examples only when the behavior
  is non-obvious, matching the written instructions exactly.
- **Outcome contract** (agent prompts). States the outcome, the evidence that
  proves it, what must not regress, the boundaries (files, tools, data), how to
  pick the next attempt after a miss, and what to report when blocked: attempts,
  evidence, the blocker, and the input that would unblock it. It counts a check as
  passed only when the agent ran it. A reasoning model gets this contract without
  step-by-step scaffolding.
- **Machine-read output** (when a program consumes the result). Uses a schema
  (Structured Outputs, or `codex exec --output-schema`) or exact markers, defines
  the empty or no-op result explicitly, and tells the caller to treat a failed run
  or unparseable output as a failure, never as an empty result.
- **Failure modes.** Says what to do with (a) missing or empty input, (b) an
  ambiguous instruction, (c) input in the wrong format. "If unsure, say so" alone
  does not cover this.
- **Autonomy** (agent prompts). Matches the autonomy the author intends: acts on
  authorized work without asking, prepares a concrete reviewable result before
  asking for approval, names the actions that need approval, and adds no
  unrequested warnings or checklists. It never demands an upfront plan or a status
  message before acting unless that plan is the deliverable, because such
  instructions can end a turn early, and it has a guard against looping on the same
  files without progress.
- **Persistence and closure** (agent prompts). The agent carries work through
  implementation, verification and a clear explanation in the same turn, acts on
  reasonable stated assumptions instead of ending with questions, and ends each run
  with either a concrete result or a named blocker plus one targeted question. It
  closes every stated step as done, blocked (with the reason) or cancelled (with the
  reason), and opens its final report with the outcome. A persistence line never
  overrides the approval gates in the instruction chain: "do not ask the user to
  confirm assumptions" is written as "do not stop to ask about assumptions; ask
  before anything public, paid, production-bound or destructive".
- **Precedence** (prompts that load skills or instruction files). User instructions
  win, and the model names the file and line that made it pause.
- **Delegation** (agents that can spawn others). Says when and how much to
  delegate, sets model and effort per child from
  [references/model-selection.md](references/model-selection.md), says what each
  child returns, and waits for all of them.
- **Verification** (coding agents). Checks scale with the change; no tests that
  mirror the implementation; broader runs only after a new failure.
- **Output style** (prose for people). Sets length and formatting, since current
  GPT models default to heavy formatting, and bans the stock phrasing the guidance
  lists.
- **Completeness.** Edge cases and stop conditions are defined; every loop has exit
  rules (pass, attempt cap, no change since the last pass, needs a human).
- **Tool fit.** Uses only tools the runtime has. A comparison against another
  provider's model is a handoff to the user.
- **Audience and utility.** Who it serves and what success looks like are explicit.
- **No over-engineering.** Vague flourishes and restrictive language written for
  weaker models are gone; absolute language stays only where correctness or safety
  needs it.
- **Intent preservation.** Scope and tone match the original. Read the files the
  prompt links to, optimize only the files passed, and leave linked content in its
  own file.
- **Extensibility** (repeated or commercial workflows only). Composes with other
  tools and survives model upgrades: model names are resolved at runtime or kept
  in config.
- **Portability** (`--portable` only). Avoids the target's proprietary syntax where
  a portable equivalent works as well.
- **Codex artifacts.** For a `SKILL.md`, `AGENTS.md` or agent `.toml`, also apply
  the Codex checks in the target guidance.

### Forward test

Run it when the prompt drives an agent or a repeated workflow and you can write one
realistic input. It may run in this session (the `forward_tester` agent) or through
`codex exec` or the Codex SDK on a `fast`-tier model with the ChatGPT sign-in, never
on an API key ([references/testing-without-api-spend.md](references/testing-without-api-spend.md)
has the commands and the checks before a batch). Skip it for a one-off prompt, or
when you cannot run it (no subagents, a usage limit, no realistic input): write
"Skipped — <reason>", and list the input you would have used under Handoff items.
Otherwise follow [references/forward-test.md](references/forward-test.md).

## Gotchas

- A `model` or `model_reasoning_effort` in an agent file overrides the spawn's
  values, so a pinned value in a file being optimized is a P1.
- A skill cannot change the session's model or effort. When the optimized prompt needs
  a specific setting, its Final version hands that work to a subagent or a
  `codex exec -m` call.
- The Codex skill catalog gets at most 2% of the context window (8,000 characters
  when the window size is unknown), shared by every installed skill, and long
  descriptions are shortened first. Keep a skill description short and put its
  trigger words first.

## Several files

Optimize each file on its own, in parallel: load the target guidance once in this
session, then spawn one `prompt_optimizer` subagent per file at the `frontier`
tier and `low` effort, resolved, each with the extracted guidance in its brief so
it fetches nothing again, and each returning the full Output for its file. Wait
for all of them, then present the results in input order.
When files reference one another (a skill and the agent that points to it),
optimize them separately and list any cross-file conflict under Handoff items.

## Output

Use exactly this structure, in this order, with no preamble and "None" for an empty
section. With several files, repeat it under a `## <path>` heading per file.

### Final version

The optimized prompt, ready to paste, with no commentary inside it. For a file,
give its complete content, frontmatter included, inside a code fence longer than
any fence the content holds.

### How to run it

1. **Model and effort.** One setting from the target's own lineup with a one-clause
   reason tied to the hardest judgment the prompt demands. For `openai`, give the
   tier, the slug resolved with [scripts/resolve_model.py](scripts/resolve_model.py)
   and the effort; for a custom-agent `.toml`, these are
   its `model` and `model_reasoning_effort` values. For other targets, use that
   provider's tiers from its guidance file.
2. **Parallel execution plan.** Split the prompt into units. Two units are parallel
   only when neither needs the other's output and they write different files.
   When any parallelism exists, the Final version must already carry it, or link
   the file that holds it: an `## Execution plan` section for `openai`, an
   `<execution>` block for `claude`, or the target's own convention, naming each
   unit's tier, effort and dependencies and telling the model to spawn them and
   wait. Summarize it here:

   | Stage | Unit | Tier → model | Effort | Depends on |
   | --- | --- | --- | --- | --- |

   A serial prompt gets "Serial — every step feeds the next" and one setting.
   Three trivial greps are one unit.
3. **Goal line** (only for long-running work with a checkable finish line). A
   ready-to-paste `/goal <end state> verified by <evidence> while preserving
   <constraints>. Use <boundaries>. Between iterations, <how to pick the next
   attempt>. If blocked, <what to report>.` Omit this item otherwise.

### Iterations

- Round 1: one line
- Total rounds: N

### Forward test

The input used, what the subagent did, and the findings and fixes, or
"Skipped — reason".

### Handoff items

Real uncertainty only: tradeoffs worth checking on another model, and for a
repeated workflow, eval cases worth keeping (input, pass condition, fail
condition).

### Unresolved issues

Open `[P0|P1] issue — why` lines.

An input that is already well optimized comes back unchanged with a one-line
justification and "Total rounds: 0". How to run it is still required.

With `--write`, after the report, write each Final version, without its fence, to
its file and list the files written. Leave a file untouched while it has an
unresolved P0.
