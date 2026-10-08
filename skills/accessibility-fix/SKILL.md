---
name: accessibility-fix
description: "Use to repair accessibility problems: 'fix the a11y issues in X', 'make this accessible', 'add missing alt text and labels'. Also applies a findings list from another accessibility skill. Edits code, verifies, leaves TODOs for judgment calls. Finding issues: $accessibility-scan. Regressions: $accessibility-diff."
license: MIT
---

# Accessibility fix

This skill remediates accessibility violations: baseline, edit, verify. Finding problems belongs to other skills: use `$accessibility-scan` (one page, automated), `$accessibility-inspect` (one page, manual), or `$accessibility-audit` (whole site, WCAG-EM), and `$accessibility-diff` checks for regressions. The engine runs here are steps inside the loop: a baseline before and a check after.

Usage: `$accessibility-fix [target|url|report]`

Shared conventions (grounding, never invent content): [references/methodology.md](references/methodology.md).

Run the whole loop in one turn: baseline, every fix the rules allow, verify, report. Given a target or worklist, do not stop to ask whether to proceed.

## Large remediations

A big worklist can go to a `worker` subagent so the edits stay out of the main thread. The steps are the same.

- Model and effort ([references/model-selection.md](references/model-selection.md)). Resolve with `python3 scripts/resolve_model.py <tier> --effort <effort>` (the path is relative to this skill folder) and set the printed `model` and `reasoning_effort` on the spawn. Use `fast` / `high` when every item in the worklist has a `Source:` line and a `mechanical` fix. Use `workhorse` / `medium` when items need locating by selector or text, or include contextual fixes. If the result comes back thin, rerun that unit one step up.
- One writer. Edits run in a single `worker`. To split the work across several, give each its own git worktree and its own files, and keep the number of children within `agents.max_concurrent_threads_per_session` (older name `agents.max_threads`) in the Codex config. Children do not spawn further agents.
- The brief stands alone, because the child does not see this skill. It carries the worklist or target, the conventions above, the stop rules below, the instruction to leave changes uncommitted, and what to return: files changed with the rule ID fixed in each, the TODOs left (rule ID and why), and the child's own before and after counts. It asks for a summary and no raw audit output.
- Verification stays with you. When the worker returns, run the Verify step yourself on the live page. Only your own verify run counts as verification, whatever the worker reports.

## Setup

The baseline and verify runs use the AccessLint MCP server's tools (`audit_live`, `audit_html`, `explain_rule`, `list_rules`). If they are not connected, add the server once:

```bash
codex mcp add accesslint -- npx -y @accesslint/mcp@latest
```

Without it, the `Fixability:` and `Fix:` fields below are unavailable. Baseline and verify with `npx -y @accesslint/cli@latest scan <target> --format json` as in `$accessibility-scan`, and treat every fix beyond the obvious attribute change as contextual.

## Input

- A findings worklist (from `$accessibility-scan`, `$accessibility-inspect`, or `$accessibility-audit`, or pasted): apply it directly; the baseline is already done.
- A target (URL, config target name, files, or a directory): audit it first for the baseline, then fix.

Given neither, ask what to fix. Don't sweep a whole codebase unprompted.

## Picking a flow (for baseline and verify)

1. `audit_live` for any URL. It ensures a debuggable Chrome (auto-launches a headless one if none is reachable) and audits the live DOM. Use `selector` to scope and `wait_for` for async content. The live DOM catches what source can't.
2. `audit_html` for raw HTML strings, files (read them first), or JSX rendered to a string.

For an authenticated session, have the user start a headed debuggable Chrome (`npx @accesslint/chrome ensure --headed`), sign in, then call `audit_live({ url, port })` to attach to it.

## Steps

1. Baseline. Audit with `format: "compact"` and record the violation set (rule ID and selector for each). Skip this if you were handed a worklist.
2. Apply. For each violation:
   - If a `Source:` line is present, open that file at that line. If several are listed (separated by `←`), the first is the JSX literal and the rest are enclosing components; use `Symbol` to disambiguate.
   - If not, grep stable hooks (`data-testid`, `id`, `aria-label`), then visible text, then tree position.
   - Use the `Fixability:` and `Fix:` fields: apply `mechanical` fixes as given; leave a `TODO` with the rule ID for `contextual` or `visual`. Don't invent content (alt text, labels, link text).
   - Group edits to the same file into one operation.
   - Edit the files in the target and the files a `Source:` line or the worklist names. A fix that needs any other file goes in the report as deferred, with the file named.
3. Verify. Re-run the same audit and compare to the baseline: every targeted violation gone, no new ones. For a precise new/fixed/pre-existing comparison on a URL, use `$accessibility-diff` rather than checking by eye. Close the loop in the report: every violation in the baseline ends as fixed, deferred with a TODO, or still failing with the reason.

`Source:` lines come from React DevTools fibers and appear only in live-DOM audits against React dev builds. Static audits won't have them; fall back to selectors. When unsure about a rule, use `explain_rule({ id })`.

## When to stop

- A violation with no `Fix:` directive: leave a `TODO`, don't guess.
- Verification fails (a new violation appeared, or a targeted one remains): make one corrective pass on the edits you made, re-verify, and say in the report that you did. If it still fails, report it and stop.

## Output

Open with one line that gives the result, for example "Fixed 12 of 15 violations on /checkout; 3 deferred as TODOs; no new violations." Then, per cycle: the flow used, violations by impact, what was applied (file and rule), what was deferred (TODOs and why), and the before and after counts.

Adapted from AccessLint/skills (MIT); the license text is in [LICENSE.txt](LICENSE.txt).
