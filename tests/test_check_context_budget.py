"""scripts/check_context_budget.py measures the AGENTS.md chain Codex loads against a budget.

Every test points CODEX_HOME at a throwaway folder, so the tester's real global AGENTS.md and
config.toml are never read.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_context_budget.py"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_context_budget_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


ccb = _load()


@pytest.fixture(autouse=True)
def codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "codex-home"
    path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(path))
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def put(root: Path, rel: str, size: int = 100, text: str | None = None) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else "x" * size, encoding="utf-8")
    return path


def run(capsys: pytest.CaptureFixture[str], root: Path, *args: str) -> tuple[int, str, str]:
    code = ccb.main([str(root), *args])
    captured = capsys.readouterr()
    return int(code), captured.out, captured.err


def report(capsys: pytest.CaptureFixture[str], root: Path, *args: str) -> dict[str, Any]:
    code, out, _ = run(capsys, root, "--json", *args)
    data = json.loads(out)
    assert isinstance(data, dict)
    assert code == (0 if data["ok"] else 1)
    return data


def paths(data: dict[str, Any]) -> list[str]:
    return [f["path"] for f in data["files"]]


def test_one_file_per_folder_on_the_way_down_override_first(
    capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    put(repo, "AGENTS.md", 10)
    put(repo, "backend/AGENTS.override.md", 20)
    put(repo, "backend/AGENTS.md", 25)
    put(repo, "backend/api/AGENTS.md", text="  \n")  # whitespace only: Codex skips it
    put(repo, "backend/api/new_dir/notes.txt", 1)
    put(repo, "frontend/AGENTS.md", 50)
    data = report(capsys, repo, "--path", "backend/api/new_dir")
    assert paths(data) == ["AGENTS.md", "backend/AGENTS.override.md"]
    data = report(capsys, repo, "--path", "backend", "--path", "frontend")
    assert paths(data) == ["AGENTS.md", "backend/AGENTS.override.md", "frontend/AGENTS.md"]


def test_the_global_file_and_codexs_config_are_read_from_codex_home(
    capsys: pytest.CaptureFixture[str], repo: Path, codex_home: Path
) -> None:
    put(codex_home, "AGENTS.md", 400)
    override = put(codex_home, "AGENTS.override.md", 40)
    put(codex_home, "config.toml", text='project_doc_fallback_filenames = ["TEAM_GUIDE.md"]\n')
    put(repo, "TEAM_GUIDE.md", 8)
    data = report(capsys, repo)
    assert data["files"][0] == {
        "path": str(override.resolve()),
        "kind": "global",
        "bytes": 40,
        "tokens_est": 10,
    }
    assert paths(data)[1:] == ["TEAM_GUIDE.md"]


def test_defaults_flag_the_file_and_the_total_and_name_the_excess(
    capsys: pytest.CaptureFixture[str], repo: Path, codex_home: Path
) -> None:
    put(codex_home, "AGENTS.md", 10_000)
    put(repo, "AGENTS.md", 16_385)
    put(repo, "a/AGENTS.md", 7_000)
    data = report(capsys, repo, "--path", "a")
    assert data["limits"]["guide_bytes"] == 16_384
    assert data["limits"]["total_bytes"] == 32_768
    assert [(o["path"], o["over_by"]) for o in data["over_budget"]] == [("AGENTS.md", 1)]
    assert data["total_over_by"] == 617
    assert data["cut_by_codex"] == []  # the project chain alone still fits Codex's cap
    code, out, _ = run(capsys, repo, "--path", "a")
    assert code == 1
    assert "OVER AGENTS.md: 16,385 B, 1 B past" in out


def test_a_chain_past_codexs_cap_fails_whatever_the_baseline(
    capsys: pytest.CaptureFixture[str], repo: Path, codex_home: Path
) -> None:
    put(codex_home, "config.toml", text="project_doc_max_bytes = 1000\n")
    put(repo, ".context-budget.toml", text="guide_bytes = 5000\ntotal_bytes = 5000\n")
    put(repo, "AGENTS.md", 600)
    put(repo, "a/AGENTS.md", 600)
    data = report(capsys, repo, "--path", "a")
    assert data["over_budget"] == []
    assert data["cut_by_codex"] == [
        {"folder": "a", "project_bytes": 1200, "cap": 1000, "cut_bytes": 200}
    ]
    assert "200 B never reach the model" in run(capsys, repo, "--path", "a")[1]


def test_a_repo_config_overrides_the_limits(capsys: pytest.CaptureFixture[str], repo: Path) -> None:
    put(repo, "AGENTS.md", 500)
    assert run(capsys, repo)[0] == 0
    put(repo, ".context-budget.toml", text="guide_bytes = 400\ntotal_bytes = 450\n")
    data = report(capsys, repo)
    assert data["over_budget"][0]["over_by"] == 100
    put(repo, ".context-budget.toml", text="guide_bytes = 1000\ntotal_bytes = 450\n")
    assert report(capsys, repo)["total_over_by"] == 50


def test_a_baselined_file_is_held_where_it_is_and_cannot_grow(
    capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    put(repo, ".context-budget.toml", text='[baseline]\n"a/AGENTS.md" = 20000\n')
    guide = put(repo, "a/AGENTS.md", 20_000)
    assert run(capsys, repo, "--all")[0] == 0
    guide.write_text("x" * 20_001, encoding="utf-8")
    assert report(capsys, repo, "--all")["over_budget"] == [
        {"path": "a/AGENTS.md", "bytes": 20_001, "limit": 20_000, "over_by": 1, "baselined": True}
    ]


def test_write_baseline_adds_and_lowers_entries_but_never_raises_one(
    capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    put(repo, "AGENTS.md", 30_000)
    put(repo, "big/AGENTS.md", 20_000)
    put(repo, "small/AGENTS.md", 1_000)
    put(repo, ".context-budget.toml", text='[baseline]\n"big/AGENTS.md" = 25000\n"gone.md" = 5\n')
    run(capsys, repo, "--all", "--write-baseline")
    config = (repo / ".context-budget.toml").read_text(encoding="utf-8")
    assert '"AGENTS.md" = 30000' in config
    assert '"big/AGENTS.md" = 20000' in config
    assert "small" not in config
    assert "gone.md" not in config
    # A file that has grown past its entry is refused; the write leaves the entry as it was.
    put(repo, "big/AGENTS.md", 22_000)
    run(capsys, repo, "--all", "--write-baseline")
    assert '"big/AGENTS.md" = 20000' in (repo / ".context-budget.toml").read_text("utf-8")
    assert run(capsys, repo, "--all")[0] == 1


def test_a_baseline_above_its_file_fails_until_lowered(
    capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    put(repo, ".context-budget.toml", text='[baseline]\n"AGENTS.md" = 30000\n')
    put(repo, "AGENTS.md", 25_000)
    code, out, _ = run(capsys, repo, "--all")
    assert code == 1
    assert "STALE AGENTS.md" in out
    run(capsys, repo, "--all", "--write-baseline")
    assert run(capsys, repo, "--all")[0] == 0


def test_write_baseline_keeps_entries_for_guides_it_did_not_measure(
    capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    put(repo, "docs/AGENTS.md", 10)
    put(repo, "apps/AGENTS.md", 20_000)
    put(repo, ".context-budget.toml", text='[baseline]\n"apps/AGENTS.md" = 20000\n')
    run(capsys, repo, "--path", "docs", "--write-baseline")
    assert '"apps/AGENTS.md" = 20000' in (repo / ".context-budget.toml").read_text("utf-8")


def test_write_baseline_never_records_the_global_file(
    capsys: pytest.CaptureFixture[str], repo: Path, codex_home: Path
) -> None:
    put(codex_home, "AGENTS.md", 20_000)
    put(repo, "AGENTS.md", 10)
    run(capsys, repo, "--write-baseline")
    assert "baseline" not in (repo / ".context-budget.toml").read_text(encoding="utf-8")


def test_all_counts_every_guide_but_not_the_global_file_or_the_total(
    capsys: pytest.CaptureFixture[str], repo: Path, codex_home: Path
) -> None:
    put(codex_home, "AGENTS.md", 10)
    for area in "abc":
        put(repo, f"{area}/AGENTS.md", 15_000)
    put(repo, "a/AGENTS.override.md", 10)
    put(repo, "node_modules/pkg/AGENTS.md", 10)
    data = report(capsys, repo, "--all")
    assert paths(data) == ["a/AGENTS.override.md", "a/AGENTS.md", "b/AGENTS.md", "c/AGENTS.md"]
    assert data["ok"] is True


def test_all_in_a_git_repo_skips_ignored_guides(
    capsys: pytest.CaptureFixture[str], repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    put(repo, ".gitignore", text="vendor/\n")
    put(repo, "AGENTS.md", 1)
    put(repo, "docs/AGENTS.md", 1)
    put(repo, "vendor/AGENTS.md", 1)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, stdin=subprocess.DEVNULL)
    assert paths(report(capsys, repo, "--all")) == ["AGENTS.md", "docs/AGENTS.md"]


def test_a_symlinked_config_is_refused_and_its_target_left_untouched(
    capsys: pytest.CaptureFixture[str], repo: Path, tmp_path: Path
) -> None:
    victim = put(tmp_path, "victim.txt", text="keep me\n")
    (repo / ".context-budget.toml").symlink_to(victim)
    put(repo, "AGENTS.md", 20_000)
    code, _, err = run(capsys, repo, "--write-baseline")
    assert code == 2
    assert "symlink" in err
    assert victim.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.parametrize(
    "setup", ["no_root", "missing_path", "path_outside", "bad_toml", "bad_value", "bad_codex"]
)
def test_usage_errors_exit_2_and_name_the_problem(
    capsys: pytest.CaptureFixture[str], repo: Path, tmp_path: Path, codex_home: Path, setup: str
) -> None:
    args: list[str] = []
    root = repo
    if setup == "no_root":
        root = tmp_path / "missing"
    elif setup == "missing_path":
        args = ["--path", "typo"]
    elif setup == "path_outside":
        args = ["--path", ".."]
    elif setup == "bad_toml":
        put(repo, ".context-budget.toml", text="guide_bytes = = 3")
    elif setup == "bad_value":
        put(repo, ".context-budget.toml", text='guide_bytes = "big"\n')
    else:
        put(codex_home, "config.toml", text='project_doc_max_bytes = "lots"\n')
    code, out, err = run(capsys, root, *args)
    assert code == 2
    assert out == ""
    assert "check_context_budget.py:" in err


def test_json_report_has_the_documented_shape(
    capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    put(repo, "AGENTS.md", 8)
    data = report(capsys, repo)
    assert set(data) == {
        "limits",
        "token_estimate",
        "files",
        "chains",
        "total_bytes",
        "total_tokens_est",
        "large",
        "over_budget",
        "stale_baseline",
        "total_over_by",
        "cut_by_codex",
        "ok",
    }
    assert data["files"] == [{"path": "AGENTS.md", "kind": "project", "bytes": 8, "tokens_est": 2}]
