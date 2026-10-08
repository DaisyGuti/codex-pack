#!/usr/bin/env python3
"""Does a skill's description make Codex load the skill when it should, and only then?

    eval_triggers.py --skill plan-ticket                     every query, once
    eval_triggers.py --skill plan-ticket --only-first        just the first query (a smoke test)
    eval_triggers.py --skill plan-ticket --skip 1            all but the first (after --only-first)
    eval_triggers.py --skill plan-ticket --runs 3 --max-parallel 3 --json
    eval_triggers.py --skill eng --fixture small-repo        run inside a copy of a small repo

Each skill has evals/triggers/<skill>.json: a list of {"query": ..., "should_trigger": ...}.
The method is the one at agentskills.io/skill-creation/optimizing-descriptions: a run
TRIGGERED the skill when the skill's SKILL.md got loaded, and did not when the agent went on
without consulting it. It gets loaded in one of two ways, and each run records which:

  read      the agent ran a shell command that opens the SKILL.md (seen in the event stream)
  injected  the query named the skill with `$name` ("Use $eng to ..."), so Codex put the
            SKILL.md into the session itself and the agent never opened it. No event shows
            this; it is in the run's session rollout file, which is read after the run ends.

A query passes when its trigger rate over the runs is above 0.5 (it
should trigger) or below 0.5 (it should not); exactly 0.5 passes neither. The SKILL.md of any
other pack skill the run read is listed too: a near-miss that loads a neighbour is worth knowing.

Each run is `codex exec --json` in a fresh temp directory, read-only, ignoring the
user's own config (which may turn on Fast mode, 2.5x usage), on the ChatGPT sign-in: the API
key variables are removed from the child's environment and `codex login status` must say
ChatGPT before anything starts. Model and effort come from resolve_model.py (`--tier`,
default fast, and `--effort`, default low). A run stops the moment the target SKILL.md read
is seen, otherwise when the agent's turn completes or --timeout seconds pass. A run whose
turn completed without a read is then checked for an injection; if its rollout file cannot be
found or read the run is an ERROR, never "no trigger". Runs stay on
disk (no --ephemeral) so codex_usage.py can measure them afterwards. Apps (ChatGPT connectors
such as GitHub) are switched off with `--disable apps` unless --allow-apps is given: the
read-only sandbox does not stop a connector from writing.

The temp directory is empty by default, which understates a skill meant for work inside a
repository: asked to "fix the 500 on login", the agent finds no repository and says so.
`--fixture NAME` copies evals/fixtures/NAME into it and runs `git init` plus one commit
first, so the agent starts in a repo with a clean history.

A run that errors or times out is an ERROR, never "did not trigger": it is left out of the
trigger rate, and a query with no valid run is left out of the pass rate and listed.
Tokens come from the turn's own `turn.completed` event, so a run stopped early has none.

Exit codes: 0 finished, 1 at least one run errored, 2 usage error, 3 the Codex CLI cannot run,
is not signed in with ChatGPT, or the skill is not installed under the Codex home.

Stdlib only, so it runs under any Python 3.12+.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

EXIT_ERRORED_RUNS = 1
EXIT_USAGE = 2
EXIT_NO_CLI = 3

DEFAULT_TIMEOUT_S = 150.0
MAX_PARALLEL_CAP = 4
# Keys that would bill a metered account instead of the ChatGPT plan.
BILLING_ENV = ("CODEX_API_KEY", "OPENAI_API_KEY")
# One JSONL line can carry a whole file's contents; asyncio's 64 KB default would abort the run.
_LINE_LIMIT = 32 * 1024 * 1024
_KILL_GRACE_S = 5.0
# The rollout file is created as the session starts, but allow for a slow disk.
_ROLLOUT_WAIT_S = 5.0
_ROLLOUT_POLL_S = 0.25

DETECTED_BY_READ = "read"
DETECTED_BY_INJECTED = "injected"

# Any spelling of the path (~/.codex/skills/x/SKILL.md, the symlink target in the pack, a
# relative skills/x/SKILL.md) ends the same way.
_SKILL_FILE = re.compile(r"skills/([A-Za-z0-9][A-Za-z0-9._-]*)/SKILL\.md(?![\w-]|\.\w)")

# What Codex puts in the session for `$name`: a user message whose text opens with
#   <skill>\n<name>eng</name>\n<path>/.../skills/eng/SKILL.md</path>\n---\nname: eng ...
# Anchored to the start of the message because the catalogue of available skills, which
# every session carries, also names every SKILL.md path.
_INJECTED_SKILL = re.compile(
    r"\A\s*<skill>\s*<name>[^<]*</name>\s*<path>[^<]*skills/"
    r"([A-Za-z0-9][A-Za-z0-9._-]*)/SKILL\.md</path>"
)
_THREAD_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z-]*")
_FIXTURE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class UsageError(Exception):
    """The invocation or the eval files are wrong; nothing was run."""


class CliUnavailable(Exception):
    """Codex cannot be run here, or is not signed in with ChatGPT."""


class RolloutUnavailable(Exception):
    """A finished run's session rollout cannot be found or read, so an injection is unknown."""


class FixtureError(Exception):
    """The fixture could not be copied or turned into a git repository."""


# --------------------------------------------------------------------------- events


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def parse_usage(raw: object) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    return Usage(
        input_tokens=_int(raw.get("input_tokens")),
        cached_input_tokens=_int(raw.get("cached_input_tokens")),
        output_tokens=_int(raw.get("output_tokens")),
        reasoning_output_tokens=_int(raw.get("reasoning_output_tokens")),
    )


def skill_reads(event: dict[str, Any]) -> list[str]:
    """Skill names whose SKILL.md this event shows the agent opening, in order.

    Only a shell command counts. The agent's own messages and reasoning can quote a path
    without having read the file, and a command's output is never searched for the same
    reason. Both item.started and item.completed carry the command; the caller de-duplicates.
    """
    item = event.get("item")
    if not isinstance(item, dict) or item.get("type") != "command_execution":
        return []
    command = item.get("command")
    return _SKILL_FILE.findall(command) if isinstance(command, str) else []


@dataclass
class RunScan:
    """What one run's event stream has shown so far. Feed it one JSONL line at a time."""

    target: str
    pack_skills: frozenset[str]
    triggered: bool = False
    detected_by: str | None = None  # DETECTED_BY_READ or DETECTED_BY_INJECTED once triggered
    thread_id: str | None = None
    neighbours: list[str] = field(default_factory=list)
    usage: Usage | None = None
    turn_done: bool = False
    error: str | None = None

    @property
    def finished(self) -> bool:
        """Nothing further in this run can change its answer."""
        return self.triggered or self.turn_done or self.error is not None

    def feed(self, line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return  # a non-JSON line (a startup banner) is not an event
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        for name in skill_reads(event):
            self._loaded(name, DETECTED_BY_READ)
        if kind == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str):
                self.thread_id = thread_id
        elif kind == "turn.completed":
            self.turn_done = True
            self.usage = parse_usage(event.get("usage"))
        elif kind == "turn.failed":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            self.error = f"turn failed: {message or 'no message'}"
        elif kind == "error" and self.error is None:
            self.error = f"codex error: {event.get('message') or 'no message'}"

    def note_injected(self, names: Iterable[str]) -> None:
        """Skills the run's rollout shows Codex injected (the `$name` form of a query)."""
        for name in names:
            self._loaded(name, DETECTED_BY_INJECTED)

    def _loaded(self, name: str, how: str) -> None:
        if name == self.target:
            if not self.triggered:
                self.detected_by = how
            self.triggered = True
        elif name in self.pack_skills and name not in self.neighbours:
            self.neighbours.append(name)


# ------------------------------------------------------------------------ rollouts


def injected_skills(rollout: Iterable[str]) -> list[str]:
    """Skill names a rollout shows Codex injecting, in order, from its JSONL lines.

    Only a user message whose text opens with the `<skill>` block counts; the skills
    catalogue and the agent's own words can name the same paths without loading anything.
    """
    found: list[str] = []
    for line in rollout:
        try:
            record = json.loads(line)
        except ValueError:
            continue  # a half-written last line is not a record
        payload = record.get("payload") if isinstance(record, dict) else None
        if not isinstance(payload, dict) or record.get("type") != "response_item":
            continue
        if payload.get("type") != "message" or payload.get("role") != "user":
            continue
        content = payload.get("content")
        for part in content if isinstance(content, list) else []:
            text = part.get("text") if isinstance(part, dict) else None
            match = _INJECTED_SKILL.match(text) if isinstance(text, str) else None
            if match and match.group(1) not in found:
                found.append(match.group(1))
    return found


def find_rollout(codex_home: Path, thread_id: str) -> Path | None:
    """sessions/YYYY/MM/DD/rollout-<timestamp>-<thread id>.jsonl, found by its thread id."""
    if not _THREAD_ID.fullmatch(thread_id):
        return None  # never let an odd id widen the glob
    matches = sorted((codex_home / "sessions").glob(f"*/*/*/rollout-*-{thread_id}.jsonl"))
    return matches[-1] if matches else None


async def read_injected(codex_home: Path, thread_id: str | None) -> list[str]:
    """The skills injected into one run, or RolloutUnavailable when that cannot be known."""
    if thread_id is None:
        raise RolloutUnavailable(
            "the event stream never named a thread (no thread.started), "
            "so the session rollout cannot be checked for an injected skill"
        )
    deadline = time.monotonic() + _ROLLOUT_WAIT_S
    path = find_rollout(codex_home, thread_id)
    while path is None and time.monotonic() < deadline:
        await asyncio.sleep(_ROLLOUT_POLL_S)
        path = find_rollout(codex_home, thread_id)
    if path is None:
        raise RolloutUnavailable(
            f"no session rollout for thread {thread_id} under {codex_home / 'sessions'}, "
            "so an injected skill cannot be ruled out"
        )
    try:
        text = await asyncio.to_thread(path.read_text, "utf-8", "replace")
    except OSError as exc:
        raise RolloutUnavailable(f"cannot read the session rollout {path}: {exc}") from exc
    return injected_skills(text.splitlines())


# ------------------------------------------------------------------------ scoring


@dataclass
class RunResult:
    triggered: bool | None  # None when the run errored: unknown, never "no"
    neighbours: list[str]
    error: str | None
    usage: Usage | None
    seconds: float
    stopped_early: bool = False
    detected_by: str | None = None  # "read" or "injected" when triggered


@dataclass
class QueryOutcome:
    number: int  # the query's position in its eval file, so --skip does not renumber it
    query: str
    should_trigger: bool
    runs: list[RunResult]

    @property
    def valid_runs(self) -> list[RunResult]:
        return [r for r in self.runs if r.error is None]

    @property
    def errors(self) -> list[str]:
        return [r.error for r in self.runs if r.error is not None]

    @property
    def trigger_rate(self) -> float | None:
        valid = self.valid_runs
        return sum(bool(r.triggered) for r in valid) / len(valid) if valid else None

    @property
    def passed(self) -> bool | None:
        """None when no run finished, so there is nothing to judge."""
        rate = self.trigger_rate
        if rate is None:
            return None
        return rate > 0.5 if self.should_trigger else rate < 0.5

    @property
    def neighbours(self) -> list[str]:
        seen: list[str] = []
        for run in self.runs:
            seen.extend(n for n in run.neighbours if n not in seen)
        return seen

    @property
    def detected_by(self) -> dict[str, int]:
        """How many triggered runs each mechanism caught, e.g. {"read": 2, "injected": 1}."""
        counts: dict[str, int] = {}
        for run in self.runs:
            if run.triggered and run.detected_by is not None:
                counts[run.detected_by] = counts.get(run.detected_by, 0) + 1
        return counts

    @property
    def tokens(self) -> int | None:
        counted = [r.usage.total for r in self.runs if r.usage is not None]
        return sum(counted) if counted else None


def _rate(passed: int, total: int) -> float | None:
    return passed / total if total else None


def summarize(outcomes: Iterable[QueryOutcome]) -> dict[str, Any]:
    outcomes = list(outcomes)
    judged = [o for o in outcomes if o.passed is not None]
    positives = [o for o in judged if o.should_trigger]
    negatives = [o for o in judged if not o.should_trigger]
    return {
        "queries": len(outcomes),
        "judged": len(judged),
        "unjudged": [o.query for o in outcomes if o.passed is None],
        "pass_rate": _rate(sum(bool(o.passed) for o in judged), len(judged)),
        "positive_pass_rate": _rate(sum(bool(o.passed) for o in positives), len(positives)),
        "negative_pass_rate": _rate(sum(bool(o.passed) for o in negatives), len(negatives)),
        "failures": [
            {
                "number": o.number,
                "query": o.query,
                "should_trigger": o.should_trigger,
                "trigger_rate": o.trigger_rate,
                "neighbours": o.neighbours,
            }
            for o in judged
            if not o.passed
        ],
    }


# --------------------------------------------------------------------- the eval set


@dataclass(frozen=True)
class Case:
    number: int  # 1-based position in the eval file
    query: str
    should_trigger: bool


def load_queries(path: Path) -> list[Case]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise UsageError(f"{path} must hold a non-empty list of queries")
    queries: list[Case] = []
    for i, entry in enumerate(raw, start=1):
        query = entry.get("query") if isinstance(entry, dict) else None
        should = entry.get("should_trigger") if isinstance(entry, dict) else None
        if not isinstance(query, str) or not query.strip() or not isinstance(should, bool):
            raise UsageError(
                f'{path} entry {i} needs a "query" string and a boolean "should_trigger"'
            )
        queries.append(Case(i, query, should))
    return queries


def pack_skill_names(skills_dir: Path) -> frozenset[str]:
    return frozenset(p.parent.name for p in skills_dir.glob("*/SKILL.md"))


# ------------------------------------------------------------------- the Codex CLI


def _load_resolver() -> Any:
    """resolve_model.py, loaded by path from beside this file: the one place that knows where
    the Codex binary is and which model a tier means."""
    sibling = Path(__file__).resolve().with_name("resolve_model.py")
    spec = importlib.util.spec_from_file_location("resolve_model", sibling)
    if spec is None or spec.loader is None:
        raise CliUnavailable(f"cannot load {sibling}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in BILLING_ENV}


def check_chatgpt_login(binary: str) -> None:
    """Refuse unless Codex itself says it is signed in with ChatGPT."""
    try:
        done = subprocess.run(
            [binary, "login", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CliUnavailable(f"`codex login status` could not run: {exc}") from exc
    said = (done.stdout + done.stderr).strip()
    if done.returncode != 0 or "chatgpt" not in said.lower():
        raise CliUnavailable(
            f"`codex login status` must report a ChatGPT sign-in; it said: {said or '(nothing)'}"
        )


def build_command(
    binary: str, model: str, effort: str, query: str, allow_apps: bool = False
) -> list[str]:
    # Apps (ChatGPT connectors such as GitHub) stay off unless asked for: the read-only
    # sandbox limits shell commands, and a connector call is not a shell command.
    return [
        binary,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ignore-user-config",
        *([] if allow_apps else ["--disable", "apps"]),
        "--sandbox",
        "read-only",
        "-m",
        model,
        "-c",
        f"model_reasoning_effort={effort}",
        query,
    ]


async def _stop(proc: asyncio.subprocess.Process) -> None:
    """End the run's whole process group: SIGTERM, then SIGKILL if it is still there."""
    if proc.returncode is not None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            # Already gone. macOS answers EPERM, not ESRCH, for a group whose only member
            # exited but has not been reaped yet, which is the usual case right after
            # the last event, so the wait below is what reaps it.
            break
        try:
            await asyncio.wait_for(proc.wait(), _KILL_GRACE_S)
            return
        except TimeoutError:
            continue
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(proc.wait(), _KILL_GRACE_S)


@dataclass(frozen=True)
class RunConfig:
    binary: str
    model: str
    effort: str
    target: str
    pack_skills: frozenset[str]
    codex_home: Path  # where the session rollouts are kept
    timeout_s: float = DEFAULT_TIMEOUT_S
    events_dir: Path | None = None
    allow_apps: bool = False
    fixture: Path | None = None  # copied into the run's directory and committed there


def prepare_workdir(workdir: Path, fixture: Path | None) -> None:
    """Copy the fixture into the run's directory and commit it, so the agent starts in a repo
    with one commit and a clean tree. No fixture leaves the directory empty."""
    if fixture is None:
        return
    # Ignore the user's git config (hooks, templates, a global ignore file) so the commit holds
    # exactly the fixture's files whoever runs this.
    env = {**child_env(), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    identity = ["-c", "user.name=eval-triggers", "-c", "user.email=eval-triggers@example.invalid"]
    try:
        shutil.copytree(fixture, workdir, dirs_exist_ok=True)
        for args in (
            ["init", "-q", "-b", "main"],
            ["add", "-A"],
            ["commit", "-q", "-m", "Initial"],
        ):
            subprocess.run(
                ["git", *identity, *args],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
    except (OSError, shutil.Error, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", None) or ""
        raise FixtureError(
            f"could not set up fixture {fixture.name}: {exc} {detail}".strip()
        ) from exc


async def _read_events(proc: asyncio.subprocess.Process, scan: RunScan, sink: Any) -> None:
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace")
        if sink is not None:
            sink.write(line)
        scan.feed(line)
        if scan.finished:
            return


async def run_once(cfg: RunConfig, query: str, label: str) -> RunResult:
    started = time.monotonic()
    scan = RunScan(cfg.target, cfg.pack_skills)
    error: str | None = None
    proc: asyncio.subprocess.Process | None = None
    sink = None
    # The directory the agent works in holds only the fixture (or nothing), so stderr goes to
    # its own file.
    with (
        tempfile.TemporaryDirectory(prefix="eval-triggers-") as workdir,
        tempfile.TemporaryFile("w+b") as stderr,
    ):
        try:
            await asyncio.to_thread(prepare_workdir, Path(workdir), cfg.fixture)
            if cfg.events_dir is not None:
                cfg.events_dir.mkdir(parents=True, exist_ok=True)
                sink = (cfg.events_dir / f"{label}.jsonl").open("w", encoding="utf-8")
            proc = await asyncio.create_subprocess_exec(
                *build_command(cfg.binary, cfg.model, cfg.effort, query, cfg.allow_apps),
                cwd=workdir,
                env=child_env(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
                start_new_session=True,  # so the whole process tree can be killed together
                limit=_LINE_LIMIT,
            )
            try:
                await asyncio.wait_for(_read_events(proc, scan, sink), cfg.timeout_s)
                if not scan.finished:
                    # The stream closed first; give the process a moment to report its status.
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(proc.wait(), _KILL_GRACE_S)
            except TimeoutError:
                error = f"timed out after {cfg.timeout_s:g}s"
            except ValueError as exc:  # a line past _LINE_LIMIT
                error = f"unreadable event stream: {exc}"
        except FixtureError as exc:
            error = str(exc)
        except OSError as exc:
            error = f"could not start codex: {exc}"
        finally:
            if proc is not None:
                await _stop(proc)
            if sink is not None:
                sink.close()
        stopped_early = scan.triggered and not scan.turn_done
        if error is None and scan.error is not None:
            error = scan.error
        if error is None and not scan.finished:
            # The stream ended without a finished turn: the process died on its own.
            stderr.seek(0)
            tail = stderr.read()[-400:].decode("utf-8", errors="replace").strip()
            error = f"codex exited {proc.returncode if proc else '?'} before finishing: {tail}"
        if error is None and not scan.triggered:
            # No read was seen. An injected skill leaves no event, only a line in the rollout.
            try:
                scan.note_injected(await read_injected(cfg.codex_home, scan.thread_id))
            except RolloutUnavailable as exc:
                error = str(exc)
    seconds = time.monotonic() - started
    if error is not None:
        return RunResult(None, scan.neighbours, error, scan.usage, seconds)
    return RunResult(
        scan.triggered,
        scan.neighbours,
        None,
        scan.usage,
        seconds,
        stopped_early,
        scan.detected_by,
    )


async def gather_outcomes(
    queries: list[Case],
    runs: int,
    max_parallel: int,
    run_one: Callable[[str, str], Awaitable[RunResult]],
    on_done: Callable[[str, RunResult], None] | None = None,
) -> list[QueryOutcome]:
    """Every (query, run) pair through `run_one(query, label)`, at most max_parallel at once.

    One pair failing never cancels the others: run_one reports its own failure as an
    errored RunResult, and anything it raises is turned into one here.
    """
    gate = asyncio.Semaphore(max_parallel)

    async def one(case: Case, ri: int) -> RunResult:
        query = case.query
        label = f"q{case.number:02d}-r{ri + 1}"
        async with gate:
            try:
                result = await run_one(query, label)
            except Exception as exc:  # noqa: BLE001 - reported as this run's error, not raised
                result = RunResult(None, [], f"{type(exc).__name__}: {exc}", None, 0.0)
        if on_done is not None:
            on_done(label, result)
        return result

    grid = [[asyncio.ensure_future(one(case, ri)) for ri in range(runs)] for case in queries]
    outcomes = []
    for case, row in zip(queries, grid, strict=True):
        results = list(await asyncio.gather(*row))
        outcomes.append(QueryOutcome(case.number, case.query, case.should_trigger, results))
    return outcomes


# ------------------------------------------------------------------------ report


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render(skill: str, model: str, effort: str, outcomes: list[QueryOutcome]) -> str:
    summary = summarize(outcomes)
    lines = [f"{skill}: {len(outcomes)} queries on {model} at {effort} effort", ""]
    lines.append(f"{'#':>2}  {'result':<6} {'expect':<8} {'rate':>5}  {'tokens':>8}  query")
    for o in outcomes:
        verdict = {True: "PASS", False: "FAIL", None: "ERROR"}[o.passed]
        expect = "trigger" if o.should_trigger else "ignore"
        tokens = "-" if o.tokens is None else f"{o.tokens:,}"
        row = f"{o.number:>2}  {verdict:<6} {expect:<8} {_pct(o.trigger_rate):>5}  {tokens:>8}"
        lines.append(f"{row}  {o.query}")
        if o.detected_by:
            how = ", ".join(f"{name} x{count}" for name, count in o.detected_by.items())
            lines.append(f"{'':>4}detected by: {how}")
        if o.neighbours:
            lines.append(f"{'':>4}also loaded: {', '.join(o.neighbours)}")
        lines.extend(f"{'':>4}error: {e}" for e in o.errors)
    lines += [
        "",
        f"pass rate {_pct(summary['pass_rate'])} over {summary['judged']} judged queries "
        f"(should trigger {_pct(summary['positive_pass_rate'])}, "
        f"should not {_pct(summary['negative_pass_rate'])})",
    ]
    if summary["unjudged"]:
        lines.append(
            f"{len(summary['unjudged'])} query(ies) had no finished run and are not judged"
        )
    if summary["failures"]:
        lines.append("failures:")
        for f in summary["failures"]:
            want = "should trigger" if f["should_trigger"] else "should not trigger"
            extra = f"; loaded instead: {', '.join(f['neighbours'])}" if f["neighbours"] else ""
            lines.append(f"  - {f['query']} ({want}, rate {_pct(f['trigger_rate'])}{extra})")
    return "\n".join(lines)


def to_json(skill: str, model: str, effort: str, outcomes: list[QueryOutcome]) -> str:
    def outcome(o: QueryOutcome) -> dict[str, Any]:
        return {
            "number": o.number,
            "query": o.query,
            "should_trigger": o.should_trigger,
            "triggered": [r.triggered for r in o.runs],
            "detected_by": o.detected_by,
            "trigger_rate": o.trigger_rate,
            "neighbours": o.neighbours,
            "passed": o.passed,
            "errors": o.errors,
            "tokens": o.tokens,
            "runs": [asdict(r) for r in o.runs],
        }

    return json.dumps(
        {
            "skill": skill,
            "model": model,
            "effort": effort,
            "summary": summarize(outcomes),
            "queries": [outcome(o) for o in outcomes],
        },
        indent=2,
    )


# --------------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test whether a skill's description triggers it, using codex exec."
    )
    parser.add_argument("--skill", required=True, metavar="NAME")
    parser.add_argument("--runs", type=int, default=1, metavar="N", help="runs per query")
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=2,
        metavar="N",
        help=f"runs at once (default 2, capped at {MAX_PARALLEL_CAP}): they share one usage window",
    )
    parser.add_argument("--only-first", action="store_true", help="run just the first query")
    parser.add_argument(
        "--allow-apps",
        action="store_true",
        help="leave apps (ChatGPT connectors such as GitHub) on. They are off by default because "
        "the read-only sandbox does not stop a connector from writing. Allowing them is closer "
        "to real use, at the risk of real writes",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        metavar="N",
        help="leave out the first N queries (continue after --only-first with --skip 1)",
    )
    parser.add_argument("--tier", default="fast", help="model tier from resolve_model.py")
    parser.add_argument("--effort", default="low", help="reasoning effort (default low)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, metavar="SECONDS")
    parser.add_argument(
        "--fixture",
        metavar="NAME",
        help="run each query in a git repository made from evals/fixtures/NAME (copied into "
        "the run's temp directory and committed there) instead of an empty folder",
    )
    parser.add_argument("--events-dir", type=Path, metavar="DIR", help="keep each run's raw events")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def resolve_model(resolver: Any, tier: str, effort: str) -> tuple[str, str]:
    name = resolver.normalize_tier(tier)
    if name is None:
        raise UsageError(f"unknown tier {tier!r}; valid values: {resolver.valid_tier_names()}")
    if effort not in resolver.EFFORT_ORDER:
        raise UsageError(f"unknown effort {effort!r}; valid: {', '.join(resolver.EFFORT_ORDER)}")
    result, code = resolver.resolve(name, effort, resolver.load_catalog())
    if code:
        raise CliUnavailable(result["error"])
    return str(result["model"]), str(result["effort"])


def _run(args: argparse.Namespace) -> int:
    if args.runs < 1:
        raise UsageError("--runs must be at least 1")
    if args.max_parallel < 1:
        raise UsageError("--max-parallel must be at least 1")
    if args.timeout <= 0:
        raise UsageError("--timeout must be positive")
    max_parallel = min(args.max_parallel, MAX_PARALLEL_CAP)
    if max_parallel != args.max_parallel:
        print(f"note: --max-parallel capped at {MAX_PARALLEL_CAP}", file=sys.stderr)

    skills_dir = REPO / "skills"
    pack_skills = pack_skill_names(skills_dir)
    if args.skill not in pack_skills:
        raise UsageError(f"no skill {args.skill!r} in {skills_dir} (have: {sorted(pack_skills)})")
    queries = load_queries(REPO / "evals" / "triggers" / f"{args.skill}.json")
    if args.only_first and args.skip:
        raise UsageError("--only-first and --skip cannot be combined")
    if args.skip < 0 or args.skip >= len(queries):
        raise UsageError(f"--skip must be between 0 and {len(queries) - 1}")
    queries = queries[:1] if args.only_first else queries[args.skip :]

    fixture: Path | None = None
    if args.fixture is not None:
        fixtures_dir = REPO / "evals" / "fixtures"
        fixture = fixtures_dir / args.fixture
        if not _FIXTURE_NAME.fullmatch(args.fixture) or not fixture.is_dir():
            have = sorted(p.name for p in fixtures_dir.glob("*") if p.is_dir())
            raise UsageError(f"no fixture {args.fixture!r} in {fixtures_dir} (have: {have})")

    resolver = _load_resolver()
    binary = resolver._codex_binary()  # noqa: SLF001 - the one finder; duplicating it would drift
    if binary is None:
        raise CliUnavailable("the Codex CLI was not found (PATH, $CODEX_CLI_PATH, ChatGPT app)")
    installed = resolver.codex_home() / "skills" / args.skill / "SKILL.md"
    if not installed.is_file():
        raise CliUnavailable(
            f"{args.skill} is not installed ({installed} is missing): run install.sh"
        )
    check_chatgpt_login(binary)
    model, effort = resolve_model(resolver, args.tier, args.effort)

    cfg = RunConfig(
        binary,
        model,
        effort,
        args.skill,
        pack_skills,
        resolver.codex_home(),
        args.timeout,
        args.events_dir,
        args.allow_apps,
        fixture,
    )
    if args.allow_apps:
        print("note: --allow-apps is on: connector calls can make real writes", file=sys.stderr)

    def progress(label: str, result: RunResult) -> None:
        if result.error:
            state = "error"
        elif result.triggered:
            state = f"triggered ({result.detected_by})"
        else:
            state = "no trigger"
        print(f"  {label}: {state} ({result.seconds:.0f}s)", file=sys.stderr)

    outcomes = asyncio.run(
        gather_outcomes(
            queries, args.runs, max_parallel, lambda q, label: run_once(cfg, q, label), progress
        )
    )
    print(
        to_json(args.skill, model, effort, outcomes)
        if args.json
        else render(args.skill, model, effort, outcomes)
    )
    return EXIT_ERRORED_RUNS if any(o.errors for o in outcomes) else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except CliUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NO_CLI
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
