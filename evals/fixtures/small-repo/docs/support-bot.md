# Support bot

Runs hourly from a scheduler. It reads open tickets, applies `prompts/triage.md`,
and writes a decision for each one to the `support_decisions` queue. A script parses
the JSON reply, so anything outside the JSON object breaks the run.

Owner: support engineering. Escalations go to the on-call channel.
