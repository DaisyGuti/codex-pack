# Third-party notices

Most of this pack is original. The skills below include or adapt work from other
projects, and the pack is shared, so each one carries its upstream's license notice.
Every copied or adapted file was modified for Codex; each notice file says how.

| Skill | Upstream | License | Notice file |
| --- | --- | --- | --- |
| [`accessibility-scan`](skills/accessibility-scan/SKILL.md) | [AccessLint/skills](https://github.com/AccessLint/skills) | MIT | [`skills/accessibility-scan/LICENSE.txt`](skills/accessibility-scan/LICENSE.txt) |
| [`accessibility-inspect`](skills/accessibility-inspect/SKILL.md) | [AccessLint/skills](https://github.com/AccessLint/skills) | MIT | [`skills/accessibility-inspect/LICENSE.txt`](skills/accessibility-inspect/LICENSE.txt) |
| [`accessibility-audit`](skills/accessibility-audit/SKILL.md) | [AccessLint/skills](https://github.com/AccessLint/skills) | MIT | [`skills/accessibility-audit/LICENSE.txt`](skills/accessibility-audit/LICENSE.txt) |
| [`accessibility-fix`](skills/accessibility-fix/SKILL.md) | [AccessLint/skills](https://github.com/AccessLint/skills) | MIT | [`skills/accessibility-fix/LICENSE.txt`](skills/accessibility-fix/LICENSE.txt) |
| [`accessibility-diff`](skills/accessibility-diff/SKILL.md) | [AccessLint/skills](https://github.com/AccessLint/skills) | MIT | [`skills/accessibility-diff/LICENSE.txt`](skills/accessibility-diff/LICENSE.txt) |
| [`web-design-guidelines`](skills/web-design-guidelines/SKILL.md) | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | MIT | [`skills/web-design-guidelines/LICENSE.txt`](skills/web-design-guidelines/LICENSE.txt) |
| [`ux-review`](skills/ux-review/SKILL.md) (partly) | [phazurlabs/sumi](https://github.com/phazurlabs/sumi) | Apache-2.0 | [`skills/ux-review/LICENSE-sumi.txt`](skills/ux-review/LICENSE-sumi.txt) |
| [`eng`](skills/eng/SKILL.md) (the ExecPlan reference and the `reviewer` agent) | [openai/openai-cookbook](https://github.com/openai/openai-cookbook) | MIT | [OpenAI Cookbook notice](#openai-cookbook-mit) below |
| [`prompt-optimizer`](skills/prompt-optimizer/SKILL.md) (partly) | [openai/openai-cookbook](https://github.com/openai/openai-cookbook) | MIT | [OpenAI Cookbook notice](#openai-cookbook-mit) below |

## Notes

- **AccessLint/skills.** The five accessibility skills and their shared methodology
  ([`references/accessibility-methodology.md`](references/accessibility-methodology.md),
  linked into each skill) come from `plugins/accesslint/skills`. The repository has no
  LICENSE file; its README states "MIT" under "License" and its plugin manifest names
  AccessLint as author with license "MIT". The copyright line in each `LICENSE.txt`
  follows those statements.
- **vercel-labs/agent-skills.** `web-design-guidelines` comes from
  `skills/web-design-guidelines`. The repository has no LICENSE file; its README states
  "MIT" under "License". The skill bundles no rules: it fetches the current guidelines
  at review time from
  [vercel-labs/web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines)
  (MIT).
- **phazurlabs/sumi.** In `ux-review`, `references/critique-protocol.md` and three
  sections of `references/accessibility.md` (APCA contrast, cognitive and neurodiversity
  accommodations, testing methodology) are adapted from sumi's `a11y` and `roast`
  commands and two of its skills. The files were modified. The rest of `ux-review`,
  including `references/craft.md`, was written for this pack.
- **WCAG 2.2 and the W3C ARIA documents.** `ux-review/references/accessibility.md`
  cites success criteria and short rule statements from
  [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and
  [Using ARIA](https://www.w3.org/TR/using-aria/), with attribution to the W3C, and
  otherwise paraphrases them.
- **openai/openai-cookbook.** Four pieces were adapted and modified for Codex; none is
  a copy of a whole page.
  [`agents/reviewer.toml`](agents/reviewer.toml) adapts the review prompt and the
  findings shape from `examples/codex/build_code_review_with_codex_sdk.md`.
  [`skills/eng/references/execplan.md`](skills/eng/references/execplan.md) adapts the
  PLANS.md template from `articles/codex_exec_plans.md`.
  [`skills/prompt-optimizer/references/diagnose-and-patch.md`](skills/prompt-optimizer/references/diagnose-and-patch.md)
  adapts the two metaprompt templates from `examples/gpt-5/gpt-5-1_prompting_guide.ipynb`.
  Section 8 of
  [`skills/prompt-optimizer/references/openai-prompting-guidance.md`](skills/prompt-optimizer/references/openai-prompting-guidance.md)
  adapts the symptom-to-remedy remedies from `examples/gpt-5/gpt-5_troubleshooting_guide.ipynb`
  and `examples/gpt-5/gpt-5-2_prompting_guide.ipynb`. Read at commit `0eac144` (2026-10-01).

## OpenAI Cookbook (MIT)

Applies to the four adaptations listed in the notes above.

```text
MIT License

Copyright (c) 2025 OpenAI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
