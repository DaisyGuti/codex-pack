# codex-pack

A self-contained set of Codex skills, custom agents and global instructions for
working with OpenAI's Codex (the ChatGPT desktop app and the Codex CLI). Each piece
picks its own OpenAI model and reasoning effort, sending small or mechanical work
to cheaper models, and every run's usage can be measured afterwards.

It is built for a team: each person installs it on their own machine, the ticket
skills work only the tickets assigned to whoever is signed in to the tracker CLI, and
held work is marked the same way for everyone (see [Ticket trackers](#ticket-trackers)).

| Path | What it is |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Global Codex instructions for the team: working rules, ticket boards, models and delegation |
| [`skills/eng/`](skills/eng/SKILL.md) | `$eng`: the engineering pass for any repo, held to [the engineering standards](skills/eng/references/engineering-standards.md), splitting work onto cheaper subagents; lands every change by pull request or merge request, never on the default branch |
| [`skills/prompt-optimizer/`](skills/prompt-optimizer/SKILL.md) | `$prompt-optimizer`: optimizes a prompt or instruction file for the model that runs it and says which model and effort to use |
| [`skills/write-ticket/`](skills/write-ticket/SKILL.md) | `$write-ticket`: checks the premise against the real repo, then files an issue in the shape and with the labels the ticket workers need |
| [`skills/plan-ticket/`](skills/plan-ticket/SKILL.md) | `$plan-ticket`: writes a ticket's short build plan (files, pattern to copy, how to tell it's done) and sets its model and run labels, so the plan can be read before a worker builds it |
| [`skills/daily-grooming/`](skills/daily-grooming/SKILL.md) | `$daily-grooming`: tidies the whole board: settles closed items, syncs priorities, flags duplicates and gaps, promotes to Ready and plans what is unplanned |
| [`skills/work-tickets/`](skills/work-tickets/SKILL.md) | `$work-tickets`: works your Ready tickets in parallel waves, each on the model its label names |
| [`skills/ticket-worker/`](skills/ticket-worker/SKILL.md) | `$ticket-worker`: works one issue from plan to an open pull or merge request; merging closes the issue |
| [`skills/ux-review/`](skills/ux-review/SKILL.md) | `$ux-review`: reviews a screen, flow, mockup or screenshot for usability, accessibility and visual craft |
| [`skills/web-design-guidelines/`](skills/web-design-guidelines/SKILL.md) | `$web-design-guidelines`: audits UI code against Vercel's Web Interface Guidelines, fetched fresh each run |
| [`skills/accessibility-scan/`](skills/accessibility-scan/SKILL.md) | `$accessibility-scan`: automated WCAG scan of one live page |
| [`skills/accessibility-inspect/`](skills/accessibility-inspect/SKILL.md) | `$accessibility-inspect`: hands-on keyboard and screen-reader pass of one live page in Chrome |
| [`skills/accessibility-audit/`](skills/accessibility-audit/SKILL.md) | `$accessibility-audit`: whole-site WCAG audit following the W3C's evaluation method |
| [`skills/accessibility-fix/`](skills/accessibility-fix/SKILL.md) | `$accessibility-fix`: fixes the violations a scan finds and re-scans to confirm |
| [`skills/accessibility-diff/`](skills/accessibility-diff/SKILL.md) | `$accessibility-diff`: which accessibility problems a change added or fixed |
| [`skills/codex-project-setup/`](skills/codex-project-setup/SKILL.md) | `$codex-project-setup`: writes or refreshes a repo's `AGENTS.md` |
| [`skills/codex-usage/`](skills/codex-usage/SKILL.md) | `$codex-usage`: tokens, estimated credits and plan percentage per run |
| [`agents/`](agents/) | Custom subagents `eng`, `ticket_worker`, `prompt_optimizer`, and the read-only `reviewer` and `forward_tester` |
| [`references/model-selection.md`](references/model-selection.md) | Which model tier and effort for which kind of work |
| [`references/ticket-labels.md`](references/ticket-labels.md) | When each ticket label goes on, and how held work is marked |
| [`references/testing-without-api-spend.md`](references/testing-without-api-spend.md) | When to test with `codex exec` or the Codex SDK on the ChatGPT sign-in, and when an API key is really needed |
| [`references/trackers/`](references/trackers/) | How each tracker operation is done on GitHub (`gh`) and on GitLab (`glab`) |
| [`scripts/resolve_model.py`](scripts/resolve_model.py) | Turns a tier into a model your account has, with a supported effort |
| [`scripts/codex_usage.py`](scripts/codex_usage.py) | Per-run usage from Codex's own records |
| [`registry.example.md`](registry.example.md) | Template for the tracker, board, lanes, labels and repo list the ticket skills read |
| [`evals/triggers/`](evals/triggers/) | For each skill, about 20 requests that should and should not trigger it, for testing its description |
| [`docs/sources.md`](docs/sources.md) | The documentation and measurements behind the design |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | Where the UX and accessibility skills come from, and their licenses |

## Install on a new machine

Needs: Codex (the ChatGPT desktop app or the Codex CLI), signed in; `git`; Python
3.11 or newer; and for the ticket skills, the CLI of your tracker, signed in: `gh`
for GitHub, or `glab` plus `jq` for GitLab (macOS ships `jq`; on Linux install it).

```bash
git clone <this repository's URL> ~/codex-pack
cd ~/codex-pack
./install.sh
```

The installer links each skill and `AGENTS.md` into `${CODEX_HOME:-~/.codex}` and
copies each agent file there; Codex refused a symlinked agent file when tested on
Codex CLI 0.158-0.160 (the docs do not say), and `--check` catches a stale copy. It
never overwrites a file it did not put there: an existing non-empty
`~/.codex/AGENTS.md` is left alone with a note on how to adopt this one, and links
that belong to another pack checkout are refused unless you pass
`--replace-other-pack`. On first run it creates `registry.md` from
`registry.example.md`; fill it in before using the ticket skills, starting with its
`tracker:` line. Restart Codex afterwards.

**Your own preferences** (how you like replies written, tools or credits you have,
rules for a repo only you work in) go in your own `~/.codex/config.toml` as
`developer_instructions = '''...'''`, a top-level key above any `[table]`. Codex adds
them to every session alongside this pack's `AGENTS.md`. Keep them out of the
repository: everything committed here reaches everyone who installs the pack.

```bash
./install.sh --check       # changes nothing; reports drift and anything missing
./install.sh --uninstall   # removes only what this pack installed
```

Skills and `AGENTS.md` are symlinks, so a `git pull` updates them. Agent files are
copies, so rerun `./install.sh` after changing anything in `agents/`.

## Sharing with a teammate

1. Give them access to this repository (on GitHub: Settings, Collaborators).
2. They install it as above, then fill in their own `registry.md`: the tracker, the
   board, and a row per repo with the path of their own local clone. It is untracked,
   so each person's paths stay on their machine.
3. They sign in to `gh` (or `glab`) as themselves. The ticket skills work only tickets
   assigned to that login.
   On GitLab, also let git use that sign-in, or pushes start failing once the stored
   token expires:
   `git config --global credential.https://gitlab.com.helper ''` then
   `git config --global --add credential.https://gitlab.com.helper '!glab auth git-credential'`
   (use your GitLab host in place of `gitlab.com` if it is self-managed).
4. They set a session default in `~/.codex/config.toml` (the "Recommended team
   default" in [references/model-selection.md](references/model-selection.md)) and put
   any personal preferences there as `developer_instructions`.
5. For the accessibility skills, they add the browser tools below.

Updates reach everyone with `git pull` (and `./install.sh` when `agents/` changed).

## Ticket trackers

The ticket skills describe their work as tracker operations (list the board, move a
card to a lane, comment, open a review request) and read how to do each one
from `references/trackers/<tracker>.md`, where `<tracker>` comes from `registry.md`.
GitHub uses Projects with a Status and a Priority field; GitLab uses an issue board
whose lanes and priorities are labels, and merge requests in place of pull requests.
To support another tracker, add a file with the same operations and name it in the
registry.

- **How they fit together.** `$write-ticket` files a ticket (what and why).
  `$plan-ticket` writes its build plan (how) and sets its model and run labels, so a
  person can read the plan first; `$daily-grooming` does that for the whole board.
  `$work-tickets` builds your Ready tickets in parallel, and `$ticket-worker` builds
  one. A worker writes the plan itself when a ticket has none.
- **How work lands.** Every change the pack makes goes on a branch and into the
  default branch by pull request (merge request on GitLab); Codex never commits or
  pushes to the default branch itself, even where a repo's own instructions allow
  direct pushes. A ticket worker ends with the review open and never closes the issue
  or moves its card to Done: merging closes the issue, and `$daily-grooming` settles
  it to Done and clears the dependency holds that waited on it. `$codex-project-setup`
  writes the same rule into a repo's `AGENTS.md`.
- **Whose tickets.** `$work-tickets`, `$ticket-worker` and `$plan-ticket` work only
  tickets assigned to whoever is signed in to `gh` or `glab` on the machine. Unassigned
  tickets are reported and left alone until someone is assigned. `$daily-grooming`
  looks after the whole board and never changes assignees.
- **Held work.** A ticket or review that is waiting on something carries the `blocked`
  label and a comment that starts `Blocked: dependency`, `Blocked: decision`,
  `Blocked: live action` or `Blocked: failure` and says what would clear it. No label
  names a person. A held review must not be merged; any merge automation should refuse
  one carrying the label. [references/ticket-labels.md](references/ticket-labels.md)
  has the full rule.
- **Board automations.** On a GitHub board, turn on the built-in "Item closed" and
  "Pull request merged" workflows (the board's Settings, Workflows), so a ticket closed
  by a merged review moves to Done straight away. Boards created through the API start
  with them off; without them, `$daily-grooming` moves closed tickets on its next run.
- **Tested so far.** On GitHub, the whole flow has run end to end in Codex on a test
  repo and board: filing, planning, labelling, moving cards, a worker fixing the bug
  with tests, and landing it by pull request that closed the ticket on merge. On
  GitLab.com (Free plan, a project board) every adapter command and the same flow have
  run, through merge request and grooming to done; see
  [docs/test-runs/](docs/test-runs/). Group-wide boards, self-managed GitLab and
  paid-plan labels are still marked `UNVERIFIED:`, so start those with `--dry-run`.

## Use

```text
$eng fix the failing date parser in src/dates.ts
$prompt-optimizer --file path/to/prompt.md
$write-ticket add rate limiting to the signup endpoint
$plan-ticket
$daily-grooming --dry-run
$work-tickets --dry-run
$work-tickets --priority P1
$ticket-worker work issue 42 in my-repo
$ux-review this checkout screenshot
$accessibility-scan http://localhost:3000
$codex-project-setup
$codex-usage
```

Each skill shows a display name, icon and starter prompt in the desktop app's
Skills list (`skills/<name>/agents/openai.yaml`).

## Browser tools for the accessibility skills

The accessibility skills drive a real page. `$accessibility-scan` and
`$accessibility-diff` need Node and Chrome installed (they run AccessLint's CLI
through `npx`, which starts Chrome itself).
`$accessibility-inspect` needs Chrome DevTools connected to Codex, and
`$accessibility-fix`, `$accessibility-audit` and `$accessibility-inspect` do more with
AccessLint's server connected:

```bash
codex mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest
codex mcp add accesslint -- npx -y @accesslint/mcp@latest
```

Restart Codex after adding them.

## Models

Prompts name a tier (`fast`, `workhorse`, `frontier`) and resolve it with
`scripts/resolve_model.py`, which reads the account's live model list and takes the
newest listed model in each tier. A new OpenAI model is picked up with no edit here;
when the pick differs from the script's built-in fallback list, it prints a note. Add
the new model's credit rates to `scripts/codex_usage.py`
([pricing](https://learn.chatgpt.com/docs/pricing.md)); the usage report warns about
any listed model it cannot price.

A Codex skill cannot choose the session's own model. The session runs on what each
person picked or set in `~/.codex/config.toml`; the skills choose models only for the
subagents they spawn (`$work-tickets` per ticket label, `$ticket-worker` when asked to
work one issue directly, `$eng`'s helpers and reviewer). No agent file pins a model,
because a model in an agent file overrides the one a spawn asks for. A sensible
default for everyone is in
[references/model-selection.md](references/model-selection.md), "Recommended team
default".

## Measuring usage

```bash
python3 scripts/codex_usage.py                       # last 10 runs
python3 scripts/codex_usage.py --run <id>            # one run, per thread
python3 scripts/codex_usage.py --since 2026-10-07 --summary
python3 scripts/codex_usage.py --since 2026-10-07 --csv ~/Documents/codex-usage.csv
```

Runs started with `codex exec --ephemeral` leave no record.

## Developing

```bash
scripts/check.sh   # ruff, format, mypy, pytest, Codex's skill validator, skill rules, standalone check
```

`scripts/validate_skills.sh` also checks every skill against the Agent Skills rules
(`scripts/check_skills.py`), that the tracker adapters agree, and that nothing names
a path from one machine. `scripts/check_pack.py` checks the pack's own files: agent
files set no model and keep the reviewer and forward tester read-only, every skill path
the instructions name exists, and no file holds an invisible character or a secret.
To keep your own details out of the pack, list them one per line in an untracked
`.personal-strings` file at the repo root; the check then fails on any tracked file
that contains one.

`scripts/eval_triggers.py --skill NAME` tests whether a skill's description makes Codex
load it: it runs each query in `evals/triggers/NAME.json` through `codex exec` on the
ChatGPT sign-in and counts a run as triggered when that skill's `SKILL.md` got loaded:
either the agent read it with a command (`read`), or the query named it as `$name` and
Codex injected it into the session itself (`injected`, found afterwards in the run's
session rollout file; a run whose rollout cannot be read is an error, never a miss). The
report says which of the two caught each trigger. Runs start in an empty folder; add
`--fixture small-repo` to start each one in a copy of `evals/fixtures/small-repo` with a
fresh `git init` and one commit, which the coding skills need before "fix the login bug"
means anything.
Real runs spend your plan's five-hour usage window, so start with `--only-first`, keep
`--max-parallel` small, and measure afterwards with `scripts/codex_usage.py --since`.
Apps (ChatGPT connectors such as GitHub) are off by default, because the read-only
sandbox does not stop a connector from writing; `--allow-apps` leaves them on, which is
closer to real use at the risk of real writes.
