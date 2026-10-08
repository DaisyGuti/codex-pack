---
name: accessibility-audit
description: "Use for a whole-site or whole-product accessibility assessment: 'audit my site for accessibility', 'WCAG or Section 508 conformance report'. Samples pages per WCAG-EM, runs scan and inspect on each, writes one report. One page: $accessibility-scan. Fixes: $accessibility-fix."
license: MIT
---

# Accessibility audit

Usage: `$accessibility-audit [target|url] [--level AA|AAA] [--selector <css>]`

This is a full WCAG 2.2 accessibility audit using WCAG-EM. It defines scope, samples representative pages and flows, runs both evaluation tiers, and produces one conformance report:

- Automated tier: `$accessibility-scan` (the rule engine).
- Semi-automated manual tier: `$accessibility-inspect` (keyboard, focus, state, reflow, and the rest the engine can't decide).

This skill assesses. Repairs belong to `$accessibility-fix` and before-and-after comparisons to `$accessibility-diff`. One page with no sampling is an `$accessibility-scan`. A larger sample runs one subagent per page (step 4), which keeps the main thread light.

Run the audit to the end in one turn. Do not stop to confirm the scope or the sample: write down the assumptions you made at steps 1 to 3, run every step, and ask a question only when no target can be found. Every step either completes or is named in the report as skipped, with the reason.

The full doctrine (WCAG-EM in detail, the severity rubric with examples, the no-proxy boundary, grounding) is in [references/methodology.md](references/methodology.md). The rules needed to run this skill are below.

## Grading

Each finding carries a severity and an evidence basis. Keep them separate.

- Evidence basis: ● verified (deterministic, with cited proof) · ◐ flagged (evidence captured, a person decides) · ○ human-required (needs assistive technology or lived experience; handed off, not emulated).
- Severity: critical (blocks a core task) · serious (major barrier) · moderate (friction, still completable) · minor (polish).

## WCAG-EM steps

Run in order and state what you did at each.

1. Scope. State the target and its boundary, the goal (default WCAG 2.2 AA; `--level AAA` adds AAA), the technologies in use, and the assistive-technology baseline the human handoff should cover. You scope that baseline; you don't test it.
2. Explore. Search the repo (file search and grep) for routes, templates, and shared components. Note key flows, content types, and stateful UI (modals, wizards, empty and error states). `accesslint.config.json` targets are a starting point.
3. Sample. Choose a structured set (entry page, each key flow end to end, every page with a new template or complex widget, and the important states) and a small random set. Say what's in each and why.
4. Evaluate. Each sampled page or state gets its own Codex subagent (the built-in `worker`), so it runs in its own context and returns only its findings. For a sample of one or two pages, run the tiers inline instead.

   Set up the wave before spawning:
   - Model and effort. This is rubric-driven verification, so start at `workhorse` / `medium` ([references/model-selection.md](references/model-selection.md)). Resolve it once with `python3 scripts/resolve_model.py workhorse --effort medium` (the path is relative to this skill folder) and set the printed `model` and `reasoning_effort` explicitly on every spawn. Read the printed `notes` and pass on any that change what happened. Exit 3 means the account has no model for the tier: say so and use the nearest tier that resolves.
   - Thread limit. Read `agents.max_concurrent_threads_per_session` (older name `agents.max_threads`) from `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`) and the project's `.codex/config.toml`. Spawn at most that many pages at a time; when neither key is set, use waves of four. Open threads count against the limit, so close each child's thread as soon as its result is collected. When a spawn fails for lack of a free thread, wait for a running child to return, close it, and spawn that page again. Any other spawn error: record the page as not evaluated with the error text, and go on.
   - Children do not spawn further agents. Nesting is undocumented, so each child runs both tiers itself.

   Each child's brief stands alone, because a subagent does not see this skill. It carries the page or state (URL, `--selector`, `--wait-for`, any sign-in notes), the grading rules above, the dedup rule below and the instruction to edit no files. It also tells the child to skip the tear-down step of `$accessibility-scan`, because the Chrome that `ensure` starts is shared and stopping it would end the other children's work, and to report the `managed` value `ensure` printed. Each child:
   - runs `$accessibility-scan` (`--format json`) first, then `$accessibility-inspect` against the same rendered state, passing scan's results (or at least the list of SCs the engine covered) into the inspect run;
   - dedups by SC ownership **before driving, not after**: `$accessibility-scan` owns rule-detectable criteria, `$accessibility-inspect` owns interaction and judgment criteria; inspect never re-checks an engine-owned SC, and where both still cover the same SC at the same element, `$accessibility-scan`'s result wins;
   - returns one structured block and no raw logs: per finding, the SC, severity, evidence basis (●/◐/○), location, tier, evidence, and fix or handoff, plus this page's per-SC ledger (verified / flagged / engine-owned / N/A / not exercised) and the `managed` value.

   Wait for every child. A page whose block is missing, malformed or thin (no ledger) is rerun once at `workhorse` / `high` (resolve it with `--effort high`); if it fails again, list it under "not evaluated" in the report and the SCs it would have covered stay undetermined. Then stop the shared browser once (`npx -y @accesslint/chrome@latest stop --all`, skipped when every child reported `"managed":false`) and aggregate the blocks in step 5.

   A shared browser is optional and improves selector matching across tiers, but it's a pre-wired precondition, not something this skill sets up at runtime: the browser MCP binds to its Chrome at server start (`--autoConnect` or `--browser-url`), with the engine pointed at the same port. Without it (the default), each child runs both tiers against the same URL and `--wait-for` gate and dedups by SC ownership.
5. Report. Aggregate into the format below. Conformance has three states: pass or fail only for ● findings; everything ◐ or ○, and every SC no page exercised, is undetermined and goes to a human. One sampled page failing an SC fails it for the whole scope at that level. Don't report conformance you can't support, and don't let a not-exercised SC read as a pass. Keep the ledger to counts and bare SC lists, group undetermined SCs by shared reason (one clause per group), and spend the report's words on failures, flags, and handoffs: a pass is its SC number in the list, with at most one sentence of narration for the whole passing set.

## Report format

```
# Accessibility audit — <product / scope>
WCAG 2.2 Level AA · WCAG-EM · <N> pages/states sampled
Result: <one sentence: the conformance picture and the single most important fix>

## Scope
- Target & boundary: <…>     Goal: WCAG 2.2 AA
- Technologies in use: <…>
- AT baseline (for the human handoff, not tested here): <SR+browser pairs, keyboard-only, …>

## Sample
- Structured: <page/state> — <why>   (×N)
- Random: <page/state>

## Conformance (per success criterion)
- Pass ●: <n>  ·  Fail ●: <n>  ·  Undetermined (◐/○/not exercised): <n>  ·  N/A: <n>
- Fail ●: <SCs>   Pass ●: <SCs>   N/A: <SCs>
- Undetermined: <SCs (shared reason)> · <SCs (shared reason)>
- Pass/fail is asserted only for ● criteria; ◐/○ and not-exercised are undetermined.

## Findings — by severity, tagged by evidence basis
### Critical
- [●] <barrier> — SC x.x.x — where: <selector / file:line> — tier: scan|inspect — → `$accessibility-fix`
- [◐] <barrier> — SC x.x.x — evidence: <screenshot / measurement> — confirm: <what a person checks>
### Serious / Moderate / Minor
[same shape]

## Human-required (○) — the testing handoff
- <what only AT or lived experience reveals> — SC x.x.x
    needs: <functional ability + AT, per Section 508 FPC>   flow: <sampled flow>

## Recommendations
- Root-cause / pattern fixes (one change that clears many instances) → hand to `$accessibility-fix`.
- What to send to human and AT testing, and on which flows.
- Wire `$accessibility-diff` into CI for the sampled targets.
```

## Notes

- Assess only; the repairs are `$accessibility-fix`'s and the before-and-after comparison is `$accessibility-diff`'s. Usability is ◐ and lived experience is ○, handed off for a person to test.
- Conformance is per SC across the whole sample. Don't average failures away.
- Two browsers can drift selectors; prefer a shared browser for ●-precision, otherwise note that dedup is best-effort.
- State what wasn't covered (pages outside the sample, ○ criteria). Omitting it reads as "all clear".
- Use `list_rules` and `explain_rule` (AccessLint MCP tools) for engine-rule metadata. If the server isn't connected, add it with `codex mcp add accesslint -- npx -y @accesslint/mcp@latest`; the audit runs without it.

Adapted from AccessLint/skills (MIT); the license text is in [LICENSE.txt](LICENSE.txt).
