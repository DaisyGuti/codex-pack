# GitLab end-to-end test, 2026-10-08

A full run of the ticket skills against GitLab.com on the Free plan: file a ticket, plan it, have a worker build it, land it by merge request, merge, and groom the board. Written from Codex's own session logs. The project owner is shown as `<owner>`, the local clone as `<clone>`, and home paths as `~`.

## Setup

- **Project:** a throwaway private project `<owner>/codex-pack-e2e` holding `evals/fixtures/small-repo`, with a planted bug (a login with `+` in the email returns a 500). Its CONTRIBUTING.md requires a merge request and one reviewer.
- **Board:** the project's `Development` board with lists for `status::ready`, `status::in-progress`, `status::in-review` and `status::blocked`; GitLab's built-in Open and Closed lists stand in for backlog and done. Labels `priority::0` to `priority::3`, `blocked`, `run:worker`, `run:solo`, `bug`.
- **Registry:** `tracker: gitlab`, host `gitlab.com`, board scope `project`, the project path, the optional `review` lane, and one repo row for the project.
- **Before Codex ran:** every operation in `references/trackers/gitlab.md` was run by hand with `glab` 1.121 against the project, and the adapter was corrected (see "Problems found").
- **Each step:** `codex exec --json --ignore-user-config --disable apps -s danger-full-access -c approval_policy=never -m gpt-6.1-sol -c model_reasoning_effort=medium "<prompt>"` from the clone, on a ChatGPT sign-in (no API key), the team default model, connectors off.

## Results

| Step | Prompt | Time | Result | Credits | Tokens | 5h limit |
| --- | --- | --- | --- | --- | --- | --- |
| Step 1 | `$write-ticket` | 1m41s | ticket #12 filed in Ready | 3.63 | 342,182 | +2% |
| Step 2 | `$plan-ticket` | 1m18s | plan posted, labels kept | 2.75 | 346,400 | +1% |
| Step 3, first attempt | `$work-tickets` | 4m31s | held: tests could not run | 10.92 | 1,309,135 | +6% |
| Step 3, retry after fixing the sample project | `$work-tickets` | 4m29s | merge request !8, card in review | 11.33 | 1,434,657 | +6% |
| Step 4 (by hand) | merge !8 | | #12 closed by the merge | | | |
| Step 5 | `$daily-grooming` | 1m29s | closed tickets moved to done | 4.07 | 428,509 | +2% |

About 33 credits in all, roughly 17% of a ChatGPT Plus five-hour window; the failed first worker attempt accounts for 11 of them.

## Step 1: file the ticket

Prompt: `$write-ticket --repo codex-pack-e2e --ready --assignee me Login returns a 500 when the email address contains a plus sign`

**Outcome.** Filed issue #12 in the Ready lane (`status::ready`), assigned to the signed-in user, with `priority::2`, `bug`, `run:worker`, `model:sonnet` and `project:codex-pack-e2e`. It reproduced the crash with a literal `+` before writing, and found no duplicate.

**What the session ran:**

- `cat ~/codex-pack/skills/write-ticket/references/registry.md ~/codex-pack/skills/write-ticket/assets/ticket-template.md ~/codex-pack/skills/write-ticket/references/ticket-labels.md` -> exit 0
- `pwd; rg --files -g 'AGENTS.md' -g 'CLAUDE.md' -g 'README*' -g '*login*' -g '*auth*' -g '*decision*'` -> exit 0
- `cat ~/codex-pack/skills/write-ticket/references/trackers/gitlab.md ~/codex-pack/skills/write-ticket/references/model-selection.md` -> exit 0
- `git status --short; rg --files; cat README.md api/auth.py tests/test_login.py` -> exit 0
- `cat main.py tests/conftest.py CONTRIBUTING.md pyproject.toml ; python3 -m pytest tests/test_login.py ; python3 ~/codex-pack/skills/write-ticket/scripts/resolve_model.py workhorse` -> exit 0
- `set -o pipefail ; export GITLAB_HOST=gitlab.com ; glab api --hostname gitlab.com user | jq -r .username ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/boards' ; glab api --hostname gitlab.com --paginate...` -> exit 0
- `set -o pipefail ; glab auth status --hostname gitlab.com ; cat db/migrations/0001_create_users_and_orders.sql ; python3 - <<'PY' ; import sqlite3 ; from pathlib import Path ; from api.auth import login, ...` -> exit 0
- `python3 - <<'PY' ; from pathlib import Path ; import tempfile ; text = '''## Context ; ; The Shop API exposes POST /login for this repo's existing users. Login reportedly returns HTTP 500 for email addresses containing a plus s...` -> exit 0
- `set -o pipefail ; export GITLAB_HOST=gitlab.com ; glab label create -R <owner>/codex-pack-e2e --name 'model:sonnet' --color '#ededed' --description 'Workhorse tier: ordinary implementation' ; glab label create -...` -> exit 0
- `set -o pipefail ; export GITLAB_HOST=gitlab.com ; glab api --hostname gitlab.com -X PUT 'projects/<owner>%2Fcodex-pack-e2e/issues/12' -f add_labels='priority::2' -f remove_labels='priority::0,priority::1,priority::3' < /dev...` -> exit 0
- turn usage: input 339521, cached 295040, output 2661

**Its final message:**

> Created [#12: Fix login failure for email addresses containing a plus sign](https://gitlab.com/<owner>/codex-pack-e2e/-/work_items/12).
> 
> - **Ready**, assigned to **@<owner>**, as requested.
> - **P2**: assumed an important bug without evidence of a launch blocker.
> - **run:worker**, **model:sonnet** → `gpt-6.1-sol`: ordinary implementation with regression tests.
> - Labels: **bug**, **project:codex-pack-e2e**.
> 
> Reproduced the exception with a literal `+`; `%2B` succeeds. The ticket includes a TBD to confirm the failing client’s encoding. Existing tests could not run because pytest is unavailable.

## Step 2: plan it

Prompt: `$plan-ticket`

**Outcome.** With no ticket number it picked #12 as the signed-in user's next Ready ticket, posted a 157-word `### Final Plan` comment and kept the model and run labels.

**What the session ran:**

- `pwd; rg --files -g AGENTS.md -g CLAUDE.md -g '*registry*' . ~/codex-pack/skills/plan-ticket ~/.codex/skills/plan-ticket` -> exit 1
- `cat ~/codex-pack/skills/plan-ticket/SKILL.md ~/codex-pack/skills/plan-ticket/references/registry.md ~/codex-pack/skills/plan-ticket/references/plan-one-ticket.md ~/cod...` -> exit 0
- `cat ~/codex-pack/skills/plan-ticket/references/trackers/gitlab.md ~/codex-pack/skills/eng/references/model-selection.md` -> exit 0
- `ls -la; git status --short` -> exit 0
- `set -o pipefail ; export GITLAB_HOST=gitlab.com ; glab auth status --hostname gitlab.com ; glab api --hostname gitlab.com user | jq -r .username` -> exit 0
- `glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/boards'` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com user | jq -r .username ; glab api --hostname gitlab.com --paginate --output ndjson 'projects/<owner>%2Fcodex-pack-e2e/issues?state=opened&per_page=100&labels=stat...` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/issues/12' | jq '{title,body:.description,labels,assignees:[.assignees[].username],state:(if .state==\"opened\" then \"open\" e...` -> exit 0
- `cat README.md ; head -n 70 pyproject.toml ; rg -n 'login|email|unquote' api tests main.py` -> exit 0
- `python3 ~/codex-pack/skills/plan-ticket/scripts/resolve_model.py workhorse` -> exit 0
- `python3 - <<'PY' ; from pathlib import Path ; import tempfile ; plan = '''### Final Plan ; ; **Files to touch:** "'`api/auth.py` and `tests/test_login.py`. Follow the scope in [README.md](https://gitlab.com/<owner>/codex-pa...` -> exit 0
- `python3 - <<'PY' ; from pathlib import Path ; p=Path('<tmpfile>') ; s=p.read_text().replace('through "'`main.app` (confirm the callable'"\\'s name before impleme...` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/issues/12' | jq '{title,labels,state}' ; glab api --hostname gitlab.com --paginate --output ndjson 'projects/<owner>%2Fcode...` -> exit 0
- turn usage: input 344306, cached 315648, output 2094

**Its final message:**

> Planned [codex-pack-e2e#12](https://gitlab.com/<owner>/codex-pack-e2e/-/issues/12#note_3979820414): Fix login failure for email addresses containing a plus sign.
> 
> Posted and verified the 157-word plan. Retained `model:sonnet` (ordinary implementation; currently `gpt-6.1-sol`) and `run:worker` (locally testable code).
> 
> Run `$work-tickets --limit 1` to ship the top of your queue.

## Step 3, first attempt: work it

Prompt: `$work-tickets --limit 1`

**Outcome.** The worker (a `ticket_worker` subagent on gpt-6.1-sol at medium, the model `model:sonnet` resolves to) wrote the fix and regression tests, then could not run them: the sample project never declared its test tool, so `python -m pytest` failed with `No module named pytest`. It stopped correctly: swapped `status::ready` for `status::blocked`, added the `blocked` label, posted a `Blocked: failure` comment quoting the error with an "Unblocks when" line, and committed nothing.

**What the session ran:**

- `cat ~/codex-pack/skills/work-tickets/references/orchestrator.md` -> exit 0
- `cat ~/codex-pack/skills/work-tickets/references/registry.md` -> exit 0
- `pwd; rg --files -g AGENTS.md -g CLAUDE.md -g '*state*' -g '.codex*'` -> exit 1
- `cat ~/codex-pack/skills/work-tickets/references/trackers/gitlab.md` -> exit 0
- `cat ~/.codex/skills/eng/references/model-selection.md; cat ~/.codex/config.toml` -> exit 0
- `ls -la; ls ~/codex-pack/skills/work-tickets/scripts` -> exit 0
- `sed -n '355,510p' ~/codex-pack/skills/work-tickets/references/trackers/gitlab.md` -> exit 0
- `set -o pipefail ; glab auth status --hostname gitlab.com ; glab api --hostname gitlab.com user | jq -r .username` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/boards' ; glab api --hostname gitlab.com --paginate --output ndjson 'projects/<owner>%2Fcodex-pack-e2e/labels?per_page=100'...` -> exit 0
- `git fetch origin --prune ; git status --short ; git symbolic-ref --short refs/remotes/origin/HEAD ; ls ~/.codex/state/ready-worker-<owner>-codex-pack-e2e*` -> exit 1
- `set -o pipefail ; glab api --hostname gitlab.com --paginate --output ndjson 'projects/<owner>%2Fcodex-pack-e2e/issues?state=opened&per_page=100&labels=status::ready' | jq -c --argjson lanes '[\"status::backlog\"...` -> exit 0
- `ls ~/.codex/state ; python3 ~/codex-pack/skills/work-tickets/scripts/resolve_model.py workhorse --effort medium` -> exit 0
- `python3 - <<'PY' ; import json,os,re,fcntl,datetime,pathlib ; root=pathlib.Path(os.environ.get('CODEX_HOME',os.path.expanduser('~/.codex')))/'state' ; root.mkdir(parents=True,exist_ok=True) ; key='<owner>-codex-pack-e2e-116...` -> exit 0
- `git worktree prune ; git fetch origin --prune ; git worktree add ~/.codex/state/ready-worktrees/<owner>-codex-pack-e2e-11671826-<owner>/slot-1/codex-pack-e2e -b slot-1-ticket-12 or...` -> exit 0
- `python3 - <<'PY' ; import json,fcntl,datetime ; p='~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json' ; with open(p+'.lock','a') as lock: ; fcntl.flock(lock,fcntl.LOCK_EX) ; s=json....` -> exit 0
- `python3 - <<'PY' ; import json,fcntl ; p='~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json' ; with open(p+'.lock','a') as l: ; fcntl.flock(l,fcntl.LOCK_EX) ; s=json.load(open(p)) ;...` -> exit 0
- `python3 - <<'PY' ; import json,fcntl ; p='~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json' ; with open(p+'.lock','a') as l: ; fcntl.flock(l,fcntl.LOCK_EX) ; s=json.load(open(p)); ...` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/issues/12' | jq '{state,labels,assignees:[.assignees[].username]}' ; glab api --hostname gitlab.com --paginate --output ndjson ...` -> exit 0
- `osascript -e 'display notification \"Ready worker complete: 0 done, 0 in review, 1 blocked, 0 skipped (board <owner>-codex-pack-e2e-11671826, <owner>)\" with title \"Codex Ready Worker\"' ; python3 - <<'PY' ...` -> exit 0
- turn usage: input 744153, cached 690176, output 4009

**What the worker subagent ran** (gpt-6.1-sol at medium):

- `cat ~/codex-pack/skills/ticket-worker/SKILL.md`
- `cat ~/codex-pack/skills/ticket-worker/references/protocol.md ; cat ~/codex-pack/skills`
- `sed -n '320,620p' ~/codex-pack/skills/ticket-worker/references/protocol.md`
- `sed -n '175,360p' ~/codex-pack/skills/ticket-worker/references/trackers/gitlab.md`
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/issues/12' | jq '{title, body:.description, labels, assignee`
- `cat CONTRIBUTING.md pyproject.toml api/auth.py tests/test_login.py tests/conftest.py main.py db/connection.py web/components/SignupForm.jsx ; git log -1 --format='%H %cI' -- README`
- `rg -n 'login|urlencode|fetch\\(' web tests api ; cat scripts/migrate.py`
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/issues/12' | jq '{state:(if .state==\"opened\" then \"open\" else .state end),closed_at}'`
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/issues/12' | jq '{state:(if .state==\"opened\" then \"open\" else .state end),closed_at}'`
- `set -o pipefail ; glab api --hostname gitlab.com -X GET 'projects/<owner>%2Fcodex-pack-e2e/labels' -f search=blocked | jq -r '.[].name'`

**Its final message:**

> 0 completed · 0 in review · 1 blocked · 0 skipped.
> 
> [Issue #12](https://gitlab.com/<owner>/codex-pack-e2e/-/work_items/12): fix and regression tests written, but `python -m pytest` failed with `No module named pytest`. Migrations passed. Changes remain in the preserved worktree; no commit or review was created.
> 
> Retry needs Python ≥3.12 with pytest and the ticket’s blocked state cleared.

**Between the attempts (by hand):** the sample project gained `[dependency-groups] dev = ["pytest>=8"]`, a `.gitignore`, and "run the tests with `uv run pytest`" in CONTRIBUTING.md and the README; #12 went back to `status::ready` with a comment; the run's `blocked[]` entry was removed from the state file so the ticket could be dispatched again.

## Step 3, retry after fixing the sample project

Prompt: `$work-tickets --limit 1`

**Outcome.** The worker ran all 12 tests and the fresh-database migrations, read CONTRIBUTING.md ("open a pull request, one reviewer"), and landed by review: merge request !8 with no label and `Closes #12`, a comment on #12 with the link, and the card moved from `status::ready` to `status::in-review`. The report read "Completed: 0 · In review: 1 · Blocked: 0".

**What the session ran:**

- `cat ~/codex-pack/skills/work-tickets/references/orchestrator.md` -> exit 0
- `cat ~/codex-pack/skills/work-tickets/references/registry.md` -> exit 0
- `pwd; rg --files -g AGENTS.md -g CLAUDE.md -g '*state*' -g '*ticket*'` -> exit 1
- `cat ~/.codex/skills/eng/references/model-selection.md` -> exit 0
- `cat ~/codex-pack/skills/work-tickets/references/trackers/gitlab.md` -> exit 0
- `ls -la; rg --files ~/codex-pack/skills/work-tickets ~/.codex/state` -> exit 0
- `sed -n '345,440p' ~/codex-pack/skills/work-tickets/references/trackers/gitlab.md` -> exit 0
- `set -o pipefail ; glab auth status --hostname gitlab.com ; glab api --hostname gitlab.com user | jq -r .username ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/boards' < /dev/nul...` -> exit 0
- `cat ~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json ; rg 'max_concurrent|max_threads' ~/.codex/config.toml ; git fetch origin --prune < /dev...` -> exit 0
- `sed -n '440,510p' ~/codex-pack/skills/work-tickets/references/trackers/gitlab.md ; cat ~/.codex/skills/ticket-worker/SKILL.md` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com --paginate --output ndjson 'projects/<owner>%2Fcodex-pack-e2e/issues?state=opened&per_page=100&labels=status::ready' | jq -c --argjson lanes '[\"status::backlog\"...` -> exit 0
- `git -C ~/.codex/state/ready-worktrees/<owner>-codex-pack-e2e-11671826-<owner>/slot-1/codex-pack-e2e status --short ; git log -3 --oneline slot-1-ticket-12 ; git symbolic-ref --shor...` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/issues/12' | jq '{title,body:.description,labels,assignees:[.assignees[].username],state}' ; glab api --hostname gitlab.com --p...` -> exit 0
- `python3 - <<'PY' ; import json,fcntl,datetime,pathlib ; p=pathlib.Path('~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json') ; with open(str(p)+'.lock','a') as lock: ; fcntl.flock(lo...` -> exit 0
- `python3 - <<'PY' ; import json,fcntl,datetime,pathlib ; p=pathlib.Path('~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json') ; with open(str(p)+'.lock','a') as lock: ; fcntl.flock(lo...` -> exit 0
- `python3 - <<'PY' ; import json,fcntl ; p='~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json' ; with open(p+'.lock','a') as lock: ; fcntl.flock(lock,fcntl.LOCK_EX) ; s=json.load(open...` -> exit 0
- `python3 - <<'PY' ; import json,fcntl ; p='~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json' ; with open(p+'.lock','a') as lock: ; fcntl.flock(lock,fcntl.LOCK_EX) ; s=json.load(open...` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com 'projects/<owner>%2Fcodex-pack-e2e/merge_requests/8' | jq '{state,web_url,source_branch,target_branch,sha}' ; glab api --hostname gitlab.com 'projects/<owner>...` -> exit 0
- turn usage: input 846294, cached 786688, output 3830

**What the worker subagent ran** (gpt-6.1-sol at medium):

- `cat ~/.codex/skills/ticket-worker/SKILL.md`
- `cat ~/.codex/skills/ticket-worker/references/protocol.md ; cat ~/.codex/state/ready-wo`
- `cat ~/.codex/skills/ticket-worker/references/trackers/gitlab.md ; cat ~/.codex/skills/`
- `test -w ~/.codex/state/ready-worktrees/<owner>-codex-pack-e2e-11671826-<owner>/slot-2/codex-pack-e2e ; glab auth status --hostname gitlab.com ; set -o pipefa`
- `sed -n '305,332p' ~/.codex/skills/ticket-worker/references/protocol.md ; cat api/auth.py tests/test_login.py tests/conftest.py main.py scripts/migrate.py db/connecti`
- `python3 - <<'PY' ; import fcntl,json ; from pathlib import Path ; plan='''### Final Plan ; ; _Re-validated 2026-10-08: CONTRIBUTING.md now requires uv run pytest with the declared dev dependency`
- `python3 - <<'PY' ; import fcntl,json,subprocess ; from pathlib import Path ; p='~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json' ; with open(p+'.lo`
- `git status --porcelain ; git diff ; set -o pipefail ; glab api --hostname gitlab.com projects/<owner>%2Fcodex-pack-e2e/issues/12 | jq '{state,closed_at}'\`
- `python3 - <<'PY' ; import fcntl,json,subprocess ; from pathlib import Path ; p='~/.codex/state/ready-worker-<owner>-codex-pack-e2e-11671826-<owner>.json' ; with open(p+'.lo`
- `glab mr create -R <owner>/codex-pack-e2e --source-branch slot-2-ticket-12 --target-branch main --title 'Fix login failure for email addresses containing a plus sign' --description-file /t`
- `python3 - <<'PY' ; from pathlib import Path ; Path('/tmp/ticket-12-slot-2-result.md').write_text('''Review: https://gitlab.com/<owner>/codex-pack-e2e/-/merge_requests/8 ; ; Fixed missing-use`

**Its final message:**

> Completed: 0 · In review: 1 · Blocked: 0 · Skipped: 0.
> 
> #12’s login fix is ready in [MR !8](https://gitlab.com/<owner>/codex-pack-e2e/-/merge_requests/8). All 12 tests and fresh-database migrations passed. One reviewer is needed before merge.
> 
> The earlier worktree was preserved; this run’s worktree was removed. Original client encoding remains unverified.

## Step 4: merge (by hand)

`glab mr merge 8 -R <owner>/codex-pack-e2e --yes --remove-source-branch`. Issue #12 closed within a second (`state: closed`), still carrying `status::in-review`, which is what step 5 then cleaned up.

## Step 5: groom the board

Prompt: `$daily-grooming`

**Outcome.** Found the closed tickets still carrying a lane label (a merge leaves the lane label on) and moved all of them to done (`status::done`), including #12. Nothing else needed attention.

**What the session ran:**

- `cat ~/codex-pack/skills/daily-grooming/SKILL.md` -> exit 0
- `pwd; rg --files -g AGENTS.md -g CLAUDE.md -g '*registry*' -g '*brief*'` -> exit 1
- `cat ~/codex-pack/skills/daily-grooming/references/grooming.md ~/codex-pack/skills/daily-grooming/references/registry.md` -> exit 0
- `cat ~/codex-pack/skills/daily-grooming/references/trackers/gitlab.md ~/codex-pack/skills/daily-grooming/references/ticket-labels.md ~/codex-pack/skills/daily-grooming/references/plan...` -> exit 0
- `rg --files --hidden -g '"'! .git'"'` -> exit 0
- `set -o pipefail ; GITLAB_HOST=gitlab.com glab auth status --hostname gitlab.com ; glab api --hostname gitlab.com user | jq -r .username` -> exit 0
- `sed -n '340,415p' ~/codex-pack/skills/daily-grooming/references/trackers/gitlab.md ; cat README.md pyproject.toml` -> exit 0
- `sed -n '425,480p' ~/codex-pack/skills/daily-grooming/references/trackers/gitlab.md` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com --paginate --output ndjson \"projects/<owner>%2Fcodex-pack-e2e/issues?state=opened&per_page=100\" | jq -c '{number:.iid,title,body:.description,labels,assignees:[...` -> exit 0
- `glab api --hostname gitlab.com "projects/<owner>%2Fcodex-pack-e2e/boards"` -> exit 0
- `glab api --hostname gitlab.com --paginate --output ndjson "projects/<owner>%2Fcodex-pack-e2e/labels?per_page=100"` -> exit 0
- `sed -n '480,550p' ~/codex-pack/skills/daily-grooming/references/trackers/gitlab.md` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com --paginate --output ndjson \"projects/<owner>%2Fcodex-pack-e2e/issues?state=opened&per_page=100\" | jq -c '{number:.iid,title,body:.description,labels,url:.web_ur...` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/4\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/5\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/7\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com --paginate --output ndjson \"projects/<owner>%2Fcodex-pack-e2e/issues?state=opened&order_by=created_at&sort=desc&per_page=100\" | jq -c '{number:.iid,title,body:....` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/6\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/2\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/1\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/3\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/11\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/10\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/9\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/8\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e/issues/12\" | jq '{number:.iid,title,state:(if .state==\"opened\" then \"open\" else .state end),closed_at,labels}` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com \"projects/<owner>%2Fcodex-pack-e2e\" | jq .id ; glab api --hostname gitlab.com --paginate --output ndjson \"projects/<owner>%2Fcodex-pack-e2e/merge_requests?...` -> exit 0
- `set -o pipefail ; for ticket_number in 2 3 4 5 6 7 8 9 10 11 12; do ; glab api --hostname gitlab.com -X PUT "projects/<owner>%2Fcodex-pack-e2e/issues/$ticket_number" -f add_labels="status::done" -f remove_labels="status::ba...` -> exit 0
- `set -o pipefail ; glab api --hostname gitlab.com -X GET \"projects/<owner>%2Fcodex-pack-e2e/issues\" -f state=all -f search=\"\" -f per_page=20 | jq '{total:length,closed_done:([.[]|select(.state==\"closed\" and...` -> exit 0
- turn usage: input 426398, cached 374272, output 2111

**Its final message:**

> Moved 11 closed issues (#2–#12) to Done on the Development board. Verified all 12 issues now carry `status::done`.
> 
> - **Moved to Done (11):** #2–#12; #1 was already Done.
> - **Duplicates to Review (0)**
> - **Ready (0)**
> - **Backlog (0)**
> - **In progress (0)**
> - **Blocked (0)**
> - **Needs Attention (0)**
> - **Counts:** 0 plans written, 11 Done labels added, 0 open tickets held.
> 
> All eight steps were accounted for; auditing, triage and planning had no open tickets to process. The adapter omits closed issues from its board listing, so its all-state search was used to find and confirm them.

## Problems found, and what changed

- **GitLab adapter, found by running every command by hand** (all fixed in `references/trackers/gitlab.md`, commit `1805380`): `glab api` has no `--jq` and needs `-X PUT` for edits; label colors need a leading `#`; the merge request's closing references carry no `references`, so the same-project check uses `project_id`; the issue search never reaches comments, so model-fit notes use the notes search; a label name that does not exist is created silently; a line starting with `/` runs as a quick action; on the Free plan `::` labels do not replace each other, so every lane or priority move removes the others explicitly (confirmed in steps 3 and 5).
- **Grooming and closed issues:** the adapter's list of board items covered open issues only, while on GitHub a closed issue stays on the board. Step 5's session worked around it with a search; the adapter now documents the closed-issue form of the call and `$daily-grooming` step 1 uses it.
- **The sample project** never declared its test tool, which held the first worker attempt (correctly). It now declares pytest as a dev dependency and says to run `uv run pytest`, in `evals/fixtures/small-repo` too.
- **Not checkable on a personal Free account,** and still marked `UNVERIFIED:` in the adapter: group-wide boards and subgroups, a self-managed host, paid-plan scoped labels.

The GitHub runs of the same flow are summarized in [docs/sources.md](../sources.md), "Trigger and end-to-end tests".
