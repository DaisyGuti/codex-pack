# ExecPlan

Read this when the work will run for hours or across sessions, and a fresh agent
must be able to pick it up from one file. An ExecPlan is a design document that
doubles as a progress log. It is adapted from the PLANS.md template in OpenAI's
Cookbook article "Using PLANS.md for multi-hour problem solving"
(`articles/codex_exec_plans.md`, MIT, Copyright (c) 2025 OpenAI; the notice is in
`THIRD_PARTY_NOTICES.md` at the root of this pack). "ExecPlan" is a shorthand the
Cookbook chose; Codex has no special training on it, so the plan file and the repo's
`AGENTS.md` have to say what it means.

A repo opts in with one line in its `AGENTS.md`, such as: "When writing complex
features or significant refactors, use an ExecPlan from design to implementation."
When the repo has no such line, say in your report that you kept a plan file and
where it is.

## Where it lives

Write the plan as one Markdown file in the place the repo keeps designs, and match
its neighbours' naming and dating. Commit it with the work. Read the engineering
standards on durable output first.

## What a good plan does

- It is self-contained. The reader has the working tree and this file, and nothing
  else: no memory of earlier plans, no chat history. Repeat any assumption you rely
  on. Explain what the reader needs in your own words instead of pointing to a blog
  or a document that may move. A plan that builds on another checked-in plan may
  reference it; otherwise copy in the context it needs.
- It defines every term of art in plain language the first time it appears, and says
  where that term shows up in this repo (a file or a command).
- It starts with why the work matters: what someone can do afterwards that they
  could not do before, and how to see it working.
- It states acceptance as behavior a person can observe: a command to run and the
  output to expect, a request and its response, a test that fails before the change
  and passes after. For example: after starting the server, GET /health returns 200
  with body OK. When the change is internal, show how its effect can still be
  demonstrated.
- It resolves ambiguity itself, and records why. It never leaves a key decision to
  the reader.
- It names files by repo-relative path, functions and modules precisely, the working
  directory for each command, and where new files go.
- Its steps are safe to run twice. A step that can fail halfway says how to retry or
  roll back. Prefer additive changes first and removals after the tests pass.
- It includes the validation: how to start the system, what to observe, the exact
  test commands and how to read their results.

## Sections

Write these in order. Narrative sections are prose; only Progress uses checkboxes.

1. **Purpose / Big Picture.** A few sentences: what the user gains and how to see it.
2. **Progress.** A checkbox list of granular steps, each with a timestamp when done.
   Every stopping point is recorded here, even when it splits a task into "done"
   and "remaining". This section always matches the real state of the work.
3. **Surprises & Discoveries.** Anything unexpected (a bug, a performance finding, a
   behavior the docs did not mention), each with a short piece of evidence such as
   test output.
4. **Decision Log.** Each decision with its rationale, the date and who made it.
5. **Outcomes & Retrospective.** At each major milestone and at the end: what was
   achieved, what remains, what was learned, compared with the Purpose.
6. **Context and Orientation.** The current state as if the reader knows nothing: key
   files by full path, how the parts fit together.
7. **Plan of Work.** The sequence of edits in prose: for each, the file, the place in
   it, and what to add or change. Concrete and minimal.
8. **Concrete Steps.** The exact commands and where to run them, with a short
   expected transcript. Update it as the work proceeds.
9. **Validation and Acceptance.** How to exercise the system, with specific inputs
   and outputs.
10. **Idempotence and Recovery.** What is safe to repeat, and the retry or rollback
    path for anything risky.
11. **Artifacts and Notes.** The few transcripts, diffs or snippets that prove
    success, kept short.
12. **Interfaces and Dependencies.** The libraries, modules and services to use and
    why, plus the types and function signatures that must exist at the end of each
    milestone.

Title the plan for what it delivers. Put one line near the top saying the plan is a
living document and that Progress, Surprises & Discoveries, Decision Log and
Outcomes & Retrospective stay current as work proceeds.

## Milestones and prototypes

Introduce each milestone with a short paragraph: its scope, what exists at the end
that did not exist before, the commands to run, and the acceptance to expect. Each
milestone is independently verifiable and moves the whole plan forward. Progress
tracks the granular steps; milestones tell the story.

When a larger change carries real unknowns, add a labelled prototyping milestone
that tests feasibility first, such as a small spike on a library you have not used.
Say how to run it, and the criteria for keeping or discarding it. Evaluate unrelated
new libraries in separate spikes.

## While you work from a plan

- Go to the next milestone without asking the user what to do next. Resolve
  ambiguities yourself, record the decision, and commit often. The repo's approval
  rules for public, paid and production actions still apply.
- Update every living section at each stopping point, and add or split Progress
  entries to say what is done and what is next.
- When you change course, write the reason in the Decision Log and reflect it in
  Progress.
- When you revise the plan, make the change consistent across all sections and add a
  note at the bottom saying what changed and why.
- Before you finish, close every item: done, blocked with the reason, or cancelled
  with the reason.
