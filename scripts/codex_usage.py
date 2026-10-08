#!/usr/bin/env python3
"""Per-run usage report, read from the records Codex already keeps. Never a second logger.

    codex_usage.py                       the last 10 runs, one compact table
    codex_usage.py --since 2026-10-07    every run from that local date on
    codex_usage.py --run 01a1168f        one row per thread of the matching run(s)
    codex_usage.py --summary             aggregate by skill and by model
    codex_usage.py --csv usage.csv       one row per thread, for a spreadsheet
    codex_usage.py --json                everything, machine-readable

Where the numbers come from, all under ${CODEX_HOME:-~/.codex} and all read-only:

  * state_N.sqlite (the highest N), table `threads`: one row per thread. A thread is one
    model conversation: a root, a subagent it spawned, or a Codex auto-review approver.
  * each thread's rollout JSONL (`threads.rollout_path`): cumulative token usage, the
    plan's 5-hour and weekly meters, the model, effort and speed in force, turn timings,
    and the tool calls and messages that show which skills ran.

A RUN is a root thread plus every descendant. An auto-review thread (model
`codex-auto-review`) has no parent id, so it is attributed to the one run that was in a
turn when it started; zero or several candidates leave it listed as unattributed.

A model the live Codex catalog lists but CREDIT_RATES lacks is warned about on stderr (and
at the end of --summary): its runs would show "n/a" credits. The only per-release edit this
script needs is the one new line in CREDIT_RATES.

Credits are an ESTIMATE from the published per-million-token rates in CREDIT_RATES, at
Standard speed, times 2.5 for Fast mode (a thread whose rollout records the "priority"
service tier; no record means Standard). A thread that switched model or speed partway is
priced at the last one it used and says so. A model with no rate (such as codex-auto-review)
reports tokens and "n/a" credits, never a guessed number. A trailing "+" on a run's
credits means some of its threads were n/a and are left out of the sum. The 5h / weekly
columns are changes in the plan's own meters, which are account-wide: a "!" marks a run
whose delta is unreliable because the window reset mid-run or another run overlapped it.
The first meter reading arrives after the run's first model call, so a delta undercounts
that one call.

A thread whose rollout is missing or unreadable falls back to the index's own token total
and is marked partial ("~"); its credits are n/a because input and output cannot be split.

Runs started with `codex exec --ephemeral` leave no record and cannot appear here.

Stdlib only. Nothing is ever written under the Codex home: the live database is WAL-mode
and cannot be opened read-only in place, so a copy of it (and its -wal / -shm files) in a
temporary directory is what gets queried.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Standard-speed credits per 1,000,000 tokens: (input, cached input, output).
# Source: Codex pricing page, https://learn.chatgpt.com/docs/pricing.md, read 2026-10-07.
# Fast mode ("priority" service tier) uses the included subscription limits at 2.5x.
# Update this table and its date together when OpenAI changes a rate.
CREDIT_RATES: dict[str, tuple[float, float, float]] = {
    "gpt-6-astra": (250.0, 25.0, 1250.0),
    "gpt-6.1-sol": (50.0, 2.5, 250.0),
    "gpt-6-sol": (50.0, 5.0, 250.0),
    "gpt-6-luna": (2.5, 0.25, 12.5),
    "gpt-5.6-sol": (100.0, 10.0, 500.0),
    "gpt-5.6-terra": (50.0, 5.0, 300.0),
    "gpt-5.6-luna": (5.0, 0.5, 30.0),
    "gpt-5.5": (125.0, 12.5, 750.0),
}
FAST_MULTIPLIER = 2.5
FAST_SERVICE_TIER = "priority"

# The plan meters, told apart by window length: some readings carry only the weekly meter,
# in the `primary` slot, so the slot name says nothing.
FIVE_HOUR_MINUTES = 300
WEEK_MINUTES = 10080

DEFAULT_LAST = 10
PREVIEW_CHARS = 40
EXIT_NO_DATA = 1  # Codex data missing or unreadable; argparse owns exit 2
_SNAPSHOT_ATTEMPTS = 3  # the live db may be mid-write when copied

_REQUIRED_COLUMNS = (
    "id",
    "rollout_path",
    "created_at_ms",
    "updated_at_ms",
    "source",
    "cwd",
    "model",
    "reasoning_effort",
    "tokens_used",
    "agent_role",
    "title",
    "first_user_message",
)

# A rollout line is only parsed if it holds one of these; world_state dumps and tool
# outputs are the bulk of a file and carry nothing this report reads.
_LINE_MARKERS = (
    "token_count",
    "token_usage_record",
    "thread_settings_applied",
    "turn_context",
    "task_started",
    "task_complete",
    "SKILL.md",
    '"user"',
)
_SKILL_PATH = re.compile(r"skills/(?:\.system/)?([\w.-]+)/SKILL\.md")
_SKILL_MENTION = re.compile(r"(?<![\w$])\$([A-Za-z][\w-]*)")
# Codex injects AGENTS.md and the environment as user messages; the AGENTS.md text names
# every installed skill, so counting a `$name` inside it would credit every run with all of them.
_INJECTED_PREFIXES = ("# AGENTS.md instructions", "<")


class UsageError(Exception):
    """The Codex data cannot be read; main() turns it into a message and exit 1."""


# --- data -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """Cumulative tokens for a thread. OpenAI's convention: cached tokens are a subset of
    input, and reasoning tokens are a subset of output (so neither is added again)."""

    input: int = 0
    cached: int = 0
    output: int = 0
    reasoning: int = 0
    total: int = 0

    @property
    def uncached(self) -> int:
        return max(self.input - self.cached, 0)


@dataclass(frozen=True)
class Reading:
    """One look at the plan meters, taken from a token_count event."""

    ts: float
    window: str  # "5h" | "week"
    used_percent: float
    resets_at: int | None


@dataclass
class RolloutFacts:
    usage: Usage | None = None
    model: str | None = None
    effort: str | None = None
    fast: bool = False
    mixed: bool = False  # more than one model or speed seen: priced at the last one
    intervals: list[tuple[float, float]] = field(default_factory=list)
    readings: list[Reading] = field(default_factory=list)
    skills: set[str] = field(default_factory=set)
    malformed: int = 0


@dataclass
class Thread:
    id: str
    parent_id: str | None
    kind: str  # "root" | "child" | "guardian"
    role: str
    model: str
    effort: str
    fast: bool
    created: float
    cwd: str
    preview: str
    usage: Usage
    credits: float | None
    duration_s: float
    intervals: list[tuple[float, float]]
    skills: set[str]
    readings: list[Reading]
    notes: list[str]
    malformed: int


@dataclass(frozen=True)
class MeterSpan:
    start: float
    end: float

    @property
    def delta(self) -> float:
        return self.end - self.start


@dataclass
class Meter:
    five_hour: MeterSpan | None = None
    weekly: MeterSpan | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class Run:
    root: Thread
    threads: list[Thread]  # root first, then the rest by creation time
    intervals: list[tuple[float, float]]  # merged spans in which the run was in a turn
    meter: Meter = field(default_factory=Meter)

    @property
    def id(self) -> str:
        return self.root.id

    @property
    def start(self) -> float:
        return self.root.created

    @property
    def tokens(self) -> int:
        return sum(t.usage.total for t in self.threads)

    @property
    def credits(self) -> float | None:
        return _sum_credits(self.threads)[0]

    @property
    def credits_partial(self) -> bool:
        return _sum_credits(self.threads)[1]

    @property
    def skills(self) -> list[str]:
        return sorted(set().union(*(t.skills for t in self.threads)))

    @property
    def duration_s(self) -> float:
        return sum(end - start for start, end in self.intervals)


def _sum_credits(threads: list[Thread]) -> tuple[float | None, bool]:
    """(sum over the priced threads or None when none is priced, whether any was left out)."""
    priced = [t.credits for t in threads if t.credits is not None]
    left_out = any(t.credits is None and t.usage.total > 0 for t in threads)
    return (sum(priced) if priced else None), left_out


@dataclass
class Collected:
    runs: list[Run]  # oldest first
    unattributed: list[Thread]  # auto-review threads that fit zero or several runs


# --- credits and time -------------------------------------------------------------------


def estimate_credits(usage: Usage, model: str, fast: bool) -> float | None:
    rates = CREDIT_RATES.get(model)
    if rates is None:
        return None
    rate_in, rate_cached, rate_out = rates
    base = (usage.uncached * rate_in + usage.cached * rate_cached + usage.output * rate_out) / 1e6
    return base * (FAST_MULTIPLIER if fast else 1.0)


def _load_resolver() -> Any:
    """resolve_model.py, loaded by path from beside this file. It is the one place that knows
    where the Codex catalog is (the CLI, then the cache file); the path is resolved first, so
    it is found from the symlink a skill folder holds."""
    sibling = Path(__file__).resolve().with_name("resolve_model.py")
    spec = importlib.util.spec_from_file_location("resolve_model", sibling)
    if spec is None or spec.loader is None:
        raise UsageError(f"cannot load {sibling}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


def listed_catalog_slugs() -> list[str]:
    """Slugs the live Codex catalog lists to users, or [] when it cannot be read."""
    try:
        catalog = _load_resolver().load_catalog()
    except (OSError, UsageError):  # resolve_model.py is not beside this file
        return []
    return [slug for slug, info in catalog.models.items() if info.visibility == "list"]


def unpriced_warnings(slugs: Iterable[str]) -> list[str]:
    """One warning per listed model that CREDIT_RATES has no entry for."""
    return [
        f"warning: {slug} is listed in the Codex catalog but has no entry in CREDIT_RATES, so "
        "its runs show n/a credits; add its rates from https://learn.chatgpt.com/docs/pricing.md"
        for slug in sorted(set(slugs))
        if slug not in CREDIT_RATES
    ]


def _epoch(stamp: object) -> float | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None


def merge_intervals(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _overlaps(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    return any(
        a_start <= b_end and b_start <= a_end for a_start, a_end in a for b_start, b_end in b
    )


def _contains(spans: list[tuple[float, float]], moment: float) -> bool:
    return any(start <= moment <= end for start, end in spans)


# --- rollout files ----------------------------------------------------------------------


def _obj(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _usage_from(value: object) -> Usage | None:
    raw = _obj(value)
    if not isinstance(raw.get("input_tokens"), int) or not isinstance(
        raw.get("output_tokens"), int
    ):
        return None

    def count(key: str) -> int:
        number = raw.get(key)
        return number if isinstance(number, int) else 0

    total = count("total_tokens") or count("input_tokens") + count("output_tokens")
    return Usage(
        input=count("input_tokens"),
        cached=count("cached_input_tokens"),
        output=count("output_tokens"),
        reasoning=count("reasoning_output_tokens"),
        total=total,
    )


def _readings_from(rate_limits: object, ts: float) -> list[Reading]:
    limits = _obj(rate_limits)
    if limits.get("limit_id") != "codex":  # other limits (e.g. "premium") are different meters
        return []
    found: list[Reading] = []
    for slot in ("primary", "secondary"):
        meter = _obj(limits.get(slot))
        minutes = meter.get("window_minutes")
        window = {FIVE_HOUR_MINUTES: "5h", WEEK_MINUTES: "week"}.get(
            minutes if isinstance(minutes, int) else 0
        )
        used = meter.get("used_percent")
        resets = meter.get("resets_at")
        if window and isinstance(used, int | float):
            found.append(
                Reading(ts, window, float(used), resets if isinstance(resets, int) else None)
            )
    return found


def _skill_names(text: str, known: set[str]) -> set[str]:
    return {name for name in _SKILL_PATH.findall(text) if name in known}


def _mentions(text: str, known: set[str]) -> set[str]:
    return {name for name in _SKILL_MENTION.findall(text) if name in known}


def read_rollout(path: Path, known_skills: set[str]) -> RolloutFacts:
    """Fold one rollout JSONL into the facts this report needs. Raises OSError if unreadable;
    a line that is not valid JSON is skipped and counted instead."""
    facts = RolloutFacts()
    models: set[str] = set()
    speeds: set[bool] = set()
    started: dict[str, float] = {}  # turn_id -> start, until its task_complete arrives
    last_ts = 0.0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if not any(marker in line for marker in _LINE_MARKERS):
                # Not parsed, but a truncated tail (the file is being written) still counts.
                if not (line.startswith("{") and line.endswith("}")):
                    facts.malformed += 1
                continue
            try:
                record = json.loads(line)
            except ValueError:
                facts.malformed += 1
                continue
            if not isinstance(record, dict):
                facts.malformed += 1
                continue
            ts = _epoch(record.get("timestamp")) or last_ts
            last_ts = max(last_ts, ts)
            kind = record.get("type")
            payload = _obj(record.get("payload"))
            sub = payload.get("type")

            if kind == "event_msg" and sub == "token_count":
                info = _obj(payload.get("info"))  # null before the first model call
                _keep_larger(facts, _usage_from(info.get("total_token_usage")))
                facts.readings.extend(_readings_from(payload.get("rate_limits"), ts))
            elif kind == "token_usage_record":
                _keep_larger(facts, _usage_from(payload.get("thread_token_usage")))
            elif kind == "event_msg" and sub == "thread_settings_applied":
                settings = _obj(payload.get("thread_settings"))
                facts.fast = settings.get("service_tier") == FAST_SERVICE_TIER
                speeds.add(facts.fast)
                if isinstance(settings.get("model"), str):
                    facts.model = settings["model"]
                    models.add(settings["model"])
            elif kind == "turn_context":
                if isinstance(payload.get("model"), str):
                    facts.model = payload["model"]
                    models.add(payload["model"])
                if isinstance(payload.get("effort"), str):
                    facts.effort = payload["effort"]
            elif kind == "event_msg" and sub == "task_started":
                started[str(payload.get("turn_id"))] = ts
            elif kind == "event_msg" and sub == "task_complete":
                begin = started.pop(str(payload.get("turn_id")), None)
                if begin is not None and ts >= begin:
                    facts.intervals.append((begin, ts))
            elif kind == "response_item":
                _read_skill_evidence(facts, payload, known_skills)

    # A turn with no task_complete is still running, or died: it lasted until the last event.
    facts.intervals.extend((begin, last_ts) for begin in started.values() if last_ts >= begin)
    facts.mixed = len(models) > 1 or len(speeds) > 1
    return facts


def _keep_larger(facts: RolloutFacts, candidate: Usage | None) -> None:
    # Both event kinds carry the cumulative total; the largest is the latest.
    if candidate is not None and (facts.usage is None or candidate.total >= facts.usage.total):
        facts.usage = candidate


def _read_skill_evidence(facts: RolloutFacts, payload: dict[str, Any], known: set[str]) -> None:
    sub = payload.get("type")
    if sub in ("function_call", "custom_tool_call"):
        # function_call keeps its text in `arguments`; custom_tool_call (exec) in `input`.
        text = payload.get("arguments") or payload.get("input")
        if isinstance(text, str):
            facts.skills |= _skill_names(text, known)
    elif sub == "message" and payload.get("role") == "user":
        content = payload.get("content")
        for part in content if isinstance(content, list) else []:
            text = _obj(part).get("text")
            if isinstance(text, str) and not text.lstrip().startswith(_INJECTED_PREFIXES):
                facts.skills |= _mentions(text, known)


# --- the thread index -------------------------------------------------------------------


@contextmanager
def index_snapshot(home: Path) -> Iterator[sqlite3.Connection]:
    """Connection to a throwaway copy of the newest thread index.

    The live file is in WAL mode and refuses a read-only open, so the db and its -wal and
    -shm files are copied together: the copy still holds rows written seconds ago.
    """
    candidates = [p for p in home.glob("state_*.sqlite") if re.fullmatch(r"state_\d+", p.stem)]
    if not candidates:
        raise UsageError(f"no state_N.sqlite thread index under {home}")
    live = max(candidates, key=lambda p: int(p.stem.split("_")[1]))
    with tempfile.TemporaryDirectory(prefix="codex-usage-") as scratch:
        problem = ""
        for _ in range(_SNAPSHOT_ATTEMPTS):
            for suffix in ("", "-wal", "-shm"):
                source = live.with_name(live.name + suffix)
                if source.exists():
                    shutil.copy2(source, Path(scratch) / source.name)
            conn = sqlite3.connect(Path(scratch) / live.name)
            try:
                conn.execute("SELECT 1 FROM threads LIMIT 1")
            except sqlite3.DatabaseError as exc:  # copied mid-write: copy again
                problem = str(exc)
                conn.close()
                continue
            try:
                yield conn
            finally:
                conn.close()
            return
        raise UsageError(f"could not read a copy of {live.name}: {problem}")


@dataclass(frozen=True)
class ThreadRow:
    id: str
    rollout_path: str | None
    created_ms: int
    updated_ms: int
    source: str | None
    cwd: str
    model: str
    effort: str
    tokens_used: int
    role: str
    preview: str


def load_rows(conn: sqlite3.Connection) -> list[ThreadRow]:
    have = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
    missing = [column for column in _REQUIRED_COLUMNS if column not in have]
    if missing:
        raise UsageError(f"the threads table has changed; missing column(s): {', '.join(missing)}")
    # The names come from the constant above, never from input.
    query = f"SELECT {', '.join(_REQUIRED_COLUMNS)} FROM threads"
    rows: list[ThreadRow] = []
    for record in conn.execute(query):
        tid, path, created, updated, source, cwd, model, effort, used, role, title, first = record
        text = " ".join(str(first or title or "").split())
        rows.append(
            ThreadRow(
                id=str(tid),
                rollout_path=path if isinstance(path, str) and path else None,
                created_ms=int(created or 0),
                updated_ms=int(updated or 0),
                source=source if isinstance(source, str) else None,
                cwd=str(cwd or ""),
                model=str(model or ""),
                effort=str(effort or ""),
                tokens_used=int(used or 0),
                role=str(role or ""),
                preview=text[:PREVIEW_CHARS],
            )
        )
    return rows


def classify(row: ThreadRow) -> tuple[str, str | None, str]:
    """(kind, parent id, role). Roots store plain text in `source`; children store JSON."""
    source = row.source or ""
    if source.startswith("{"):
        try:
            sub = _obj(json.loads(source)).get("subagent")
        except ValueError:
            sub = None
        spawn = _obj(_obj(sub).get("thread_spawn"))
        if isinstance(spawn.get("parent_thread_id"), str):
            role = spawn.get("agent_role")
            return (
                "child",
                spawn["parent_thread_id"],
                row.role or (role if isinstance(role, str) else ""),
            )
        if _obj(sub).get("other") == "guardian":
            return "guardian", None, row.role or "auto-review"
    return "root", None, row.role or "root"


def discover_skills(home: Path) -> set[str]:
    """Names of installed skills: folders under $CODEX_HOME/skills (and its .system) and
    ~/.agents/skills. A name mentioned anywhere else is not counted."""
    roots = [home / "skills", home / "skills" / ".system", Path.home() / ".agents" / "skills"]
    return {
        entry.name
        for root in roots
        if root.is_dir()
        for entry in root.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    }


# --- assembling runs --------------------------------------------------------------------


def build_thread(
    row: ThreadRow, kind: str, parent: str | None, role: str, home: Path, skills: set[str]
) -> Thread:
    facts: RolloutFacts | None = None
    notes: list[str] = []
    if row.rollout_path:
        path = Path(row.rollout_path)
        try:
            facts = read_rollout(path if path.is_absolute() else home / path, skills)
        except OSError:
            notes.append("partial: rollout unreadable")
    else:
        notes.append("partial: no rollout path")
    if facts is not None and facts.usage is None:
        notes.append("partial: rollout has no token record")

    model = (facts.model if facts else None) or row.model
    effort = (facts.effort if facts else None) or row.effort
    fast = facts.fast if facts else False
    intervals = list(facts.intervals) if facts else []
    if facts is not None and facts.usage is not None:
        usage: Usage = facts.usage
        credits = estimate_credits(usage, model, fast)
    else:
        # Only a total survives, so input and output cannot be priced separately.
        usage = Usage(total=row.tokens_used)
        credits = None
    if facts is not None and facts.mixed:
        notes.append("mixed model or speed: priced at the last one used")
    if not intervals:
        intervals = [(row.created_ms / 1000, max(row.updated_ms, row.created_ms) / 1000)]
    return Thread(
        id=row.id,
        parent_id=parent,
        kind=kind,
        role=role,
        model=model,
        effort=effort,
        fast=fast,
        created=row.created_ms / 1000,
        cwd=row.cwd,
        preview=row.preview,
        usage=usage,
        credits=credits,
        duration_s=sum(end - start for start, end in merge_intervals(intervals)),
        intervals=intervals,
        skills=set(facts.skills) if facts else set(),
        readings=list(facts.readings) if facts else [],
        notes=notes,
        malformed=facts.malformed if facts else 0,
    )


def _meter_for(threads: list[Thread]) -> Meter:
    meter = Meter()
    for window, attribute in (("5h", "five_hour"), ("week", "weekly")):
        readings = sorted(
            (r for t in threads for r in t.readings if r.window == window), key=lambda r: r.ts
        )
        if not readings:
            continue
        setattr(meter, attribute, MeterSpan(readings[0].used_percent, readings[-1].used_percent))
        if len({r.resets_at for r in readings if r.resets_at is not None}) > 1:
            meter.flags.append(f"{window} window reset")
        elif readings[-1].used_percent < readings[0].used_percent:
            meter.flags.append(f"{window} meter fell")
    return meter


def collect(home: Path, since: float | None = None) -> Collected:
    skills = discover_skills(home)
    with index_snapshot(home) as conn:
        rows = load_rows(conn)
    by_id = {row.id: row for row in rows}
    kinds = {row.id: classify(row) for row in rows}

    children: dict[str, list[str]] = defaultdict(list)
    roots: list[str] = []
    guardians: list[str] = []
    for row in rows:
        kind, parent, _ = kinds[row.id]
        if kind == "guardian":
            guardians.append(row.id)
        elif kind == "child" and parent in by_id:
            children[parent].append(row.id)
        else:  # a root, or a child whose parent is no longer in the index
            roots.append(row.id)

    def members(root: str) -> list[str]:
        found, stack, seen = [root], list(children[root]), {root}
        while stack:
            tid = stack.pop()
            if tid in seen:
                continue
            seen.add(tid)
            found.append(tid)
            stack.extend(children[tid])
        return found

    floor_ms = since * 1000 if since is not None else None
    runs: list[Run] = []
    for root_id in roots:
        ids = members(root_id)
        if floor_ms is not None and max(by_id[i].updated_ms for i in ids) < floor_ms:
            continue  # nothing in this run can reach the window, so its rollouts stay unread
        threads = [build_thread(by_id[root_id], "root", None, kinds[root_id][2], home, skills)]
        threads += [
            build_thread(by_id[i], "child", kinds[i][1], kinds[i][2], home, skills) for i in ids[1:]
        ]
        threads[1:] = sorted(threads[1:], key=lambda t: t.created)
        spans = [span for t in threads for span in t.intervals]
        runs.append(Run(threads[0], threads, merge_intervals(spans)))
    runs.sort(key=lambda r: r.start)

    unattributed: list[Thread] = []
    for gid in guardians:
        row = by_id[gid]
        if floor_ms is not None and row.updated_ms < floor_ms:
            continue
        guard = build_thread(row, "guardian", None, kinds[gid][2], home, skills)
        owners = [run for run in runs if _contains(run.intervals, guard.created)]
        if len(owners) == 1:
            owners[0].threads.append(guard)
        else:
            unattributed.append(guard)

    for run in runs:
        run.meter = _meter_for(run.threads)
        if any(other is not run and _overlaps(run.intervals, other.intervals) for other in runs):
            run.meter.flags.append("another run overlapped")
    return Collected(runs, sorted(unattributed, key=lambda t: t.created))


# --- selecting and formatting -----------------------------------------------------------


def parse_when(text: str, *, end: bool) -> float:
    """A local date or date-time. A bare date as an upper bound means the end of that day."""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a date or date-time (try 2026-10-07)"
        ) from exc
    if end and len(text) == 10:
        moment += timedelta(days=1)
    return moment.astimezone().timestamp()  # a naive value is read as local time


def short_ids(runs: list[Run]) -> dict[str, str]:
    """The shortest prefix (at least 8 characters) that tells each run from the others.
    Thread ids are time-ordered, so runs a minute apart share their first 8 characters."""
    out: dict[str, str] = {}
    for run in runs:
        length = 8
        while any(o.id != run.id and o.id[:length] == run.id[:length] for o in runs):
            length += 1
        out[run.id] = run.id[:length]
    return out


def _tokens(n: int) -> str:
    return f"{n:,}"


def _credits(value: float | None, partial: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f}" + ("+" if partial else "")


def _duration(seconds: float) -> str:
    whole = round(seconds)
    if whole < 60:
        return f"{whole}s"
    if whole < 3600:
        return f"{whole // 60}m{whole % 60:02d}s"
    return f"{whole // 3600}h{whole % 3600 // 60:02d}m"


def _speed(fast: bool) -> str:
    return "fast" if fast else "std"


def _delta(span: MeterSpan | None, flagged: bool) -> str:
    if span is None:
        return "-"
    return f"{span.delta:+.1f}" + ("!" if flagged else "")


def _local(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M")


def _table(header: list[str], rows: list[list[str]], right: set[int]) -> str:
    widths = [
        max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i])
        for i in range(len(header))
    ]

    def line(cells: list[str]) -> str:
        parts = [
            c.rjust(widths[i]) if i in right else c.ljust(widths[i]) for i, c in enumerate(cells)
        ]
        return "  ".join(parts).rstrip()

    return "\n".join([line(header), *(line(r) for r in rows)])


def run_table(runs: list[Run], ids: dict[str, str]) -> str:
    header = ["start", "run", "skills", "root (model/effort/speed)", "children", "tokens",
              "credits", "5h%", "wk%", "time", "preview"]  # fmt: skip
    rows: list[list[str]] = []
    for run in runs:
        root = run.root
        kids = Counter(t.model for t in run.threads[1:])
        flagged = bool(run.meter.flags)
        partial = any(n.startswith("partial") for t in run.threads for n in t.notes)
        rows.append(
            [
                _local(run.start),
                ids[run.id],
                ",".join(run.skills) or "-",
                f"{root.model}/{root.effort}/{_speed(root.fast)}",
                ", ".join(f"{m} x{n}" for m, n in sorted(kids.items())) or "-",
                _tokens(run.tokens) + ("~" if partial else ""),
                _credits(run.credits, run.credits_partial),
                _delta(run.meter.five_hour, flagged),
                _delta(run.meter.weekly, flagged),
                _duration(run.duration_s),
                root.preview,
            ]
        )
    return _table(header, rows, right={5, 6, 7, 8, 9})


def thread_table(run: Run, ids: dict[str, str]) -> str:
    header = ["thread", "parent", "role", "model/effort/speed", "input", "cached", "output",
              "reasoning", "total", "credits", "time", "notes"]  # fmt: skip
    rows = [
        [
            t.id[:13],
            (t.parent_id or "-")[:13],
            t.role,
            f"{t.model}/{t.effort}/{_speed(t.fast)}",
            _tokens(t.usage.input),
            _tokens(t.usage.cached),
            _tokens(t.usage.output),
            _tokens(t.usage.reasoning),
            _tokens(t.usage.total),
            _credits(t.credits),
            _duration(t.duration_s),
            "; ".join(t.notes),
        ]
        for t in run.threads
    ]
    meter = run.meter
    flagged = bool(meter.flags)
    head = (
        f"run {ids[run.id]}  {_local(run.start)}  skills: {','.join(run.skills) or '-'}  "
        f"5h {_delta(meter.five_hour, flagged)}  wk {_delta(meter.weekly, flagged)}"
        + (f"  [{'; '.join(meter.flags)}]" if flagged else "")
    )
    return head + "\n" + _table(header, rows, right={4, 5, 6, 7, 8, 9, 10})


def unattributed_line(threads: list[Thread]) -> str:
    tokens = sum(t.usage.total for t in threads)
    return (
        f"unattributed auto-review: {len(threads)} thread(s), {_tokens(tokens)} tokens "
        "(started in no run, or in several at once); credits n/a"
    )


def footer(runs: list[Run], unattributed: list[Thread]) -> str:
    lines: list[str] = []
    if unattributed:
        lines.append(unattributed_line(unattributed))
    skipped = sum(t.malformed for r in runs for t in r.threads)
    if skipped:
        lines.append(f"{skipped} malformed rollout line(s) skipped")
    lines.append(
        "~ partial (index total only)   + some threads n/a, left out   ! meter delta unreliable"
    )
    return "\n".join(lines)


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def summary(runs: list[Run], unattributed: list[Thread]) -> str:
    by_skill: dict[str, list[Run]] = defaultdict(list)
    for run in runs:
        for name in run.skills or ["(no skill)"]:
            by_skill[name].append(run)
    skill_rows = []
    for name, group in sorted(by_skill.items()):
        credits = [c for r in group if (c := r.credits) is not None]
        per_run = [float(r.tokens) for r in group]
        skill_rows.append(
            [
                name,
                str(len(group)),
                _tokens(sum(r.tokens for r in group)),
                _credits(sum(credits) if credits else None, any(r.credits_partial for r in group)),
                _tokens(round(_median(per_run))),
                _credits(_median(credits) if credits else None),
            ]
        )

    tokens_by_model: dict[str, list[float]] = defaultdict(list)
    credits_by_model: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        buckets: dict[str, list[Thread]] = defaultdict(list)
        for t in run.threads:
            buckets[t.model].append(t)
        for model, threads in buckets.items():
            tokens_by_model[model].append(float(sum(t.usage.total for t in threads)))
            if (priced := _sum_credits(threads)[0]) is not None:
                credits_by_model[model].append(priced)
    model_rows = []
    for model, tokens in sorted(tokens_by_model.items()):
        credits = credits_by_model.get(model, [])
        model_rows.append(
            [
                model,
                str(len(tokens)),
                _tokens(round(sum(tokens))),
                _credits(sum(credits) if credits else None),
                _tokens(round(_median(tokens))),
                _credits(_median(credits) if credits else None),
            ]
        )
    header = ["", "runs", "tokens", "credits", "median tokens/run", "median credits/run"]
    out = [
        f"{len(runs)} run(s); a run that used several skills counts under each.",
        "",
        _table(["by skill", *header[1:]], skill_rows, right={1, 2, 3, 4, 5}),
        "",
        _table(["by model", *header[1:]], model_rows, right={1, 2, 3, 4, 5}),
    ]
    if unattributed:
        out += ["", unattributed_line(unattributed)]
    return "\n".join(out)


CSV_COLUMNS = [
    *("run_id", "run_start", "skills", "thread_id", "parent_id", "role", "model", "effort"),
    *("speed", "input", "cached", "uncached", "output", "reasoning", "total", "est_credits"),
    *("duration_s", "cwd", "meter_5h_start", "meter_5h_end", "meter_5h_delta"),
    *("meter_week_start", "meter_week_end", "meter_week_delta", "meter_flags", "notes"),
]


def _thread_fields(t: Thread) -> dict[str, Any]:
    return {
        "thread_id": t.id,
        "parent_id": t.parent_id or "",
        "role": t.role,
        "model": t.model,
        "effort": t.effort,
        "speed": _speed(t.fast),
        "input": t.usage.input,
        "cached": t.usage.cached,
        "uncached": t.usage.uncached,
        "output": t.usage.output,
        "reasoning": t.usage.reasoning,
        "total": t.usage.total,
        "est_credits": "" if t.credits is None else round(t.credits, 6),
        "duration_s": round(t.duration_s, 1),
        "cwd": t.cwd,
        "notes": "; ".join(t.notes),
    }


def _meter_fields(meter: Meter) -> dict[str, Any]:
    out: dict[str, Any] = {"meter_flags": "; ".join(meter.flags)}
    for prefix, span in (("meter_5h", meter.five_hour), ("meter_week", meter.weekly)):
        if span is not None:
            out |= {
                f"{prefix}_start": span.start,
                f"{prefix}_end": span.end,
                f"{prefix}_delta": round(span.delta, 3),
            }
    return out


def csv_rows(runs: list[Run], unattributed: list[Thread]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        base = {"run_id": run.id, "run_start": _local(run.start), "skills": ",".join(run.skills)}
        for position, t in enumerate(run.threads):
            meter = _meter_fields(run.meter) if position == 0 else {}
            rows.append({**base, **_thread_fields(t), **meter})
    for t in unattributed:
        rows.append({"run_id": "unattributed", "run_start": _local(t.created), **_thread_fields(t)})
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _thread_json(t: Thread) -> dict[str, Any]:
    return {
        "thread_id": t.id,
        "parent_id": t.parent_id,
        "kind": t.kind,
        "role": t.role,
        "model": t.model,
        "effort": t.effort,
        "speed": _speed(t.fast),
        "tokens": {
            "input": t.usage.input,
            "cached": t.usage.cached,
            "uncached": t.usage.uncached,
            "output": t.usage.output,
            "reasoning": t.usage.reasoning,
            "total": t.usage.total,
        },
        "est_credits": t.credits,
        "duration_s": round(t.duration_s, 1),
        "cwd": t.cwd,
        "skills": sorted(t.skills),
        "notes": t.notes,
        "malformed_lines": t.malformed,
    }


def to_json(runs: list[Run], unattributed: list[Thread]) -> str:
    def span(s: MeterSpan | None) -> dict[str, float] | None:
        return None if s is None else {"start": s.start, "end": s.end, "delta": s.delta}

    return json.dumps(
        {
            "runs": [
                {
                    "run_id": r.id,
                    "start": _local(r.start),
                    "preview": r.root.preview,
                    "skills": r.skills,
                    "tokens": r.tokens,
                    "est_credits": r.credits,
                    "credits_partial": r.credits_partial,
                    "duration_s": round(r.duration_s, 1),
                    "meter": {
                        "five_hour": span(r.meter.five_hour),
                        "weekly": span(r.meter.weekly),
                        "flags": r.meter.flags,
                    },
                    "threads": [_thread_json(t) for t in r.threads],
                }
                for r in runs
            ],
            "unattributed_auto_review": [_thread_json(t) for t in unattributed],
        },
        indent=2,
    )


def select(
    collected: Collected, *, since: float | None, until: float | None, skill: str | None,
    run: str | None, last: int | None,
) -> tuple[list[Run], list[Thread]]:  # fmt: skip
    runs = [
        r
        for r in collected.runs
        if (since is None or r.start >= since)
        and (until is None or r.start < until)
        and (skill is None or skill in r.skills)
        and (run is None or any(t.id.startswith(run) for t in r.threads))
    ]
    if last is not None:
        runs = runs[-last:]
    unattributed = [] if (run or skill) else [
        t for t in collected.unattributed
        if (since is None or t.created >= since) and (until is None or t.created < until)
    ]  # fmt: skip
    return runs, unattributed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0] if __doc__ else None,
        epilog="\n\n".join((__doc__ or "").split("\n\n")[1:]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--since", metavar="WHEN", help="runs started at or after this local date or date-time"
    )
    parser.add_argument(
        "--until",
        metavar="WHEN",
        help="runs started before this; a bare date means the end of that day",
    )
    parser.add_argument(
        "--last",
        type=int,
        metavar="N",
        help=(
            f"the most recent N runs (default {DEFAULT_LAST} for the table; every matching run "
            "when --since, --until, --skill, --run, --summary, --csv or --json is given)"
        ),
    )
    parser.add_argument(
        "--run", metavar="ID", help="runs with a thread whose id starts with ID; one row per thread"
    )
    parser.add_argument("--skill", metavar="NAME", help="only runs that used this skill")
    shape = parser.add_mutually_exclusive_group()
    shape.add_argument("--summary", action="store_true", help="aggregate by skill and by model")
    shape.add_argument(
        "--csv",
        type=Path,
        metavar="PATH",
        help="write one row per thread to PATH (blank est_credits means n/a)",
    )
    shape.add_argument("--json", action="store_true", help="print every run and thread as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        since = parse_when(args.since, end=False) if args.since else None
        until = parse_when(args.until, end=True) if args.until else None
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.last is not None and args.last < 1:
        parser.error("--last must be at least 1")

    warnings = unpriced_warnings(listed_catalog_slugs())
    for warning in warnings:
        print(warning, file=sys.stderr)

    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    if args.csv and args.csv.resolve().is_relative_to(home.resolve()):
        parser.error("--csv must not write under the Codex home")
    try:
        collected = collect(home, since)
    except UsageError as exc:
        print(f"codex_usage: {exc}", file=sys.stderr)
        return EXIT_NO_DATA

    scoped = any((args.since, args.until, args.skill, args.run, args.summary, args.csv, args.json))
    last = args.last if args.last is not None else (None if scoped else DEFAULT_LAST)
    runs, unattributed = select(
        collected, since=since, until=until, skill=args.skill, run=args.run, last=last
    )

    if args.json:
        print(to_json(runs, unattributed))
    elif args.csv:
        rows = csv_rows(runs, unattributed)
        write_csv(args.csv, rows)
        print(f"wrote {len(rows)} thread row(s) across {len(runs)} run(s) to {args.csv}")
    elif not runs and not unattributed:
        print("no runs match")
    elif args.summary:
        print(summary(runs, unattributed))
        if warnings:
            print("\n" + "\n".join(warnings))
    else:
        ids = short_ids(collected.runs)
        if args.run:
            print("\n\n".join(thread_table(r, ids) for r in runs))
        else:
            print(run_table(runs, ids))
        print()
        print(footer(runs, unattributed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
