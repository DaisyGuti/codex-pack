"""check_facts.py lists the numbers, links and code an edit dropped, and nothing else."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_facts.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_facts_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load()

BEFORE = """# Upload outage

We have identified an issue that may have impacted users. Between 14:02 and 14:31 UTC,
12% of requests failed after the deploy of v2.4.1. See https://status.example.com/incidents.
Set `DB_PASSWORD` and read the [runbook](docs/runbook.md).

1. Roll back.
2. Watch the error rate.

```sh
helm rollback upload 41
```
"""


def test_a_reworded_edit_that_keeps_every_fact_passes() -> None:
    after = """# Upload outage

Between 14:02 and 14:31 UTC, 12% of requests failed after the deploy of v2.4.1.
Details: https://status.example.com/incidents. Set `DB_PASSWORD`, then read the
[runbook](docs/runbook.md). Roll back, then watch the error rate.

```sh
helm rollback upload 41
```
"""
    assert check.dropped(BEFORE, after) == []


@pytest.mark.parametrize(
    ("cut", "kind", "value"),
    [
        ("12% of", "number", "12%"),
        ("14:31", "number", "14:31"),
        (
            " See https://status.example.com/incidents.",
            "link",
            "https://status.example.com/incidents",
        ),
        ("[runbook](docs/runbook.md)", "link", "docs/runbook.md"),
        ("`DB_PASSWORD`", "code", "DB_PASSWORD"),
    ],
)
def test_each_dropped_fact_is_named(cut: str, kind: str, value: str) -> None:
    assert (kind, value) in check.dropped(BEFORE, BEFORE.replace(cut, ""))


def test_a_changed_code_block_is_reported() -> None:
    after = BEFORE.replace("upload 41", "upload 40")
    assert ("code-block", "helm rollback upload 41") in check.dropped(BEFORE, after)


def test_renumbering_or_unlisting_steps_is_not_a_dropped_number() -> None:
    after = BEFORE.replace("1. Roll back.\n2. Watch the error rate.", "Roll back and watch.")
    assert [k for k, _ in check.dropped(BEFORE, after) if k == "number"] == []


def test_cutting_a_repeated_fact_is_not_reported() -> None:
    before = "The limit is 500 requests.\n\nRemember: the limit is 500 requests.\n"
    assert check.dropped(before, "The limit is 500 requests.\n") == []


def test_main_lists_what_was_dropped_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before, after = tmp_path / "before.md", tmp_path / "after.md"
    before.write_text(BEFORE, encoding="utf-8")
    after.write_text(BEFORE.replace("12% of", ""), encoding="utf-8")
    assert check.main([str(before), str(after)]) == 1
    assert "dropped number: 12%" in capsys.readouterr().out


def test_main_exits_zero_when_nothing_was_dropped(tmp_path: Path) -> None:
    before = tmp_path / "before.md"
    before.write_text(BEFORE, encoding="utf-8")
    assert check.main([str(before), str(before)]) == 0


def test_a_missing_file_is_unusable_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    present = tmp_path / "after.md"
    present.write_text("x", encoding="utf-8")
    assert check.main([str(tmp_path / "missing.md"), str(present)]) == 2
    assert "no such file" in capsys.readouterr().err
