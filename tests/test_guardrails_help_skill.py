"""The guardrails-help skill stays consistent with the hook it explains."""

from __future__ import annotations

import json
import re

import yaml
from test_guardrails_support import REPO, SCRIPT, SKILL_DIR, G

SKILL = SKILL_DIR / "SKILL.md"
INSTALLED_SCRIPT = "${CODEX_HOME:-~/.codex}/skills/guardrails-help/scripts/guardrails.py"


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    assert text.startswith("---\n"), "the opening --- must be line 1"
    head, _, body = text[4:].partition("\n---\n")
    fields = yaml.safe_load(head)
    assert isinstance(fields, dict)
    return {str(k): str(v) for k, v in fields.items()}, body


def test_frontmatter_follows_the_conventions() -> None:
    text = SKILL.read_text(encoding="utf-8")
    fields, _ = frontmatter(text)
    assert set(fields) == {"name", "description"}
    assert fields["name"] == "guardrails-help" == SKILL_DIR.name
    description = fields["description"]
    assert description.startswith("Use when")
    assert "guardrails[" in description  # the text a blocked call produces
    assert len(description) <= 230  # the pack's catalog budget is tight
    assert len(text.splitlines()) < 500


def test_skill_matches_the_hook() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert f"{G.ALLOW_DIR}/{G.ALLOW_FILE}" in text
    for rule_id in ("gcp-public-access", "guardrails-tamper", "cannot-decide"):
        assert rule_id in G.RULE_BY_ID and rule_id in text
    for rule in G.RULES:
        if not rule.allowlistable:
            assert rule.id in text  # the skill says these cannot be listed


def test_skill_commands_run_the_installed_script() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert f'python3 "{INSTALLED_SCRIPT}" --list-rules' in text
    assert f'python3 "{INSTALLED_SCRIPT}" --recent' in text
    link = SKILL_DIR / "scripts" / "guardrails.py"
    assert link.resolve() == SCRIPT.resolve()


def test_reference_links_resolve_and_the_long_reference_has_contents() -> None:
    text = SKILL.read_text(encoding="utf-8")
    links = re.findall(r"\]\(((?:references|scripts)/[^)]+)\)", text)
    assert links and all((SKILL_DIR / link).exists() for link in links)
    ref = (SKILL_DIR / "references" / "rule-sources.md").read_text(encoding="utf-8")
    assert "## Contents" in ref


def test_skill_files_name_no_claude_paths_or_settings() -> None:
    for path in [SKILL, *SKILL_DIR.glob("references/*.md"), SKILL_DIR / "agents" / "openai.yaml"]:
        text = path.read_text(encoding="utf-8")
        assert "CLAUDE_" not in text and ".claude/" not in text, path
        assert "/Users/" not in text, path


def test_openai_yaml_points_at_real_icons() -> None:
    data = yaml.safe_load((SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    interface = data["interface"]
    for key in ("icon_small", "icon_large"):
        assert (SKILL_DIR / interface[key]).is_file()
    assert "$guardrails-help" in interface["default_prompt"]


def test_trigger_evals_cover_both_sides() -> None:
    path = REPO / "evals" / "triggers" / "guardrails-help.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    hits = [r for r in rows if r["should_trigger"]]
    assert len(rows) >= 18 and 8 <= len(hits) <= len(rows) - 8
