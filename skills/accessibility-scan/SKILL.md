---
name: accessibility-scan
description: "Use for an automated accessibility check of one live page: 'is this page accessible', 'check a11y on this URL', 'find contrast issues'. Runs the AccessLint engine and lists WCAG 2.2 violations with selector and file:line. Keyboard and screen-reader checks: $accessibility-inspect. Whole site: $accessibility-audit."
license: MIT
---

# Accessibility scan

Audit a live page and report each violation and where it is. This skill locates problems and leaves the code as it is.

Usage: `$accessibility-scan [target|url]`

Shared grounding and honesty conventions: [references/methodology.md](references/methodology.md).

The target is a URL, a config target name (`dev`, `storybook`, ...), or nothing, which audits the default target from `accesslint.config.json`. If none is given and no config exists, ask for a URL or suggest `npx @accesslint/cli init`.

Prerequisites: Node with `npx`, Chrome installed, and network access for `npx` to fetch the AccessLint packages (a sandbox that blocks the network needs approval for these commands). The commands below use `@latest` so the scan always runs the current rule set; pin a version, for example `@accesslint/cli@<version>`, when a repeatable result matters more than the newest rules.

## 1. Audit

```bash
PORT=$(npx -y @accesslint/chrome@latest ensure | node -e 'process.stdin.on("data",d=>process.stdout.write(""+JSON.parse(d).port))')
npx -y @accesslint/cli@latest scan <target> --port "$PORT" --format json
```

`<target>` is the URL or config target name. Omit it (leave the argument out entirely, no `""`) to audit the config's default target. Add flags as needed: `--selector`, `--wait-for "<selector>"`, `--include-aaa`, `--disable <rules>`, or pin them per-target in `accesslint.config.json`.

## 2. Report

Open with one line that gives the result: the page, and the violation count by impact. Then one entry per violation:

- where: selector verbatim, plus `file:line (symbol)` if `source` is present. Don't fabricate. If no violation has `source`, note "source mapping unavailable; located by selector only".
- evidence: contrast ratio, missing attribute, empty name.
- fix: mechanical change, or `NEEDS HUMAN`.

A scan with zero violations means the engine found nothing it can detect. Say that, and add that keyboard operation, focus order and screen-reader behavior are unchecked (`$accessibility-inspect` covers them). Never write "this page is accessible" from a clean scan.

Leave the files unedited. Offer `$accessibility-fix` for the repairs, and `$accessibility-diff` to confirm afterward that a change added nothing.

## 3. Tear down

Run this even when the scan failed, so no browser is left running.

```bash
npx -y @accesslint/chrome@latest stop --all  # skip if ensure reported "managed":false
```

## Notes

- `ensure` determines the port; don't hardcode 9222.
- CLI exit 2 means a bad URL or target, or the page never loaded; check the dev server, fix the call if it was a typo, and rerun once. An unknown target name makes the CLI list the available targets from `accesslint.config.json`.

Adapted from AccessLint/skills (MIT); the license text is in [LICENSE.txt](LICENSE.txt).
