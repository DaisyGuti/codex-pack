---
name: model-usage-audit
description: "Use to audit how a product's code calls AI models, any provider: call sites, model ids, limits, cost, data flow, secrets, evals. Writes a findings report; states evidence and gaps, never compliance. Codex's own spend: $codex-usage."
---

# Model usage audit

Produce evidence and findings about how a codebase calls AI models, and a report that a
reviewer can act on. The script finds the facts; you read the code, fetch the provider pages,
and judge. Provider facts (model lifecycles, prices, authorizations) change often, so fetch
them on the day and cite the page and date. Never state that a system is compliant,
authorized or ready for an authorization decision. Report evidence and gaps; a person with the
authority decides.

The audit covers every provider the code calls: the Anthropic SDK, Claude on Vertex AI or
Bedrock, Gemini on Vertex AI, OpenAI, LangChain, LlamaIndex, LiteLLM and raw HTTP. It is not
limited to OpenAI: a product built on another provider is audited against that provider's
pages. Which model Codex itself should run for a task is `$model-recommender`'s question, and
what Codex runs cost is `$codex-usage`'s.

This skill reads code and writes a report. It does not change the audited code unless the user
asks for a specific fix afterward.

## Steps

1. **Scope.** The target is the argument, or the current folder. If the repository holds
   several services, list them and confirm which are in scope. Ask only if it is unclear.

2. **Inventory.** Run the script. It prints a readable summary and, with `--json-out`, saves
   the full result to a file you can reread. Write the file to a temporary folder outside the
   repository (`mktemp -d`):

   ```sh
   python3 ${CODEX_HOME:-~/.codex}/skills/model-usage-audit/scripts/inventory_model_calls.py <repo> --json-out <tmp>/model-inventory.json --limit 80
   ```

   The result lists call sites with the settings seen inside each call's parentheses, model
   ids with a form (`dated`, `undated`, `latest-alias`, `preview`), dependencies, routing
   hints, secret hits (values hidden), log and sensitive-word hints, tracked env files, and
   eval-looking files. Every hit is a lead. A timeout or retry count set when the client is
   built shows on the client line and applies to every call made through that client, so read
   the two together. The script skips vendored folders, linked worktrees and files over 1 MB,
   and does not see prompts stored outside the repository. If a section was cut off by
   `--limit`, read the rest from the JSON file.

3. **Read the code behind the hits.** For each file with call sites, read the call and the
   code that builds its inputs and uses its output. Build one row per call path: entry point,
   provider and route, the model id after resolving constants and environment variables, the
   parameters, who triggers it (a user waiting, a job, a pipeline), what data enters the
   prompt, and what is stored or logged. Drop false positives (comments, tests with mocks) and
   say how many you dropped. For a large repository with separate services, read each service
   in a parallel read-only subagent (a `workhorse` tier spawn at `medium` effort, with the
   model and effort resolved per
   [references/model-selection.md](references/model-selection.md)) and merge the rows
   yourself.

4. **Fetch the lifecycle facts.** Open the lifecycle pages for the providers found
   ([references/sources-to-fetch.md](references/sources-to-fetch.md)), write the deprecations
   file in the format given there, and rerun the inventory with `--deprecations FILE`. The
   model ids in the output now carry lifecycle status and retirement dates.

5. **Run the checks** in [references/checks.md](references/checks.md) against every call path:
   model ids, request parameters, limits and retries, caching and batching, responses and
   errors, data sent, where it goes, secrets, evals, cost, resilience. Fetch the migration
   page for each model in use to check parameters. Give each finding a severity from the
   scale in that file, with `file:line` evidence, why it matters, and a fix.

6. **Estimate cost** per call path with the arithmetic in section 10 of the checks file. Fetch
   prices on the day. Use measured token counts when logs or the usage fields exist and label
   anything estimated.

7. **Record the data flow and authorization evidence** per route, from fetched pages only.
   Quote what the page says with its URL and date. Where nothing is found, write "no evidence
   found" and the question to ask the vendor.

8. **Write the report** from [references/report-template.md](references/report-template.md).
   Order findings by severity, then by cheapness of the fix. Keep secrets, customer records and
   prompt text out of it. Tell the user where the file is, then summarize the three most
   important findings in plain language.

## Judgment calls

- A hit in a test or fixture with a mocked client is recorded as a note and left out of the
  findings. A real key in a fixture is Critical.
- A provider's recommendation (for example keeping activity logs) can collide with data
  minimization. Present both and name the decision-maker.
- If the user asks whether a route is "FedRAMP" or "approved", answer with what the fetched
  pages say and the gaps, and say the decision belongs to the authorizing official or the
  compliance owner.
- If the repo calls a model through an internal gateway, the gateway's config decides the
  real model and route. Say what could not be checked.
- To change a model id the product calls, run `$model-recommender` on the path first (it
  recommends OpenAI models; for another provider, use that provider's own guidance). To
  rewrite a prompt you found, use `$prompt-optimizer`.
