"""Structure checks for the six team-comms skills that scripts/check_skills.py and
scripts/check_pack.py cannot make: the sending rules, the Slack tool names, the connect
guide, the trigger evals and the writing rules the skills hold themselves to.

Left to check_skills.py and check_pack.py, so not repeated here: frontmatter and name rules,
description and body length, links and backticked paths that must resolve, `${CODEX_HOME}`
skill paths that must exist, `~/.claude` and machine paths (validate_skills.sh), and secrets.
Claude-plugin checks (plugin.json fields, `${CLAUDE_PLUGIN_ROOT}`, allowed frontmatter keys,
`claude plugin eval` case folders) have no counterpart in this pack.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
SKILLS = ["adr", "design-doc", "slack-catchup", "slack-draft", "slack-send", "status-update"]
SLACK_SKILLS = ["slack-catchup", "slack-draft", "slack-send"]
GUIDE = SKILLS_DIR / "slack-send" / "references" / "connect-slack.md"
WRITE_TOOLS = ("slack_send_message", "slack_schedule_message", "slack_add_reaction")
MIN_QUERIES_PER_CLASS = 10
TOC_THRESHOLD = 100  # reference files longer than this need a Contents list


def _lint_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "lint_draft_for_skills", ROOT / "scripts" / "lint_draft.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lint: Any = _lint_module()


def real_markdown() -> list[Path]:
    """Markdown the skills own: no symlinks, so a shared file is read once."""
    files: list[Path] = []
    for skill in SKILLS:
        folder = SKILLS_DIR / skill
        files += [
            p
            for p in sorted(folder.rglob("*.md"))
            if not p.is_symlink() and "assets" not in p.relative_to(folder).parts
        ]
    return files


def test_every_skill_has_its_scripts_linked_into_the_pack_scripts_folder() -> None:
    for skill in SKILLS:
        links = list((SKILLS_DIR / skill / "scripts").glob("*.py"))
        assert links, f"{skill} links no script"
        for link in links:
            assert link.is_symlink()
            assert link.resolve() == (ROOT / "scripts" / link.name).resolve()


def test_posting_lives_only_in_slack_send() -> None:
    for skill in SKILLS:
        if skill == "slack-send":
            continue
        for path in sorted((SKILLS_DIR / skill).rglob("*.md")):
            if path.name == GUIDE.name:
                continue  # the guide lists every tool, write tools included
            text = path.read_text(encoding="utf-8")
            for tool in WRITE_TOOLS:
                assert tool not in text, f"{path} names {tool}; only slack-send may write to Slack"


def test_draft_only_rule_is_stated_at_the_top_of_slack_draft() -> None:
    text = (SKILLS_DIR / "slack-draft" / "SKILL.md").read_text(encoding="utf-8")
    body = text.split("---", 2)[2]
    assert "drafts only" in body.split("## 1.")[0].lower()


def test_catchup_states_it_is_read_only_before_any_step() -> None:
    text = (SKILLS_DIR / "slack-catchup" / "SKILL.md").read_text(encoding="utf-8")
    top = text.split("## 1.")[0].lower()
    assert "only reads" in top
    assert "never posts" in top


def test_slack_send_keeps_its_confirmation_and_secret_rules() -> None:
    text = " ".join((SKILLS_DIR / "slack-send" / "SKILL.md").read_text(encoding="utf-8").split())
    assert "A silent or ambiguous answer means do not send" in text
    assert "A `secret` finding stops the send" in text
    assert "no edits after the confirmation" in text
    assert "do not retry" in text
    assert "Never guess a channel" in text
    assert "In a non-interactive run" in text


@pytest.mark.parametrize("skill", SLACK_SKILLS)
def test_slack_skills_point_to_the_connect_guide_and_share_one_file(skill: str) -> None:
    folder = SKILLS_DIR / skill
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert "references/connect-slack.md" in text
    guide = folder / "references" / "connect-slack.md"
    assert guide.resolve() == GUIDE.resolve()
    assert (ROOT / "docs" / "connect-slack.md").resolve() == GUIDE.resolve()


def test_every_slack_tool_named_in_a_skill_is_listed_in_the_connection_guide() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    seen: set[str] = set()
    for skill in SLACK_SKILLS:
        text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
        for tool in re.findall(r"\b(slack_(?!helpers)[a-z_]+)\b", text):
            seen.add(tool)
            assert f"`{tool}`" in guide, f"{skill} uses {tool}, missing from connect-slack.md"
    assert seen, "no Slack tool name found; the pattern went blind"


def test_the_guide_names_the_server_the_skills_expect() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    assert "codex mcp add slack --url https://mcp.slack.com/mcp" in guide
    assert "mcp__slack__<tool>" in guide
    for skill in SLACK_SKILLS:
        text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "mcp__slack__" in text


@pytest.mark.parametrize(
    "path",
    [p for p in real_markdown() if "references" in p.parts],
    ids=lambda p: p.name,
)
def test_long_reference_files_have_a_contents_list(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if len(text.splitlines()) > TOC_THRESHOLD:
        assert "## Contents" in text, f"{path.name} is over {TOC_THRESHOLD} lines"


@pytest.mark.parametrize("skill", SKILLS)
def test_trigger_evals_have_both_classes(skill: str) -> None:
    cases = json.loads((ROOT / "evals" / "triggers" / f"{skill}.json").read_text(encoding="utf-8"))
    queries = [c["query"] for c in cases]
    assert len(queries) == len(set(queries))
    assert sum(1 for c in cases if c["should_trigger"]) >= MIN_QUERIES_PER_CLASS
    assert sum(1 for c in cases if not c["should_trigger"]) >= MIN_QUERIES_PER_CLASS


def test_prose_follows_the_writing_rules() -> None:
    problems = []
    for path in real_markdown():
        for finding in lint.check_prose(path.read_text(encoding="utf-8")):
            if finding.rule in {"contrast", "hype"}:
                problems.append(f"{path.relative_to(ROOT)}:{finding.line}: {finding.excerpt}")
    assert not problems, "\n".join(problems)
