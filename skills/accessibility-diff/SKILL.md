---
name: accessibility-diff
description: "Use to see what a change did to accessibility: 'did my change break a11y', 'what issues did this PR add', or a CI regression gate. Compares a live page's WCAG violations before and after (uncommitted changes or --branch). Full check of one page: $accessibility-scan."
license: MIT
---

# Accessibility diff

Report only what changed. This skill reports and leaves the code as it is.

Usage: `$accessibility-diff [--branch [<name>]] [target|url]`

Shared grounding and honesty conventions: [references/methodology.md](references/methodology.md).

Parse the arguments: if `--branch <name>` is present, remove it and use branch mode (no value means the default branch, below). The rest is the target: a URL, a config target name, or nothing for the default target from `accesslint.config.json`. If none is given and there's no config, ask for a URL.

Default branch:

```bash
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD --short 2>/dev/null | sed 's|.*/||'); DEFAULT_BRANCH=${DEFAULT_BRANCH:-main}
```

## 1. Audit

```bash
PORT=$(npx -y @accesslint/chrome@latest ensure | node -e 'process.stdin.on("data",d=>process.stdout.write(""+JSON.parse(d).port))')
```

**Whose changes are in the tree.** Stash and branch mode both move every uncommitted change in the working tree out of the way. Use them only when every uncommitted change belongs to this session or to the person who asked for the diff. When another session or another person may also have uncommitted work in this tree, never stash or check out over it; use worktree mode instead.

Worktree mode (safe in a shared tree). Build the baseline in a separate checkout and scan it on its own port:

```bash
BASE_DIR=$(mktemp -d) && git worktree add --detach "$BASE_DIR" "${BASE_REF:-HEAD}"
# install and start the project's dev server inside $BASE_DIR on a free port, as its README says
npx -y @accesslint/cli@latest scan <baseline url> --port "$PORT" --snapshot accesslint-diff --snapshot-dir "$BASE_DIR" --update-snapshot
npx -y @accesslint/cli@latest scan <target> --port "$PORT" --snapshot accesslint-diff --snapshot-dir "$BASE_DIR" --format json
# stop that dev server, then: git worktree remove --force "$BASE_DIR"
```

`BASE_REF` is `HEAD` for uncommitted changes or the branch name for `--branch`. If the project cannot run a second dev server, say so and stop rather than stashing.

Stash mode (default when the tree is yours alone). Tell the user first: _"Running in diff mode — stashing your changes to capture a baseline, then restoring. Your working tree will be fully restored."_ If `git stash push` fails, warn and exit.

```bash
git stash push -u -m "accesslint-diff-baseline"
npx -y @accesslint/cli@latest scan <target> --port "$PORT" --snapshot accesslint-diff --snapshot-dir /tmp --update-snapshot
git stash pop && sleep 2
npx -y @accesslint/cli@latest scan <target> --port "$PORT" --snapshot accesslint-diff --snapshot-dir /tmp --format json
```

Branch mode (`--branch <name>`). Tell the user first: _"Diffing against `<name>` — checking out that branch to capture a baseline, then restoring. Your working tree will be fully restored."_ Branch switching triggers a rebuild but not a browser reload, so the CLI opens a fresh tab each run to read the current build. Use `--wait-for "<selector>"` to hold the audit until the rebuild is ready; without it, warn that a slow build may give a stale baseline.

```bash
git diff --quiet && git diff --cached --quiet || git stash push -u -m "accesslint-diff-branch"
git checkout <branch>
npx -y @accesslint/cli@latest scan <target> --port "$PORT" --snapshot accesslint-diff --snapshot-dir /tmp --update-snapshot [--wait-for "<selector>"]
git checkout - && git stash pop 2>/dev/null
npx -y @accesslint/cli@latest scan <target> --port "$PORT" --snapshot accesslint-diff --snapshot-dir /tmp --format json [--wait-for "<selector>"]
```

Pass `--selector` and `--include-aaa` to both runs.

Finish the run in one turn: baseline, current scan, report, and the working tree restored. If a step fails partway, restore the tree first (`git stash pop`, `git checkout -`, or removing the worktree), then report what failed. Retry a failed scan once before giving up.

## 2. Report

```
Accessibility diff — http://localhost:3000/ vs main (94 rules, live DOM)
2 new · 1 fixed · 4 pre-existing hidden

New — Critical
- color-contrast — 2.1:1 (needs 4.5:1), #bbb on #fff
    where: main > p.subtitle   fix: darken to #767676
Fixed
- img-alt — <img src="old.jpg"> (no longer present)
```

For each new violation: where (selector verbatim, plus `file:line (symbol)` if `source` is present; don't fabricate), evidence, and fix (mechanical change or `NEEDS HUMAN`).

Open the report with the verdict in one line: how many violations the change added, and whether the change is clean. Leave the files unedited; `$accessibility-fix` repairs the new violations, and a second `$accessibility-diff` confirms the repair.

## 3. Tear down

```bash
npx -y @accesslint/chrome@latest stop --all  # skip if ensure reported "managed":false
```

## Notes

- `ensure` determines the port; don't hardcode 9222.
- CLI exit 2 means a bad URL or target, or the page never loaded; check the dev server.
- A target name resolves the same in both runs only if `accesslint.config.json` is unchanged across the stash or checkout. If your changes touch the config, pass an explicit URL.
- Stash mode: `sleep 2` covers most HMR cases; if the baseline looks identical to current, add `--wait-for "<selector>"`.
- Branch mode: no HMR; the CLI opens a fresh tab each run, and `--wait-for` is the rebuild gate.
- Large DOM changes between runs cause selector drift; re-run `$accessibility-scan` for the full picture.
- Codex's default `workspace-write` sandbox keeps `.git` read-only, so the stash, checkout or worktree may need approval. When it is refused, say so and stop; without a baseline there is no diff. After any run, confirm the tree is restored (`git stash list` shows nothing left from this run).

Adapted from AccessLint/skills (MIT); the license text is in [LICENSE.txt](LICENSE.txt).
