#!/usr/bin/env python3
"""Turn a model tier (fast / workhorse / frontier) into a slug this account really has.

The Codex prompts in this pack describe work by tier and call this script, so no prompt
carries a model slug that can go stale. The live catalog decides: a model counts for a tier
when it is listed, is not being upgraded away, and its description names the tier
("workhorse", "frontier", "fast"); descriptions that start with Older / Previous / Legacy
are skipped, and the newest version in the slug wins (then "Latest" in the description, then
the catalog's own priority). A new release therefore resolves with no edit here.
PREFERRED_MODELS below is only the fallback, for a catalog that cannot classify a tier or is
unreachable, and a note says whenever the catalog's pick differs from its first slug.

    resolve_model.py TIER [--effort LEVEL]   resolve one tier to a JSON object on stdout
    resolve_model.py --all                   all three tiers at their default efforts, as one
                                             JSON object {"fast": {...}, "workhorse": {...},
                                             "frontier": {...}}: one call instead of three
    resolve_model.py --list                  print the account's catalog
    resolve_model.py --check FILE [FILE ...] validate Codex custom-agent TOML files

TIER is fast|workhorse|frontier, or the same word as a ticket label
(`model:fast|model:workhorse|model:frontier`). The Claude names haiku|sonnet|opus and the
labels `model:haiku|model:sonnet|model:opus` are accepted as aliases for the same three tiers,
so a board that labels tickets with either vocabulary resolves.

Catalog sources, in order: `codex debug models` (run with `codex` on PATH, else
$CODEX_CLI_PATH, else the CLI bundled in the ChatGPT desktop app), then
$CODEX_HOME/models_cache.json, then a fallback that returns the first preference
unverified. The binary goes first because the cache file is shared by
every Codex client on the machine and holds whichever one wrote it last: measured
2026-10-06, a 0.151.0 client and a 0.158.0 client overwrote it within a minute of each
other, and only 0.158.0 listed the gpt-6 models. The binary answers in about 20 ms (and
refreshes the cache file as a side effect).
Exit codes: 0 ok, 1 --check found an error, 2 bad arguments, 3 a real catalog has no
model for the tier.

Stdlib only, so it runs under any Python 3.11+ (--check needs tomllib; resolving alone
works on older interpreters).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Fallback model slugs, used only when the catalog cannot name a model for a tier. Source:
# OpenAI's Codex "Models" and "Subagents" docs, fetched 2026-10-06. Rule: the first slug
# listed that the account actually has wins, so a newer model goes at the front of its list
# and older accounts keep working.
PREFERRED_MODELS: dict[str, tuple[str, ...]] = {
    "frontier": ("gpt-6-astra",),
    "workhorse": ("gpt-6.1-sol", "gpt-6-sol", "gpt-5.6-sol"),
    "fast": ("gpt-6-luna", "gpt-5.6-luna"),
}

# Starting reasoning effort per tier. Source: the same docs (fetched 2026-10-06). This is the
# pack's own choice and does not follow the catalog's per-model default (gpt-6.1-sol: low,
# gpt-6-sol: medium): Astra starts at low, the workhorse Sol at medium, Luna at high.
DEFAULT_EFFORT: dict[str, str] = {"frontier": "low", "workhorse": "medium", "fast": "high"}

# Aliases for boards that label tickets with Claude tier names; map them onto ours. The
# primary names (fast / workhorse / frontier) need no entry, and a `model:` prefix is
# accepted in front of either vocabulary.
TIER_ALIASES: dict[str, str] = {"haiku": "fast", "sonnet": "workhorse", "opus": "frontier"}

# Weakest to strongest. A level outside this list cannot be ordered, so it can be neither
# clamped to nor compared and is dropped when the catalog is read.
EFFORT_ORDER: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)
_RANK = {level: i for i, level in enumerate(EFFORT_ORDER)}

# How the catalog's description wording maps to a tier, checked in this order (read from the
# live catalog 2026-10-08: "Latest workhorse model...", "Frontier intelligence...", "Fast and
# affordable model..."). A description that matches none of them leaves the model unclassified.
_TIER_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("workhorse", re.compile(r"\bworkhorse\b", re.IGNORECASE)),
    ("frontier", re.compile(r"\bfrontier\b", re.IGNORECASE)),
    ("fast", re.compile(r"\bfast\b", re.IGNORECASE)),
)
# "Older generation...", "Previous generation...", "Legacy coding model." Never the newest.
_SUPERSEDED = re.compile(r"^\s*(older|previous|legacy)\b", re.IGNORECASE)
# gpt-6.1-sol -> (6, 1); gpt-6-sol -> (6, 0).
_SLUG_VERSION = re.compile(r"^gpt-(\d+)(?:\.(\d+))?-")
_LATEST_PRIORITY = 10**9  # sorts a model with no catalog priority last

EXIT_CHECK_ERROR = 1
EXIT_USAGE = 2
EXIT_NO_MODEL = 3

_CODEX_TIMEOUT_S = 30

# The ChatGPT desktop app ships the Codex CLI here, and a Codex session's shell exposes
# neither it on PATH nor $CODEX_CLI_PATH (measured 2026-10-06); used only if it is runnable.
BUNDLED_CODEX_APP = Path(
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
)


@dataclass(frozen=True)
class ModelInfo:
    slug: str
    efforts: tuple[str, ...]  # supported levels, weakest first
    default_effort: str | None
    visibility: str | None
    description: str = ""
    priority: int | None = None  # the catalog's own display order; lowest is first
    upgrading: bool = False  # the catalog names a successor: this model is being retired


@dataclass
class Catalog:
    source: str  # "models_cache" | "codex_debug_models" | "fallback"
    models: dict[str, ModelInfo] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # why an earlier source was skipped

    @property
    def verified(self) -> bool:
        return self.source != "fallback"


def parse_catalog(payload: object) -> dict[str, ModelInfo] | None:
    """Read the `{"models": [...]}` shape Codex emits; None when it is not that shape."""
    if not isinstance(payload, dict):
        return None
    entries = payload.get("models")
    if not isinstance(entries, list):
        return None
    models: dict[str, ModelInfo] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        levels = entry.get("supported_reasoning_levels")
        if not isinstance(slug, str) or not isinstance(levels, list):
            continue
        efforts = {
            level["effort"]
            for level in levels
            if isinstance(level, dict)
            and isinstance(level.get("effort"), str)
            and level["effort"] in _RANK
        }
        if not efforts:
            continue
        default = entry.get("default_reasoning_level")
        visibility = entry.get("visibility")
        description = entry.get("description")
        priority = entry.get("priority")
        models[slug] = ModelInfo(
            slug=slug,
            efforts=tuple(sorted(efforts, key=_RANK.__getitem__)),
            default_effort=default if isinstance(default, str) else None,
            visibility=visibility if isinstance(visibility, str) else None,
            description=description if isinstance(description, str) else "",
            priority=priority
            if isinstance(priority, int) and not isinstance(priority, bool)
            else None,
            upgrading=bool(entry.get("upgrade")),
        )
    return models or None


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _runnable(path: str | Path) -> bool:
    return Path(path).is_file() and os.access(path, os.X_OK)


def _codex_binary() -> str | None:
    """`codex` on PATH, else $CODEX_CLI_PATH, else the desktop app's bundled copy."""
    found = shutil.which("codex")
    if found:
        return found
    override = os.environ.get("CODEX_CLI_PATH")
    if override and _runnable(override):
        return override
    return str(BUNDLED_CODEX_APP) if _runnable(BUNDLED_CODEX_APP) else None


def _read_cache() -> tuple[dict[str, ModelInfo] | None, str | None]:
    path = codex_home() / "models_cache.json"
    if not path.exists():
        return None, None
    try:
        models = parse_catalog(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        models = None
    if models is None:
        return None, f"{path} is unreadable or not a model catalog"
    return models, None


def _run_codex() -> tuple[dict[str, ModelInfo] | None, str | None]:
    binary = _codex_binary()
    if binary is None:
        return None, None
    try:
        done = subprocess.run(
            [binary, "debug", "models"],
            capture_output=True,
            text=True,
            timeout=_CODEX_TIMEOUT_S,
            check=False,
        )
        models = parse_catalog(json.loads(done.stdout)) if done.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        models = None
    if models is None:
        return None, f"`{binary} debug models` did not return a model catalog"
    return models, None


def load_catalog() -> Catalog:
    notes: list[str] = []
    for source, reader in (("codex_debug_models", _run_codex), ("models_cache", _read_cache)):
        models, problem = reader()
        if problem:
            notes.append(f"{problem}; trying the next catalog source")
        if models is not None:
            return Catalog(source=source, models=models, notes=notes)
    notes.append("no model catalog is available, so the slug below is unverified")
    return Catalog(source="fallback", notes=notes)


def normalize_tier(raw: str) -> str | None:
    name = raw.strip().lower().removeprefix("model:")
    name = TIER_ALIASES.get(name, name)
    return name if name in PREFERRED_MODELS else None


def valid_tier_names() -> str:
    names = [*PREFERRED_MODELS, *TIER_ALIASES]
    return ", ".join([*names, *(f"model:{name}" for name in names)])


def clamp_effort(requested: str, supported: tuple[str, ...]) -> str:
    """Nearest supported level to `requested`; a tie goes to the lower level."""
    return min(supported, key=lambda level: (abs(_RANK[level] - _RANK[requested]), _RANK[level]))


def infer_tier(description: str) -> str | None:
    """The tier a catalog description names, whatever the model's age; None if it names none."""
    return next((tier for tier, word in _TIER_WORDS if word.search(description)), None)


def slug_version(slug: str) -> tuple[int, int]:
    match = _SLUG_VERSION.match(slug)
    return (int(match[1]), int(match[2] or 0)) if match else (0, 0)


def _newest_first(info: ModelInfo) -> tuple[int, int, bool, int, str]:
    major, minor = slug_version(info.slug)
    priority = _LATEST_PRIORITY if info.priority is None else info.priority
    return (-major, -minor, "latest" not in info.description.lower(), priority, info.slug)


def _is_candidate(info: ModelInfo) -> bool:
    """Listed, not being retired, and not described as older than the current generation."""
    return (
        info.visibility == "list" and not info.upgrading and not _SUPERSEDED.match(info.description)
    )


def catalog_pick(tier: str, catalog: Catalog) -> ModelInfo | None:
    """The newest model the catalog itself files under `tier`; None if it files none there."""
    candidates = [
        info
        for info in catalog.models.values()
        if _is_candidate(info) and infer_tier(info.description) == tier
    ]
    return min(candidates, key=_newest_first) if candidates else None


def tier_of(slug: str, catalog: Catalog) -> str | None:
    """The tier of a slug: what its catalog description says, else the hard-coded lists."""
    info = catalog.models.get(slug)
    named = infer_tier(info.description) if info else None
    return named or next((t for t, slugs in PREFERRED_MODELS.items() if slug in slugs), None)


def _unclassified_notes(catalog: Catalog) -> list[str]:
    """A visible, current model whose description names no tier: a release worth a look."""
    return [
        f"unclassified visible model {info.slug}: its description names no tier"
        for info in catalog.models.values()
        if _is_candidate(info) and info.description and infer_tier(info.description) is None
    ]


def choose(tier: str, catalog: Catalog) -> tuple[ModelInfo | None, list[str]]:
    """The model for `tier` and the notes that explain how it was chosen.

    The catalog's classification comes first; the hard-coded preference list is the fallback
    for a tier the catalog cannot classify (including a catalog whose entries carry no
    description at all).
    """
    preferences = PREFERRED_MODELS[tier]
    notes = _unclassified_notes(catalog)
    picked = catalog_pick(tier, catalog)
    if picked is not None:
        if picked.slug != preferences[0]:
            notes.append(
                f"catalog picks {picked.slug} for tier {tier}; "
                f"the hard-coded list leads with {preferences[0]}"
            )
        return picked, notes
    if any(info.description for info in catalog.models.values()):
        notes.append(f"catalog names no current model for tier {tier}; using the hard-coded list")
    for position, slug in enumerate(preferences):
        info = catalog.models.get(slug)
        if info is not None:
            notes.extend(
                f"{missing} not available on this account; using {slug}"
                for missing in preferences[:position]
            )
            return info, notes
    return None, notes


def resolve(tier: str, requested: str | None, catalog: Catalog) -> tuple[dict[str, Any], int]:
    preferences = PREFERRED_MODELS[tier]
    wanted = requested or DEFAULT_EFFORT[tier]
    notes = list(catalog.notes)

    if not catalog.verified:
        result = {
            "tier": tier,
            "model": preferences[0],
            "effort": wanted,
            "supported_efforts": [],
            "source": catalog.source,
            "notes": notes,
        }
        return result, 0

    info, chosen_notes = choose(tier, catalog)
    notes.extend(chosen_notes)
    if info is None:
        tried = ", ".join(preferences)
        message = f"no model for tier {tier} in the {catalog.source} catalog; tried: {tried}"
        return {"error": message, "notes": notes}, EXIT_NO_MODEL

    effort = clamp_effort(wanted, info.efforts)
    if effort != wanted:
        label = "requested" if requested else "default"
        notes.append(f"{label} effort {wanted} is not supported by {info.slug}; using {effort}")
    result = {
        "tier": tier,
        "model": info.slug,
        "effort": effort,
        "supported_efforts": list(info.efforts),
        "source": catalog.source,
        "notes": notes,
    }
    return result, 0


def resolve_all(catalog: Catalog) -> int:
    """Every tier resolved against one catalog read; a tier the account lacks fails the lot."""
    results: dict[str, dict[str, Any]] = {}
    for tier in PREFERRED_MODELS:
        result, code = resolve(tier, None, catalog)
        if code:
            print(result["error"], file=sys.stderr)
            for note in result["notes"]:
                print(f"note: {note}", file=sys.stderr)
            return code
        results[tier] = result
    print(json.dumps(results))
    return 0


def list_catalog(catalog: Catalog) -> int:
    for note in catalog.notes:
        print(f"note: {note}", file=sys.stderr)
    if not catalog.verified:
        print("catalog unavailable (fallback); the preference lists are:")
        for tier, slugs in PREFERRED_MODELS.items():
            print(f"  {tier}: {', '.join(slugs)} (default effort {DEFAULT_EFFORT[tier]})")
        return 0
    print(f"source: {catalog.source}")
    print(f"{'slug':<22}{'tier':<11}{'visibility':<12}{'default':<9}efforts")
    for info in catalog.models.values():
        print(
            f"{info.slug:<22}{tier_of(info.slug, catalog) or '-':<11}{info.visibility or '-':<12}"
            f"{info.default_effort or '-':<9}{','.join(info.efforts)}"
        )
    return 0


def _check_one(path: Path, catalog: Catalog) -> list[tuple[str, str]]:
    """Findings for one agent file, as (level, message) with level error|warning."""
    import tomllib  # lazy: only --check needs it, and resolving works on older Pythons

    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [("error", f"cannot read as TOML: {exc}")]

    slug = config.get("model")
    effort = config.get("model_reasoning_effort")
    findings: list[tuple[str, str]] = []
    if slug is not None and not isinstance(slug, str):
        findings.append(("error", "model must be a string"))
        slug = None
    if effort is not None and not isinstance(effort, str):
        findings.append(("error", "model_reasoning_effort must be a string"))
        effort = None

    if slug is None:
        # No model set: the agent inherits its parent's, so only the effort's name can be judged.
        if effort is not None and effort not in _RANK:
            findings.append(("error", f"unknown effort {effort!r}"))
        return findings

    info = catalog.models.get(slug)
    if info is None:
        unknown = f"unknown model {slug!r} (not in the {catalog.source} catalog)"
        return [*findings, ("error", unknown)]
    if effort is not None and effort not in info.efforts:
        supported = ", ".join(info.efforts)
        findings.append(("error", f"effort {effort!r} is not supported by {slug} ({supported})"))

    tier = tier_of(slug, catalog)
    if tier:
        best, _ = choose(tier, catalog)
        if best is not None and slug_version(best.slug) > slug_version(slug):
            findings.append(("warning", f"stale: {best.slug} is now available for tier {tier}"))
    return findings


def check_files(paths: list[str], catalog: Catalog) -> int:
    for note in catalog.notes:
        print(f"note: {note}", file=sys.stderr)
    if not catalog.verified:
        print("catalog unavailable (fallback mode); slugs and efforts were not judged")
        return 0
    errors = warnings = 0
    for raw in paths:
        for level, message in _check_one(Path(raw), catalog):
            print(f"{raw}: {level}: {message}")
            errors += level == "error"
            warnings += level == "warning"
    print(f"checked {len(paths)} file(s): {errors} error(s), {warnings} warning(s)")
    return EXIT_CHECK_ERROR if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve a model tier to an available Codex model and effort.",
        epilog=f"tiers: {valid_tier_names()}",
    )
    parser.add_argument("tier", nargs="?", metavar="TIER")
    parser.add_argument("--effort", choices=EFFORT_ORDER, metavar="LEVEL")
    parser.add_argument(
        "--all",
        action="store_true",
        help="resolve every tier at its default effort, as one JSON object",
    )
    parser.add_argument("--list", action="store_true", help="print the account's catalog")
    parser.add_argument("--check", nargs="+", metavar="FILE", help="validate agent TOML files")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    modes = [bool(args.tier), args.all, args.list, bool(args.check)]
    if sum(modes) != 1:
        parser.error("give exactly one of TIER, --all, --list or --check")
    if args.effort and not args.tier:
        parser.error("--effort goes with a TIER")

    if args.check:
        try:
            import tomllib  # noqa: F401
        except ModuleNotFoundError:
            print("--check needs Python 3.11+ (tomllib); run it with python3.12", file=sys.stderr)
            return EXIT_USAGE
        return check_files(args.check, load_catalog())
    if args.list:
        return list_catalog(load_catalog())
    if args.all:
        return resolve_all(load_catalog())

    tier = normalize_tier(args.tier)
    if tier is None:
        parser.error(f"unknown tier {args.tier!r}; valid values: {valid_tier_names()}")
    result, code = resolve(tier, args.effort, load_catalog())
    if code:
        print(result["error"], file=sys.stderr)
        for note in result["notes"]:
            print(f"note: {note}", file=sys.stderr)
        return code
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
