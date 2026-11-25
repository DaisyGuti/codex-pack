---
name: adr
description: Use when the user records a decision already made ("write an ADR", "we decided on X", "supersede ADR 7"). Writes a numbered MADR file in the repo. To weigh options first, use $design-doc.
---

# Architecture decision record

An ADR records one decision that has been made (or is proposed): the situation, the options
weighed, the choice and why. It is short. The format is MADR;
[assets/madr-template.md](assets/madr-template.md) is the template and
[references/madr-guide.md](references/madr-guide.md) explains each section.

Take the decision title and any `supersedes N` from the request. Every script call below
runs from the user's repo, with the script at its installed path.

## 1. Locate the folder

Run `python3 ${CODEX_HOME:-~/.codex}/skills/adr/scripts/doc_tool.py adr locate`. It reports
the folder (an existing `docs/adr`, `docs/decisions` or similar, else `docs/decisions` to be
created), the next number and width, the existing records with their statuses, and an index
file if the folder keeps one.

- If existing records use another template (for example Nygard's Status, Context,
  Decision, Consequences), say so and ask once whether to match it or use MADR. MADR is the
  default.
- Read the two most recent records to match their level of detail.

## 2. Gather the decision

From the conversation and the repo, collect: the context and question, the decision
drivers, at least two options (the rejected ones matter most to a future reader), the
chosen option and the reason, consequences good and bad, and how the team will confirm the
code follows the decision. Ask for what is missing in one message. Never invent decision
makers or dates: take names from the user, and use `[TODO: names]` markers only until the
user provides them.

Status: `accepted` when the user says the decision is made, otherwise `proposed`. The other
statuses are `rejected` and `deprecated`. A record that replaces another is created with
`--supersedes`.

## 3. Create the record

`python3 ${CODEX_HOME:-~/.codex}/skills/adr/scripts/doc_tool.py adr new "<title>" --status <status> [--supersedes N ...]`

The title states the decision in a short phrase ("Use Postgres for the audit log"). The
script numbers the file, names it from the title, fills the date and status, and prints the
path as JSON. With `--supersedes N` it checks every named record exists and has a status
line before writing anything, then sets the old record's status to a `superseded by`
line that links the new record and adds a `Supersedes` link to the new record. The old
record's text is otherwise left alone; never rewrite an accepted record's reasoning.

Then fill the new file with `apply_patch`. Keep the Decision Outcome line in the form
`Chosen option: "<option>", because <reason>.`

To change a status later:
`python3 ${CODEX_HOME:-~/.codex}/skills/adr/scripts/doc_tool.py adr set-status <N> <status>`.

## 4. Check

1. `python3 ${CODEX_HOME:-~/.codex}/skills/adr/scripts/doc_tool.py adr check <file>` until
   it prints `ok`.
2. `python3 ${CODEX_HOME:-~/.codex}/skills/adr/scripts/lint_draft.py <file>` until it
   prints `clean`.
3. If `locate` reported an index file, read it and add one line for the new record in the
   index's existing format. If it reported none, add nothing.

Writing rules: plain, direct sentences, no hype words, and no contrasting "not X" clause
after a claim. Say what the thing is and stop.

## 5. Report

Give the user the path, the one-sentence decision, the status, and any record it
superseded. Do not commit unless asked.
