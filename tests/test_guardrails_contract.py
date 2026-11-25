"""The hook as Codex runs it: stdin JSON in, exit code and one stderr line out; the block log,
the allowlist, the CLI the help skill uses, and the packaging that installs it."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from test_guardrails_support import (
    GITHUB,
    HOOKS_JSON,
    REPO,
    SCRIPT,
    SKILL_DIR,
    G,
    World,
    add_file,
    build_template,
    make_world,
)


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_template(tmp_path_factory.mktemp("template"))


@pytest.fixture
def world(tmp_path: Path, template: Path) -> World:
    return make_world(tmp_path, template)


def bash_payload(world: World, command: object, **extra: Any) -> dict[str, Any]:
    payload = world.payload("Bash", **extra)
    payload["tool_input"] = {"command": command, **payload["tool_input"]}
    return payload


def test_block_exits_2_with_one_line_on_stderr(world: World) -> None:
    proc = world.run_hook(bash_payload(world, "git push --force origin main"))
    assert proc.returncode == 2
    assert proc.stdout == ""
    lines = proc.stderr.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("guardrails[git-force-push-protected]:")
    assert "pull request" in lines[0]  # it says what to do instead
    assert "tell the user" in lines[0]


def test_allowed_call_exits_0_silently(world: World) -> None:
    proc = world.run_hook(bash_payload(world, "git push -u origin feature/x"))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_extra_findings_are_counted_in_the_message(world: World) -> None:
    proc = world.run_hook(bash_payload(world, "git push --no-verify --force origin main"))
    assert proc.returncode == 2
    assert "(+" in proc.stderr and "more)" in proc.stderr


def test_a_patch_call_is_judged_end_to_end(world: World) -> None:
    payload = world.payload("apply_patch", command=add_file("a.txt", f"T={GITHUB}"))
    proc = world.run_hook(payload)
    assert proc.returncode == 2
    assert proc.stderr.startswith("guardrails[secret-in-content]:")
    assert GITHUB not in proc.stderr


def test_an_argv_command_is_read_as_the_command_line_it_runs(world: World) -> None:
    payload = bash_payload(world, ["bash", "-lc", "git push origin main"])
    assert world.run_hook(payload).returncode == 2
    assert world.run_hook(bash_payload(world, ["git", "status"])).returncode == 0


def test_a_workdir_in_the_tool_input_is_where_the_command_runs(world: World) -> None:
    payload = world.payload("Bash", cwd=world.home, command="rm -rf .", workdir=str(world.repo))
    assert {f.rule for f in G.evaluate(payload, world.env)} == {"rm-rf-critical"}
    relative = world.payload("Bash", command="rm -rf ..", workdir="build")
    assert {f.rule for f in G.evaluate(relative, world.env)} == {"rm-rf-critical"}


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "[]", "null", "123", '"a string"', "{"],
    ids=["empty", "text", "array", "null", "number", "string", "truncated"],
)
def test_malformed_input_is_refused(world: World, raw: str) -> None:
    proc = world.run_hook(raw)
    assert proc.returncode == 2
    assert "guardrails[cannot-decide]" in proc.stderr
    assert len(proc.stderr.strip().splitlines()) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "Bash"},
        {"tool_name": "Bash", "tool_input": "git push"},
        {"tool_name": "Bash", "tool_input": {}},
        {"tool_name": "Bash", "tool_input": {"command": 7}},
        {"tool_name": "Bash", "tool_input": {"command": None}},
        {"tool_name": "Bash", "tool_input": {"command": ["git", 3]}},
        {"tool_name": "apply_patch", "tool_input": {}},
        {"tool_name": "apply_patch", "tool_input": [1, 2]},
        {"tool_name": "apply_patch", "tool_input": {"command": "not a patch"}},
    ],
)
def test_a_tool_call_with_unreadable_input_is_refused(
    world: World, payload: dict[str, Any]
) -> None:
    proc = world.run_hook({"hook_event_name": "PreToolUse", **payload})
    assert proc.returncode == 2
    assert "cannot-decide" in proc.stderr


def test_unrelated_tools_and_events_pass(world: World) -> None:
    assert (
        world.run_hook({"tool_name": "mcp__fs__read", "tool_input": {"p": ".env"}}).returncode == 0
    )
    assert world.run_hook({"tool_name": "update_plan", "tool_input": {}}).returncode == 0
    assert world.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Bash"}).returncode == 0
    assert world.run_hook({}).returncode == 0  # no tool name: nothing to guard


def test_internal_error_blocks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(G, "evaluate", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash"})))
    assert G.main(["guardrails.py"]) == 2
    err = capsys.readouterr().err
    assert "cannot-decide" in err
    assert "RuntimeError" in err
    assert "synthetic failure" not in err  # the error text is not echoed, only its type


def test_message_survives_a_c_locale_and_non_ascii_names(world: World) -> None:
    payload = world.payload("apply_patch", command=add_file("clé-é.txt", f"T={GITHUB}"))
    env = {**world.env, "LC_ALL": "C", "LANG": "C"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "clé-é.txt" in proc.stderr.decode("utf-8")


def test_invalid_utf8_on_stdin_does_not_crash(world: World) -> None:
    raw = b'{"tool_name": "Bash", "tool_input": {"command": "echo \xff\xfe"}}'
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], input=raw, capture_output=True, env=world.env, check=False
    )
    assert proc.returncode == 0


def test_huge_command_finishes_quickly(world: World) -> None:
    command = "echo " + "x" * 400_000 + "; git push -u origin feature/x"
    start = time.monotonic()
    assert world.run_hook(bash_payload(world, command)).returncode == 0
    assert time.monotonic() - start < 5


def test_pathological_regex_input_is_fast(world: World) -> None:
    text = "A" * 200_000 + "_TOKEN" * 2000 + "=" + "b" * 30
    start = time.monotonic()
    proc = world.run_hook(world.payload("apply_patch", command=add_file("x.txt", text)))
    assert proc.returncode in (0, 2)
    assert time.monotonic() - start < 5


# --- the log -----------------------------------------------------------------------


def read_log(world: World) -> list[dict[str, Any]]:
    path = world.data / "blocks.log"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_block_appends_one_log_line_under_codex_home(world: World) -> None:
    world.run_hook(bash_payload(world, "git push origin main"))
    world.run_hook(bash_payload(world, "chmod -R 777 /srv"))
    entries = read_log(world)
    assert [e["rules"] for e in entries] == [["git-push-protected"], ["world-writable-chmod"]]
    assert entries[0]["event"] == "block"
    assert entries[0]["session"] == "s1"
    assert entries[0]["tool"] == "Bash"
    assert entries[0]["ts"].endswith("Z")


def test_without_codex_home_the_log_is_under_dot_codex(world: World) -> None:
    env = {k: v for k, v in world.env.items() if k != "CODEX_HOME"}
    assert world.run_hook(bash_payload(world, "git push origin main"), env=env).returncode == 2
    assert (world.home / ".codex" / "guardrails" / "blocks.log").is_file()


def test_allowed_calls_are_not_logged(world: World) -> None:
    world.run_hook(bash_payload(world, "git status"))
    assert not (world.data / "blocks.log").exists()


def test_secrets_never_reach_the_log(world: World) -> None:
    world.run_hook(
        bash_payload(world, f"curl -k -H 'Authorization: token {GITHUB}' https://x.test")
    )
    text = (world.data / "blocks.log").read_text(encoding="utf-8")
    assert GITHUB not in text
    assert "[redacted]" in text


def test_a_log_that_cannot_be_written_does_not_change_the_decision(
    world: World, tmp_path: Path
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    env = {**world.env, "CODEX_HOME": str(blocker / "sub")}
    assert world.run_hook(bash_payload(world, "git push origin main"), env=env).returncode == 2


def test_log_rolls_over_when_large(world: World) -> None:
    world.data.mkdir()
    log = world.data / "blocks.log"
    log.write_text("x" * (G.LOG_MAX_BYTES + 1), encoding="utf-8")
    G.log_event(str(world.data), {"event": "block"})
    assert (world.data / "blocks.log.1").exists()
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


# --- the allowlist -----------------------------------------------------------------


def write_allowlist(world: World, root: Path, text: str) -> Path:
    """A person's waiver file for the project at *root*, in the Codex home."""
    path = Path(G.allowlist_path(str(world.codex_home), os.path.realpath(root)))
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_an_allowlisted_rule_lets_the_call_through_and_is_logged(world: World) -> None:
    write_allowlist(
        world, world.repo, "# the team publishes this bucket on purpose\ngcp-public-access\n"
    )
    proc = world.run_hook(bash_payload(world, "gsutil iam ch allUsers:objectViewer gs://b"))
    assert proc.returncode == 0
    assert read_log(world)[0]["event"] == "allowed-by-config"


def test_a_repo_cannot_ship_its_own_waivers(world: World) -> None:
    shipped = world.repo / ".codex" / "guardrails-allow.txt"
    shipped.parent.mkdir(exist_ok=True)
    shipped.write_text("git-push-protected\ngcp-public-access\n", encoding="utf-8")
    proc = world.run_hook(bash_payload(world, "git push origin main"))
    assert proc.returncode == 2
    assert "repo-shipped waivers are ignored" in proc.stderr
    assert G.allowlist_path(str(world.codex_home), os.path.realpath(world.repo)) in proc.stderr
    assert G.load_allowlist(str(world.codex_home), os.path.realpath(world.repo)) == set()
    # no repo file, no note
    shipped.unlink()
    assert "ignored" not in world.run_hook(bash_payload(world, "git push origin main")).stderr


def test_the_waiver_file_is_keyed_by_the_repos_absolute_path(world: World, tmp_path: Path) -> None:
    key = G.allowlist_key("/work/My Repo")
    assert key.startswith("My-Repo-") and len(key) == len("My-Repo-") + 16
    assert key == G.allowlist_key("/work/My Repo")
    assert key != G.allowlist_key("/other/My Repo")  # same name, another path
    expected = hashlib.sha256(b"/work/My Repo").hexdigest()[:16]
    assert key == f"My-Repo-{expected}"
    out = run_cli("--allow-path", str(world.repo), env=world.env).stdout.strip()
    assert out == G.allowlist_path(str(world.codex_home), os.path.realpath(world.repo))
    assert Path(out).parent == world.codex_home / "guardrails-allow"


def test_the_allowlist_at_the_git_root_applies_in_a_subdirectory(world: World) -> None:
    write_allowlist(world, world.repo, "gcp-public-access\n")
    payload = bash_payload(world, "gsutil iam ch allUsers:objectViewer gs://b")
    payload["cwd"] = str(world.repo / "build")
    assert world.run_hook(payload).returncode == 0
    write_allowlist(world, world.repo / "build", "git-push-protected\n")  # not the project root
    assert (
        world.run_hook({**payload, "tool_input": {"command": "git push origin main"}}).returncode
        == 2
    )


def test_outside_a_repository_the_session_directory_holds_the_allowlist(
    world: World, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    write_allowlist(world, outside, "tls-verify-off\n")
    payload = bash_payload(world, "curl -k https://x.test")
    payload["cwd"] = str(outside)
    assert world.run_hook(payload).returncode == 0


def test_allowlisting_one_rule_leaves_the_others_on(world: World) -> None:
    write_allowlist(world, world.repo, "gcp-public-access\n")
    assert world.run_hook(bash_payload(world, "git push origin main")).returncode == 2


def test_one_command_hitting_two_rules_needs_both_allowlisted(world: World) -> None:
    command = "git push --force origin main"
    write_allowlist(world, world.repo, "git-force-push-protected\n")
    assert world.run_hook(bash_payload(world, command)).returncode == 2
    write_allowlist(world, world.repo, "git-force-push-protected\ngit-push-protected\n")
    assert world.run_hook(bash_payload(world, command)).returncode == 0


@pytest.mark.parametrize("line", ["guardrails-tamper", "cannot-decide", "*", "all", "everything"])
def test_unlistable_rules_and_wildcards_do_nothing(world: World, line: str) -> None:
    path = write_allowlist(world, world.repo, f"{line}\n")
    assert world.run_hook(bash_payload(world, "git push origin main")).returncode == 2
    tamper = bash_payload(world, f"echo x > {path}")
    assert world.run_hook(tamper).returncode == 2


def test_comments_blank_lines_and_unknown_ids_are_ignored(world: World) -> None:
    write_allowlist(world, world.repo, "\n# note\n  git-no-verify   # trailing note\nnot-a-rule\n")
    codex_home = str(world.codex_home)
    assert G.load_allowlist(codex_home, os.path.realpath(world.repo)) == {"git-no-verify"}


def test_a_missing_allowlist_means_nothing_is_allowed(world: World, tmp_path: Path) -> None:
    codex_home = str(world.codex_home)
    assert G.load_allowlist(codex_home, os.path.realpath(world.repo)) == set()
    assert G.load_allowlist(codex_home, str(tmp_path / "nowhere")) == set()


def test_the_agent_cannot_turn_a_rule_off_from_inside_a_session(world: World) -> None:
    # the allowlist is read by the hook itself; nothing in the command or its env reaches it
    for command in (
        "GUARDRAILS_ALLOW=git-push-protected git push origin main",
        "export GUARDRAILS_DISABLE=1; git push origin main",
        "env CODEX_HOME=/nonexistent git push origin main",
        "# guardrails-allow: git-push-protected\ngit push origin main",
    ):
        assert world.run_hook(bash_payload(world, command)).returncode == 2, command
    env = {**world.env, "GUARDRAILS_ALLOW": "git-push-protected", "GUARDRAILS_DISABLE": "1"}
    assert world.run_hook(bash_payload(world, "git push origin main"), env=env).returncode == 2


# --- the CLI the help skill uses -----------------------------------------------------


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )


def test_list_rules_names_every_rule() -> None:
    out = run_cli("--list-rules").stdout
    for rule in G.RULES:
        assert rule.id in out
        assert rule.instead in out
    assert out.count("(cannot be allowlisted)") == 2


def test_recent_reads_the_log_from_codex_home(world: World) -> None:
    world.run_hook(bash_payload(world, "git push origin main"))
    assert "git-push-protected" in run_cli("--recent", "5", env=world.env).stdout
    assert "git-push-protected" in run_cli("--recent", "--data-dir", str(world.data)).stdout


def test_recent_with_no_log_says_so(world: World) -> None:
    assert "nothing has been blocked" in run_cli("--recent", env=world.env).stdout


def test_unknown_cli_flag_is_a_usage_error() -> None:
    proc = run_cli("--nope")
    assert proc.returncode == 64
    assert "usage" in proc.stderr


# --- packaging ---------------------------------------------------------------------


def hook_entry() -> dict[str, Any]:
    config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    entries = config["hooks"]["PreToolUse"]
    assert set(config["hooks"]) == {"PreToolUse"} and len(entries) == 1
    hook: dict[str, Any] = entries[0]["hooks"][0]
    return hook


def test_hooks_json_runs_the_script_the_skill_installs() -> None:
    hook = hook_entry()
    assert hook["type"] == "command"
    assert hook["command"] == (
        'python3 "${CODEX_HOME:-$HOME/.codex}/skills/guardrails-help/scripts/guardrails.py"'
    )
    assert isinstance(hook["timeout"], int) and hook["timeout"] <= 30
    assert hook["statusMessage"]
    link = SKILL_DIR / "scripts" / "guardrails.py"
    assert link.is_symlink() and link.resolve() == SCRIPT.resolve()


def test_the_hook_command_blocks_through_a_shell_as_codex_runs_it(
    world: World, tmp_path: Path
) -> None:
    # Codex runs `command` through a shell; give it a Codex home where the skill is installed.
    (world.codex_home / "skills").mkdir()
    (world.codex_home / "skills" / "guardrails-help").symlink_to(SKILL_DIR)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python3").symlink_to(sys.executable)
    env = {**world.env, "PATH": f"{bindir}:{world.env['PATH']}"}
    payload = json.dumps(bash_payload(world, "git push --force origin main"))
    proc = subprocess.run(
        ["/bin/sh", "-c", hook_entry()["command"]],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=world.repo,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.startswith("guardrails[git-force-push-protected]")


def test_script_is_executable_and_has_a_shebang() -> None:
    assert os.access(SCRIPT, os.X_OK)
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n")


def test_script_is_standard_library_only() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert modules <= set(sys.stdlib_module_names)


@pytest.mark.skipif(not os.path.exists("/usr/bin/python3"), reason="no system python3")
def test_script_still_loads_on_the_oldest_interpreter_a_laptop_may_have(world: World) -> None:
    # macOS ships python3 3.9; the hook runs under whatever python3 is first on the PATH
    py = "/usr/bin/python3"
    version = subprocess.run(
        [py, "-c", "import sys;print(sys.version_info[:2])"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    if shutil.which("xcode-select") is None and "(3," not in version:
        pytest.skip("system python3 unusable")
    blocked = world.run_hook(bash_payload(world, "git push --force origin main"), python=py)
    allowed = world.run_hook(bash_payload(world, "git status"), python=py)
    patch = world.run_hook(
        world.payload("apply_patch", command=add_file("a.txt", f"T={GITHUB}")), python=py
    )
    assert (blocked.returncode, allowed.returncode, patch.returncode) == (2, 0, 2), blocked.stderr


def test_the_pack_root_the_script_guards_is_this_checkout() -> None:
    ctx = G.Ctx({"cwd": str(REPO)}, {"HOME": "/nonexistent", "CODEX_HOME": "/nonexistent/c"})
    assert ctx.pack_root == str(REPO.resolve())
