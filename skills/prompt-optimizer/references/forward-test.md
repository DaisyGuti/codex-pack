# Forward test

Read this when the skill's Forward test section says to run one.

A forward test runs the candidate prompt on one realistic input and compares what
happened with what the prompt intends. Pick the route by how many cases you need.

**One decisive case: in this session.** Spawn the read-only `forward_tester` agent
with the model and effort the Final version recommends set explicitly (resolve them
with [scripts/resolve_model.py](../scripts/resolve_model.py)); the agent file sets
none, so the spawn's values are the ones that run. Its brief is the Final version
plus the realistic input, and leaves out the intended answer and any suspected
weakness. It cannot write; when the prompt's job writes to shared systems (pushes,
posts, board edits), it describes those actions instead.

**Several cases, or the same case again after a patch: `codex exec` or the Codex SDK.**
Run each case on the `fast` tier (resolve it with the same script) through the ChatGPT
sign-in, never on an API key, in a read-only sandbox, one case at a time before any
batch. The commands, the checks to run first and the limits are in
[testing-without-api-spend.md](testing-without-api-spend.md). A fast-tier model can
behave differently from the setting the prompt recommends, so confirm a result that
matters with one `forward_tester` run on the recommended setting.

Compare what it did with what the prompt intends; each gap is a round 6 finding,
fixed in the prompt. When the failure came from `--evidence`, follow
[diagnose-and-patch.md](diagnose-and-patch.md) to name the cause before changing
wording, and re-run the failing inputs after the patch.

Then metaprompt it: ask the same subagent to reread its instructions and point to
anything that made it slower, unsure or off course, and to propose targeted,
general changes. Repeat the test once more only when the first run surfaced a P0
or P1, and then keep only the suggestions both runs share. Adopt a suggestion only
when it generalizes beyond this one input.
