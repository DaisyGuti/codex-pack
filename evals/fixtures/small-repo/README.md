# Shop API

A small orders and invoices service. Python backend (standard library and SQLite),
React pages under `web/`.

## Run it

    python scripts/migrate.py        # create or update app.db
    python main.py                   # serves on http://127.0.0.1:8080

Settings come from `config.toml` if it exists, then from environment variables
(`SHOP_HOST`, `SHOP_PORT`, `SHOP_DATABASE`, `SHOP_PAGE_SIZE`).

## Layout

- `main.py` entry point and WSGI app
- `api/` request handlers (`/orders`, `/login`)
- `billing/` payment helpers, including `retry.py`
- `services/export.py` the nightly order export
- `db/` connection helper and SQL migrations
- `web/` the invoices page and the signup form
- `prompts/`, `agents/`, `docs/support-bot.md` the support triage bot's instructions

## Tests

    uv run pytest

See `CONTRIBUTING.md` for how changes land.
