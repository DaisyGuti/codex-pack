"""Shared helpers for the guardrails tests: the hook module, a throwaway repo and Codex home,
and a runner that feeds the script a payload the way Codex does.

Everything here is synthetic. Fake credentials are assembled from pieces at run time so no
file in this repo holds a literal a secret scanner would flag. No test reads or writes the
real ~/.codex: every world sets HOME and CODEX_HOME to directories under tmp_path.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "guardrails.py"
SKILL_DIR = REPO / "skills" / "guardrails-help"
HOOKS_JSON = REPO / "hooks" / "hooks.json"
PATH = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"

# Credential-shaped values built from parts.
GITHUB = "gh" + "p_" + "a1B2c3D4e5F6" * 3
AWS = "AK" + "IA" + "QWERTYUIOPASDFGH"
RANDOM_VALUE = "Zk3Jf9aQw2" + "LmN8pXr5Tv7Bc1"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("guardrails_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


G = _load()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def build_template(root: Path) -> Path:
    """One repo on branch feature/x with a build/ directory, to copy for each test."""
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    git(repo, "checkout", "-q", "-b", "feature/x")
    (repo / "build").mkdir()
    return repo


@dataclass
class World:
    """A repo on feature/x, a fake home and Codex home, and the environment a hook sees."""

    repo: Path
    home: Path
    codex_home: Path
    env: dict[str, str]

    @property
    def data(self) -> Path:
        return self.codex_home / "guardrails"

    def payload(self, tool: str, cwd: Path | None = None, **tool_input: Any) -> dict[str, Any]:
        return {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": tool,
            "tool_input": tool_input,
            "cwd": str(cwd or self.repo),
        }

    def rules(self, tool: str, cwd: Path | None = None, **tool_input: Any) -> list[str]:
        """Sorted rule ids the hook raises for one call."""
        found = G.evaluate(self.payload(tool, cwd, **tool_input), self.env)
        return sorted({f.rule for f in found})

    def bash(self, command: str, cwd: Path | None = None) -> list[str]:
        return self.rules("Bash", cwd, command=command)

    def patch(self, text: str, cwd: Path | None = None) -> list[str]:
        return self.rules("apply_patch", cwd, command=text)

    def run_hook(
        self, payload: object, env: dict[str, str] | None = None, python: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """The script as Codex runs it: JSON on stdin, exit code and stderr back."""
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            [python or sys.executable, str(SCRIPT)],
            input=raw,
            capture_output=True,
            text=True,
            env=env if env is not None else self.env,
            cwd=str(self.repo),
            check=False,
        )


def make_world(tmp_path: Path, template: Path) -> World:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    codex_home = tmp_path / "codex-home"
    shutil.copytree(template, repo)
    home.mkdir()
    codex_home.mkdir()
    env = {"HOME": str(home), "CODEX_HOME": str(codex_home), "PATH": PATH}
    return World(repo, home, codex_home, env)


def add_file(path: str, *lines: str) -> str:
    """An apply_patch text that adds one file."""
    body = "".join(f"+{line}\n" for line in lines)
    return f"*** Begin Patch\n*** Add File: {path}\n{body}*** End Patch"


def update_file(path: str, hunk: str, move_to: str | None = None) -> str:
    """An apply_patch text that updates one file with *hunk* (lines starting ` `, `-`, `+`)."""
    move = f"*** Move to: {move_to}\n" if move_to else ""
    return f"*** Begin Patch\n*** Update File: {path}\n{move}@@\n{hunk}\n*** End Patch"


def delete_file(path: str) -> str:
    return f"*** Begin Patch\n*** Delete File: {path}\n*** End Patch"
