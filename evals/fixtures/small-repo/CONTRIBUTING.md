# Contributing

- Branch from `main`, open a pull request, one reviewer.
- CI must pass: migrations apply to an empty database, then the tests with `uv run pytest` (uv installs pytest from the dev group).
- New behaviour comes with a test; a bug fix comes with a regression test.
- Schema changes are a new numbered file in `db/migrations/`. Never edit one that has shipped.
- Keep `billing/` function signatures stable; other services import them.
- Code review focus: error handling, retries, anything that touches money.
