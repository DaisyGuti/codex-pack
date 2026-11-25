"""The review rule: Codex's own rounds, then one optional Claude read when the Claude CLI is
installed. It mirrors the Claude Code pack, where a Codex read follows the Claude rounds."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STANDARDS = REPO / "skills" / "eng" / "references" / "engineering-standards.md"
ENG = REPO / "skills" / "eng" / "SKILL.md"
PROTOCOL = REPO / "skills" / "ticket-worker" / "references" / "protocol.md"


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_a_claude_read_follows_the_codex_rounds_once_and_never_blocks_by_its_absence() -> None:
    rule = _flat(STANDARDS)
    assert "**At most two rounds.**" in rule and "no third `reviewer` round" in rule
    assert "**Then a Claude read, when the Claude CLI is installed.**" in rule
    assert "`command -v claude`" in rule
    assert "never run it again after the fixes" in rule
    assert "When the CLI is missing, fails or is not signed in, skip it" in rule
    # The read is read-only: the diff arrives on stdin and only read tools are available.
    assert '--tools "Read,Grep,Glob" --permission-mode dontAsk' in rule
    assert "Do not edit, write or run anything." in rule
    # It comes after Codex's own rounds, never before them.
    assert rule.index("Then Codex's built-in review") < rule.index("Then a Claude read")


def test_eng_and_the_ticket_worker_both_run_the_claude_read() -> None:
    eng = _flat(ENG)
    assert "`command -v claude`" in eng and "Claude read" in eng
    protocol = _flat(PROTOCOL)
    assert "**Claude read.** Then the standards file's Claude read" in protocol
    assert "git -C $WT diff origin/<default_branch>...HEAD | claude -p" in protocol
    assert "Never run it twice." in protocol
    # The push waits for it.
    assert protocol.index("**Claude read.**") < protocol.index("**Review.** Per repo")


def test_the_claude_read_ignores_the_repos_own_settings() -> None:
    # `claude -p` skips the trust prompt, so a repo's .claude/settings.json hooks would run
    # during the "read-only" review; only the user's settings may load.
    for text in (_flat(STANDARDS), _flat(PROTOCOL)):
        command = text[text.index("claude -p") :]
        command = command[: command.index("--no-session-persistence") + 60]
        assert "--no-session-persistence --setting-sources user" in command


def test_no_other_claude_text_in_the_review_paths() -> None:
    # The review rule names the Claude CLI on purpose ("Claude CLI", "Claude read",
    # `claude -p`, `command -v claude`); the guides may name a repo's `CLAUDE.md`,
    # `.claude/settings.json`, Claude Code and the dated model:claude-* labels. Any other Claude
    # text is a port leftover.
    banned = re.compile(
        r"(?<!-v )\bclaude\b"
        r"(?!\s+(?:-p|CLI|read|Code|allowance)\b|\.md|/settings\.json|-(?:haiku|sonnet|opus|\*))",
        re.I,
    )
    shipped = [
        p
        for root in ("skills/eng", "skills/ticket-worker", "agents")
        for p in (REPO / root).rglob("*")
        if p.is_file() and not p.is_symlink() and p.suffix in (".md", ".toml", ".yaml")
    ]
    assert shipped
    hits = [
        f"{p.relative_to(REPO)}:{n}"
        for p in shipped
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if banned.search(line)
    ]
    assert hits == []
