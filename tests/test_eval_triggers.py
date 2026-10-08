"""scripts/eval_triggers.py: event parsing, pass/fail math, and the run loop.

Nothing here starts the real Codex CLI. Event fixtures are trimmed from real
`codex exec --json` output and from a real session rollout file (CLI 0.160.0, 2026-10-08,
home path generalised). The run loop is exercised against small fake `codex` scripts written
into tmp.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "eval_triggers.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_triggers_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


et = _load()

PACK = frozenset({"plan-ticket", "write-ticket", "daily-grooming"})

# Real events: the agent opens the skill with a shell command.
READ_PLAN_NEXT = json.dumps(
    {
        "type": "item.started",
        "item": {
            "id": "item_1",
            "type": "command_execution",
            "command": (
                '/bin/zsh -lc "cat /home/user/.codex/skills/plan-ticket/SKILL.md '
                "&& pwd && rg --files -g 'AGENTS.md' | head -60\""
            ),
            "aggregated_output": "",
            "exit_code": None,
            "status": "in_progress",
        },
    }
)
READ_WRITE_TICKET = READ_PLAN_NEXT.replace("plan-ticket", "write-ticket")
# The agent's own words may name a path without having opened it.
MESSAGE_QUOTING_PATH = json.dumps(
    {
        "type": "item.completed",
        "item": {
            "id": "item_0",
            "type": "agent_message",
            "text": "I will load ~/.codex/skills/plan-ticket/SKILL.md next.",
        },
    }
)
THREAD_ID = "01a11c1b-3598-7b30-ac23-dfbf0a5af9f2"
THREAD_STARTED = json.dumps({"type": "thread.started", "thread_id": THREAD_ID})
TURN_STARTED = '{"type":"turn.started"}'
TURN_COMPLETED = json.dumps(
    {
        "type": "turn.completed",
        "usage": {
            "input_tokens": 120893,
            "cached_input_tokens": 74496,
            "cache_write_input_tokens": 0,
            "output_tokens": 664,
            "reasoning_output_tokens": 0,
        },
    }
)
# The CLI's own docs name this event; no run in the pilot produced one, so its shape is assumed.
TURN_FAILED = '{"type":"turn.failed","error":{"message":"usage limit reached"}}'


def scan(*lines: str, target: str = "plan-ticket") -> Any:
    s = et.RunScan(target, PACK)
    for line in lines:
        s.feed(line)
    return s


# ----------------------------------------------------------------- event parsing


def test_a_shell_read_of_the_target_skill_triggers() -> None:
    s = scan(TURN_STARTED, READ_PLAN_NEXT)
    assert s.triggered and s.finished and s.neighbours == []


@pytest.mark.parametrize(
    "command",
    [
        "cat ~/.codex/skills/plan-ticket/SKILL.md",
        "sed -n 1,200p /anywhere/codex-pack/skills/plan-ticket/SKILL.md",
        "cat skills/plan-ticket/SKILL.md",
        "cd $CODEX_HOME && head -40 'skills/plan-ticket/SKILL.md'",
    ],
)
def test_every_spelling_of_the_path_counts(command: str) -> None:
    event = {"type": "item.started", "item": {"type": "command_execution", "command": command}}
    assert et.skill_reads(event) == ["plan-ticket"]


@pytest.mark.parametrize(
    "command",
    [
        "cat ~/.codex/skills/plan-ticket/references/registry.md",  # a reference, not the skill
        "ls ~/.codex/skills/plan-ticket",
        "cat ~/.codex/skills/plan-ticket/SKILL.md.bak",
    ],
)
def test_other_files_in_the_skill_folder_do_not_count(command: str) -> None:
    event = {"type": "item.started", "item": {"type": "command_execution", "command": command}}
    assert et.skill_reads(event) == []


def test_the_agents_own_words_do_not_count() -> None:
    s = scan(MESSAGE_QUOTING_PATH, TURN_COMPLETED)
    assert not s.triggered and s.turn_done


def test_command_output_is_not_searched() -> None:
    event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "ls",
            "aggregated_output": "skills/plan-ticket/SKILL.md\n",
        },
    }
    assert et.skill_reads(event) == []


def test_a_neighbour_is_recorded_once_and_only_if_it_is_a_pack_skill() -> None:
    other = READ_PLAN_NEXT.replace("plan-ticket", "cloudflare")  # installed, but not in this pack
    s = scan(READ_WRITE_TICKET, READ_WRITE_TICKET, other, TURN_COMPLETED)
    assert not s.triggered
    assert s.neighbours == ["write-ticket"]


def test_a_neighbour_read_before_the_target_is_kept() -> None:
    s = scan(READ_WRITE_TICKET, READ_PLAN_NEXT)
    assert s.triggered and s.neighbours == ["write-ticket"]


def test_turn_completed_carries_the_usage_and_ends_the_run() -> None:
    s = scan(READ_WRITE_TICKET, TURN_COMPLETED)
    assert s.finished and not s.triggered
    assert s.usage == et.Usage(120893, 74496, 664, 0)
    assert s.usage.total == 120893 + 664  # input already includes the cached part


def test_a_run_is_not_finished_until_something_decides_it() -> None:
    assert not scan(TURN_STARTED, READ_WRITE_TICKET).finished


def test_turn_failed_is_an_error_not_a_miss() -> None:
    s = scan(TURN_FAILED)
    assert s.finished and s.error == "turn failed: usage limit reached"


def test_garbage_lines_are_skipped() -> None:
    s = scan("", "not json", "[1, 2]", '{"type":"item.started","item":"x"}', READ_PLAN_NEXT)
    assert s.triggered and s.error is None


# --------------------------------------------------------------------- pass / fail


def run(triggered: bool | None, error: str | None = None, **kw: Any) -> Any:
    return et.RunResult(triggered, kw.get("neighbours", []), error, kw.get("usage"), 1.0)


def outcome(should: bool, *runs: Any) -> Any:
    return et.QueryOutcome(1, "q", should, list(runs))


@pytest.mark.parametrize(
    ("should", "results", "passed"),
    [
        (True, [True], True),
        (True, [False], False),
        (True, [True, True, False], True),  # 2/3 is above half
        (True, [True, False], False),  # exactly half passes neither kind
        (False, [True, False], False),
        (False, [False], True),
        (False, [True, False, False], True),  # 1/3 is below half
        (False, [True], False),
    ],
)
def test_pass_fail_math(should: bool, results: list[bool], passed: bool) -> None:
    assert outcome(should, *[run(r) for r in results]).passed is passed


def test_an_errored_run_is_left_out_of_the_rate_never_counted_as_no() -> None:
    o = outcome(True, run(True), run(None, "timed out"), run(None, "timed out"))
    assert o.trigger_rate == 1.0
    assert o.passed is True
    assert o.errors == ["timed out", "timed out"]


def test_a_query_with_only_errored_runs_is_not_judged() -> None:
    o = outcome(False, run(None, "timed out"))
    assert o.trigger_rate is None and o.passed is None


def test_summary_splits_positives_and_negatives_and_lists_failures() -> None:
    outcomes = [
        et.QueryOutcome(1, "a", True, [run(True)]),
        et.QueryOutcome(2, "b", True, [run(False, neighbours=["write-ticket"])]),
        et.QueryOutcome(3, "c", False, [run(False)]),
        et.QueryOutcome(4, "d", False, [run(False)]),
        et.QueryOutcome(5, "e", False, [run(None, "boom")]),
    ]
    s = et.summarize(outcomes)
    assert s["judged"] == 4 and s["unjudged"] == ["e"]
    assert s["pass_rate"] == 0.75
    assert s["positive_pass_rate"] == 0.5
    assert s["negative_pass_rate"] == 1.0
    assert s["failures"] == [
        {
            "number": 2,
            "query": "b",
            "should_trigger": True,
            "trigger_rate": 0.0,
            "neighbours": ["write-ticket"],
        }
    ]


def test_summary_with_nothing_judged_has_no_rates() -> None:
    s = et.summarize([et.QueryOutcome(1, "a", True, [run(None, "boom")])])
    assert s["pass_rate"] is None and s["positive_pass_rate"] is None


def test_tokens_add_up_over_runs_that_have_a_count() -> None:
    usage = et.Usage(100, 50, 10, 0)
    o = outcome(False, run(False, usage=usage), run(True), run(False, usage=usage))
    assert o.tokens == 220
    assert outcome(True, run(True)).tokens is None


# ---------------------------------------------------------------------- eval files


def test_every_shipped_eval_file_loads_and_names_a_real_skill() -> None:
    files = sorted((REPO / "evals" / "triggers").glob("*.json"))
    assert files
    for path in files:
        cases = et.load_queries(path)
        assert (REPO / "skills" / path.stem / "SKILL.md").is_file(), path
        assert {c.should_trigger for c in cases} == {True, False}, path
        assert [c.number for c in cases] == list(range(1, len(cases) + 1))


@pytest.mark.parametrize(
    "body",
    ["not json", "[]", "{}", '[{"query": "x"}]', '[{"query": "", "should_trigger": true}]',
     '[{"query": "x", "should_trigger": "yes"}]', "[1]"],
)  # fmt: skip
def test_a_malformed_eval_file_is_a_usage_error(tmp_path: Path, body: str) -> None:
    path = tmp_path / "x.json"
    path.write_text(body)
    with pytest.raises(et.UsageError):
        et.load_queries(path)


def test_a_missing_eval_file_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(et.UsageError):
        et.load_queries(tmp_path / "nope.json")


# ------------------------------------------------------------- command and environment


def test_the_command_is_the_read_only_json_form_with_the_model_and_effort() -> None:
    assert et.build_command("/bin/codex", "gpt-x", "low", "plan it") == [
        "/bin/codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--disable",
        "apps",
        "--sandbox",
        "read-only",
        "-m",
        "gpt-x",
        "-c",
        "model_reasoning_effort=low",
        "plan it",
    ]
    assert "--ephemeral" not in et.build_command("c", "m", "low", "q")  # codex_usage needs the run


def test_billing_keys_never_reach_the_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    monkeypatch.setenv("KEEP_ME", "1")
    env = et.child_env()
    assert "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env
    assert env["KEEP_ME"] == "1"


# ---------------------------------------------------------------- the session rollout

# A real rollout, trimmed: the skills catalogue every session carries (it names each SKILL.md
# by a short path), then the `$eng` skill Codex injected as a user message, then the agent's
# first reply. Home path generalised; the injected text cut after the frontmatter.
CATALOGUE: dict[str, Any] = {
    "type": "response_item",
    "payload": {
        "type": "message",
        "role": "developer",
        "content": [
            {
                "type": "input_text",
                "text": "<skills_instructions>\n## Skills\n- eng: Use when asked to fix a bug, "
                "build a feature or refactor. (file: r0/eng/SKILL.md)\n</skills_instructions>",
            }
        ],
    },
}
INJECTED_ENG: dict[str, Any] = {
    "type": "response_item",
    "payload": {
        "type": "message",
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": "<skill>\n<name>eng</name>\n"
                "<path>/home/user/codex-pack/skills/eng/SKILL.md</path>\n---\nname: eng\n"
                "description: Use when asked to fix a bug, build a feature, refactor, change "
                "architecture or review a diff in a code repo.\n---\n\n# Engineering pass\n\n"
                "Do the job end to end in the repo you were pointed at.\n\n</skill>",
            }
        ],
    },
}
INJECTED_PLAN_TICKET = json.loads(
    json.dumps(INJECTED_ENG).replace("<name>eng</name>", "<name>plan-ticket</name>")
    .replace("skills/eng/", "skills/plan-ticket/")
)  # fmt: skip
ASSISTANT_REPLY: dict[str, Any] = {
    "type": "response_item",
    "payload": {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "I will inspect the repo first."}],
    },
}
SESSION_META: dict[str, Any] = {
    "type": "session_meta",
    "payload": {"id": THREAD_ID, "originator": "codex_exec", "cli_version": "0.160.0"},
}


def rollout_lines(*records: dict[str, Any]) -> list[str]:
    return [json.dumps({"ordinal": n, **r}) for n, r in enumerate(records)]


def write_rollout(
    home: Path, *records: dict[str, Any], thread_id: str = THREAD_ID, day: str = "2026/10/08"
) -> Path:
    """sessions/YYYY/MM/DD/rollout-<timestamp>-<thread id>.jsonl, the way Codex lays it out."""
    folder = home / "sessions" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-2026-10-08T11-21-47-{thread_id}.jsonl"
    path.write_text("\n".join(rollout_lines(SESSION_META, CATALOGUE, *records, ASSISTANT_REPLY)))
    return path


def test_an_injected_skill_is_found_in_the_rollout() -> None:
    lines = rollout_lines(SESSION_META, CATALOGUE, INJECTED_ENG, ASSISTANT_REPLY)
    assert et.injected_skills(lines) == ["eng"]


def test_the_catalogue_and_the_agents_words_are_not_an_injection() -> None:
    block = INJECTED_ENG["payload"]["content"][0]["text"]
    agent_quotes_it = {
        "type": "response_item",
        "payload": {"type": "message", "role": "assistant", "content": [{"text": block}]},
    }
    user_quotes_it_later = {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "see this:\n" + block}],
        },
    }
    lines = rollout_lines(SESSION_META, CATALOGUE, agent_quotes_it, user_quotes_it_later)
    assert et.injected_skills(lines) == []


def test_two_injections_come_back_in_order_and_once_each() -> None:
    lines = rollout_lines(INJECTED_PLAN_TICKET, INJECTED_ENG, INJECTED_ENG)
    assert et.injected_skills(lines) == ["plan-ticket", "eng"]


def test_garbage_and_half_written_rollout_lines_are_skipped() -> None:
    lines = ["", "not json", "[1]", '{"type":"response_item","payload":"x"}', '{"type":"resp']
    lines += rollout_lines(INJECTED_ENG)
    assert et.injected_skills(lines) == ["eng"]


def test_a_rollout_is_found_by_its_thread_id_alone(tmp_path: Path) -> None:
    other = write_rollout(tmp_path, thread_id="01a11c1b-0000-7b30-ac23-dfbf0a5af9f2")
    wanted = write_rollout(tmp_path, day="2026/10/07")
    assert et.find_rollout(tmp_path, THREAD_ID) == wanted
    assert et.find_rollout(tmp_path, "01a11c1b-3598-7b30-ac23-dfbf0a5af9ff") is None
    assert other.is_file()


def test_an_odd_thread_id_never_widens_the_search(tmp_path: Path) -> None:
    write_rollout(tmp_path)
    assert et.find_rollout(tmp_path, "*") is None
    assert et.find_rollout(tmp_path, "../*") is None


# ------------------------------------------------------------------- a fake codex


def fake_codex(tmp_path: Path, body: str, name: str = "codex") -> str:
    """An executable Python script standing in for the CLI. `argv`, `cwd` and `env` are
    pre-bound for `body`; it can print events and sleep like the real thing."""
    path = tmp_path / name
    path.write_text(
        f"#!{sys.executable}\nimport json, os, sys, time\n"
        "argv, cwd, env = sys.argv, os.getcwd(), dict(os.environ)\n" + body
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def emit(*events: str) -> str:
    return "".join(f"print({e!r}, flush=True)\n" for e in events)


def home_of(binary: str) -> Path:
    """The Codex home a test run uses: beside its fake binary, inside the test's tmp dir."""
    return Path(binary).parent / "codex-home"


def cfg(
    binary: str,
    timeout_s: float = 20.0,
    events_dir: Path | None = None,
    fixture: Path | None = None,
) -> Any:
    return et.RunConfig(
        binary, "gpt-x", "low", "plan-ticket", PACK, home_of(binary), timeout_s, events_dir,
        False, fixture,
    )  # fmt: skip


def run_once(config: Any, query: str = "plan my next ticket") -> Any:
    return asyncio.run(et.run_once(config, query, "q01-r1"))


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_run_stops_at_once_when_the_skill_is_read_and_the_process_is_killed(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "pid"
    binary = fake_codex(
        tmp_path,
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        + emit(TURN_STARTED, READ_PLAN_NEXT)
        + "time.sleep(60)\n",
    )
    started = time.monotonic()
    result = run_once(cfg(binary))
    assert time.monotonic() - started < 15
    assert result.triggered is True and result.error is None and result.stopped_early
    assert result.detected_by == "read"
    assert not alive(int(pid_file.read_text()))


def test_a_run_that_completes_without_the_skill_did_not_trigger(tmp_path: Path) -> None:
    binary = fake_codex(
        tmp_path, emit(THREAD_STARTED, TURN_STARTED, READ_WRITE_TICKET, TURN_COMPLETED)
    )
    write_rollout(home_of(binary))
    result = run_once(cfg(binary))
    assert result.triggered is False and result.error is None and result.detected_by is None
    assert result.neighbours == ["write-ticket"]
    assert result.usage is not None and result.usage.output_tokens == 664


def test_a_run_that_times_out_is_an_error_and_is_killed(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    binary = fake_codex(
        tmp_path,
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        + emit(TURN_STARTED)
        + "time.sleep(60)\n",
    )
    result = run_once(cfg(binary, timeout_s=1.0))
    assert result.triggered is None and result.error == "timed out after 1s"
    assert not alive(int(pid_file.read_text()))


def test_a_process_that_dies_before_finishing_is_an_error_with_its_stderr(tmp_path: Path) -> None:
    binary = fake_codex(
        tmp_path, emit(TURN_STARTED) + "print('auth required', file=sys.stderr)\nsys.exit(3)\n"
    )
    result = run_once(cfg(binary))
    assert result.triggered is None
    assert (
        result.error is not None and "exited 3" in result.error and "auth required" in result.error
    )


def test_a_failed_turn_is_an_error(tmp_path: Path) -> None:
    binary = fake_codex(tmp_path, emit(TURN_STARTED, TURN_FAILED))
    result = run_once(cfg(binary))
    assert result.triggered is None and result.error == "turn failed: usage limit reached"


def test_a_missing_binary_is_an_error_result(tmp_path: Path) -> None:
    result = run_once(cfg(str(tmp_path / "absent")))
    assert result.triggered is None and result.error is not None


def test_the_child_gets_an_empty_directory_no_stdin_and_no_billing_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    seen = tmp_path / "seen.json"
    binary = fake_codex(
        tmp_path,
        "json.dump({'argv': argv, 'listing': os.listdir(cwd), 'cwd': cwd,"
        " 'stdin': sys.stdin.read(), 'keys': [k for k in env if k.endswith('API_KEY')]}, "
        f"open({str(seen)!r}, 'w'))\n" + emit(TURN_COMPLETED),
    )
    run_once(cfg(binary), "plan #73")
    got = json.loads(seen.read_text())
    assert got["listing"] == [] and got["stdin"] == "" and got["keys"] == []
    assert got["argv"][-1] == "plan #73" and "--sandbox" in got["argv"]
    assert not Path(got["cwd"]).exists()  # the temp directory is removed afterwards


def test_raw_events_are_kept_when_asked(tmp_path: Path) -> None:
    binary = fake_codex(tmp_path, emit(TURN_STARTED, TURN_COMPLETED))
    kept = tmp_path / "events"
    run_once(cfg(binary, events_dir=kept))
    assert (kept / "q01-r1.jsonl").read_text().splitlines()[-1] == TURN_COMPLETED


def test_a_very_long_event_line_does_not_break_the_run(tmp_path: Path) -> None:
    big = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "x" * 300_000}}
    )
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, big, TURN_COMPLETED))
    write_rollout(home_of(binary))
    assert run_once(cfg(binary)).triggered is False


# --------------------------------------------------------------------- the fan-out


def test_errors_stay_errors_and_order_survives_parallel_runs() -> None:
    cases = [et.Case(n, f"q{n}", n % 2 == 1) for n in range(1, 6)]
    in_flight = 0
    peak = 0

    async def fake(query: str, label: str) -> Any:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02 * (6 - int(query[1])))  # later queries finish first
        in_flight -= 1
        if query == "q2":
            raise RuntimeError("boom")
        return run(query != "q4")

    done: list[str] = []
    outcomes = asyncio.run(
        et.gather_outcomes(cases, 2, 3, fake, lambda label, _r: done.append(label))
    )
    assert [o.number for o in outcomes] == [1, 2, 3, 4, 5]
    assert peak == 3
    assert len(done) == 10 and "q02-r2" in done
    assert outcomes[1].errors == ["RuntimeError: boom"] * 2
    assert outcomes[1].passed is None  # not "did not trigger"
    assert outcomes[3].trigger_rate == 0.0


# --------------------------------------------------------------------- the whole CLI


class StubResolver:
    """Stands in for resolve_model.py so no test asks the real CLI for its catalog."""

    EFFORT_ORDER = ("low", "medium", "high")

    def __init__(self, binary: str | None, home: Path) -> None:
        self.binary, self.home = binary, home

    def _codex_binary(self) -> str | None:
        return self.binary

    def codex_home(self) -> Path:
        return self.home

    def normalize_tier(self, raw: str) -> str | None:
        return raw if raw in {"fast", "workhorse", "frontier"} else None

    def valid_tier_names(self) -> str:
        return "fast, workhorse, frontier"

    def load_catalog(self) -> None:
        return None

    def resolve(self, tier: str, effort: str, _catalog: None) -> tuple[dict[str, Any], int]:
        return {"model": f"model-{tier}", "effort": effort}, 0


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway pack with one skill, three queries and an installed copy."""
    root = tmp_path / "pack"
    (root / "skills" / "plan-ticket").mkdir(parents=True)
    (root / "skills" / "plan-ticket" / "SKILL.md").write_text("---\nname: plan-ticket\n---\n")
    (root / "skills" / "write-ticket").mkdir(parents=True)
    (root / "skills" / "write-ticket" / "SKILL.md").write_text("---\nname: write-ticket\n---\n")
    (root / "evals" / "triggers").mkdir(parents=True)
    (root / "evals" / "triggers" / "plan-ticket.json").write_text(
        json.dumps(
            [
                {"query": "plan the next ticket", "should_trigger": True},
                {"query": "write a ticket", "should_trigger": False},
                {"query": "plan my week", "should_trigger": False},
            ]
        )
    )
    home = tmp_path / "codex-home"
    (home / "skills" / "plan-ticket").mkdir(parents=True)
    (home / "skills" / "plan-ticket" / "SKILL.md").write_text("x")
    write_rollout(home)  # the one thread every fake CLI below reports; it injected nothing
    monkeypatch.setattr(et, "REPO", root)
    return home


def install_stub(
    monkeypatch: pytest.MonkeyPatch, binary: str | None, home: Path, login: str | None = "ok"
) -> None:
    monkeypatch.setattr(et, "_load_resolver", lambda: StubResolver(binary, home))
    monkeypatch.setattr(
        et, "check_chatgpt_login", lambda _b: None if login == "ok" else _raise_no_cli()
    )


def _raise_no_cli() -> None:
    raise et.CliUnavailable("not signed in with ChatGPT")


# A fake CLI that triggers only for queries containing "plan the".
KEYWORD_CLI = (
    "q = argv[-1]\n"
    + f"print({THREAD_STARTED!r}, flush=True)\n"
    + 'print(\'{"type":"turn.started"}\', flush=True)\n'
    + f"if 'plan the' in q: print({READ_PLAN_NEXT!r}, flush=True)\n"
    + f"else: print({TURN_COMPLETED!r}, flush=True)\n"
)


def test_main_runs_the_skill_end_to_end_and_reports_json(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_stub(monkeypatch, fake_codex(tmp_path, KEYWORD_CLI), pack)
    assert et.main(["--skill", "plan-ticket", "--json", "--runs", "2"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["model"] == "model-fast" and report["effort"] == "low"
    assert [q["triggered"] for q in report["queries"]] == [
        [True, True],
        [False, False],
        [False, False],
    ]
    assert report["summary"]["pass_rate"] == 1.0 and report["summary"]["failures"] == []


def test_main_text_report_lists_failures_and_keeps_file_numbers(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    binary = fake_codex(
        tmp_path, emit(THREAD_STARTED, TURN_STARTED, READ_WRITE_TICKET, TURN_COMPLETED)
    )
    install_stub(monkeypatch, binary, pack)
    assert et.main(["--skill", "plan-ticket", "--skip", "1"]) == 0
    out = capsys.readouterr().out
    assert " 2  PASS" in out and " 3  PASS" in out and " 1  " not in out
    assert "also loaded: write-ticket" in out
    assert "pass rate 100% over 2 judged queries" in out


def test_main_only_first_runs_one_query(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_stub(monkeypatch, fake_codex(tmp_path, KEYWORD_CLI), pack)
    assert et.main(["--skill", "plan-ticket", "--only-first", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["queries"]) == 1


def test_main_exits_1_when_a_run_errored_and_does_not_hide_it(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_stub(monkeypatch, fake_codex(tmp_path, "sys.exit(7)\n"), pack)
    assert et.main(["--skill", "plan-ticket", "--only-first"]) == 1
    out = capsys.readouterr().out
    assert "ERROR" in out and "exited 7" in out and "not judged" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["--skill", "no-such-skill"],
        ["--skill", "plan-ticket", "--runs", "0"],
        ["--skill", "plan-ticket", "--max-parallel", "0"],
        ["--skill", "plan-ticket", "--timeout", "0"],
        ["--skill", "plan-ticket", "--skip", "3"],
        ["--skill", "plan-ticket", "--only-first", "--skip", "1"],
        ["--skill", "plan-ticket", "--tier", "gigantic"],
        ["--skill", "plan-ticket", "--effort", "extreme"],
    ],
)
def test_usage_errors_exit_2(
    argv: list[str], pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_stub(monkeypatch, fake_codex(tmp_path, emit(TURN_COMPLETED)), pack)
    assert et.main(argv) == et.EXIT_USAGE


def test_a_missing_skill_argument_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as stopped:
        et.main([])
    assert stopped.value.code == 2


def test_no_cli_exits_3(pack: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub(monkeypatch, None, pack)
    assert et.main(["--skill", "plan-ticket"]) == et.EXIT_NO_CLI


def test_a_skill_that_is_not_installed_exits_3_rather_than_scoring_every_query_a_miss(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (pack / "skills" / "plan-ticket" / "SKILL.md").unlink()
    install_stub(monkeypatch, fake_codex(tmp_path, emit(TURN_COMPLETED)), pack)
    assert et.main(["--skill", "plan-ticket"]) == et.EXIT_NO_CLI


def test_not_signed_in_with_chatgpt_exits_3(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_stub(monkeypatch, fake_codex(tmp_path, emit(TURN_COMPLETED)), pack, login="api")
    assert et.main(["--skill", "plan-ticket"]) == et.EXIT_NO_CLI


def test_max_parallel_is_capped_at_four(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_stub(monkeypatch, fake_codex(tmp_path, KEYWORD_CLI), pack)
    seen: list[int] = []
    real = et.gather_outcomes

    async def spy(queries: Any, runs: int, max_parallel: int, *rest: Any) -> Any:
        seen.append(max_parallel)
        return await real(queries, runs, max_parallel, *rest)

    monkeypatch.setattr(et, "gather_outcomes", spy)
    assert et.main(["--skill", "plan-ticket", "--max-parallel", "9", "--only-first"]) == 0
    assert seen == [4] and "capped at 4" in capsys.readouterr().err


def login_script(tmp_path: Path, text: str, code: int) -> str:
    return fake_codex(tmp_path, f"print({text!r})\nsys.exit({code})\n", name="login-codex")


def test_the_login_check_accepts_only_a_chatgpt_sign_in(tmp_path: Path) -> None:
    et.check_chatgpt_login(login_script(tmp_path, "Logged in using ChatGPT", 0))
    for text, code in (("Logged in using an API key", 0), ("Not logged in", 1), ("", 0)):
        with pytest.raises(et.CliUnavailable):
            et.check_chatgpt_login(login_script(tmp_path, text, code))


def test_stopping_tolerates_the_error_macos_gives_for_a_group_that_just_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(_pgid: int, _sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    async def go() -> int | None:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(0.3)", start_new_session=True
        )
        monkeypatch.setattr(et.os, "killpg", refuse)
        await et._stop(proc)
        return proc.returncode

    assert asyncio.run(go()) == 0


def test_apps_are_off_by_default_and_allow_apps_drops_the_switch() -> None:
    default = et.build_command("c", "m", "low", "q")
    assert default[default.index("--disable") + 1] == "apps"
    assert "--disable" not in et.build_command("c", "m", "low", "q", allow_apps=True)


def test_main_passes_the_apps_switch_through_and_notes_allow_apps(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = tmp_path / "argv.json"
    binary = fake_codex(
        tmp_path,
        f"json.dump(argv, open({str(seen)!r}, 'w'))\n" + emit(THREAD_STARTED, TURN_COMPLETED),
    )
    install_stub(monkeypatch, binary, pack)
    assert et.main(["--skill", "plan-ticket", "--only-first"]) == 0
    assert "--disable" in json.loads(seen.read_text())
    assert "allow-apps" not in capsys.readouterr().err
    assert et.main(["--skill", "plan-ticket", "--only-first", "--allow-apps"]) == 0
    assert "--disable" not in json.loads(seen.read_text())
    assert "--allow-apps is on" in capsys.readouterr().err


# ------------------------------------------------- explicit invocation: the injected skill


@pytest.fixture
def quick_rollout_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(et, "_ROLLOUT_WAIT_S", 0.3)
    monkeypatch.setattr(et, "_ROLLOUT_POLL_S", 0.05)


def test_a_skill_injected_by_name_triggers_though_no_command_read_it(tmp_path: Path) -> None:
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, TURN_STARTED, TURN_COMPLETED))
    write_rollout(home_of(binary), INJECTED_PLAN_TICKET)
    result = run_once(cfg(binary), "Use $plan-ticket to plan #73")
    assert result.triggered is True and result.error is None
    assert result.detected_by == "injected" and not result.stopped_early


def test_the_rollout_is_read_after_the_run_not_before(tmp_path: Path) -> None:
    """The fake CLI writes its rollout while it runs, as the real one does."""
    text = "\n".join(rollout_lines(INJECTED_PLAN_TICKET))
    folder = home_of(str(tmp_path / "codex")) / "sessions" / "2026" / "10" / "08"
    path = folder / f"rollout-2026-10-08T11-21-47-{THREAD_ID}.jsonl"
    body = f"os.makedirs({str(folder)!r})\nopen({str(path)!r}, 'w').write({text!r})\n" + emit(
        THREAD_STARTED, TURN_COMPLETED
    )
    result = run_once(cfg(fake_codex(tmp_path, body)), "Use $plan-ticket")
    assert result.triggered is True and result.detected_by == "injected"


def test_an_injected_neighbour_is_listed_and_does_not_trigger_the_target(tmp_path: Path) -> None:
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, TURN_STARTED, TURN_COMPLETED))
    injected_write_ticket = json.loads(
        json.dumps(INJECTED_PLAN_TICKET).replace("plan-ticket", "write-ticket")
    )
    write_rollout(home_of(binary), injected_write_ticket)
    result = run_once(cfg(binary), "Use $write-ticket")
    assert result.triggered is False and result.neighbours == ["write-ticket"]
    assert result.detected_by is None


def test_a_command_read_wins_and_needs_no_rollout(tmp_path: Path) -> None:
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, READ_PLAN_NEXT) + "time.sleep(60)\n")
    result = run_once(cfg(binary))  # no rollout was written at all
    assert result.triggered is True and result.error is None and result.detected_by == "read"


def test_a_missing_rollout_is_an_error_never_no_trigger(
    tmp_path: Path, quick_rollout_wait: None
) -> None:
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, TURN_STARTED, TURN_COMPLETED))
    result = run_once(cfg(binary))
    assert result.triggered is None
    assert result.error is not None and THREAD_ID in result.error


def test_an_unreadable_rollout_is_an_error(tmp_path: Path) -> None:
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, TURN_COMPLETED))
    home = home_of(binary)
    folder = home / "sessions" / "2026" / "10" / "08"
    (folder / f"rollout-2026-10-08T11-21-47-{THREAD_ID}.jsonl").mkdir(parents=True)  # not a file
    result = run_once(cfg(binary))
    assert result.triggered is None
    assert result.error is not None and "cannot read the session rollout" in result.error


def test_a_run_that_never_named_its_thread_is_an_error_when_nothing_was_read(
    tmp_path: Path,
) -> None:
    binary = fake_codex(tmp_path, emit(TURN_STARTED, TURN_COMPLETED))
    write_rollout(home_of(binary))
    result = run_once(cfg(binary))
    assert result.triggered is None
    assert result.error is not None and "thread.started" in result.error


def test_an_errored_turn_is_not_also_checked_for_a_rollout(tmp_path: Path) -> None:
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, TURN_FAILED))
    result = run_once(cfg(binary))
    assert result.error == "turn failed: usage limit reached"


def test_report_says_which_mechanism_caught_each_trigger() -> None:
    read = et.RunResult(True, [], None, None, 1.0, detected_by="read")
    injected = et.RunResult(True, [], None, None, 1.0, detected_by="injected")
    miss = et.RunResult(False, [], None, None, 1.0)
    outcomes = [et.QueryOutcome(1, "Use $plan-ticket", True, [read, injected, injected, miss])]
    assert outcomes[0].detected_by == {"read": 1, "injected": 2}
    assert "detected by: read x1, injected x2" in et.render("plan-ticket", "m", "low", outcomes)
    report = json.loads(et.to_json("plan-ticket", "m", "low", outcomes))
    assert report["queries"][0]["detected_by"] == {"read": 1, "injected": 2}
    assert [r["detected_by"] for r in report["queries"][0]["runs"]] == [
        "read", "injected", "injected", None,
    ]  # fmt: skip


# ----------------------------------------------------------------------------- fixtures


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=30
    )
    return done.stdout.strip()


def make_fixture(root: Path) -> Path:
    fixture = root / "demo"
    (fixture / "pkg").mkdir(parents=True)
    (fixture / "README.md").write_text("# demo\n")
    (fixture / "pkg" / "main.py").write_text("print('hi')\n")
    (fixture / ".github" / "workflows").mkdir(parents=True)
    (fixture / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    return fixture


def test_a_fixture_becomes_a_repo_with_one_commit_and_a_clean_tree(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    et.prepare_workdir(work, make_fixture(tmp_path))
    assert (work / "pkg" / "main.py").read_text() == "print('hi')\n"
    assert git(work, "status", "--porcelain") == ""
    assert git(work, "rev-list", "--count", "HEAD") == "1"
    assert git(work, "branch", "--show-current") == "main"
    tracked = git(work, "ls-files").splitlines()
    assert ".github/workflows/ci.yml" in tracked and "pkg/main.py" in tracked


def test_no_fixture_leaves_the_directory_empty(tmp_path: Path) -> None:
    et.prepare_workdir(tmp_path, None)
    assert list(tmp_path.iterdir()) == []


def test_a_users_git_config_does_not_change_the_fixture_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ignore_all = tmp_path / "ignore"
    ignore_all.write_text("*.py\n")
    config = tmp_path / "gitconfig"
    config.write_text(f"[core]\n\texcludesfile = {ignore_all}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    work = tmp_path / "work"
    work.mkdir()
    et.prepare_workdir(work, make_fixture(tmp_path))
    assert "pkg/main.py" in git(work, "ls-files").splitlines()


def test_a_fixture_that_cannot_be_set_up_is_an_error_result(tmp_path: Path) -> None:
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, TURN_COMPLETED))
    result = run_once(cfg(binary, fixture=tmp_path / "no-such-fixture"))
    assert result.triggered is None
    assert result.error is not None and "could not set up fixture no-such-fixture" in result.error


def test_the_child_starts_inside_the_committed_fixture(tmp_path: Path) -> None:
    seen = tmp_path / "seen.json"
    binary = fake_codex(
        tmp_path,
        "import subprocess\n"
        "json.dump({'files': sorted(os.listdir(cwd)),"
        " 'status': subprocess.run(['git', 'status', '--porcelain'], capture_output=True,"
        " text=True).stdout,"
        " 'commits': subprocess.run(['git', 'rev-list', '--count', 'HEAD'],"
        " capture_output=True, text=True).stdout.strip()}, "
        f"open({str(seen)!r}, 'w'))\n" + emit(THREAD_STARTED, TURN_COMPLETED),
    )
    write_rollout(home_of(binary))
    result = run_once(cfg(binary, fixture=make_fixture(tmp_path)))
    assert result.error is None
    got = json.loads(seen.read_text())
    assert got == {"files": [".git", ".github", "README.md", "pkg"], "status": "", "commits": "1"}


def test_the_shipped_small_repo_covers_every_path_the_coding_queries_name(tmp_path: Path) -> None:
    fixture = REPO / "evals" / "fixtures" / "small-repo"
    work = tmp_path / "work"
    work.mkdir()
    et.prepare_workdir(work, fixture)
    assert git(work, "status", "--porcelain") == ""
    tracked = set(git(work, "ls-files").splitlines())
    for needed in (
        "main.py", "README.md", "CONTRIBUTING.md", "billing/retry.py", "api/orders.py",
        "api/auth.py", "services/export.py", "web/pages/InvoicesPage.jsx",
        "web/components/SignupForm.jsx", ".github/workflows/ci.yml",
        "prompts/triage.md", "agents/triage.toml", "docs/support-bot.md",
        ".codex/agents/reviewer.toml", "skills/deploy/SKILL.md",
    ):  # fmt: skip
        assert needed in tracked, needed
    assert any(t.startswith("db/migrations/") for t in tracked)
    assert any(t.startswith("tests/test_") for t in tracked)
    main = (work / "main.py").read_text()
    assert "tomllib" in main and "def load" not in main  # config loading is inline, to extract


def test_main_runs_each_query_inside_the_named_fixture(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_fixture(tmp_path / "pack" / "evals" / "fixtures")
    seen = tmp_path / "listing.json"
    binary = fake_codex(
        tmp_path,
        f"json.dump(sorted(os.listdir(cwd)), open({str(seen)!r}, 'w'))\n"
        + emit(THREAD_STARTED, TURN_COMPLETED),
    )
    install_stub(monkeypatch, binary, pack)
    assert et.main(["--skill", "plan-ticket", "--only-first", "--fixture", "demo"]) == 0
    assert json.loads(seen.read_text()) == [".git", ".github", "README.md", "pkg"]
    assert et.main(["--skill", "plan-ticket", "--only-first"]) == 0  # the default is still empty
    assert json.loads(seen.read_text()) == []


@pytest.mark.parametrize("name", ["no-such-fixture", "../pack", "..", "a/b", ".hidden", ""])
def test_an_unknown_or_path_like_fixture_name_is_a_usage_error(
    name: str, pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_fixture(tmp_path / "pack" / "evals" / "fixtures")
    install_stub(monkeypatch, fake_codex(tmp_path, emit(TURN_COMPLETED)), pack)
    assert et.main(["--skill", "plan-ticket", "--fixture", name]) == et.EXIT_USAGE


def test_main_reports_the_mechanism_and_shows_it_in_progress(
    pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_rollout(pack, INJECTED_PLAN_TICKET)
    binary = fake_codex(tmp_path, emit(THREAD_STARTED, TURN_COMPLETED))
    install_stub(monkeypatch, binary, pack)
    assert et.main(["--skill", "plan-ticket", "--only-first", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["queries"][0]["detected_by"] == {"injected": 1}
    assert "triggered (injected)" in captured.err
