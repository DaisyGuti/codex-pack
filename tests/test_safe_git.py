"""Scripts that read a repository they were pointed at must not let its config run programs."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import safe_git  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan_repo = load("scan_repo")
check_context_budget = load("check_context_budget")
inventory_model_calls = load("inventory_model_calls")


@pytest.fixture(autouse=True)
def tester_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    return done.stdout.strip()


def marker_script(folder: Path, name: str) -> tuple[Path, Path]:
    """A program that records that it ran, and the file it records to."""
    marker = folder / f"{name}.ran"
    script = folder / f"{name}.sh"
    script.write_text(f'#!/bin/sh\necho ran >> "{marker}"\nprintf "\\0"\n', encoding="utf-8")
    script.chmod(0o755)
    return script, marker


@pytest.fixture
def hostile_repo(tmp_path: Path) -> tuple[Path, list[Path]]:
    """A repo whose own config names a program for every setting that makes git run one, with a
    commit that carries a signature (so anything that verifies it runs gpg)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "AGENTS.md").write_text("x\n", encoding="utf-8")
    (repo / ".env").write_text("A=1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat: first")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    parent = git(repo, "rev-parse", "HEAD")
    signed = tmp_path / "signed-commit"
    signed.write_text(
        f"tree {tree}\nparent {parent}\nauthor A <a@e.invalid> 1700000000 +0000\n"
        "committer A <a@e.invalid> 1700000000 +0000\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n abcd\n -----END PGP SIGNATURE-----\n\n"
        "fix: signed\n",
        encoding="utf-8",
    )
    git(repo, "update-ref", "HEAD", git(repo, "hash-object", "-t", "commit", "-w", str(signed)))
    markers = []
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for key in ("core.fsmonitor", "gpg.program", "gpg.ssh.program", "gpg.x509.program"):
        script, marker = marker_script(tmp_path, key.replace(".", "-"))
        markers.append(marker)
        git(repo, "config", key, str(script))
    for hook in ("reference-transaction", "post-index-change", "post-checkout"):
        script, marker = marker_script(tmp_path, hook)
        markers.append(marker)
        (hooks / hook).write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
        (hooks / hook).chmod(0o755)
    git(repo, "config", "core.hooksPath", str(hooks))
    git(repo, "config", "log.showSignature", "true")
    return repo, markers


def test_no_program_named_in_the_repos_config_runs_for_any_script(
    hostile_repo: tuple[Path, list[Path]],
) -> None:
    repo, markers = hostile_repo
    facts = scan_repo.scan(repo)
    guides = check_context_budget.repo_guides(repo, ("AGENTS.md",))
    env_files = inventory_model_calls.tracked_env_files(repo)
    # the scripts still answer: the signature is counted without anything verifying it
    assert facts["commits"]["sampled"] == 2
    assert facts["commits"]["with_signature"] == 1
    assert facts["commits"]["conventional_commits"] == 2
    assert [p.name for p in guides] == ["AGENTS.md"]
    assert env_files == [".env"]
    assert [m.name for m in markers if m.exists()] == [], "git ran a program the repo named"


def test_the_git_command_overrides_every_program_setting_and_the_system_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    argv = safe_git.git_argv(Path("/r"), "log")
    assert argv[:2] == ["git", "--no-pager"] and argv[-3:] == ["-C", "/r", "log"]
    assert "-c" in argv
    for setting in ("core.fsmonitor=false", "gpg.program=false", "core.hooksPath=/dev/null"):
        assert argv[argv.index(setting) - 1] == "-c"
    env = safe_git.git_env()
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and "GIT_DIR" not in env
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull  # the caller's own config is kept


def test_git_gets_neither_system_nor_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/home/someone/.gitconfig")
    env = safe_git.isolated_git_env()
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert "GIT_DIR" not in env and "GIT_CONFIG_COUNT" not in env


@pytest.mark.parametrize(
    ("module", "call"),
    [
        (scan_repo, lambda m, root: m.git(root, "rev-parse", "--show-toplevel")),
        (check_context_budget, lambda m, root: m.repo_guides(root, ("AGENTS.md",))),
        (inventory_model_calls, lambda m, root: m.tracked_env_files(root)),
    ],
    ids=["scan_repo", "check_context_budget", "inventory_model_calls"],
)
def test_each_script_starts_git_through_the_shared_helper(
    module: ModuleType, call: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def spy(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        seen.append((argv, kwargs.get("env") or {}))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", spy)
    call(module, tmp_path)
    assert seen
    for argv, env in seen:
        assert argv[:1] == ["git"]
        for setting in safe_git.HARDENED_CONFIG:
            assert setting in argv, argv
        assert env.get("GIT_CONFIG_NOSYSTEM") == "1"
