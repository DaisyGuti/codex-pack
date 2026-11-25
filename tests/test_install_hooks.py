"""install.sh and the guardrails hooks.json, run against a throwaway CODEX_HOME.

The installer is copied into a pack of its own under tmp_path (one skill, hooks/hooks.json), so
neither this checkout's skills nor the real ~/.codex is ever touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"
HOOKS_JSON = REPO / "hooks" / "hooks.json"
HOOK_MARK = "skills/guardrails-help/scripts/guardrails.py"


class Pack:
    def __init__(self, root: Path) -> None:
        self.root = root / "codex-pack"
        self.home = root / "codex-home"
        (root / "home").mkdir()
        (self.root / "skills" / "guardrails-help").mkdir(parents=True)
        (self.root / "skills" / "guardrails-help" / "SKILL.md").write_text("# g\n", "utf-8")
        (self.root / "hooks").mkdir()
        shutil.copy(INSTALLER, self.root / "install.sh")
        shutil.copy(HOOKS_JSON, self.src)
        self.env = {
            "CODEX_HOME": str(self.home),
            "HOME": str(root / "home"),
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        }

    @property
    def src(self) -> Path:
        return self.root / "hooks" / "hooks.json"

    @property
    def dest(self) -> Path:
        return self.home / "hooks.json"

    def install(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(self.root / "install.sh"), *args],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )


@pytest.fixture
def pack(tmp_path: Path) -> Pack:
    return Pack(tmp_path)


def test_install_links_hooks_json_and_asks_for_trust(pack: Pack) -> None:
    done = pack.install()
    assert done.returncode == 0, done.stdout + done.stderr
    assert pack.dest.is_symlink() and pack.dest.resolve() == pack.src.resolve()
    assert f"linked: {pack.dest}" in done.stdout
    assert "/hooks" in done.stdout  # the person must review and trust it once
    again = pack.install()
    assert f"already linked: {pack.dest}" in again.stdout


def test_check_reports_the_link_and_a_missing_one(pack: Pack) -> None:
    missing = pack.install("--check")
    assert missing.returncode == 1
    assert f"missing: {pack.dest} is not linked" in missing.stdout
    pack.install()
    ok = pack.install("--check")
    assert ok.returncode == 0, ok.stdout
    assert f"ok: {pack.dest} -> {pack.src}" in ok.stdout


def test_a_hooks_json_of_your_own_is_left_alone_and_the_entry_is_printed(pack: Pack) -> None:
    pack.home.mkdir()
    own = '{"hooks": {"Stop": []}}\n'
    pack.dest.write_text(own, encoding="utf-8")
    done = pack.install()
    assert done.returncode == 0
    assert pack.dest.read_text(encoding="utf-8") == own and not pack.dest.is_symlink()
    assert f"left alone: {pack.dest}" in done.stdout
    printed = done.stdout.split("PreToolUse list:\n", 1)[1].split("\n  ->", 1)[0]
    entry = json.loads(printed)
    assert entry == json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]
    check = pack.install("--check")
    assert check.returncode == 1
    assert "does not run the guardrails hook" in check.stdout


def test_a_hooks_json_of_your_own_that_runs_the_hook_passes_the_check(pack: Pack) -> None:
    pack.home.mkdir()
    entry = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]
    merged = {"hooks": {"Stop": [], "PreToolUse": [entry]}}
    pack.dest.write_text(json.dumps(merged), encoding="utf-8")
    assert "already present" in pack.install().stdout
    check = pack.install("--check")
    assert check.returncode == 0, check.stdout
    assert f"ok: {pack.dest} is your own and runs the guardrails hook" in check.stdout


def test_an_empty_hooks_json_is_replaced(pack: Pack) -> None:
    pack.home.mkdir()
    pack.dest.write_text("", encoding="utf-8")
    done = pack.install()
    assert done.returncode == 0
    assert pack.dest.is_symlink()


def test_a_symlink_into_another_pack_is_refused_without_the_flag(
    pack: Pack, tmp_path: Path
) -> None:
    other = tmp_path / "other-pack"
    (other / "skills").mkdir(parents=True)
    (other / "hooks").mkdir()
    (other / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (other / "hooks" / "hooks.json").write_text(HOOKS_JSON.read_text(encoding="utf-8"), "utf-8")
    pack.home.mkdir()
    pack.dest.symlink_to(other / "hooks" / "hooks.json")
    refused = pack.install()
    assert refused.returncode == 1
    assert "another pack checkout" in refused.stdout
    taken = pack.install("--replace-other-pack")
    assert taken.returncode == 0, taken.stdout
    assert pack.dest.resolve() == pack.src.resolve()


def test_uninstall_removes_only_our_link(pack: Pack) -> None:
    pack.install()
    done = pack.install("--uninstall")
    assert f"removed: {pack.dest}" in done.stdout
    assert not pack.dest.exists() and not pack.dest.is_symlink()
    pack.dest.write_text('{"hooks": {}}', encoding="utf-8")
    pack.install("--uninstall")
    assert pack.dest.read_text(encoding="utf-8") == '{"hooks": {}}'


def test_a_pack_without_hooks_installs_as_before(pack: Pack) -> None:
    shutil.rmtree(pack.root / "hooks")
    done = pack.install()
    assert done.returncode == 0
    assert "skipped: no" in done.stdout and not pack.dest.exists()
    assert pack.install("--check").returncode == 0


def test_the_shipped_hook_names_the_marker_install_looks_for() -> None:
    assert HOOK_MARK in HOOKS_JSON.read_text(encoding="utf-8")
    assert f'HOOK_MARK="{HOOK_MARK}"' in INSTALLER.read_text(encoding="utf-8")
