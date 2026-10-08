# Target guidance

Read the section for the resolved target, plus "Codex artifacts" when the input is
a `SKILL.md`, `AGENTS.md` or custom-agent `.toml`. Load guidance once per run, and
record in the iteration log which source you used and its date.

The OpenAI snapshot ships with this skill as
[openai-prompting-guidance.md](openai-prompting-guidance.md). Refresh it only when `--refresh-guidance` was passed or its
recorded snapshot date is more than three months old (a snapshot with no readable
date counts as old): re-fetch the source URLs in its header, keep its structure,
and bump the date. Overwrite the snapshot only after every source fetched; if one
failed, keep the existing file and log it as stale. Rewriting a snapshot is the one
file change allowed without `--write`. Other targets have no bundled snapshot:
fetch that provider's official prompting guide for the run, and without web access
fall back to generic conventions and log the target as unconfirmed.

When a fetch below fails, or returns an error page or a page missing the expected
frontmatter or section, use the fallback named for it. Where none is named, log
the source as unconfirmed and continue.

## openai

Two layers, both required:

1. **Model behavior, live.** Fetch
   `https://developers.openai.com/api/docs/guides/prompt-guidance.md` once. Its
   frontmatter names the current flagship and gives
   `latestModelInfo.promptingGuide`, a site-relative URL. When the page you
   fetched already has a `## Prompting best practices` section (on 2026-10-07 it
   was the same page), read that; fetch `https://developers.openai.com` plus the
   `promptingGuide` path (drop the `#anchor`) only when it does not. Read only that
   section, stopping at the next `## ` heading. When your brief already carries
   this section, use it and fetch nothing. This is the source of truth for how the current models behave
   (initiative, instruction sensitivity, writing style, delegation, testing).
   Without web access, or when this fetch is unusable, read
   `${CODEX_HOME:-$HOME/.codex}/skills/.system/openai-docs/references/prompting-guide.md`,
   the copy Codex ships, and say so in the log.
2. **Techniques, snapshot.** Read
   [openai-prompting-guidance.md](openai-prompting-guidance.md) sections 1, 2, 4
   and 5: message roles, structure, examples, structured outputs,
   reasoning-model prompting and tool definitions. Where it disagrees with the live
   page about a specific model, the live page wins.

For a coding-agent prompt, also compare it with the starter prompt in OpenAI's
[Codex Prompting Guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide.md):
autonomy and persistence, code implementation, editing constraints, plan closure,
review mode and the final-answer rules. That prompt was tuned on gpt-5.x Codex
models, so where it conflicts with the live best-practices section, the live
section wins. Three of its defaults clash with this user's setup and must not be
copied in: stopping when unexpected changes appear (working trees are often shared, so those
changes are left alone and reported), ASCII-only edits (match each file's existing
characters), and a bold default visual style (inside an existing design system,
keep its look).

Model and effort recommendations come from [`model-selection.md`](model-selection.md),
resolved with `scripts/resolve_model.py` in this skill's folder. A prompt that will
outlive this month names a tier, or reads its model from config; it never
hard-codes a slug.

## Codex artifacts

Apply on top of the `openai` section. Sources: OpenAI's
[Build skills](https://learn.chatgpt.com/docs/build-skills.md),
[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md.md) and
[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md) pages,
and the skill-creator Codex ships at
`${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/SKILL.md` (read it when
the input is a `SKILL.md`).

**SKILL.md**

- The `description` is an instruction ("Use when ..."), written from the user's
  intent first, with a boundary naming the neighbouring skill where similar requests
  would misroute. Trigger words come first, because Codex shortens descriptions when
  many skills are installed (the catalog gets at most 2% of the context window, or
  8,000 characters when the size is unknown, shared by all skills). It stays well
  under the 1,024-character limit. A catch-all description is a P1.
- Frontmatter is valid YAML with `name` and `description`. `name` is 1 to 64
  lowercase letters, digits and single hyphens, with no leading or trailing hyphen,
  and equals the folder name. Quote a description that holds a colon followed by a
  space. A SKILL.md body under 500 lines is the target; files it links sit one level
  down, and it says when to load each one.
- `agents/openai.yaml`, when present, uses only the keys `interface` (`display_name`,
  `short_description`, `icon_small`, `icon_large`, `brand_color`, `default_prompt`),
  `policy` (`allow_implicit_invocation`) and `dependencies`, and every icon path
  exists. A skill that needs an MCP server declares it there.
- The body is as short as the task allows and assumes Codex is capable. Keep only
  guidance that changes decisions. Detail that serves one mode moves to
  `references/` and is linked where it is needed; deterministic logic moves to
  `scripts/`.
- No README, changelog or install guide inside a skill folder.
- User instructions are stated to outrank the skill.
- A workflow that retries or writes to outside systems has a stopping condition
  proportional to its risk. Approval to do the task never widens its permissions.

**AGENTS.md**

- Durable repository rules only, one owner per fact, and links in place of copies.
  A root file works best as a short router to supporting docs.
- A conflict with another instruction file is a P1: current models pause or change
  course on conflicting guidance.
- Every command either exists in the repo or is marked unknown.
- The whole instruction chain fits `project_doc_max_bytes` (32 KiB by default).
- A `## Code Review Rules` section, when present, gives each rule as the behavior
  to flag plus the safe path, and leaves formatting and lint to CI.

**Custom agent `.toml`**

- Defines `name`, `description` and `developer_instructions`.
- One narrow job, with `sandbox_mode` and tools that match it. A read-only agent
  stays read-only only while the session keeps its sandbox: in the CLI a live
  `/permissions` change or `--yolo` is reapplied to children and beats the file, so
  the instructions describe a write instead of assuming it cannot happen.
- Sets no `model` or `model_reasoning_effort`: a value in an agent file overrides
  the one a spawn asks for, so the session that spawns the agent sizes each run
  from `model-selection.md`. A pinned value is a P1; when one is truly intended,
  check it with `python3 scripts/resolve_model.py --check <file>`.
- `developer_instructions` that point at a skill keep one source of truth; a copy
  of the skill's text inside the TOML is a P1.

## claude, gemini, llama, heygen

Fetch the provider's official prompting guide (Anthropic's prompt engineering
docs, Google's Gemini prompting strategies, Meta's Llama prompting guide, HeyGen's
script and Magic Edit docs) and apply it; record the URL and date in the
iteration log. For `claude`, XML tags are the structuring convention and How to
run it names a Claude model tier with an effort level. For `heygen`, check script
pacing and pronounceability, voice and delivery direction, and whether a Magic
Edit instruction matches a real HyperFrames capability.
