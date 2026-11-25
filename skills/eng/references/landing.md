# Landing a change: per-host commands and the review body

Every change lands as a pull request (GitHub) or merge request (GitLab) into the default
branch. You push your own branch and open the review by default: opening it is the
expected end of an engineering task and needs no separate go. A person merges it. Nothing
is committed or pushed to the default branch, even where the repo's instruction files
allow it, and you never merge or enable auto-merge. Sources: GitHub CLI manual,
`gh pr create` (<https://cli.github.com/manual/gh_pr_create>), and GitLab CLI
documentation, `glab mr create` (<https://docs.gitlab.com/cli/mr/create/>). Re-read the
page when a flag below is rejected.

## Contents

- Find the host and the default branch
- Branch and commit
- Open the review on GitHub
- Open the review on GitLab
- When the review cannot be opened
- Writing the review

## Find the host and the default branch

```sh
git remote get-url origin                           # github.com or a GitLab host decides the CLI
git symbolic-ref --short refs/remotes/origin/HEAD   # prints origin/<default-branch>
```

When `origin/HEAD` is unset, `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`
on GitHub and `glab repo view` on GitLab name the default branch. A self-hosted GitLab host
does not contain the word "gitlab" in every case; when the host is unclear, check which CLI
is signed in (`gh auth status`, `glab auth status`) and say which you chose.

## Branch and commit

```sh
git fetch origin
git worktree add ../<repo>-<branch> -b <type>/<short-name> origin/<default-branch>
```

- Name the branch for the change (`fix/export-duplicate-rows`), from the latest
  `origin/<default-branch>`. Make it in a separate worktree whenever `git status --short`
  lists paths you did not touch, and work there from the start. Never switch the shared
  tree's branch. If you already edited in the shared tree, apply your own paths' diff to the
  worktree and say so in the report.
- Stage by path (`git add <path> ...`), then run `git status --short` and confirm every
  staged path is yours. Never `git add -A`, `git add .` or `git commit -a`.
- Never stash, `git checkout -- <path>`, `git reset --hard` or `git clean` in a tree
  someone else may be using. Never amend, rebase a shared tree, or force-push unless the
  user asked.
- Follow the repo's commit style; Conventional Commits (`fix(api): ...`) when the repo
  states none. Never bypass hooks (`--no-verify`) or signing. If the repo signs commits
  and signing fails, stop and report the error.
- On a long run, commit as each piece works; documentation lands in the same commit as the
  code it describes.
- The default `workspace-write` sandbox keeps `.git` read-only, so a commit may need
  approval or fail. When it is refused, say so in the report and leave the change ready to
  commit; never loop on it.

## Open the review on GitHub

After the gates passed on exactly what you push. Skip this only when the brief says to
leave the work local.

```sh
git push -u origin <branch>
gh pr create --base <default-branch> --head <branch> --title "<title>" --body-file <branch>-body.md
```

Use `--template <file>` or fill the repo's pull request template when it has one. Add
`--draft` when the user wants a draft. Never merge it yourself.

## Open the review on GitLab

```sh
git push -u origin <branch>
glab mr create --source-branch <branch> --target-branch <default-branch> \
  --title "<title>" --description-file <branch>-body.md --yes
```

Fill the repo's merge request template when it has one (`.gitlab/merge_request_templates/`).
Add `--draft` for a draft. Never merge it yourself.

## When the review cannot be opened

No remote, an unknown host, a CLI that is missing or signed out, or a brief that says to
leave the work local: leave the commit on the branch, and put in the report the branch
name, the exact push and create commands above with the values filled in, and the drafted
title and body. Retry a transient network failure twice, then stop and report.

## Writing the review

Write for a reviewer new to the change. User instructions win; keep the repo's required
template sections and title conventions, adapting the outline below.

- Use a short, concrete title and an opening paragraph explaining the problem and
  resulting behavior. Use plain English and active verbs; explain necessary terms. Cut
  stock phrases, process narration, repetition, abandoned approaches and contrastive
  phrasing.
- Follow this order, including only sections that help review the change: **What this PR
  implements** (a few bullets about behavior), **Architecture** (a diagram only when it
  clarifies a boundary or flow), **Decisions and why** (material choices and their
  consequences), **Review guide and limits** (where to start and meaningful gaps), **UI
  evidence** (for UI changes), then **Validation and rollout** (checks run, results, what
  was left to CI, the covering test, deployment steps). Link relevant issues or decisions.
- Name anything that touches authentication, authorization, payments, personal data or
  secrets, and list each test deleted or merged, by file, with its one-line reason.
- Scale detail to the change. A small fix usually needs a paragraph and a few validation
  lines. Aim for 150-300 words for an ordinary PR; add detail, tables, diagrams or stack
  links only when they help review.
- For a UI change to one screen or state, embed a screenshot of the final UI in **UI
  evidence**. For a multi-step UI change, include a Playwright video of the complete
  affected flow. Let screens settle and pause roughly 1-2 seconds at meaningful states so
  labels and results can be read. Put pauses in the recording script, separate from
  automated checks. Use safe demo data, inspect the image or watch the whole video, and
  include the viewport and a short caption.
- Attach or embed the media so it can be viewed from the PR; a local file path alone is
  insufficient. Follow repo sharing conventions and approval rules. If capture or
  attachment fails, state why, where any artifact is available and that evidence is
  missing. Verify the PR media link before claiming inclusion.
- State failed, skipped or unconfirmed checks plainly, including a review that could not
  run. Keep test counts and CI claims tied to this branch and tested commit. Check the
  body against the final diff and remove stale claims before opening the review.
- After every create or edit, read the body back from the host and check its `Closes` and
  `Refs` lines; a ticket the change finishes only in part gets `Refs`, never `Closes`.
