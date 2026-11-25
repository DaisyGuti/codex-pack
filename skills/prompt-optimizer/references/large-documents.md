# Prompts that name large documents

A prompt that asks one session to read several long PDFs, spreadsheets, standards, pages or
repositories runs out of context before it does the work. Rewrite it as a chain that runs from
one paste. Files, folders and links the prompt names are inputs for the model that will run
it: do not open, fetch or read them yourself while optimizing, because a long standard or
spreadsheet overflows this session's context too. Read only the `--file` prompts and the
guidance in the target's section of [target-guidance.md](target-guidance.md). Keep every
document the prompt names.

## Contents

- The chain
- Example shape
- What each extraction must do
- Small inputs

## The chain

1. **One extraction prompt per document**, all in parallel. Each carries the task and the
   criteria for what counts as relevant (the sections, controls, process steps or columns the
   user named), and tells the model to search or read page ranges rather than read the whole
   file. It writes a notes file, such as `notes/<document>.md`. Each entry there is a verbatim
   excerpt with its source: document title, path or link, and page, section, control id, or
   sheet and row. It records "nothing relevant" when that is the result, and lists any parts
   it could not read.
2. **One extraction prompt per source the task needs but the user did not supply**, such as
   CNSSI 1253, FIPS 199 and NIST SP 800-60 for a DoD categorization review. Do not leave
   these as open questions. When the publisher posts the document openly, the extraction
   downloads it from the publisher's site and records the URL and version it used. When you
   know a needed source is not public (an internal wiki, a login-only portal), ask the user
   for a copy before you write the final version. When a download fails at run time, the
   extraction stops and asks the user for a copy rather than citing the document from memory.
3. **The main prompt**, which holds the extraction prompts and runs the chain. Its
   `## Execution plan` section starts one subagent per extraction prompt, gives it that prompt
   word for word with its own tier and effort (resolved per
   [model-selection.md](model-selection.md)), and waits until every notes file is written.
   The main prompt then reads the notes files in place of the documents, cites the sources
   recorded there, and opens a source document only to check one citation.

Keep the user's original steps and approvals in the main prompt.

## Example shape

```text
## Extraction: process-instruction
...the extraction prompt for one document...

## Extraction: control-catalog
...

## Execution plan
Stage 1, in parallel: one subagent per extraction above, given its text word for word;
process-instruction and control-catalog on the fast tier, high effort.
Stage 2, after every notes file exists: the review below, in this session.

...the review, the approval step and anything that follows it...
```

## What each extraction must do

- **Record what the input is first.** You have not opened it, so the prompt must not depend on
  a guess: a pull request can hold design documents rather than code, and a spreadsheet can
  lack the columns you expect. The extraction records the input's type, layout and size, then
  pulls what is relevant from what is actually there.
- **Not depend on a tool that may be missing on the runner's machine.** Have it try one route
  on a single page range first (for a PDF, `pdftotext -f <first> -l <last>`, which needs
  poppler, then a Python library), move to the next route when that fails, and stop and name
  what to install when none works.
- **Stop and ask instead of guessing** when the input cannot be read.

## Small inputs

A README or one short page can stay in the main prompt instead of getting its own extraction.
