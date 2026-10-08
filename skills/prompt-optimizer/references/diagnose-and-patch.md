# Diagnose, then patch

Read this when `--evidence` is passed, or when a forward test shows the prompt
misbehaving. It splits the fix in two passes so the cause is named before any wording
changes. The method and both templates are adapted from the metaprompting section of
OpenAI's Cookbook "GPT-5.1 Prompting Guide"
(`examples/gpt-5/gpt-5-1_prompting_guide.ipynb`, MIT, Copyright (c) 2025 OpenAI; the
notice is in `THIRD_PARTY_NOTICES.md` at the root of this pack).

## Rules for both passes

- One group of related failures per run. A mix of unrelated failures (too long, too
  many tool calls, wrong units) blurs the analysis; run the passes once per group.
- Pass 1 asks for causes only, with no fixes; the Cookbook keeps the two apart, and
  fixes come in pass 2.
- Run each pass as a separate call: a fresh subagent, or `codex exec` through the
  ChatGPT sign-in ([testing-without-api-spend.md](testing-without-api-spend.md)), at
  the setting [model-selection.md](model-selection.md) gives for prompt work.
  Model-proposed fixes can be over-specific to the failures shown, so keep only the
  ones that generalize.
- After the patch, re-run the failing inputs (the forward test in
  [forward-test.md](forward-test.md)) and compare. A patch that has not been re-run is
  a hypothesis.

## Pass 1: diagnose

Brief the analyst with the prompt and a small batch of failures, each with its input,
the actions taken, the output, and the signal that it was wrong (a correction, a
rating, a failed check). Name the failure types you expect, and leave the fact-finding
to the analyst.

```text
You are a prompt engineer debugging an instruction file for a model-driven agent.

<prompt>
[THE CURRENT PROMPT]
</prompt>

<failures>
[THE FAILURE BATCH: input, actions taken, output, signal]
</failures>

Do not propose fixes yet. For each distinct failure mode:
1. Name it in a few words and describe it.
2. Quote the exact lines of the prompt most likely to cause or reinforce it, and name
   any contradictions between lines (for example "be concise" against "cover every
   case", or "avoid tools" against "always check with a tool").
3. Say how those lines steer the model toward the observed behavior.
4. Classify the cause: the instruction is missing; it is present but unclear; it is
   present but was not followed; or the cause is outside the prompt (a tool, the
   harness, the input).
```

## Pass 2: patch

Brief the patcher with the prompt and the pass 1 analysis.

```text
You analyzed this prompt and its failure modes.

<prompt>
[THE CURRENT PROMPT]
</prompt>

<analysis>
[THE PASS 1 OUTPUT]
</analysis>

Propose a minimal revision that reduces the observed failures and keeps the good
behavior.
- Do not redesign the prompt.
- Prefer small, explicit edits: resolve conflicting rules, remove redundant or
  contradictory lines, tighten vague guidance.
- State each tradeoff (for example, when concision wins over completeness, or exactly
  when a tool must and must not be used).
- Keep the structure and length about the same, unless a short merge removes obvious
  duplication.
- Leave out any failure whose cause lies outside the prompt; list it separately.

Return patch_notes (each change and the reason for it) and the full revised prompt.
```

## Using the result

Fix the first three cause classes in the prompt, report the fourth under Handoff
items, and turn each failure into an eval case for Handoff items. When the failure is a
malformed tool call or other erratic output, pass 1 almost always finds two prompt
sections that contradict each other; feed it the tool configuration along with the
prompt.
