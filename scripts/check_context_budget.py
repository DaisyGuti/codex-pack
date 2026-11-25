#!/usr/bin/env python3
"""Measure the AGENTS.md chain Codex loads before it starts work, and fail past a budget.

Codex builds its instructions once per run. It reads the global file in CODEX_HOME
(AGENTS.override.md when it is non-empty, otherwise AGENTS.md), then walks from the project
root down to the working folder and takes, in each folder, the first non-empty file of
AGENTS.override.md, AGENTS.md and the names in `project_doc_fallback_filenames`. Project files
stop being added once their combined size reaches `project_doc_max_bytes` (32 KiB by default),
so text past that cap never reaches the model. A guide that grows a little with every merge
request is never seen whole in a diff, but every run pays for all of it.

Usage:
    check_context_budget.py [ROOT] [--path FOLDER ...] [--all] [--json] [--write-baseline]

ROOT is the repo root (default: the current directory). Each --path is a folder inside ROOT;
the chain Codex loads when it starts there is counted, plus the global file. --all counts every
instruction file in the repo instead, without the global file, the total limit or the cap (no
run loads them all): the form a CI guard runs. Tokens are an estimate (bytes / 4).

The global file, the cap and the fallback names come from CODEX_HOME (default ~/.codex) and
its config.toml. Limits: 16 KiB per file and 32 KiB in total (the global file included),
unless ROOT/.context-budget.toml says otherwise:

    guide_bytes = 16384
    total_bytes = 32768
    [baseline]               # a ratchet: a file already over the limit is held at its size
    "backend/AGENTS.md" = 39000

A baselined file may not grow past its baseline, and a baseline above its file's size is stale
(exit 1) until `--write-baseline` lowers it. The total limit rises by the excess the baselines
already hold. `--write-baseline` lowers or adds baseline entries for the files now over the
limit and never raises one. A chain past Codex's cap always fails: no baseline holds it.

Exit codes: 0 within budget, 1 over budget, 2 usage error (bad root, path or config).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_git import git_argv, git_env  # noqa: E402

CONFIG_NAME = ".context-budget.toml"
DEFAULT_GUIDE_BYTES = 16_384  # about 4k tokens: room for a root guide and an area guide
DEFAULT_TOTAL_BYTES = 32_768  # Codex's default project_doc_max_bytes, global file included
DEFAULT_CODEX_CAP = 32_768  # project_doc_max_bytes when config.toml does not set it
BYTES_PER_TOKEN = 4  # a rough average for English prose and code; an estimate, not a count
OVERRIDE_NAME = "AGENTS.override.md"
AGENTS_NAME = "AGENTS.md"
# Folders --all never enters: dependencies and VCS data hold other people's guides.
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__"})


class UsageError(Exception):
    """Bad root, path or config; main turns it into exit code 2."""


@dataclass(frozen=True)
class Limits:
    guide_bytes: int
    total_bytes: int
    baseline: dict[str, int]


@dataclass(frozen=True)
class CodexConfig:
    home: Path
    cap: int  # project_doc_max_bytes
    names: tuple[str, ...]  # the per-folder lookup order, fallback names last


@dataclass(frozen=True)
class Entry:
    path: Path
    label: str  # the key a baseline uses: the path from the root, or the absolute path outside it
    kind: str  # "global" or "project"
    size: int


def whole_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def load_limits(root: Path) -> Limits:
    config = root / CONFIG_NAME
    if not config.is_file():
        return Limits(DEFAULT_GUIDE_BYTES, DEFAULT_TOTAL_BYTES, {})
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # ValueError: bad TOML or bytes that are not UTF-8
        raise UsageError(f"{config}: cannot read the config: {exc}") from exc
    guide = data.get("guide_bytes", DEFAULT_GUIDE_BYTES)
    total = data.get("total_bytes", DEFAULT_TOTAL_BYTES)
    baseline = data.get("baseline", {})
    if not (
        whole_number(guide)
        and whole_number(total)
        and isinstance(baseline, dict)
        and all(whole_number(v) for v in baseline.values())
    ):
        raise UsageError(
            f"{config}: guide_bytes and total_bytes must be whole numbers, and [baseline] a "
            'table of "path" = bytes'
        )
    return Limits(guide, total, {str(k): v for k, v in baseline.items()})


def load_codex_config() -> CodexConfig:
    """CODEX_HOME and the two discovery settings its config.toml may change."""
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    config = home / "config.toml"
    data: dict[str, Any] = {}
    if config.is_file():
        try:
            data = tomllib.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UsageError(f"{config}: cannot read Codex's config: {exc}") from exc
    cap = data.get("project_doc_max_bytes", DEFAULT_CODEX_CAP)
    fallback = data.get("project_doc_fallback_filenames", [])
    if not whole_number(cap) or not (
        isinstance(fallback, list) and all(isinstance(n, str) for n in fallback)
    ):
        raise UsageError(
            f"{config}: project_doc_max_bytes must be a whole number and "
            "project_doc_fallback_filenames a list of file names"
        )
    names = (
        OVERRIDE_NAME,
        AGENTS_NAME,
        *(n for n in fallback if n not in (OVERRIDE_NAME, AGENTS_NAME)),
    )
    return CodexConfig(home, cap, names)


def non_empty(path: Path) -> bool:
    """Codex skips a file with nothing but whitespace in it."""
    try:
        return path.is_file() and bool(path.read_bytes().strip())
    except OSError:
        return False


def first_guide(folder: Path, names: tuple[str, ...]) -> Path | None:
    """The one file Codex takes from a folder: the first non-empty name in lookup order."""
    return next((folder / n for n in names if non_empty(folder / n)), None)


def resolve_folder(root: Path, folder: str) -> Path:
    path = (root / folder).resolve()
    if path != root and root not in path.parents:
        raise UsageError(f"--path {folder}: not inside the repo root {root}; give a folder in it")
    if not path.is_dir():
        raise UsageError(f"--path {folder}: no such folder in {root}; check the spelling")
    return path


def chain(root: Path, folder: Path, names: tuple[str, ...]) -> list[Path]:
    """The project files Codex loads when it starts in `folder`, root first."""
    here = root
    folders = [root]
    for part in folder.relative_to(root).parts:
        here = here / part
        folders.append(here)
    return [g for f in folders if (g := first_guide(f, names))]


def repo_guides(root: Path, names: tuple[str, ...]) -> list[Path]:
    """Every instruction file in the repo, root first: tracked and unignored files in a git
    repo (fast, skips ignored dependencies), a walk otherwise."""
    # The repo is untrusted: its config must not run programs (core.fsmonitor, gpg.program).
    git = subprocess.run(
        git_argv(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        + [f"*{name}" for name in names],
        capture_output=True,
        check=False,
        env=git_env(),
    )
    if git.returncode == 0 and (root / ".git").exists():
        found = {
            root / rel
            for rel in git.stdout.decode().split("\0")
            if rel and Path(rel).name in names and not SKIP_DIRS.intersection(Path(rel).parts)
        }
    else:
        found = set()
        for here, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            found.update(Path(here) / f for f in files if f in names)
    order = {name: i for i, name in enumerate(names)}
    return sorted(
        (p for p in found if non_empty(p)),
        key=lambda p: (p.relative_to(root).parent.parts, order[p.name]),
    )


def make_entry(root: Path, path: Path, kind: str) -> Entry:
    path = path.resolve()
    label = path.relative_to(root).as_posix() if root in path.parents else str(path)
    return Entry(path, label, kind, path.stat().st_size)


def collect(
    root: Path, folders: list[Path], codex: CodexConfig, everything: bool = False
) -> tuple[list[Entry], list[dict[str, object]]]:
    """Every file loaded, each once, in load order, and each starting folder's chain."""
    if everything:
        return [make_entry(root, p, "project") for p in repo_guides(root, codex.names)], []
    entries: list[Entry] = []
    seen: set[Path] = set()
    glob = first_guide(codex.home, (OVERRIDE_NAME, AGENTS_NAME))
    if glob:
        entries.append(make_entry(root, glob, "global"))
        seen.add(glob.resolve())
    chains: list[dict[str, object]] = []
    for folder in folders or [root]:
        files = [p.resolve() for p in chain(root, folder, codex.names)]
        for path in files:
            if path not in seen:
                seen.add(path)
                entries.append(make_entry(root, path, "project"))
        size = sum(p.stat().st_size for p in files)
        chains.append(
            {
                "folder": folder.relative_to(root).as_posix(),
                "project_bytes": size,
                "cap": codex.cap,
                "cut_bytes": max(0, size - codex.cap),
            }
        )
    return entries, chains


def tokens(size: int) -> int:
    return -(-size // BYTES_PER_TOKEN)


def evaluate(
    entries: list[Entry], chains: list[dict[str, object]], limits: Limits, check_total: bool
) -> dict[str, object]:
    """Measure the entries against the limits; the JSON report main prints."""
    over = []
    for entry in entries:
        cap = limits.baseline.get(entry.label, limits.guide_bytes)
        if entry.size > cap:
            over.append(
                {
                    "path": entry.label,
                    "bytes": entry.size,
                    "limit": cap,
                    "over_by": entry.size - cap,
                    "baselined": entry.label in limits.baseline,
                }
            )
    # A baselined file over the guide limit is held where it is, so its excess is not new growth.
    held = sum(
        max(0, min(e.size, limits.baseline[e.label]) - limits.guide_bytes)
        for e in entries
        if e.label in limits.baseline
    )
    # A baseline above its file's size has not been lowered yet; failing here keeps a shrunk
    # file from growing back to its old size under a stale entry.
    stale = [
        {"path": e.label, "bytes": e.size, "baseline": limits.baseline[e.label]}
        for e in entries
        if e.label in limits.baseline and e.size < limits.baseline[e.label]
    ]
    total = sum(e.size for e in entries)
    total_over = max(0, total - limits.total_bytes - held) if check_total else 0
    cut = [c for c in chains if c["cut_bytes"]]
    return {
        "limits": {
            "guide_bytes": limits.guide_bytes,
            "total_bytes": limits.total_bytes,
            "held_by_baseline_bytes": held,
        },
        "token_estimate": f"bytes / {BYTES_PER_TOKEN}, an estimate",
        "files": [
            {"path": e.label, "kind": e.kind, "bytes": e.size, "tokens_est": tokens(e.size)}
            for e in entries
        ],
        "chains": chains,
        "total_bytes": total,
        "total_tokens_est": tokens(total),
        "large": [e.label for e in entries if e.size > limits.guide_bytes],
        "over_budget": over,
        "stale_baseline": stale,
        "total_over_by": total_over,
        "cut_by_codex": cut,
        "ok": not over and not stale and not total_over and not cut,
    }


def safe_label(label: str) -> bool:
    """A baseline key is a path inside the repo: relative, with no `..`."""
    path = Path(label)
    return not path.is_absolute() and ".." not in path.parts


def write_baseline(root: Path, entries: list[Entry], limits: Limits) -> None:
    """Hold each file now over the limit at its size; lower an entry, never raise one.

    An entry for a guide this run did not measure (it is still on disk) stays as it was.
    """
    config = root / CONFIG_NAME
    if config.is_symlink() or (config.exists() and root not in config.resolve().parents):
        raise UsageError(f"{config}: is a symlink or leaves the repo; replace it with a plain file")
    measured = {e.label for e in entries}
    new = {
        label: size
        for label, size in limits.baseline.items()
        if label not in measured and safe_label(label) and (root / label).is_file()
    }
    for e in entries:
        # A file outside the repo (the global AGENTS.md) is machine-specific: never held.
        if e.size > limits.guide_bytes and safe_label(e.label):
            new[e.label] = min(e.size, limits.baseline.get(e.label, e.size))
    lines = [f"guide_bytes = {limits.guide_bytes}", f"total_bytes = {limits.total_bytes}"]
    if new:
        lines += [
            "",
            "[baseline]",
            *(f"{json.dumps(k, ensure_ascii=False)} = {v}" for k, v in sorted(new.items())),
        ]
    # Write beside the target and swap it in, so a half-written file never replaces the config.
    fd, temp = tempfile.mkstemp(dir=root, prefix=CONFIG_NAME + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(temp, config)
    except BaseException:
        os.unlink(temp)
        raise


def render(report: dict[str, Any]) -> str:
    files = report["files"]
    out = ["Codex instruction files (tokens are an estimate: bytes / 4)"]
    out += [
        f"  {f['bytes']:>9,} B  ~{f['tokens_est']:>7,} tok  {f['kind']:<7} {f['path']}"
        for f in files
    ]
    if not files:
        out.append("  (no instruction files found)")
    out.append(f"  {report['total_bytes']:>9,} B  ~{report['total_tokens_est']:>7,} tok  total")
    limits = report["limits"]
    held = limits["held_by_baseline_bytes"]
    out.append(
        f"Limits: {limits['guide_bytes']:,} B per file, {limits['total_bytes']:,} B in total"
        + (f" (+{held:,} held by the baseline)" if held else "")
    )
    for item in report["over_budget"]:
        kind = "baseline" if item["baselined"] else "limit"
        out.append(
            f"OVER {item['path']}: {item['bytes']:,} B, {item['over_by']:,} B past its {kind} "
            f"of {item['limit']:,} B. Split it: move area detail into a guide the index links to."
        )
    if report["total_over_by"]:
        out.append(f"OVER total: {report['total_over_by']:,} B past the total limit.")
    out += [
        f"CUT {c['folder'] or '.'}: the project chain is {c['project_bytes']:,} B; Codex reads "
        f"{c['cap']:,} B (project_doc_max_bytes), so {c['cut_bytes']:,} B never reach the model."
        for c in report["cut_by_codex"]
    ]
    out += [
        f"STALE {item['path']}: {item['bytes']:,} B, baseline {item['baseline']:,} B. "
        "Lower it with --write-baseline."
        for item in report["stale_baseline"]
    ]
    out.append("Within budget." if report["ok"] else "Over budget.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("root", nargs="?", default=".", help="the repo root (default: .)")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        metavar="FOLDER",
        help="a folder in the repo Codex starts in (repeatable)",
    )
    parser.add_argument(
        "--all", action="store_true", help="count every instruction file in the repo"
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help=f"lower or add {CONFIG_NAME} baseline entries for files over the limit (never raises)",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits 2 on a usage error already
        return int(exc.code or 0)
    try:
        root = Path(args.root).resolve()
        if not root.is_dir():
            raise UsageError(f"{args.root}: not a folder; give the repo root")
        limits = load_limits(root)
        codex = load_codex_config()
        folders = [resolve_folder(root, f) for f in args.path]
        entries, chains = collect(root, folders, codex, args.all)
        if args.write_baseline:
            write_baseline(root, entries, limits)
            limits = load_limits(root)
    except (UsageError, OSError) as exc:
        print(f"check_context_budget.py: {exc}", file=sys.stderr)
        return 2
    report = evaluate(entries, chains, limits, check_total=not args.all)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
