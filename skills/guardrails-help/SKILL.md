---
name: guardrails-help
description: Use when a call fails with "guardrails[...]", or to ask what the guardrails hook blocks, what it blocked lately, or how a person allows one. Not for writing hooks.
---

# Guardrails help

The pack's guardrails hook ([scripts/guardrails.py](scripts/guardrails.py)) runs before every
shell command and every `apply_patch` edit. It refuses a risky call with exit code 2 and one line
that starts with `guardrails[<rule-id>]`. A person decides whether a refused action ever runs;
the agent does not.

## If a call was just blocked

1. Stop. Tell the user in one or two sentences what was blocked and why, using the rule's reason.
2. Take the safe path the message names when it matches what the user wants. For a protected
   branch: push a feature branch, then open a pull request (`gh pr create`) or merge request
   (`glab mr create`).
3. Do not retry the same goal in another form: other flags, `sh -c`, a script file, a split
   command, a variable. That is the evasion the rules exist to stop.
4. Never write to a waiver file under `${CODEX_HOME:-~/.codex}/guardrails-allow/`, the hook
   script, a `hooks.json` or the hook settings in `config.toml`. The `guardrails-tamper` rule
   blocks it; only a person changes them.

## Show the rules

Run this and present the output as a short table of rule id, what it blocks, why, and the safe
alternative. The script is the source of truth, so do not answer from memory.

```sh
python3 "${CODEX_HOME:-~/.codex}/skills/guardrails-help/scripts/guardrails.py" --list-rules
```

## Show recent blocks

```sh
python3 "${CODEX_HOME:-~/.codex}/skills/guardrails-help/scripts/guardrails.py" --recent 20
```

It reads `${CODEX_HOME:-~/.codex}/guardrails/blocks.log`. Each line is JSON with `ts`, `event`,
`rules`, `tool`, `cwd`, `session` and `command` (credential-shaped text replaced by
`[redacted]`). `event` is `block`, or `allowed-by-config` when the person's waiver file let a
rule through. Group repeats by rule so the user sees patterns.

## How a person runs a blocked command on purpose

The hook fires only on the agent's tool calls, so a person has these routes:

1. **One time:** run the command in their own terminal.
2. **A repo that needs a rule off:** a person lists the rule ids, one per line with `#` for
   comments, in `${CODEX_HOME:-~/.codex}/guardrails-allow/<key>.txt`. The key names the repo:
   `<basename>-<16 hex>`, the git root's last path component (anything outside `A-Za-z0-9._-`
   becomes `-`) and the first 16 hex digits of the SHA-256 of its absolute path with symlinks
   resolved (the session directory outside a repo). Print the file's path rather than work it out:

   ```sh
   python3 "${CODEX_HOME:-~/.codex}/skills/guardrails-help/scripts/guardrails.py" --allow-path
   ```

   ```text
   # the docs bucket is public on purpose
   gcp-public-access
   ```

   They write it in an editor or their own terminal, never through the agent. It applies to that
   checkout on that machine only. A `.codex/guardrails-allow.txt` committed in a repo is ignored
   (a cloned repo must not switch rules off); the block message says so when one exists. Unknown
   ids are ignored, so a typo leaves the rule on. `guardrails-tamper` and `cannot-decide` cannot
   be listed.
3. **Turn the hook off:** in Codex, `/hooks` (Settings > Hooks in the app) disables it, or the
   person removes the entry from `${CODEX_HOME:-~/.codex}/hooks.json`.

Nothing a command or an environment variable says can turn a rule off. Only the waiver file can.

## Install and trust

`install.sh` links `${CODEX_HOME:-~/.codex}/hooks.json` to the pack's `hooks/hooks.json` when no
hooks file exists, and prints the entry to add by hand when one does. Codex runs a new or changed
hook only after a person reviews and trusts it once with `/hooks`; until then nothing is blocked.

## What the rules do not see

State these limits plainly when asked whether something is covered:

- The text of a script file a command runs, aliases, and values a command computes
  (`$(some-tool)`), except the current branch and variables set earlier on the same line.
- Programs that start other programs themselves, and encoded or obfuscated commands.
- A search over a whole directory (`grep -r`, `rg`) that reaches a `.env` file. Only a command
  that names the secret file is blocked.
- MCP tools and hosted tools such as web search: the hook matches `Bash` and `apply_patch` only.
- Files a person attaches to the prompt.

## Failure behavior

The script fails closed on its own errors: malformed input, a crash or a command too nested to
read exits 2 with `guardrails[cannot-decide]`. Codex has no setting that blocks when a hook
cannot run, so a missing `python3` or a hook timeout (15 seconds) lets the call through. If the
guard itself breaks, tell the user rather than working around it.

## Tests for code that handles credentials

The content rules see test files too. Build fake tokens from pieces at run time (for example
`"gh" + "p_" + "a" * 36`) so the file holds no literal that looks like a real credential.

The facts behind each rule, with sources: [references/rule-sources.md](references/rule-sources.md).
