# Severity examples

Tag each issue as the loop in [SKILL.md](../SKILL.md) says. These show where the lines fall.

- **P0**: two instructions contradict each other; the output format cannot be parsed by the
  step that consumes it; the prompt asks for a capability the target model or runtime lacks;
  a pinned `model` or `model_reasoning_effort` in an agent file that overrides the spawn's.
- **P1**: no handling for empty input; a rule with no scope; emphatic wording that causes a
  tool to be over-used; one prompt that has the model read several long documents whole;
  a chain the user has to start by hand; an extraction that assumes what an unopened input
  holds; a public source the task needs left as an open question.
- **P2**: wording polish, heading renaming, reordering without a behavior effect.
