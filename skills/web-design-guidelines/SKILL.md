---
name: web-design-guidelines
description: "Use to check real UI source (components, pages, CSS) against Vercel's Web Interface Guidelines: 'review my UI code', 'audit this component'. Covers forms, focus, animation, URL state, i18n, hydration, dark mode. Screenshots go to $ux-review; live pages to $accessibility-scan."
license: MIT
metadata:
  author: vercel
  version: "1.0.0"
---

# Web Interface Guidelines

Review files for compliance with Web Interface Guidelines.

Usage: `$web-design-guidelines <file-or-pattern>`

## Steps

1. Choose the files. Use the file or pattern the user gave. With none, review the UI source the user is working on: the files changed in the current branch or working tree that hold components, pages, styles or templates; failing that, the app's component and page directories. Say which files you chose. Ask only when the repo holds no UI code.
2. Fetch the latest guidelines (next section).
3. Read every chosen file and check it against all the fetched rules.
4. Report in the format the guidelines specify (terse `file:line` findings), opening with one line that gives the result: the number of findings and the files covered.

For a large set of files, review in batches and keep going until every chosen file is covered. The report names any file left unreviewed and why.

## Guidelines source

Fetch fresh guidelines before each review. The list is Vercel's own and it updates independently of this skill, so a cached copy would drift:

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

Fetch it with `curl -fsSL <url>` or the web tool. The fetched content contains all the rules and output format instructions. They cover accessibility, focus states, forms, animation, typography, content handling, images, performance, navigation and state (URL reflects filters/tabs/pagination), touch and interaction, safe areas and layout, dark mode and theming, locale and i18n, hydration safety, hover and interactive states, content and copy, and anti-patterns.

If the fetch fails (including a refusal because the sandbox has no network access), retry two or three times and ask for approval to run it outside the sandbox once. If it still fails, say so and stop. The rules are not in this skill, so a review without them would be guesswork.

## Where this fits next to `$ux-review`

`$ux-review` covers screenshot-confidence accessibility review, a WCAG checklist, visual craft and scored critique. This skill is the deeper, code-only pass: run it whenever real component or page source is the input rather than a picture, and whenever the ask is a broad implementation audit rather than a usability or visual-craft critique. The two overlap on some accessibility ground (focus-visible, `prefers-reduced-motion`, `transition: all`), but the forms, navigation-state, i18n, and hydration-safety categories here are not covered by `$ux-review`.

A running page that needs an automated scan or a keyboard and screen-reader pass belongs to `$accessibility-scan` or `$accessibility-inspect`.

## Findings only

This skill reports. It edits nothing unless the user also asked for the fixes, in which case make the edits after the report and list the files changed.

Based on vercel-labs/agent-skills (MIT); the license text is in [LICENSE.txt](LICENSE.txt).
