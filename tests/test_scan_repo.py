"""scripts/scan_repo.py reads facts from synthetic repos; nothing here touches the network."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "scan_repo.py"
SHA = "a" * 40
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scan_repo_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sr = _load()
MakeRepo = Callable[..., Path]


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**os.environ, **GIT_ENV},
        stdin=subprocess.DEVNULL,
    )


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the tester's own git config (signing, hooks, templates) out of every test."""
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def make_repo(tmp_path: Path) -> MakeRepo:
    """Build a synthetic repo: files maps relative path to text; messages are commit subjects."""

    def build(
        files: dict[str, str] | None = None,
        messages: tuple[str, ...] = ("feat: first commit",),
        remote: str | None = None,
    ) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        run_git(repo, "init", "-q", "-b", "main")
        for rel, text in (files or {}).items():
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        run_git(repo, "add", "-A")
        for message in messages:
            run_git(repo, "commit", "-q", "--allow-empty", "-m", message)
        if remote:
            run_git(repo, "remote", "add", "origin", remote)
        return repo

    return build


def scan(repo: Path) -> dict[str, Any]:
    facts = sr.scan(repo)
    assert isinstance(facts, dict)
    return facts


def test_reports_host_default_branch_and_commit_habits(make_repo: MakeRepo) -> None:
    repo = make_repo(
        messages=("feat: add export", "fix(api): handle empty page", "update stuff"),
        remote="git@gitlab.example.invalid:team/app.git",
    )
    facts = scan(repo)
    assert facts["remote"]["kind"] == "gitlab"
    assert facts["remote"]["host"] == "gitlab.example.invalid"
    assert facts["default_branch"] == "main"
    assert facts["commits"]["sampled"] == 3
    assert facts["commits"]["conventional_commits"] == 2
    assert facts["commits"]["with_signature"] == 0


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("git@github.com:org/app.git", "github"),
        ("https://git.corp.example.invalid/org/app.git", "unknown"),
        (None, "none"),
    ],
)
def test_host_kind(url: str | None, kind: str) -> None:
    assert sr.host_info(url)["kind"] == kind


def test_reads_package_scripts_and_manager(make_repo: MakeRepo) -> None:
    repo = make_repo(
        {
            "package.json": json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}}),
            "pnpm-lock.yaml": "lockfileVersion: 9\n",
        }
    )
    facts = scan(repo)
    node = next(e for e in facts["ecosystems"] if e["manifest"] == "package.json")
    assert node["manager"] == "pnpm"
    assert node["scripts"] == ["lint", "test"]
    assert facts["lockfiles"] == ["pnpm-lock.yaml"]


def test_invalid_package_json_is_reported_not_raised(make_repo: MakeRepo) -> None:
    node = scan(make_repo({"package.json": "{not json"}))["ecosystems"][0]
    assert "invalid JSON" in node["error"]


def test_makefile_targets_skip_variables_and_special_targets(make_repo: MakeRepo) -> None:
    repo = make_repo(
        {"Makefile": "CC := gcc\n.PHONY: test\ntest: build\n\tpytest\nbuild:\n\techo hi\n"}
    )
    assert scan(repo)["makefile_targets"] == ["build", "test"]


def test_pyproject_tools_and_uv_manager(make_repo: MakeRepo) -> None:
    repo = make_repo(
        {
            "pyproject.toml": "[tool.ruff]\nline-length = 100\n[tool.pytest.ini_options]\n",
            "uv.lock": "version = 1\n",
        }
    )
    py = scan(repo)["ecosystems"][0]
    assert py["manager"] == "uv"
    assert py["tools_configured"] == ["pytest", "ruff"]


def test_ci_commands_from_github_and_gitlab(make_repo: MakeRepo) -> None:
    repo = make_repo(
        {
            ".github/workflows/ci.yml": (
                "jobs:\n  t:\n    steps:\n      - run: npm test\n"
                "      - run: |\n          echo multi\n"
            ),
            ".gitlab-ci.yml": (
                "test:\n  script:\n    - make test\n    - make lint\n  only: [main]\n"
            ),
        }
    )
    commands = {c["command"] for c in scan(repo)["ci"]["commands"]}
    assert commands == {"npm test", "make test", "make lint"}


def test_dockerfile_digest_pinning_ignores_scratch_and_stage_names(make_repo: MakeRepo) -> None:
    repo = make_repo(
        {
            "Dockerfile": (
                f"FROM golang:1.22@sha256:{'b' * 64} AS build\n"
                "FROM alpine:3.20\n"
                "FROM build AS final\n"
                "FROM scratch\n"
            )
        }
    )
    assert scan(repo)["dockerfiles"][0]["from"] == [
        {"image": f"golang:1.22@sha256:{'b' * 64}", "digest_pinned": True},
        {"image": "alpine:3.20", "digest_pinned": False},
    ]


def test_github_actions_pin_counts_skip_local_and_docker_refs(make_repo: MakeRepo) -> None:
    repo = make_repo(
        {
            ".github/workflows/ci.yml": (
                "steps:\n"
                f"  - uses: actions/checkout@{SHA}\n"
                "  - uses: actions/setup-node@v4\n"
                "  - uses: ./local-action\n"
                "  - uses: docker://alpine:3.20\n"
            )
        }
    )
    assert scan(repo)["github_actions_pins"] == {"pinned": 1, "unpinned": 1}


def test_requirements_not_exactly_pinned(make_repo: MakeRepo) -> None:
    repo = make_repo({"requirements.txt": "# deps\nrequests==2.32.0\nflask>=3\n-r other.txt\n"})
    assert scan(repo)["requirements_files"] == [
        {"path": "requirements.txt", "requirements": 2, "not_exactly_pinned": 1}
    ]


def test_instruction_files_review_templates_and_codeowners(make_repo: MakeRepo) -> None:
    repo = make_repo(
        {
            ".github/pull_request_template.md": "## What\n",
            ".gitlab/merge_request_templates/default.md": "## What\n",
            ".github/CODEOWNERS": "* @team\n",
            "AGENTS.override.md": "local rules\n",
        }
    )
    files = scan(repo)["instruction_files"]
    assert files["review_templates"] == [
        ".github/pull_request_template.md",
        ".gitlab/merge_request_templates/default.md",
    ]
    assert files["codeowners"] == [".github/CODEOWNERS"]
    assert "AGENTS.override.md" in files["present"]


def test_node_modules_are_not_walked(make_repo: MakeRepo) -> None:
    assert scan(make_repo({"node_modules/dep/Dockerfile": "FROM alpine\n"}))["dockerfiles"] == []


def test_gpgsign_config_is_reported(make_repo: MakeRepo) -> None:
    repo = make_repo()
    run_git(repo, "config", "commit.gpgsign", "true")
    assert scan(repo)["commits"]["gpgsign_config"] == "true"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def test_cli_prints_json_for_a_repo(make_repo: MakeRepo) -> None:
    repo = make_repo({"README.md": "hi\n"})
    result = run_cli(str(repo))
    assert result.returncode == 0
    assert json.loads(result.stdout)["root"] == str(repo.resolve())


def test_cli_usage_errors_exit_2_with_the_fix(tmp_path: Path) -> None:
    outside = run_cli(str(tmp_path))
    assert outside.returncode == 2
    assert "pass the repo path" in outside.stderr
    missing = run_cli(str(tmp_path / "nope"))
    assert missing.returncode == 2
    assert "not a directory" in missing.stderr
    extra = run_cli("a", "b")
    assert extra.returncode == 2
    assert "at most one argument" in extra.stderr
