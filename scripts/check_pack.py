#!/usr/bin/env python3
"""Structural checks on the pack itself: its agent files, the paths its instructions name, and
the text of every file in it. Every finding fails the run.

    python3 scripts/check_pack.py [--root DIR]

Checks, each printed as `FAIL RULE where: detail`:

  agent-shape   every agents/*.toml parses, has a name equal to its file name, a description
                and developer_instructions, and sets neither `model` nor
                `model_reasoning_effort` (a value there overrides what a spawn asks for;
                measured 2026-10-07, see references/model-selection.md)
  read-only     agents/reviewer.toml and agents/forward_tester.toml set
                sandbox_mode = "read-only"
  path          every ${CODEX_HOME:-~/.codex}/skills/... path named in AGENTS.md, an agent
                file, a SKILL.md or a reference resolves to a file inside the pack
  hidden-char   no zero-width, bidirectional-control or tag character in a text file
  secret        no private-key header, API key or access token in a text file

The text checks cover every file git tracks plus every untracked file it does not ignore, so
a pasted token fails the gate before it reaches a commit. A finding names the file, the line
and the kind of match, never the matched text.

A check that matches nothing proves nothing, so the run also fails when it examined no agent
file, found no path to resolve, or listed no text file: that means the pattern or the
listing went blind.

Stdlib only; runs under any Python 3.12+.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REQUIRED_AGENT_KEYS = ("name", "description", "developer_instructions")
FORBIDDEN_AGENT_KEYS = ("model", "model_reasoning_effort")
READ_ONLY_AGENTS = ("reviewer", "forward_tester")

# The instruction files and references whose named paths must resolve. SKILL.md files are added
# by pack_doc_files() because they live one directory down.
_PATH_REFERENCE = re.compile(r"(?:\$\{CODEX_HOME:-~/\.codex\}|~/\.codex)/(skills/[^\s`'\")>\]]+)")
# Codex's own built-in skills ship inside Codex and are absent from this pack.
_NOT_IN_PACK = "skills/.system/"

# Characters a reader cannot see but a model reads, as inclusive code point ranges: soft
# hyphen, Arabic letter mark, Mongolian vowel separator, zero-width and joiner characters and
# the left-to-right and right-to-left marks, the bidirectional embeddings and overrides,
# invisible operators, bidirectional isolates, the byte-order mark, and the tag block used to
# hide text in a prompt. Code points rather than escapes, so no character is ever written out.
_HIDDEN_RANGES = (
    (0x00AD, 0x00AD),
    (0x061C, 0x061C),
    (0x180E, 0x180E),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0x2066, 0x2069),
    (0xFEFF, 0xFEFF),
    (0xE0000, 0xE007F),
)
_HIDDEN = re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _HIDDEN_RANGES) + "]")

# Each pattern is built so that its own source line does not match it.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "private key header": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "sk- API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})"),
    "GitLab token": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),
}


@dataclass(frozen=True)
class Finding:
    rule: str
    where: str
    detail: str

    def line(self) -> str:
        return f"FAIL {self.rule} {self.where}: {self.detail}"


# --- agent files -------------------------------------------------------------------------


def check_agents(root: Path) -> tuple[list[Finding], int]:
    """(findings, number of agent files examined)."""
    findings: list[Finding] = []
    files = sorted((root / "agents").glob("*.toml"))
    for path in files:
        where = f"agents/{path.name}"
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            findings.append(Finding("agent-shape", where, f"cannot be read as TOML: {error}"))
            continue
        for key in REQUIRED_AGENT_KEYS:
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                findings.append(Finding("agent-shape", where, f"`{key}` is missing or empty"))
        if isinstance(data.get("name"), str) and data["name"] != path.stem:
            findings.append(
                Finding("agent-shape", where, f"name {data['name']!r} differs from the file name")
            )
        for key in FORBIDDEN_AGENT_KEYS:
            if key in data:
                findings.append(
                    Finding("agent-shape", where, f"sets `{key}`, which overrides every spawn")
                )
    for name in READ_ONLY_AGENTS:
        path = root / "agents" / f"{name}.toml"
        if not path.is_file():
            findings.append(Finding("read-only", f"agents/{name}.toml", "the file is missing"))
            continue
        try:
            mode = tomllib.loads(path.read_text(encoding="utf-8")).get("sandbox_mode")
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue  # already reported by the shape check above
        if mode != "read-only":
            findings.append(
                Finding("read-only", f"agents/{name}.toml", 'sandbox_mode must be "read-only"')
            )
    return findings, len(files)


# --- paths named in instructions ---------------------------------------------------------


def pack_doc_files(root: Path) -> list[Path]:
    """Files whose named paths are checked: the global instructions, the agents, every
    SKILL.md and the markdown beside them."""
    files = [root / "AGENTS.md"]
    files += sorted((root / "agents").glob("*.toml"))
    files += sorted((root / "skills").glob("*/SKILL.md"))
    files += sorted((root / "skills").glob("*/references/*.md"))
    files += sorted((root / "skills").glob("*/assets/*.md"))
    files += sorted((root / "references").glob("*.md"))
    return [f for f in files if f.is_file() and not f.is_symlink()]


def check_paths(root: Path) -> tuple[list[Finding], int]:
    """(findings, number of paths examined)."""
    findings: list[Finding] = []
    examined = 0
    for doc in pack_doc_files(root):
        try:
            lines = doc.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            findings.append(Finding("path", str(doc.relative_to(root)), f"unreadable: {error}"))
            continue
        for number, line in enumerate(lines, start=1):
            for match in _PATH_REFERENCE.finditer(line):
                named = match.group(1).rstrip(".,;:")
                if named.startswith(_NOT_IN_PACK) or any(c in named for c in "*<{$"):
                    continue  # Codex's own skills, or a placeholder rather than a path
                examined += 1
                if not (root / named).exists():
                    where = f"{doc.relative_to(root)}:{number}"
                    findings.append(Finding("path", where, f"{named} does not exist in the pack"))
    return findings, examined


# --- text of every file ------------------------------------------------------------------


def listed_files(root: Path) -> list[Path]:
    """Tracked files plus untracked files git does not ignore; raises when git cannot list."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    names = sorted({n for n in out.decode("utf-8").split("\0") if n})
    return [root / n for n in names if (root / n).is_file() and not (root / n).is_symlink()]


def read_text_file(path: Path) -> str | None:
    """The file's text, or None for a binary file (a NUL byte or invalid UTF-8)."""
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def check_text(root: Path, files: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        text = read_text_file(path)
        if text is None:
            continue
        rel = path.relative_to(root)
        for number, line in enumerate(text.splitlines(), start=1):
            for match in _HIDDEN.finditer(line):
                code = f"U+{ord(match.group()):04X}"
                findings.append(Finding("hidden-char", f"{rel}:{number}", f"contains {code}"))
            for kind, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    findings.append(Finding("secret", f"{rel}:{number}", f"looks like a {kind}"))
    return findings


# --- driver ------------------------------------------------------------------------------


def run(root: Path) -> tuple[list[Finding], list[str]]:
    """(findings, one summary line per check)."""
    agent_findings, agents = check_agents(root)
    path_findings, paths = check_paths(root)
    files = listed_files(root)
    text_findings = check_text(root, files)
    findings = agent_findings + path_findings + text_findings

    # A check that examined nothing is blind, which is a failure of the check itself.
    for label, count in (("agent file", agents), ("named path", paths), ("text file", len(files))):
        if count == 0:
            findings.append(Finding("blind", "(pack)", f"no {label} was examined"))
    summary = [
        f"examined {agents} agent file(s), {paths} named path(s), {len(files)} listed file(s)"
    ]
    return findings, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the pack's own files.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        findings, summary = run(args.root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL cannot list the pack's files with git, so nothing was checked: {error}")
        return 1
    for finding in findings:
        print(finding.line())
    for line in summary:
        print(line)
    print(f"{len(findings)} failure(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
