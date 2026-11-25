# Rule sources

Facts the rules rely on, with where each came from. The hook rows were read in the Codex manual
on 2026-11-25 (Codex CLI 0.171) and checked on a live `codex exec` run; the credential and GCP
rows were fetched 2026-10-16. Re-check a row before changing the rule behind it.

## Contents

- Hook behavior
- Credential formats
- GCP
- Gaps

## Hook behavior

| Fact | Source |
| --- | --- |
| Codex reads user hooks from `$CODEX_HOME/hooks.json` (or inline `[hooks]` in `config.toml`) and project hooks from `.codex/hooks.json` in trusted projects | https://learn.chatgpt.com/docs/hooks.md, "Where Codex looks for hooks" |
| A non-managed hook runs only after a person reviews and trusts it with `/hooks` (Settings > Hooks in the app); trust is recorded against the hook's hash, so a changed definition needs a new review | Same page, "Review and trust hooks" |
| `PreToolUse` sees shell commands and unified exec as `Bash` and file edits as `apply_patch`; both put their text in `tool_input.command`. Confirmed on a live run: a string command and a patch beginning `*** Begin Patch` | Same page, "PreToolUse" and "Tool coverage" |
| Exit code 2 with the reason on stderr blocks the call, and the model receives the reason. Confirmed on a live run | Same page, "PreToolUse" |
| `permissionDecision: "ask"` is not supported: Codex marks the hook failed and runs the tool | Same page, "PreToolUse" |
| A hook error, timeout or malformed response can let the tool run; there is no setting that blocks instead | Same page, "Hooks with cloud orchestration" |
| The command runs through a shell with the session `cwd`; the manual's own examples use `$(git rev-parse ...)`. Confirmed on a live run: a `${VAR:-default}` command started the hook | Same page, "Config shape" |
| The payload carries `session_id`, `cwd`, `hook_event_name`, `model`, `permission_mode`, `turn_id`, `tool_name`, `tool_input` and `tool_use_id`, and no agent type. The pack's read-only agents are held to it by `sandbox_mode = "read-only"` instead | Same page, "Common input fields"; live run |
| Hooks are switched off by `[features] hooks = false` (`codex_hooks` is the old alias), `--disable hooks`, or `codex features disable hooks`; per-hook trust and enabled state live under `[hooks.state."<key>"]` in `config.toml` | Same page, "Turn hooks off"; `codex exec --help`; strings in the 0.171 binary |
| Hosted tools such as web search do not use the hook path, and some specialized tool paths can opt out | Same page, "Tool coverage" |

## Credential formats

| Format | Source |
| --- | --- |
| GitHub `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_` | https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github |
| GitLab `glpat-`, `gloas-`, `gldt-`, `glrt-`, `glrtr-`, `glcbt-`, `glptt-`, `glft-`, `glimt-`, `glagent-`, `glsoat-`, `glffct-` | https://docs.gitlab.com/security/tokens/ |
| AWS access key ID prefixes `AKIA` (long-term) and `ASIA` (temporary) | https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html |
| Slack `xoxb-`, `xoxp-`, `xapp-` (also `xoxe.xapp-`) | https://docs.slack.dev/authentication/tokens |
| Slack `xoxa-`, `xoxr-`, `xoxs-`, `xoxo-`, `xoxe-` and webhook URLs under `hooks.slack.com/services/` | Common scanner patterns; the Slack page above omits them (UNVERIFIED against Slack docs) |
| Google API keys start `AIza`; OAuth client secrets start `GOCSPX-` | Common scanner patterns (UNVERIFIED against Google docs) |
| Anthropic API keys start `sk-ant-` | Common scanner patterns (UNVERIFIED against Anthropic docs) |
| A service account key file is JSON with `"type": "service_account"`, `private_key_id` and `private_key` | https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys (key alternatives and risk) |

The content check also matches the PEM private-key header followed by key material, and
`NAME=value` assignments whose name contains SECRET, TOKEN, PASSWORD, API_KEY and similar words,
when the value is long, mixes letters and digits, has high entropy, and is not a placeholder,
path, URL or variable reference. That heuristic is a judgment call with no published standard behind it.

## GCP

| Fact | Source |
| --- | --- |
| `allUsers` is "anyone who is on the internet, including authenticated and unauthenticated users"; `allAuthenticatedUsers` is all users and service accounts authenticated with a Google Account | https://docs.cloud.google.com/iam/docs/principals-overview |
| Google recommends managed workload identities, Workload Identity Federation, attached service accounts and OAuth user credentials over service account keys | https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys |
| `gsutil iam ch -d` removes a binding, so it passes; `gcloud ... remove-iam-policy-binding` passes | `gsutil help iam ch` text (UNVERIFIED here: gsutil was not installed when the rule was written) |
| `gcloud run deploy ... --allow-unauthenticated` is the documented way to "make your service publicly accessible". The rule matches that exact flag, so `--no-allow-unauthenticated` passes (that spelling was not on the page fetched; UNVERIFIED) | https://docs.cloud.google.com/run/docs/authenticating/public |

## Gaps

- `git` hooks are skipped by `HUSKY=0` only when it is set on the same command as the commit or
  push. A separate `export HUSKY=0` earlier in a session is not tracked.
- `gsutil` is the legacy tool. The rules read both it and `gcloud storage`.
- The installed hook is a link into the pack checkout, so the tamper rule also guards that
  checkout's `scripts/guardrails.py` and `hooks/hooks.json`. Change them from another worktree,
  which the pack's own rules ask for anyway (work lands by pull request).
- A hook timeout or a missing `python3` lets the call through (see Hook behavior). The hook's
  git probes are capped at 2 seconds each so the 15-second timeout is not reached in practice.
