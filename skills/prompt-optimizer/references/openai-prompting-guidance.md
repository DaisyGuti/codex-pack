# OpenAI prompting guidance — bundled snapshot

> **Bundled reference for the `$prompt-optimizer` skill.** This is a frozen snapshot so the
> skill doesn't have to web-search on every run.
>
> - **Sources:**
>   - `https://developers.openai.com/api/docs/guides/prompt-engineering` (core techniques —
>     this is the page `platform.openai.com/docs/guides/prompt-engineering` now redirects to)
>   - `https://developers.openai.com/api/docs/guides/prompting` (prompts-as-application-code,
>     refining prompts, the `v1/prompts` deprecation)
>   - `https://developers.openai.com/api/docs/guides/latest-model` (model-selection guidance)
>   - `https://developers.openai.com/api/docs/guides/reasoning` (reasoning_effort mechanics,
>     reasoning summaries, encrypted reasoning items)
>   - `https://developers.openai.com/api/docs/guides/reasoning-best-practices` (how to prompt
>     reasoning models)
>   - `https://developers.openai.com/api/docs/guides/function-calling` (tool-calling prompting
>     conventions)
>   - `https://developers.openai.com/api/docs/guides/structured-outputs` (JSON schema mode)
>   - `https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra`
>     (GPT-6 Astra-specific behavioral notes — the analogue of Anthropic's per-model pages)
>   - `https://developers.openai.com/api/docs/models/gpt-6-astra` (model specs)
>   - `https://cookbook.openai.com/examples/gpt-5/gpt-5-2_prompting_guide` (GPT-5.2 prompting
>     guide — still the live reference for anyone pinned to the GPT-5.x line)
>   - `https://openai.com/index/introducing-gpt-6-sol-and-luna/` (Sol/Luna launch specs)
> - **Section 8 sources** (symptom-to-remedy troubleshooting, adapted from OpenAI's Cookbook,
>   MIT, Copyright (c) 2025 OpenAI; notice in `THIRD_PARTY_NOTICES.md` at the pack root):
>   `examples/gpt-5/gpt-5_troubleshooting_guide.ipynb` and sections 3.2 to 3.4 and 5 of
>   `examples/gpt-5/gpt-5-2_prompting_guide.ipynb` in `https://github.com/openai/openai-cookbook`
> - **Snapshot date:** 2026-09-27 (section 8 added 2026-10-08)
> - **Covers models:** GPT-6 Astra (flagship, released 2026-09-03), GPT-6 Sol and GPT-6 Luna
>   (released 2026-09-22 — Sol for heavy reasoning, Luna for high-volume/low-complexity work),
>   plus the still-live prior generation: GPT-5.2, GPT-5.1, GPT-5, and the reasoning
>   (o-series-descended) model family generally.
> - **OpenAI ships per-model prompting guides too**, same pattern as Anthropic's per-model
>   pages — read the one for the model you're targeting first: the GPT-6 Astra blog post above,
>   or the `gpt-5-2_prompting_guide` / `gpt-5-1_prompting_guide` / `gpt-5_prompting_guide`
>   notebooks in the OpenAI Cookbook for the GPT-5.x line. What differs per model: default
>   `reasoning_effort`, whether `none` effort is supported at all, instruction sensitivity,
>   initiative/bias-to-action, and delegation behavior.
> - **Refresh:** when this snapshot is more than ~3 months old, or the user passes
>   `--refresh-guidance`, re-fetch the source URLs and overwrite this file (keep the same
>   structure; bump the snapshot date). The model lineup moves fast — confirm the current
>   flagship name before reusing any model-specific section below verbatim.

---

## 1. Foundational techniques

### Message roles: `developer` > `user` > `assistant`
- Three roles, in priority order. `developer` (the old `system` role, renamed at o1 and used
  by every model since) carries the application's business logic — tone, goals, boundaries,
  examples of correct responses. `user` carries the end user's input. Think of it as **a
  function and its arguments**: the developer message defines the function, user messages are
  the arguments it's applied to.
- **`system` is now reserved for OpenAI's own internal use on reasoning models** — don't rely
  on it carrying special weight in your own prompts; use `developer` for the same purpose the
  Anthropic file calls "system prompt."
- The `instructions` API parameter is a shortcut for high-level behavior (tone, goals, example
  responses) that applies only to the current request and outranks the `input` parameter.

### Be clear and direct — but the bar differs by model family
- **GPT-style (non-reasoning) models** need precise, explicit instructions: "provide the logic
  and data required to complete the task" — don't assume they'll infer missing steps.
- **Reasoning models** (o-series, and GPT-6 Sol/Luna at higher effort) work best from a clear
  goal, strong constraints, and an explicit output contract — **without** prescribing every
  intermediate step. Over-specifying the reasoning path can hurt them.
- **GPT-6 Astra specifically has "much better judgment" than prior models** — strip
  restrictive language that was written to compensate for older models' poor judgment; it
  makes Astra stop where you'd actually be happy for it to keep going. Prefer conditional
  grants of autonomy: `The local tests use disposable fixtures and have no production access.
  Run them, fix failures, rerun without asking.`

### Structure with Markdown + XML together
- Combine Markdown headers/lists with XML tags to mark logical boundaries. Canonical developer
  message shape, in order:
  1. **Identity** — purpose, tone, goals.
  2. **Instructions** — rules, dos/don'ts.
  3. **Examples** — diverse input/output pairs.
  4. **Context** — proprietary data / retrieved documents, placed near the end.

### Few-shot examples
- Collapse examples into a **concise YAML-style or bulleted block** rather than long prose
  pairs — easier to scan and to keep updated as a team.
- **Reasoning models often don't need few-shot examples at all** — write the prompt without
  examples first, and add them only if the output format is genuinely tricky. When you do add
  examples for a reasoning model, make sure they **align exactly** with your written
  instructions; a mismatch between the two produces worse results than no examples.

### Context placement and prompt caching
- Put reusable content (the developer message, tool definitions, long reference context) at
  the **beginning** of the prompt and **first** among API parameters — caching only helps the
  tokens that come before the first point of divergence between requests.
- Retrieval-augmented context (RAG results, file search hits) goes late in the prompt, same as
  Anthropic's "long-form data at the top, query at the bottom" — except here the framing is
  "identity/instructions/examples first, context last," so verify which placement your eval
  actually rewards before assuming the Anthropic convention transfers unchanged.

### Prompts as application code
- OpenAI is winding down the reusable `v1/prompts` API object (creation de-emphasized from
  2026-06-03, shutdown 2026-11-30). Store prompt text in versioned code modules instead of a
  hosted prompt object; use typed function arguments/schemas for the dynamic slots; review
  prompt diffs in the same PR as the product-behavior change they support; cover them with
  evals the way you'd cover code with tests.

---

## 2. Output and formatting control

### `reasoning_effort` — the primary intelligence/latency/cost lever
- Values in use across the model line: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`,
  `max` — **exact support varies by model**, check the model's own page before assuming a
  value works.
  - `low` — efficient reasoning, modest latency increase; good for tool-use/planning/search/
    multi-step decisions where you don't need the deepest reasoning.
  - `medium` — the default for most workloads; the balanced point on the latency/cost/quality
    curve.
  - `high` — hard reasoning, complex debugging, deep planning, high-value tasks where quality
    matters more than latency.
  - `xhigh` / `max` — reserved for the hardest coding/agentic/research work.
- **`GPT-6 Astra does not support `none`** — it requires at least `low`. GPT-6 Sol and Luna
  both accept `none` (a change from the GPT-5.x line, where `none`/`minimal` support was
  narrower). Migrating a prompt onto Astra: replace any `none`/`minimal` effort with `low`.
- Treat `reasoning.effort` as **a tuning knob, not the primary way to recover a quality
  regression** — if raising effort is fixing a bad prompt, fix the prompt.
- Mid-conversation: use `configuration_update` to raise effort for a hard turn or lower it for
  a routine follow-up, rather than fixing one effort level for the whole session.

### `verbosity` — separate parameter, separate lever from effort
- The GPT-5.x line (`gpt-5`, `gpt-5.1`, `gpt-5.2`, `-mini`, `-nano`, `-codex`, `-pro`) exposes
  `text: {verbosity: "low" | "medium" | "high"}` in the Responses API — controls answer length/
  detail independently of `reasoning_effort` (a terse answer can still involve deep reasoning).
  Default is `medium`.
  - `low` — chatbots, quick direct answers.
  - `high` — long-form documentation, deep analysis.
- **GPT-6 Astra's model page does not list a `verbosity` parameter** — for that model, control
  length by prompting for it directly (see the GPT-5.2 `<output_verbosity_spec>` pattern
  below), the same way Anthropic tells you to prompt Opus for length since `effort` there only
  controls thinking, not visible output.
- Concrete verbosity-control template (from the GPT-5.2 guide, portable to any model without a
  native verbosity knob):
  ```
  <output_verbosity_spec>
  - Default: 3–6 sentences or ≤5 bullets for typical answers.
  - For simple "yes/no + short explanation": ≤2 sentences.
  - For complex multi-step tasks: 1 overview paragraph + ≤5 bullets.
  Avoid long narrative paragraphs; prefer compact bullets and short sections.
  </output_verbosity_spec>
  ```

### Structured Outputs (JSON schema mode) vs. JSON mode vs. function calling
- **Prefer Structured Outputs over legacy JSON mode whenever possible** — JSON mode only
  guarantees valid JSON; Structured Outputs guarantees the response matches your schema
  exactly (`strict: true`).
- **Which mechanism to reach for:**
  - Model needs to call your app's functions/tools/data -> **function calling**.
  - Model just needs to hand a shaped answer back to the user/caller -> **structured
    `text.format`**.
- Field names and descriptions in the schema double as prompt content — "create clear titles
  and descriptions for important keys," since a vague field description under-constrains the
  model the same way a vague instruction would.
- Edge cases Structured Outputs surfaces explicitly rather than silently: a detectable
  `refusal` field (safety-based refusal), truncation from hitting the token limit, and content
  filtering — handle these three, don't assume every response is a clean schema match.

### Reasoning models: avoid chain-of-thought instructions
- **Do not tell a reasoning model to "think step by step"** — it reasons internally already;
  the instruction can measurably hurt performance rather than help it. This is close to the
  opposite of Anthropic's stance, where "think thoroughly" prompting is still a live lever on
  non-extended-thinking configurations — verify which family you're targeting before reusing
  either convention.
- Reasoning models "perform best with straightforward prompts" — task, constraints, desired
  output format, stated once, without step-scaffolding.

### Markdown formatting with reasoning models
- On `developer`-role reasoning models (o1-2024-12-17 and later), Markdown formatting can be
  suppressed by default in some UIs — include the literal line `Formatting re-enabled` as the
  first line of the developer message to turn Markdown output back on.

---

## 3. GPT-6 model family — behavioral notes (what changed, what to tune)

### Model selection
| Model | Use for | Reasoning effort | Context / max output |
|---|---|---|---|
| **GPT-6 Astra** | Hardest end-to-end work: computer use, browsing, software engineering, science, professional/document work. OpenAI's most aligned model — best judgment, most trustworthy with autonomy. | `low`–`max` (no `none`) | 1.05M context, 922K max input, 128K max output |
| **GPT-6 Sol** | Strong reasoning on demanding tasks: complex, multi-step coding/agentic/reasoning-heavy work where accuracy on hard problems matters more than throughput. | `none`–`max` | 1.05M context, 922K max input, 128K max output |
| **GPT-6 Luna** | Efficient, repeatable work at scale: summarization, extraction, classification, Q&A — high volume, lower complexity. | `none`–`max` | 1.05M context, 922K max input, 128K max output |

Pick by "the reasoning your task requires, latency, and cost" — not by defaulting to the
flagship. Astra "achieves stronger results while using substantially fewer output tokens" than
its predecessor, so it isn't automatically the most expensive-per-task choice even though it's
priced highest per token.

### GPT-6 Astra specifics — from the "Rethinking skills and prompts" guide (read this before targeting Astra)
- **Bias toward action.** Astra can be more tentative about when to stop, or ask a clarifying
  question where a prior model would have just acted. Counter this explicitly: tell it to
  infer intent and act — treat "can you...", "I want to...", "help me..." as calls to act, not
  invitations to ask a follow-up question. Have it prepare a concrete, reviewable result before
  seeking approval, rather than front-loading warnings or a safety checklist nobody asked for.
- **Define "done" up front.** Because Astra can stop early, state completion explicitly and
  push it to continue through every phase: get the implementation running, inspect the result,
  fix what fails — don't assume "make it work" implies all three.
- **More sensitive to instructions buried in context files (skills, `AGENTS.md`).** If
  supporting docs disagree with each other or with the user's actual ask, Astra may pause,
  change direction, or follow a rule nobody wanted followed. Audit every skill/context file the
  model can see, give the user's instruction explicit priority over a stale doc, and keep skill
  descriptions minimal and specific:
  - Bad: `Create and validate Postgres schema migrations. Use when working with databases,
    queries, models, or persistence.`
  - Good: `Create and validate Postgres schema migrations. Use when adding or changing a
    migration.`
  - Prefer a root doc that's a thin router to supporting docs over one comprehensive doc Astra
    is expected to read start-to-end every time.
- **Delegates to sub-agents less than you might expect.** If you want parallel sub-agent use,
  say so explicitly and say how much — don't assume Astra will reach for delegation on its own
  the way some prior models over-delegated.
- **Tests proportionally to the change, without being told to stop.** Older models needed
  encouragement to test their own work; Astra does it unprompted, which means an old prompt
  that says "always run the full test suite" now produces disproportionate test runs on a
  one-line change. For small edits, scope it: rerun tests only when new failures or unresolved
  issues justify it.
- **Writing-style / "slop" blocklist.** OpenAI ships a list of banned filler phrases for prose
  output — treat this the way Anthropic's file treats "no over-engineering language," except
  here it's about the model's *own written voice*, not instruction-following:
  - Banned openers/closers: `Conclusion:`, `In short:`, `Bottom line:`, `The simplest mental
    model is:`
  - Banned hedge/filler words: `delve into`, `leverage`, `foster`, `promote`, `it's worth
    noting`, `what's important is`, `importantly`, `really`/`truly`, `genuinely`, `let's dive
    in`
  - Banned rhetorical shape: contrastive framing (`X, not Y` / `X — not Y` / `This isn't about
    X, it's about Y`), invented hyphenated compounds (`exact-head checks`, `editorial-row
    layouts`), and narrating what it *won't* do instead of just doing it.
  - Positive guidance to replace all of the above: clear concise paragraphs each developing one
    idea, sparing list use, active voice, direct statements, precise verbs over vague ones.

### Migrating a prompt across the GPT-5.x -> GPT-6 line (from the GPT-5.2 guide, same pattern applies to Astra)
1. Switch models first, **without changing the prompt** — you want to isolate the model
   change from a prompt change.
2. Pin `reasoning_effort` explicitly to match the old latency/quality profile (`none` -> `low`
   for models that dropped `none` support; otherwise preserve the same effort value across
   GPT-5 -> 5.1 -> 5.2).
3. Run your eval suite for a baseline before touching anything else.
4. If there's a regression, tune the prompt (OpenAI's Playground ships a Prompt Optimizer for
   this) — one change at a time, re-running evals after each.
- GPT-5.2 vs. GPT-5/5.1, behaviorally: more deliberate scaffolding/planning by default, lower
  verbosity, stronger instruction adherence ("less drift from user intent"), and a more
  conservative grounding bias (favors explicit reasoning and correctness over confident
  guessing).

---

## 4. Reasoning-model prompting (o-series lineage, and any model at higher `reasoning_effort`)

- Give the model **a clear goal, strong constraints, and an explicit output contract** — skip
  prescribing the intermediate steps; that's what the model's internal reasoning is for.
- **Skip few-shot by default**; add examples only for a genuinely tricky output format, and
  make sure they match your written instructions exactly if you do.
- **Skip "think step by step" and similar chain-of-thought scaffolding** — it can hinder these
  models rather than help.
- State constraints as concrete numbers where possible (`propose a solution with a budget
  under $500`) rather than vague qualifiers, and give it license to keep reasoning/iterating
  until it meets a stated success criterion.
- **For agentic or research-heavy work, define what counts as "done"** explicitly — same
  instinct as the GPT-6 Astra "define completion before starting" note above, generalized to
  the whole reasoning-model family.
- **Reasoning summaries:** set `summary: "auto"` to get the most detailed available summarizer
  for a given model; summaries land in the `summary` array on the reasoning output item and are
  opt-in — they're not included unless you ask.
- **Encrypted reasoning without server-side storage:** when `store: false`, reasoning output
  items carry an `encrypted_content` field you can pass back into a later call to preserve the
  model's reasoning state across turns without OpenAI retaining it server-side.
- Reasoning tokens occupy context-window space and bill as output tokens even though they're
  not shown by default — budget for them the same way Anthropic budgets `max_tokens` headroom
  for extended thinking.

---

## 5. Agentic / tool-use guidance

### Writing tool/function definitions
- **Apply the "intern test":** could a person execute the function correctly using nothing but
  the name, description, and parameter docs you gave the model? If not, the model can't either.
- Write clear, detailed function names and parameter descriptions — state the function's
  purpose, each parameter's meaning/format, and what the output represents. Put the
  when-to-use-this guidance in the developer message, not just the function description: "tell
  the model *exactly* when (and when not) to use each function," including edge cases,
  especially ones you've seen it get wrong before.
- Use enums and structured parameter objects to make invalid calls unrepresentable, rather than
  documenting "don't pass X and Y together" in prose.
- **Enable `strict: true` mode by default** on function tools — this makes the model's calls
  reliably match the schema instead of "best effort." For an optional field under strict mode,
  type it as `["string", "null"]` rather than simply omitting it from `required`.

### Keep the tool surface small
- Aim for **fewer than 20 tools available at the start of a turn** (a soft guideline, not a
  hard cap) — accuracy drops as the choice set grows. For a large tool ecosystem, defer rarely
  used tools behind a tool-search/namespace layer and load them on demand; keep the namespace
  description terse (it's just for the model to decide what to load) and put the real
  how-to-use guidance in the individual tool's own description.

### Reduce the model's workload
- **Don't make the model re-supply information you already have** — if you already know
  `order_id` from an earlier step, don't expose it as a parameter the model has to fill in
  again.
- **Merge functions that always fire together** — if you always call `mark_location()`
  immediately after `query_location()`, fold the marking logic into the query call instead of
  making the model orchestrate two calls it will always chain identically.
- Set `parallel_tool_calls: false` when you need a hard guarantee of "zero or one tool call per
  turn," rather than trying to word that constraint into the prompt.

### Agentic persistence and scope
- Push toward **resolving the full query before yielding control back**, rather than stopping
  at the first partial success — pair this with an explicit definition of "done" (§3, §4).
- Use a TODO-tracking or rubric pattern for multi-step agentic work so progress survives across
  turns/compaction, and have the model explain notable tool calls at the point it makes them
  rather than narrating every single one.
- **Sub-agent delegation is opt-in on GPT-6 Astra** — state explicitly when and how much it
  should delegate to parallel sub-agents; don't assume it will reach for delegation the way
  some prior models did.

---

## 6. Capability notes — native tools and model-naming

- **Built-in Responses API tools:** web search, file search (RAG over uploaded files), code
  interpreter (sandboxed code execution), computer use, and remote MCP server connections.
  Image generation and vision (image input) are separate model capabilities rather than
  Responses-API tools, and both are supported on the current flagship line.
- **A model cannot call a different provider's API on its own** — same limitation as Claude;
  any cross-model comparison or handoff is a step your application code performs, not
  something you prompt the model to do internally.
- **Output shape warning:** the Responses API's `output` array frequently holds more than one
  item (reasoning items, tool calls, message items) — never assume the final text lives at
  `output[0].content[0].text`; walk the array for the item(s) you need.
- **Pin production traffic to a specific model snapshot**, not a rolling alias, and keep an
  eval suite that would catch a behavior change if OpenAI moves the alias underneath you.
- For an app that must name a model explicitly today: `gpt-6-astra` for the flagship,
  `gpt-6-sol` for reasoning-heavy work at lower cost, `gpt-6-luna` for high-volume/low-
  complexity work. Confirm current names before hard-coding — this line moves roughly every
  season.

---

## 7. Quick checklist mapping (how the optimizer should apply this)
- **Clarity** -> §1 (message-role hierarchy; GPT-style vs. reasoning-model literalness split).
- **Examples** -> §1 Few-shot examples (YAML/bulleted block; skip entirely for reasoning
  models unless the format is genuinely tricky, and then match them exactly to the instructions).
- **XML/structure** -> §1 Markdown + XML together (Identity / Instructions / Examples /
  Context ordering).
- **Format control** -> §2 (`reasoning_effort` vs. `verbosity` are two separate levers; use
  Structured Outputs over JSON mode; the `<output_verbosity_spec>` template when a model has no
  native verbosity knob).
- **Failure-mode handling** -> §2 Structured Outputs edge cases (refusal field, truncation,
  content filtering) + §5 tool-definition edge cases ("intern test", strict mode).
- **No over-engineering** -> §3 GPT-6 Astra slop-word blocklist and "don't restate what you
  won't do" + §3 "strip restrictive language written for older models' judgment."
- **Tool fit** -> §5 (tool count under ~20, strict mode, consolidate always-chained functions,
  don't re-ask for known values) + §6 (what's actually built into the Responses API).
- **Determinism/robustness** -> §4 reasoning-model guidance (explicit "done" criteria, avoid
  step-by-step prompting) + §3 migration protocol (change model and prompt separately, eval
  between each change).
- **Evidence of a failure** -> §8 symptom-to-remedy table, after the diagnose pass in
  `diagnose-and-patch.md` has named the cause.
- **ALWAYS read the model-specific section (§3) before assigning a model or a `reasoning_effort`
  level in an optimized prompt.** GPT-6 Astra needs *less* restrictive scaffolding than older
  prompts assume and does not support `none` effort; GPT-6 Sol/Luna do support `none`; a
  reasoning model anywhere in the line performs worse, not better, if you add chain-of-thought
  instructions to it.

---

## 8. Troubleshooting: symptom to remedy

Use this when `--evidence` or a forward test shows a symptom. Name the cause with
`diagnose-and-patch.md` first; reach for a block below only when the cause is a missing
or unclear instruction. These remedies were written for GPT-5.x. GPT-6 models react
differently (section 3), so run the changed prompt on the target model before you keep a
block.

| Symptom | Usual cause | Remedy |
| --- | --- | --- |
| Correct answer, but slow: delayed first action, long exploration | Effort too high for the work, no definition of done, or conflicting guidance | Lower the effort for routine work and add an early-stop rule: act as soon as you can name the exact files or symbols to change, or can reproduce the failing test. Add one quick self-check before replying. Give trivial questions a fast path: answer at once, with no tool calls. |
| Thin or careless answer | Effort too low | Raise effort one step. Add a self-check: score the draft against a short rubric of five to seven items (clarity, correctness, edge cases, completeness) and fix once before replying. |
| Stops to ask, or hands back early | Too deferential | Add a persistence line: keep going until the request is resolved, make the most reasonable assumption when something is unclear, proceed, and record the assumption in the final report. Keep the approval gates from the instruction chain (public, paid, production, destructive actions); the Cookbook's version also says never to ask the user to confirm assumptions, and that part conflicts with them. |
| Final message too long | No length cap | State a length per kind of answer (see `<output_verbosity_spec>` in section 2). Use the `verbosity` setting where the model has one. |
| Slow start, many sequential reads | Independent reads run one at a time | Tell it to run independent or read-only actions in parallel: reading several files, searches, metadata queries, edits to unrelated files. Measure time to first action separately from model time. |
| Too many tool calls | Overlapping tool definitions, a prompt that rewards thoroughness, effort too high | Make answering from context the default, give each tool one job with a "do not use for" note, and cap calls per request unless new information makes another one necessary. |
| Malformed tool call, or repeated garbage after one | Two sections of the prompt or tool configuration contradict each other | Run the diagnose pass on the prompt plus the tool configuration, and remove the contradiction. |
| Confident wrong details on an unclear request | Missing uncertainty rule | Tell it to ask one to three precise questions, or list two or three labeled interpretations, and never to invent figures, line numbers or references. For high-risk output, add a final re-scan for unstated assumptions, ungrounded numbers and overly strong words. Where it can act, a stated assumption beats a question. |
| Does more than asked: extra features, invented styling | Scope not bounded | Say to implement exactly what was requested, to follow the existing design system, to invent no colors, tokens or components, and to take the simplest valid reading of an ambiguous instruction. |
| Loses details in long input | No re-grounding step | For inputs past roughly ten thousand tokens, ask for a short outline of the relevant sections, a restatement of the user's constraints, and claims anchored to named sections. |
| Update messages are noisy | No update rule | Allow a one or two sentence update only at a new phase or when the plan changes, each with a concrete outcome, and call newly noticed work optional. |

One group of failures per fix. When a model proposes a change to its own instructions,
run it a few times and keep what repeats; single suggestions are often specific to one
case, and a general version of them is usually the better edit.
