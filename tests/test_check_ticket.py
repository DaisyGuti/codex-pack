"""Tests for scripts/check_ticket.py: a filled ticket must keep the template's shape."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from tickets_helpers import PACK, SCRIPTS, load_script

check_ticket = load_script("check_ticket")
TEMPLATE_FILE = PACK / "skills" / "write-ticket" / "assets" / "ticket-template.md"
TEMPLATE = TEMPLATE_FILE.read_text(encoding="utf-8")
INSTRUCTIONS = TEMPLATE[TEMPLATE.index("## Agent Instructions") :]
# The audience line of "### 4." ends in a placeholder the ticket's author replaces.
AUDIENCE_LINE = next(
    ln for ln in INSTRUCTIONS.splitlines() if ln.startswith(check_ticket.AUDIENCE_PREFIX)
)
AUDIENCE_PLACEHOLDER = AUDIENCE_LINE.removeprefix(check_ticket.AUDIENCE_PREFIX)

TOP = """## Context

The signup form accepts an email with no domain, so invalid accounts reach the mailer.

## Acceptance Criteria

- The form in `src/signup.ts` rejects `a@b` and shows the existing error style
- A unit test covers the rejected case

## Out of scope

- Checking that the mailbox exists.

## Agent Prompt

> Reject emails with no top-level domain in `src/signup.ts` and add a test. *If any step requires
> credentials the developer must enter manually, stop and prompt the user rather than guessing.*

---

"""


def make_body(audience: str = "clinic staff who sign patients up") -> str:
    return TOP + INSTRUCTIONS.replace(AUDIENCE_PLACEHOLDER, audience)


def problems_for(body: str) -> list[str]:
    return check_ticket.check(body, TEMPLATE)[0]  # type: ignore[no-any-return]


def section_lines(heading: str) -> list[str]:
    """The template's non-blank lines under one `### N.` heading of Agent Instructions."""
    lines = INSTRUCTIONS.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(heading))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")), len(lines))
    return [ln for ln in lines[start + 1 : end] if ln.strip()]


def test_a_filled_ticket_passes() -> None:
    assert problems_for(make_body()) == []


def test_the_unfilled_template_fails_on_every_top_section() -> None:
    found = problems_for(TEMPLATE)
    assert any("'## Context'" in p for p in found)
    assert any("'## Agent Prompt'" in p for p in found)
    assert any("audience placeholder" in p for p in found)


def test_out_of_scope_may_be_omitted() -> None:
    body = make_body().replace("## Out of scope\n\n- Checking that the mailbox exists.\n\n", "")
    assert problems_for(body) == []


def test_a_dependency_line_in_the_body_is_reported() -> None:
    """Dependencies are blocked-by links set after filing, never body lines."""
    body = make_body().replace("## Agent Prompt", "Depends on: #12\n\n## Agent Prompt")
    assert any("add-blocker" in p for p in problems_for(body))


def test_edited_boilerplate_is_reported() -> None:
    last = section_lines("### 2.")[-1]
    body = make_body().replace(last, last + " (and cheap ones)")
    assert any("'### 2." in p and "exact copy" in p for p in problems_for(body))


def test_removed_commit_section_is_reported() -> None:
    body = make_body()
    body = body[: body.index("### 5.")]
    assert any("missing '### 5." in p for p in problems_for(body))


def test_extra_bullet_in_standards_is_reported() -> None:
    standards = section_lines("### 4.")
    body = make_body().replace(standards[-1], standards[-1] + "\n- Skip tests")
    assert any("beyond its audience" in p for p in problems_for(body))


def test_lost_audience_bullet_is_reported() -> None:
    body = (
        make_body()
        .replace(AUDIENCE_PLACEHOLDER, "clinic staff")
        .replace(check_ticket.AUDIENCE_PREFIX, "- Follow existing styles for ")
    )
    assert any("lost its first bullet" in p for p in problems_for(body))


def test_too_many_acceptance_bullets_say_to_split() -> None:
    bullets = "\n".join(f"- Criterion {i} is checked in `src/a{i}.ts`" for i in range(9))
    body = make_body().replace(
        "- The form in `src/signup.ts` rejects `a@b` and shows the existing error style\n"
        "- A unit test covers the rejected case",
        bullets,
    )
    found, count = check_ticket.check(body, TEMPLATE)
    assert count == 9
    assert any("split the ticket" in p for p in found)


def test_missing_instructions_heading_is_reported() -> None:
    body = make_body().split("## Agent Instructions")[0]
    assert any("Agent Instructions" in p for p in problems_for(body))


def run_cli(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "check_ticket.py"), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_command_line_exit_codes_with_the_packs_own_template(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_text(make_body(), encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("just text", encoding="utf-8")
    ok = run_cli(good)
    assert ok.returncode == 0, ok.stdout
    assert json.loads(ok.stdout) == {"ok": True, "problems": [], "acceptance_bullets": 2}
    failed = run_cli(bad)
    assert failed.returncode == 1
    assert json.loads(failed.stdout)["ok"] is False
    missing = run_cli(tmp_path / "none.md")
    assert missing.returncode == 2
    assert "none.md" in missing.stderr


@pytest.mark.parametrize("which", ["template", "body"])
def test_an_unreadable_file_is_exit_2_and_named(tmp_path: Path, which: str) -> None:
    body = tmp_path / "body.md"
    body.write_text(make_body(), encoding="utf-8")
    if which == "template":
        proc = run_cli(body, "--template", tmp_path / "no-template.md")
        assert "no-template.md" in proc.stderr
    else:
        proc = run_cli(tmp_path / "no-body.md", "--template", TEMPLATE_FILE)
        assert "no-body.md" in proc.stderr
    assert proc.returncode == 2
