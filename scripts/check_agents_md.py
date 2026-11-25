#!/usr/bin/env python3
"""Check a repo's AGENTS.md before it is committed.

The codex-project-setup skill runs this on the file it wrote. It fails on the defects that make
an AGENTS.md wrong or unsafe to commit, and prints notes for things a person should look at.
The size of the whole chain Codex loads is check_context_budget.py's job.

Usage:
    check_agents_md.py [PATH]    PATH is the AGENTS.md to check (default: ./AGENTS.md)

Exit codes: 0 no failures (notes may print), 1 at least one failure, 2 the file cannot be read.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Codex reads at most project_doc_max_bytes of project instructions (32 KiB by default);
# a single file past it is cut before the model sees its end.
MAX_BYTES = 32_768

# Names are for the message only. The matched text is never printed, so a real secret that
# slipped into the file is not copied into a transcript.
SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "OpenAI-style API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"),
    "GitLab token": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "inline credential": re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9/+_-]{12,}"
    ),
}
PERSONAL_PATH = re.compile(r"(?:/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|[A-Z]:\\Users\\)")
REQUIRED_HEADINGS = {
    "commands": "a Commands section with the repo's real build, test and lint commands",
    "landing": "a Landing changes section (branch, then pull or merge request)",
    "security": "a Security rules section",
}
# npm lifecycle shortcuts that run a package script without the word `run`.
SHORTCUT_SCRIPTS = frozenset({"test", "start", "stop", "restart"})
MAKE_TARGET = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*:(?!=)", re.M)
SCRIPT_CALL = re.compile(r"^(?:npm|pnpm|yarn)\s+(?:(run|run-script)\s+)?([A-Za-z0-9:_-]+)")


def code_spans(line: str) -> list[str]:
    return re.findall(r"`([^`]+)`", line)


def headings(lines: list[str]) -> list[str]:
    return [m.group(1).lower() for ln in lines if (m := re.match(r"^#{1,6}\s+(.+?)\s*$", ln))]


def nearest(folder: Path, name: str) -> Path | None:
    """`name` in `folder` or the closest parent, stopping at the repository's top."""
    for here in (folder, *folder.parents):
        if (here / name).is_file():
            return here / name
        if (here / ".git").exists():
            return None
    return None


def makefile_targets(folder: Path) -> set[str] | None:
    path = nearest(folder, "Makefile")
    if path is None:
        return None
    return set(MAKE_TARGET.findall(path.read_text(encoding="utf-8", errors="replace")))


def package_scripts(folder: Path) -> set[str] | None:
    path = nearest(folder, "package.json")
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return set()
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return set(scripts) if isinstance(scripts, dict) else set()


def cited_script(span: str) -> str | None:
    """The package script a command span runs, or None when it runs no script."""
    match = SCRIPT_CALL.match(span)
    if not match:
        return None
    explicit, name = match.groups()
    return name if explicit or name in SHORTCUT_SCRIPTS else None


def check_commands(lines: list[str], folder: Path) -> list[str]:
    """Every `make X` and package script the file cites must exist in the repo."""
    failures: list[str] = []
    make = makefile_targets(folder)
    scripts = package_scripts(folder)
    for number, line in enumerate(lines, start=1):
        for span in code_spans(line):
            if "{{" in span:
                continue
            words = span.split()
            if len(words) >= 2 and words[0] == "make":
                if make is None:
                    failures.append(f"line {number}: `{span}` cites make but there is no Makefile")
                elif words[1] not in make:
                    failures.append(f"line {number}: `{span}`: no target '{words[1]}' in Makefile")
            script = cited_script(span)
            if script is None:
                continue
            if scripts is None:
                failures.append(f"line {number}: `{span}` cites a script but no package.json")
            elif script not in scripts:
                failures.append(f"line {number}: `{span}`: no script '{script}' in package.json")
    return failures


def check_links(lines: list[str], base: Path) -> list[str]:
    """Relative markdown links must point at files that exist."""
    failures: list[str] = []
    for number, line in enumerate(lines, start=1):
        for target in re.findall(r"\]\(([^)\s]+)\)", line):
            if re.match(r"^(?:[a-z][a-z0-9+.-]*:|#|\{\{)", target, re.I):
                continue
            if not (base / target.split("#", 1)[0]).exists():
                failures.append(f"line {number}: '{target}' does not exist relative to {base}")
    return failures


def check(path: Path) -> tuple[list[str], list[str]]:
    """Return (failures, notes) for the AGENTS.md at `path`."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.splitlines()
    base = path.resolve().parent
    failures: list[str] = []
    notes: list[str] = []

    if len(raw) > MAX_BYTES:
        failures.append(
            f"{len(raw):,} bytes; Codex reads at most {MAX_BYTES:,} by default and cuts the rest. "
            "Link to the document that owns the detail or move it to an area AGENTS.md."
        )
    for number, line in enumerate(lines, start=1):
        if "{{" in line or "}}" in line or "<!--" in line:
            failures.append(f"line {number}: template placeholder or comment left in the file")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                failures.append(f"line {number}: looks like a {name}; remove it and rotate it")
        if PERSONAL_PATH.search(line):
            failures.append(f"line {number}: machine-specific path; use a repo-relative path")

    found = headings(lines)
    for key, meaning in REQUIRED_HEADINGS.items():
        if not any(key in h for h in found):
            failures.append(f"missing {meaning}")
    if not re.search(r"pull request|merge request", text, re.I):
        failures.append("the landing rule never mentions a pull request or merge request")

    failures += check_commands(lines, base)
    failures += check_links(lines, base)

    unknown = sum(ln.count("UNKNOWN") for ln in lines)
    if unknown:
        notes.append(f"{unknown} UNKNOWN left for a person to fill in")
    if (base / "CLAUDE.md").is_file() and "CLAUDE.md" not in text:
        notes.append("CLAUDE.md exists here; name it under Where the rules live instead of copying")
    return failures, notes


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) > 2:
        print(
            "check_agents_md.py: takes at most one argument, the AGENTS.md path.", file=sys.stderr
        )
        return 2
    path = Path(argv[1]) if len(argv) == 2 else Path("AGENTS.md")
    try:
        failures, notes = check(path)
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"check_agents_md.py: cannot read {path}: {exc}. Pass the path to a UTF-8 AGENTS.md.",
            file=sys.stderr,
        )
        return 2
    for note in notes:
        print(f"NOTE: {note}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"{path}: {len(failures)} failure(s), {len(notes)} note(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
