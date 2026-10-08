"""scripts/codex_usage.py against a fake Codex home built in tmp.

Every test points CODEX_HOME and HOME at a throwaway directory, so nothing here can read
the real ~/.codex or ~/.agents. The fake index is a WAL-mode database whose newest row is
still in the -wal file, the way the live one is while Codex is running.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "codex_usage.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("codex_usage_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


cu = _load()
REAL_LISTED_CATALOG_SLUGS = cu.listed_catalog_slugs

BASE = 1_791_380_000.0  # a Wednesday morning in October 2026; only differences matter


def iso(offset: float) -> str:
    return datetime.fromtimestamp(BASE + offset, UTC).isoformat().replace("+00:00", "Z")


def local(offset: float) -> str:
    """A --since/--until argument for BASE+offset, written in the machine's local time."""
    return datetime.fromtimestamp(BASE + offset).strftime("%Y-%m-%dT%H:%M:%S")


def tid(n: int) -> str:
    return f"{n:08x}-0000-7000-8000-{n:012x}"


def event(offset: float, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"timestamp": iso(offset), "type": kind, "payload": payload}


def usage(inp: int, cached: int, out: int, reasoning: int = 0) -> dict[str, int]:
    return {
        "input_tokens": inp,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": 0,
        "output_tokens": out,
        "reasoning_output_tokens": reasoning,
        "total_tokens": inp + out,
    }


def limits(
    five: float | None, week: float | None, *, reset5: int = 1000, resetw: int = 9000
) -> Any:
    def meter(used: float | None, minutes: int, resets: int) -> Any:
        return {"used_percent": used, "window_minutes": minutes, "resets_at": resets}

    return {
        "limit_id": "codex",
        "primary": None if five is None else meter(five, 300, reset5),
        "secondary": None if week is None else meter(week, 10080, resetw),
    }


def rollout(
    start: float,
    *,
    secs: float = 10,
    tokens: dict[str, int] | None = None,
    model: str = "gpt-6-luna",
    effort: str = "low",
    tier: str | None = None,
    readings: Sequence[tuple[float, Any]] | None = None,
    extra: list[dict[str, Any]] | None = None,
    turn: str = "turn-1",
) -> list[dict[str, Any]]:
    """One turn: settings, a token record, optional meter readings, and any extra events."""
    lines = [
        event(start, "session_meta", {"id": "ignored"}),
        event(start, "event_msg", {"type": "task_started", "turn_id": turn}),
        event(start, "turn_context", {"model": model, "effort": effort}),
        event(
            start,
            "event_msg",
            {"type": "thread_settings_applied", "thread_settings": {"service_tier": tier}},
        ),
    ]
    lines += extra or []
    for offset, rate in readings or []:
        info = {"total_token_usage": tokens} if tokens else None
        lines.append(
            event(
                start + offset,
                "event_msg",
                {"type": "token_count", "info": info, "rate_limits": rate},
            )
        )
    if tokens:
        lines.append(
            event(
                start + secs, "token_usage_record", {"thread_token_usage": tokens, "turn_id": turn}
            )
        )
    lines.append(event(start + secs, "event_msg", {"type": "task_complete", "turn_id": turn}))
    return lines


class FakeCodex:
    def __init__(self, root: Path) -> None:
        self.home = root / "codex-home"
        (self.home / "sessions").mkdir(parents=True)
        for skill in ("eng", ".system/imagegen"):
            (self.home / "skills" / skill).mkdir(parents=True)
        (root / "home" / ".agents" / "skills" / "localskill").mkdir(parents=True)
        self.db = self._create("state_9.sqlite")

    def _create(self, name: str) -> sqlite3.Connection:
        # Kept open for the test's life: closing the last connection checkpoints the WAL away.
        db = sqlite3.connect(self.home / name, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute(
            "CREATE TABLE threads (id TEXT, rollout_path TEXT, created_at_ms INTEGER,"
            " updated_at_ms INTEGER, source TEXT, cwd TEXT, title TEXT, first_user_message TEXT,"
            " model TEXT, reasoning_effort TEXT, tokens_used INTEGER, agent_role TEXT)"
        )
        return db

    def thread(
        self,
        n: int,
        *,
        at: float,
        lines: list[Any] | None,
        parent: int | None = None,
        guardian: bool = False,
        role: str | None = None,
        model: str = "gpt-6-luna",
        tokens_used: int = 0,
        prompt: str = "do the thing",
        db: sqlite3.Connection | None = None,
    ) -> str:
        """Add a thread. `lines=None` leaves its rollout file missing."""
        thread_id = tid(n)
        path = self.home / "sessions" / f"rollout-{thread_id}.jsonl"
        if lines is not None:
            path.write_text(
                "\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n",
                encoding="utf-8",
            )
        if guardian:
            source = json.dumps({"subagent": {"other": "guardian"}})
        elif parent is not None:
            spawn = {"parent_thread_id": tid(parent), "depth": 1, "agent_role": role}
            source = json.dumps({"subagent": {"thread_spawn": spawn}})
        else:
            source = "exec"
        (db or self.db).execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                thread_id,
                str(path),
                int((BASE + at) * 1000),
                int((BASE + at + 60) * 1000),
                source,
                "/work/repo",
                "",
                prompt,
                model,
                "low",
                tokens_used,
                role,
            ),
        )
        return thread_id


def guardian(codex: FakeCodex, n: int, at: float, tokens: dict[str, int]) -> str:
    """An auto-review thread: no parent id, the model Codex gives its approver."""
    lines = rollout(at, model="codex-auto-review", tokens=tokens)
    return codex.thread(n, at=at, guardian=True, model="codex-auto-review", lines=lines)


@pytest.fixture(autouse=True)
def no_real_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unpriced-model check reads the live Codex catalog; no test may reach the real one."""
    monkeypatch.setattr(cu, "listed_catalog_slugs", lambda: [])


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeCodex]:
    fake = FakeCodex(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(fake.home))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield fake
    fake.db.close()


def run_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert cu.main([*args, "--json"]) == 0
    result: dict[str, Any] = json.loads(capsys.readouterr().out)
    return result


def thread_of(report: dict[str, Any], n: int) -> dict[str, Any]:
    for run in report["runs"]:
        for thread in run["threads"]:
            if thread["thread_id"] == tid(n):
                found: dict[str, Any] = thread
                return found
    raise AssertionError(f"thread {n} not in report")


# --- the index ---------------------------------------------------------------------------


def test_a_row_still_in_the_wal_is_read_and_a_plain_copy_of_the_db_would_miss_it(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(100, 0, 10)))
    codex.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    codex.thread(2, at=100, lines=rollout(100, tokens=usage(200, 0, 20)))
    wal = codex.home / "state_9.sqlite-wal"
    assert wal.stat().st_size > 0

    report = run_json(capsys)
    assert {r["run_id"] for r in report["runs"]} == {tid(1), tid(2)}

    # Copying the main file alone would have shown one row: the second lives only in the WAL.
    only_main = codex.home.parent / "only-main.sqlite"
    only_main.write_bytes((codex.home / "state_9.sqlite").read_bytes())
    seen = sqlite3.connect(only_main).execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    assert seen == 1


def test_the_highest_numbered_index_wins(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    old = codex._create("state_5.sqlite")
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(1, 0, 1)), db=old)
    codex.thread(2, at=10, lines=rollout(10, tokens=usage(1, 0, 1)))
    report = run_json(capsys)
    assert [r["run_id"] for r in report["runs"]] == [tid(2)]
    old.close()


def test_a_changed_threads_table_is_reported_not_guessed_at(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.db.execute("ALTER TABLE threads DROP COLUMN tokens_used")
    assert cu.main([]) == 1
    assert "tokens_used" in capsys.readouterr().err


def test_nothing_is_ever_written_under_the_codex_home(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(100, 0, 10)))
    before = {p: p.stat().st_mtime_ns for p in codex.home.rglob("*") if p.is_file()}
    run_json(capsys)
    cu.main(["--summary"])
    after = {p: p.stat().st_mtime_ns for p in codex.home.rglob("*") if p.is_file()}
    assert before == after
    with pytest.raises(SystemExit) as refused:
        cu.main(["--csv", str(codex.home / "usage.csv")])
    assert refused.value.code == 2


# --- grouping -----------------------------------------------------------------------------


def test_a_run_is_the_root_and_every_descendant_including_a_grandchild(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(1000, 0, 100)))
    codex.thread(2, at=1, parent=1, role="explorer", lines=rollout(1, tokens=usage(2000, 0, 200)))
    codex.thread(3, at=2, parent=2, role="worker", lines=rollout(2, tokens=usage(3000, 0, 300)))
    codex.thread(4, at=500, lines=rollout(500, tokens=usage(10, 0, 1)))

    report = run_json(capsys)
    assert [r["run_id"] for r in report["runs"]] == [tid(1), tid(4)]
    first = report["runs"][0]
    assert [t["thread_id"] for t in first["threads"]] == [tid(1), tid(2), tid(3)]
    assert first["tokens"] == 1100 + 2200 + 3300
    assert thread_of(report, 3)["parent_id"] == tid(2)


def test_a_child_whose_parent_left_the_index_becomes_its_own_run(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(2, at=1, parent=99, lines=rollout(1, tokens=usage(5, 0, 5)))
    report = run_json(capsys)
    assert [r["run_id"] for r in report["runs"]] == [tid(2)]


# --- guardians ----------------------------------------------------------------------------


def test_a_guardian_inside_exactly_one_run_is_attributed_to_it(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(1, at=0, lines=rollout(0, secs=60, tokens=usage(1000, 0, 100)))
    codex.thread(2, at=1000, lines=rollout(1000, tokens=usage(1000, 0, 100)))
    guardian(codex, 3, 10, usage(500, 0, 50))

    report = run_json(capsys)
    assert [t["thread_id"] for t in report["runs"][0]["threads"]] == [tid(1), tid(3)]
    assert report["unattributed_auto_review"] == []
    guard = thread_of(report, 3)
    assert guard["kind"] == "guardian" and guard["est_credits"] is None
    # The run's credits are the priced threads only, and say so.
    assert report["runs"][0]["credits_partial"] is True
    assert report["runs"][0]["tokens"] == 1100 + 550


def test_a_guardian_overlapping_two_runs_is_unattributed(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(1, at=0, lines=rollout(0, secs=60, tokens=usage(1000, 0, 100)))
    codex.thread(2, at=30, lines=rollout(30, secs=60, tokens=usage(1000, 0, 100)))
    for n, at in ((3, 40), (4, 10), (5, 5000)):  # both runs, only the first, neither
        guardian(codex, n, at, usage(10, 0, 1))

    report = run_json(capsys)
    assert {t["thread_id"] for t in report["unattributed_auto_review"]} == {tid(3), tid(5)}
    assert [t["thread_id"] for t in report["runs"][0]["threads"]] == [tid(1), tid(4)]
    assert cu.main([]) == 0
    assert "unattributed auto-review: 2 thread(s)" in capsys.readouterr().out


# --- credits ------------------------------------------------------------------------------


def test_credits_follow_the_published_rates_and_reasoning_is_not_added_twice() -> None:
    plain = cu.Usage(input=1_000_000, cached=400_000, output=100_000, reasoning=0, total=1_100_000)
    thinking = cu.Usage(
        input=1_000_000, cached=400_000, output=100_000, reasoning=90_000, total=1_100_000
    )
    # luna: 600k uncached * 2.5 + 400k cached * 0.25 + 100k output * 12.5, per million
    assert cu.estimate_credits(plain, "gpt-6-luna", fast=False) == pytest.approx(2.85)
    assert cu.estimate_credits(thinking, "gpt-6-luna", fast=False) == pytest.approx(2.85)
    assert cu.estimate_credits(plain, "gpt-6-luna", fast=True) == pytest.approx(2.85 * 2.5)
    assert cu.estimate_credits(plain, "gpt-6-astra", fast=False) == pytest.approx(
        (600_000 * 250 + 400_000 * 25 + 100_000 * 1250) / 1e6
    )


def test_an_unknown_model_reports_tokens_and_no_credits(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(
        1, at=0, model="codex-auto-review",
        lines=rollout(0, model="codex-auto-review", tokens=usage(1000, 0, 100)),
    )  # fmt: skip
    assert thread_of(run_json(capsys), 1)["est_credits"] is None
    assert cu.main([]) == 0
    out = capsys.readouterr().out
    assert "n/a" in out and "1,100" in out


def test_fast_mode_comes_from_the_threads_service_tier(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    tokens = usage(1_000_000, 0, 0)
    codex.thread(1, at=0, lines=rollout(0, tokens=tokens, tier="priority"))
    codex.thread(2, at=100, lines=rollout(100, tokens=tokens, tier="default"))
    codex.thread(3, at=200, lines=rollout(200, tokens=tokens, tier=None))
    report = run_json(capsys)
    assert [thread_of(report, n)["speed"] for n in (1, 2, 3)] == ["fast", "std", "std"]
    assert thread_of(report, 1)["est_credits"] == pytest.approx(2.5 * 2.5)
    assert thread_of(report, 2)["est_credits"] == pytest.approx(2.5)


def test_a_thread_that_switched_model_is_priced_at_the_last_one_and_says_so(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    switch = [event(2, "turn_context", {"model": "gpt-6-sol", "effort": "high"})]
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(1_000_000, 0, 0), extra=switch))
    thread = thread_of(run_json(capsys), 1)
    assert (thread["model"], thread["effort"]) == ("gpt-6-sol", "high")
    assert thread["est_credits"] == pytest.approx(50.0)
    assert any("mixed model or speed" in note for note in thread["notes"])


# --- skills -------------------------------------------------------------------------------


def _call(offset: float, kind: str, field: str, text: str) -> dict[str, Any]:
    return event(offset, "response_item", {"type": kind, field: text})


def _user(offset: float, text: str) -> dict[str, Any]:
    body = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}
    return event(offset, "response_item", body)


def test_skills_are_detected_from_tool_calls_and_from_mentions_but_only_if_installed(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    home = str(codex.home)
    extra = [
        _call(
            1, "function_call", "arguments", json.dumps({"cmd": f"cat {home}/skills/eng/SKILL.md"})
        ),
        _call(2, "custom_tool_call", "input", f"cat {home}/skills/.system/imagegen/SKILL.md"),
        _call(3, "custom_tool_call", "input", "cat /plugins/x/skills/ghost/SKILL.md"),
        _user(4, "please run $localskill and ask $nobody"),
        # Codex injects AGENTS.md as a user message that names every skill; it is not use.
        _user(5, "# AGENTS.md instructions\n\nUse $eng or $imagegen"),
        _user(6, "<environment_context>$eng</environment_context>"),
    ]
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(10, 0, 1), extra=extra))
    codex.thread(
        2, at=500, lines=rollout(500, tokens=usage(10, 0, 1), extra=[_user(501, "$eng go")])
    )

    report = run_json(capsys)
    assert report["runs"][0]["skills"] == ["eng", "imagegen", "localskill"]
    assert report["runs"][1]["skills"] == ["eng"]

    only = run_json(capsys, "--skill", "imagegen")
    assert [r["run_id"] for r in only["runs"]] == [tid(1)]


def test_the_injected_agents_md_and_environment_messages_are_not_skill_use(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    # AGENTS.md names every installed skill; counting it would credit every run with all of them.
    injected = [
        _user(1, "# AGENTS.md instructions\n\nUse $eng or $imagegen"),
        _user(2, "<environment_context>$eng</environment_context>"),
    ]
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(10, 0, 1), extra=injected))
    assert run_json(capsys)["runs"][0]["skills"] == []


# --- selection ----------------------------------------------------------------------------


def test_since_and_until_cut_by_run_start_in_local_time(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    for n, at in ((1, 0), (2, 3600), (3, 7200)):
        codex.thread(n, at=at, lines=rollout(at, tokens=usage(10, 0, 1)))

    def ids(*args: str) -> list[str]:
        return [r["run_id"] for r in run_json(capsys, *args)["runs"]]

    assert ids("--since", local(3600)) == [tid(2), tid(3)]
    assert ids("--since", local(3600), "--until", local(7200)) == [tid(2)]
    assert ids("--last", "1") == [tid(3)]
    assert ids("--run", tid(2)[:9]) == [tid(2)]


def test_a_bare_date_as_until_covers_that_whole_day() -> None:
    noon = datetime(2026, 10, 7, 12, 0).astimezone().timestamp()
    assert cu.parse_when("2026-10-07", end=False) < noon < cu.parse_when("2026-10-07", end=True)
    assert cu.parse_when("2026-10-07T12:00", end=True) == noon


def test_the_default_shows_only_the_last_ten_runs(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    for n in range(1, 13):
        codex.thread(n, at=n * 100, lines=rollout(n * 100, tokens=usage(10, 0, 1)))
    assert cu.main([]) == 0
    table = capsys.readouterr().out.split("\n\n")[0].splitlines()
    assert len(table) == 1 + 10
    assert len(run_json(capsys, "--since", "2000-01-01")["runs"]) == 12


def test_run_ids_grow_until_runs_that_share_a_prefix_are_told_apart(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(10, 0, 1)))
    codex.thread(2, at=100, lines=rollout(100, tokens=usage(10, 0, 1)))
    one, two = (tid(1), tid(2))
    twin = f"{one[:8]}-ffff-7000-8000-{2:012x}"
    codex.db.execute("UPDATE threads SET id = ? WHERE id = ?", (twin, two))
    runs = cu.collect(codex.home).runs
    short = cu.short_ids(runs)
    # They share 9 characters, so the shortest telling prefix is 10, not the usual 8.
    assert short[one] == one[:10] and short[twin] == twin[:10]


# --- the report ---------------------------------------------------------------------------


def test_csv_has_the_documented_columns_and_the_meter_only_on_the_root_row(
    codex: FakeCodex, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(
        1,
        at=0,
        lines=rollout(
            0,
            tokens=usage(1000, 400, 100, 30),
            readings=[(1, limits(10, 20)), (9, limits(14.5, 20.5))],
        ),
    )
    codex.thread(2, at=1, parent=1, role="explorer", lines=rollout(1, tokens=usage(50, 0, 5)))
    guardian(codex, 3, 5000, usage(5, 0, 1))
    out = tmp_path / "usage.csv"
    assert cu.main(["--csv", str(out)]) == 0
    assert "wrote 3 thread row(s)" in capsys.readouterr().out

    with out.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert reader.fieldnames == cu.CSV_COLUMNS
    assert cu.CSV_COLUMNS[:18] == [
        "run_id", "run_start", "skills", "thread_id", "parent_id", "role", "model", "effort",
        "speed", "input", "cached", "uncached", "output", "reasoning", "total", "est_credits",
        "duration_s", "cwd",
    ]  # fmt: skip
    root, child, loose = rows
    assert (root["input"], root["cached"], root["uncached"], root["output"]) == (
        "1000",
        "400",
        "600",
        "100",
    )
    assert (root["reasoning"], root["total"]) == ("30", "1100")
    assert float(root["est_credits"]) == pytest.approx((600 * 2.5 + 400 * 0.25 + 100 * 12.5) / 1e6)
    assert float(root["meter_5h_delta"]) == pytest.approx(4.5)
    assert float(root["meter_week_delta"]) == pytest.approx(0.5)
    assert child["run_id"] == root["run_id"] and child["meter_5h_delta"] == ""
    assert child["parent_id"] == tid(1) and child["role"] == "explorer"
    assert loose["run_id"] == "unattributed" and loose["est_credits"] == ""


def test_the_summary_aggregates_by_skill_and_by_model_with_medians(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    use_eng = [_user(1, "$eng")]
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(1000, 0, 0), extra=use_eng))
    codex.thread(
        2, at=100, lines=rollout(100, tokens=usage(3000, 0, 0), extra=[_user(101, "$eng")])
    )
    codex.thread(3, at=200, lines=rollout(200, tokens=usage(500, 0, 0)))
    assert cu.main(["--summary"]) == 0
    out = capsys.readouterr().out
    eng = next(line for line in out.splitlines() if line.startswith("eng "))
    assert eng.split() == ["eng", "2", "4,000", "0.01", "2,000", "0.01"]
    assert "(no skill)" in out
    assert (
        next(line for line in out.splitlines() if line.startswith("gpt-6-luna")).split()[1] == "3"
    )


# --- unpriced models -----------------------------------------------------------------------


def test_every_listed_model_without_a_rate_gets_a_warning_that_names_it() -> None:
    warnings = cu.unpriced_warnings(["gpt-6.1-sol", "gpt-7-sol", "gpt-7-luna", "gpt-7-sol"])
    assert [w.split()[1] for w in warnings] == ["gpt-7-luna", "gpt-7-sol"]
    assert "CREDIT_RATES" in warnings[0] and "pricing" in warnings[0]


def test_a_catalog_whose_listed_models_are_all_priced_warns_about_nothing() -> None:
    assert cu.unpriced_warnings(list(cu.CREDIT_RATES)) == []
    assert cu.unpriced_warnings([]) == []


def test_the_warning_goes_to_stderr_and_ends_the_summary_but_stdout_json_stays_clean(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cu, "listed_catalog_slugs", lambda: ["gpt-6-luna", "gpt-7-sol"])
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(1000, 0, 0)))

    assert cu.main(["--summary"]) == 0
    done = capsys.readouterr()
    assert "gpt-7-sol is listed in the Codex catalog" in done.err
    assert done.out.rstrip().splitlines()[-1].startswith("warning: gpt-7-sol")

    assert cu.main(["--json"]) == 0
    done = capsys.readouterr()
    assert "gpt-7-sol" in done.err
    assert "warning" not in done.out  # stdout is still parseable JSON
    json.loads(done.out)


def test_the_catalog_reader_returns_only_listed_slugs_and_survives_no_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "codex-home"
    home.mkdir()
    entries = [
        {"slug": slug, "visibility": vis, "supported_reasoning_levels": [{"effort": "low"}]}
        for slug, vis in (("gpt-7-sol", "list"), ("gpt-hidden", "hide"))
    ]
    (home / "models_cache.json").write_text(json.dumps({"models": entries}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    real_loader = cu._load_resolver

    def without_the_desktop_apps_cli() -> Any:
        module = real_loader()
        monkeypatch.setattr(module, "BUNDLED_CODEX_APP", tmp_path / "absent")
        return module

    monkeypatch.setattr(cu, "_load_resolver", without_the_desktop_apps_cli)

    assert REAL_LISTED_CATALOG_SLUGS() == ["gpt-7-sol"]
    (home / "models_cache.json").unlink()
    assert REAL_LISTED_CATALOG_SLUGS() == []


# --- meters -------------------------------------------------------------------------------


def test_meter_delta_runs_from_the_earliest_to_the_latest_reading_across_threads(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(
        1,
        at=0,
        lines=rollout(
            0, tokens=usage(10, 0, 1), readings=[(1, limits(10, 20)), (4, limits(11, 20))]
        ),
    )
    codex.thread(
        2,
        at=2,
        parent=1,
        lines=rollout(2, tokens=usage(10, 0, 1), readings=[(5, limits(13.5, 21))]),
    )
    meter = run_json(capsys)["runs"][0]["meter"]
    assert meter["five_hour"] == {"start": 10.0, "end": 13.5, "delta": 3.5}
    assert meter["weekly"]["delta"] == pytest.approx(1.0)
    assert meter["flags"] == []


def test_a_window_reset_or_an_overlapping_run_flags_the_delta(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    resetting = [(1, limits(90, 20, reset5=1000)), (9, limits(3, 20, reset5=19000))]
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(10, 0, 1), readings=resetting))
    codex.thread(
        2,
        at=5,
        lines=rollout(5, tokens=usage(10, 0, 1), readings=[(1, limits(3, 20, reset5=19000))]),
    )
    codex.thread(
        3,
        at=900,
        lines=rollout(
            900, tokens=usage(10, 0, 1), readings=[(1, limits(3, 20)), (4, limits(4, 20))]
        ),
    )
    report = run_json(capsys)
    flags = {r["run_id"]: r["meter"]["flags"] for r in report["runs"]}
    assert flags[tid(1)] == ["5h window reset", "another run overlapped"]
    assert flags[tid(2)] == ["another run overlapped"]
    assert flags[tid(3)] == []
    assert cu.main([]) == 0
    assert "!" in capsys.readouterr().out


def test_the_weekly_meter_is_found_by_window_length_and_other_limits_are_ignored(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    weekly_only: dict[str, Any] = {
        "limit_id": "codex",
        "primary": {"used_percent": 5.0, "window_minutes": 10080, "resets_at": 9000},
        "secondary": None,
    }
    later = {**weekly_only, "primary": {**weekly_only["primary"], "used_percent": 7.0}}
    premium = {"limit_id": "premium", "primary": {"used_percent": 99.0, "window_minutes": 300}}
    readings = [(1, weekly_only), (2, premium), (8, later)]
    codex.thread(1, at=0, lines=rollout(0, tokens=usage(10, 0, 1), readings=readings))
    meter = run_json(capsys)["runs"][0]["meter"]
    assert meter["five_hour"] is None
    assert meter["weekly"]["delta"] == pytest.approx(2.0)


# --- damaged records ----------------------------------------------------------------------


def test_a_missing_rollout_falls_back_to_the_index_total_and_says_so(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    codex.thread(1, at=0, lines=None, tokens_used=4321)
    codex.thread(2, at=500, lines=rollout(500, tokens=usage(10, 0, 1)))
    report = run_json(capsys)
    gone = thread_of(report, 1)
    assert gone["tokens"]["total"] == 4321
    assert gone["est_credits"] is None
    assert any(n.startswith("partial") for n in gone["notes"])
    assert cu.main([]) == 0
    assert "4,321~" in capsys.readouterr().out


def test_malformed_lines_are_skipped_and_counted_not_fatal(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    lines: list[Any] = rollout(0, tokens=usage(1000, 0, 100))
    lines.insert(2, "{this is not json token_count")
    lines.insert(3, "plain garbage")
    lines.append('{"timestamp": "2026-10-07T13:0')  # a tail cut off mid-write
    codex.thread(1, at=0, lines=lines)
    report = run_json(capsys)
    thread = thread_of(report, 1)
    assert thread["malformed_lines"] == 3
    assert thread["tokens"]["total"] == 1100
    assert cu.main([]) == 0
    assert "3 malformed rollout line(s) skipped" in capsys.readouterr().out


def test_a_token_count_with_no_info_is_ignored_in_favor_of_the_record(
    codex: FakeCodex, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = rollout(0, tokens=None, readings=[(1, limits(1, 1))])
    lines.insert(-1, event(5, "token_usage_record", {"thread_token_usage": usage(70, 0, 7)}))
    codex.thread(1, at=0, lines=lines)
    assert thread_of(run_json(capsys), 1)["tokens"]["total"] == 77


def test_no_index_at_all_exits_1_with_a_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cu.main([]) == 1
    assert "no state_N.sqlite" in capsys.readouterr().err


def test_help_says_ephemeral_runs_leave_no_record(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cu.main(["--help"])
    assert "--ephemeral" in capsys.readouterr().out
