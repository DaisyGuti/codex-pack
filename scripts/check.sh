#!/usr/bin/env bash
# The full local gate. Run it before every commit; there is no remote CI.
#
#   scripts/check.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
scripts/validate_skills.sh
bash -n install.sh
echo "all gates passed"
