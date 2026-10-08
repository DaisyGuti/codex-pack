#!/usr/bin/env python3
"""Mechanical checks on every skill under skills/, from the Agent Skills spec and Codex's
build-skills page (https://agentskills.io/specification, https://learn.chatgpt.com/docs/build-skills).

    uv run python scripts/check_skills.py [--skills DIR] [--codex-home DIR]

Two kinds of finding, each printed as `LEVEL skill RULE detail`:

  FAIL  the spec says MUST (or Codex cannot load the skill). Exit status 1.
  warn  a recommendation or a heuristic. Printed, never fails the run.

Rule ids follow the "Testable checks" table of the skill-authoring research:

  FAIL  T1  SKILL.md exists                    T2  frontmatter is present and parses as YAML
        T3  name present                       T4  name is 1-64 characters
        T5  name is lowercase letters, digits and single hyphens
        T6  name equals the directory name     T7  description present and non-empty
        T8  description is at most 1024 characters
        T9  compatibility is 1-500 characters  T10 metadata maps strings to strings
        T11 allowed-tools is one string        T20 agents/openai.yaml parses, with only the
        keys interface / policy / dependencies T22 policy.allow_implicit_invocation is a boolean
        T23 icon_small / icon_large paths exist  T29 no two skills share a name
  warn  T13 unknown frontmatter key            T14 body under 500 lines
        T15 body under about 5000 tokens       T16 relative links and backticked paths resolve
        T18 every file in scripts/ is mentioned in SKILL.md
        T21 unknown interface key in openai.yaml  T24 brand_color is #RRGGBB
        T26 description says when to use it    T27 the use case comes first (first sentence
        under 150 characters)                  T28 description names a boundary
        T30 catalog budget: name + description + path over 8,000 characters

T26-T28 are heuristics on the description's wording and will have false positives.

T30 is printed as a budget line even when under. Codex lists every installed skill's name,
description and path at startup in at most 2% of the model's context window, or 8,000
characters when the window is unknown, and shortens descriptions first when over. The first
line counts the pack's own skills at the path install.sh puts them (${CODEX_HOME}/skills/NAME/
SKILL.md); the second adds every other skill installed under ${CODEX_HOME:-~/.codex}/skills,
system skills included, when that directory exists.

Needs pyyaml, which is a dev dependency, so run it with `uv run`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATALOG_BUDGET_CHARS = 8000
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_BODY_LINES = 500
MAX_BODY_CHARS = 20_000  # about 5000 tokens at 4 characters a token
MAX_FIRST_SENTENCE = 150

FRONTMATTER_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
OPENAI_TOP_KEYS = {"interface", "policy", "dependencies"}
INTERFACE_KEYS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}

_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_BRAND_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BACKTICK_PATH = re.compile(r"`((?:references|scripts|assets|agents)/[^`\s]+)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_PLACEHOLDER = re.compile(r"[*<>{}$\[\]|]")
_TRIGGER = re.compile(
    r"\buse\b(?:\s+(?:this skill|it|me))?\s+(?:when|for|whenever|if|to|after|before|while)\b"
    r"|\btriggers?\s+(?:on|when)\b|\bwhen\s+(?:the user|you)\b",
    re.IGNORECASE,
)
_BOUNDARY = re.compile(r"\bnot\b|n't\b|\binstead\b|\bnever\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


@dataclass(frozen=True)
class Finding:
    level: str  # "FAIL" | "warn"
    skill: str
    rule: str
    detail: str

    def line(self) -> str:
        return f"{self.level} {self.skill} {self.rule} {self.detail}"


@dataclass
class Skill:
    directory: Path
    frontmatter: dict[str, Any] | None = None
    body: str = ""
    text: str = ""
    findings: list[Finding] = field(default_factory=list)

    @property
    def dirname(self) -> str:
        return self.directory.name

    def fail(self, rule: str, detail: str) -> None:
        self.findings.append(Finding("FAIL", self.dirname, rule, detail))

    def warn(self, rule: str, detail: str) -> None:
        self.findings.append(Finding("warn", self.dirname, rule, detail))

    def field_text(self, key: str) -> str | None:
        value = (self.frontmatter or {}).get(key)
        return value if isinstance(value, str) else None


# --- reading a skill ----------------------------------------------------------------------


def read_skill(directory: Path) -> Skill:
    """Load SKILL.md and split its frontmatter from the body; T1 and T2."""
    skill = Skill(directory)
    path = directory / "SKILL.md"
    if not path.is_file():
        skill.fail("T1", "SKILL.md is missing")
        return skill
    skill.text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(skill.text)
    if match is None:
        skill.fail("T2", "SKILL.md does not open with a --- frontmatter block closed by ---")
        skill.body = skill.text
        return skill
    skill.body = skill.text[match.end() :]
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        reason = " ".join(str(exc).split())
        skill.fail(
            "T2", f"frontmatter is not valid YAML (quote a value that holds a colon): {reason}"
        )
        return skill
    if not isinstance(loaded, dict):
        skill.fail("T2", "frontmatter is not a mapping of keys to values")
        return skill
    skill.frontmatter = loaded
    return skill


# --- frontmatter (T3-T13) -----------------------------------------------------------------


def check_frontmatter(skill: Skill) -> None:
    meta = skill.frontmatter
    if meta is None:
        return

    name = meta.get("name")
    if name in (None, ""):
        skill.fail("T3", "name is missing")
    elif not isinstance(name, str):
        skill.fail("T5", f"name must be a string, not {type(name).__name__}")
    else:
        if not 1 <= len(name) <= MAX_NAME:
            skill.fail("T4", f"name is {len(name)} characters; the limit is {MAX_NAME}")
        if not _NAME.match(name):
            skill.fail("T5", f"name {name!r} must be lowercase letters, digits and single hyphens")
        if name != skill.dirname:
            skill.fail("T6", f"name {name!r} must equal the directory name {skill.dirname!r}")

    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        skill.fail("T7", "description is missing or empty")
    elif len(description) > MAX_DESCRIPTION:
        skill.fail(
            "T8", f"description is {len(description)} characters; the limit is {MAX_DESCRIPTION}"
        )

    if "compatibility" in meta:
        compatibility = meta["compatibility"]
        if not isinstance(compatibility, str) or not 1 <= len(compatibility) <= MAX_COMPATIBILITY:
            skill.fail("T9", f"compatibility must be a string of 1-{MAX_COMPATIBILITY} characters")
    if "metadata" in meta:
        pairs = meta["metadata"]
        if not isinstance(pairs, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in pairs.items()
        ):
            skill.fail("T10", "metadata must map string keys to string values")
    if "allowed-tools" in meta and not isinstance(meta["allowed-tools"], str):
        skill.fail("T11", "allowed-tools must be one space-separated string")

    unknown = sorted(str(key) for key in meta if key not in FRONTMATTER_KEYS)
    if unknown:
        skill.warn("T13", f"frontmatter key(s) outside the spec: {', '.join(unknown)}")


# --- body and links (T14-T16, T18) ------------------------------------------------------


def _referenced_paths(body: str) -> list[str]:
    """Relative paths a SKILL.md body points at, from markdown links and backticked
    references/ scripts/ assets/ agents/ paths. Fenced code is skipped: it shows examples."""
    prose = _FENCE.sub("", body)
    found = _MD_LINK.findall(prose) + _BACKTICK_PATH.findall(prose)
    paths: list[str] = []
    for raw in found:
        target = raw.split("#", 1)[0].split("?", 1)[0].rstrip(".,:;)")
        if not target or _SCHEME.match(target) or target.startswith(("/", "~")):
            continue
        if _PLACEHOLDER.search(target):
            continue
        paths.append(target)
    return list(dict.fromkeys(paths))


def check_body(skill: Skill) -> None:
    if skill.frontmatter is None and not skill.text:
        return
    lines = len(skill.body.splitlines())
    if lines >= MAX_BODY_LINES:
        skill.warn("T14", f"body is {lines} lines; keep it under {MAX_BODY_LINES}")
    if len(skill.body) >= MAX_BODY_CHARS:
        skill.warn(
            "T15",
            f"body is about {len(skill.body) // 4} tokens; keep it under about 5000",
        )

    for target in _referenced_paths(skill.body):
        if not (skill.directory / target).exists():  # exists() follows symlinks
            skill.warn("T16", f"{target} is referenced in SKILL.md but does not resolve")

    scripts = skill.directory / "scripts"
    if scripts.is_dir():
        for entry in sorted(scripts.iterdir()):
            if entry.is_file() and not entry.name.startswith(".") and entry.name not in skill.text:
                skill.warn("T18", f"scripts/{entry.name} is not mentioned in SKILL.md")


# --- description heuristics (T26-T28) -----------------------------------------------------


def check_description(skill: Skill, other_names: list[str]) -> None:
    description = skill.field_text("description")
    if not description or not description.strip():
        return
    text = " ".join(description.split())
    if not _TRIGGER.search(text):
        skill.warn("T26", "description does not say when to use the skill (no 'Use when ...')")
    end = _SENTENCE_END.search(text)
    first = end.end() if end else len(text)
    if first > MAX_FIRST_SENTENCE:
        skill.warn(
            "T27",
            f"first sentence is {first} characters; put the use case within the first "
            f"{MAX_FIRST_SENTENCE}, because Codex shortens descriptions",
        )
    names_neighbor = any(re.search(rf"\b{re.escape(n)}\b", text) for n in other_names)
    if not _BOUNDARY.search(text) and not names_neighbor:
        skill.warn(
            "T28", "description names no boundary (what it is not for, or a neighbouring skill)"
        )


# --- agents/openai.yaml (T20-T24) ---------------------------------------------------------


def check_openai_yaml(skill: Skill) -> None:
    path = skill.directory / "agents" / "openai.yaml"
    if not path.is_file():
        return
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        skill.fail("T20", f"agents/openai.yaml is not valid YAML: {' '.join(str(exc).split())}")
        return
    if config is None:
        config = {}
    if not isinstance(config, dict):
        skill.fail("T20", "agents/openai.yaml is not a mapping")
        return

    unknown = sorted(str(key) for key in config if key not in OPENAI_TOP_KEYS)
    if unknown:
        skill.fail(
            "T20",
            f"agents/openai.yaml key(s) {', '.join(unknown)} are not "
            "interface, policy or dependencies",
        )

    policy = config.get("policy")
    if policy is not None:
        if not isinstance(policy, dict):
            skill.fail("T22", "policy must be a mapping")
        elif "allow_implicit_invocation" in policy and not isinstance(
            policy["allow_implicit_invocation"], bool
        ):
            skill.fail("T22", "policy.allow_implicit_invocation must be true or false")

    interface = config.get("interface")
    if interface is None:
        return
    if not isinstance(interface, dict):
        skill.fail("T20", "interface must be a mapping")
        return
    extra = sorted(str(key) for key in interface if key not in INTERFACE_KEYS)
    if extra:
        skill.warn("T21", f"interface key(s) outside the documented set: {', '.join(extra)}")
    for key in ("icon_small", "icon_large"):
        icon = interface.get(key)
        if icon is None:
            continue
        if not isinstance(icon, str) or not (skill.directory / icon).exists():
            skill.fail("T23", f"interface.{key} {icon!r} does not exist relative to the skill")
    color = interface.get("brand_color")
    if color is not None and not (isinstance(color, str) and _BRAND_COLOR.match(color)):
        skill.warn("T24", f"interface.brand_color {color!r} is not #RRGGBB")


# --- across skills (T29, T30) -------------------------------------------------------------


def check_unique_names(skills: list[Skill]) -> list[Finding]:
    owners: dict[str, list[str]] = {}
    for skill in skills:
        name = skill.field_text("name")
        if name:
            owners.setdefault(name, []).append(skill.dirname)
    return [
        Finding("FAIL", ", ".join(dirs), "T29", f"{len(dirs)} skills share the name {name!r}")
        for name, dirs in owners.items()
        if len(dirs) > 1
    ]


def catalog_cost(name: str, description: str, path: str) -> int:
    return len(name) + len(description) + len(path)


def _installed_skill_dirs(codex_home: Path, own: Path) -> list[Path]:
    """Skills under ${CODEX_HOME}/skills and its .system, minus links back into this pack."""
    roots = [codex_home / "skills", codex_home / "skills" / ".system"]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.name.startswith(".") or not (entry / "SKILL.md").is_file():
                continue
            if not entry.resolve().is_relative_to(own):
                found.append(entry)
    return found


def _frontmatter_of(path: Path) -> dict[str, Any] | None:
    try:
        match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
        loaded = yaml.safe_load(match.group(1)) if match else None
    except (OSError, yaml.YAMLError):
        return None
    return loaded if isinstance(loaded, dict) else None


def budget_report(
    skills: list[Skill], skills_dir: Path, codex_home: Path
) -> tuple[list[str], list[Finding]]:
    """The T30 lines to print and any warnings. Descriptions are folded to one line, as they
    are when a client lists them."""
    pack_costs: dict[str, int] = {}
    for skill in skills:
        name = skill.field_text("name") or skill.dirname
        description = " ".join((skill.field_text("description") or "").split())
        path = str(codex_home / "skills" / skill.dirname / "SKILL.md")
        pack_costs[skill.dirname] = catalog_cost(name, description, path)
    pack_total = sum(pack_costs.values())

    others = 0
    other_count = 0
    unreadable = 0
    for directory in _installed_skill_dirs(codex_home, skills_dir.resolve()):
        meta = _frontmatter_of(directory / "SKILL.md")
        if meta is None:
            unreadable += 1
            continue
        declared = meta.get("name")
        installed_name = declared if isinstance(declared, str) else directory.name
        description = " ".join(str(meta.get("description") or "").split())
        others += catalog_cost(installed_name, description, str(directory / "SKILL.md"))
        other_count += 1

    lines = [
        f"catalog budget: this pack's {len(skills)} skills use {pack_total:,} of "
        f"{CATALOG_BUDGET_CHARS:,} characters (name + description + path)"
    ]
    findings: list[Finding] = []
    if pack_total > CATALOG_BUDGET_CHARS:
        heaviest = sorted(pack_costs.items(), key=lambda item: -item[1])
        share = ", ".join(f"{name} {cost:,}" for name, cost in heaviest)
        findings.append(
            Finding(
                "warn",
                "(pack)",
                "T30",
                f"over {CATALOG_BUDGET_CHARS:,} characters; per skill: {share}",
            )
        )
    if (codex_home / "skills").is_dir():
        both = pack_total + others
        skipped = f"; {unreadable} installed skill(s) could not be read" if unreadable else ""
        lines.append(
            f"catalog budget: with the {other_count} other skills installed under "
            f"{codex_home / 'skills'} (system skills included) the total is {both:,} of "
            f"{CATALOG_BUDGET_CHARS:,} characters{skipped}"
        )
        if both > CATALOG_BUDGET_CHARS:
            findings.append(
                Finding(
                    "warn",
                    "(installed)",
                    "T30",
                    f"pack plus installed skills use {both:,} of "
                    f"{CATALOG_BUDGET_CHARS:,} characters",
                )
            )
    return lines, findings


# --- driver -------------------------------------------------------------------------------


def check_pack(skills_dir: Path, codex_home: Path) -> tuple[list[Finding], list[str], int]:
    """(findings, budget lines, number of skills checked)."""
    directories = sorted(
        p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    skills = [read_skill(d) for d in directories]
    names = [s.field_text("name") or s.dirname for s in skills]
    for skill in skills:
        check_frontmatter(skill)
        check_body(skill)
        check_description(
            skill, [n for n in names if n != (skill.field_text("name") or skill.dirname)]
        )
        check_openai_yaml(skill)
    findings = [f for skill in skills for f in skill.findings] + check_unique_names(skills)
    lines, budget_findings = budget_report(skills, skills_dir, codex_home)
    return findings + budget_findings, lines, len(skills)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Check every skill against the Agent Skills spec.")
    parser.add_argument("--skills", type=Path, default=root / "skills", metavar="DIR")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"),
        metavar="DIR",
        help="where installed skills are counted for the catalog budget "
        "(default $CODEX_HOME or ~/.codex)",
    )
    args = parser.parse_args(argv)
    if not args.skills.is_dir():
        print(f"FAIL: no skills directory at {args.skills}", file=sys.stderr)
        return 1

    findings, budget, checked = check_pack(args.skills, args.codex_home)
    for finding in findings:
        print(finding.line())
    for line in budget:
        print(line)
    failures = sum(f.level == "FAIL" for f in findings)
    warnings = len(findings) - failures
    print(f"checked {checked} skill(s): {failures} failure(s), {warnings} warning(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
