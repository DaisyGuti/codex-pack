"""Tests for scripts/registry.py: first-run creation, readiness checks, parsing, board URLs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tickets_helpers import PACK, SCRIPTS, filled_registry_text, load_script

registry = load_script("registry")
EXAMPLE = PACK / "registry.example.md"


@pytest.fixture(autouse=True)
def all_tools_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend every CLI is on PATH so readiness results do not depend on this machine."""
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")


def fake_tools(tmp_path: Path) -> dict[str, str]:
    """An environment whose PATH holds stand-ins for git, gh, glab and jq, for subprocess runs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("git", "gh", "glab", "jq"):
        tool = bin_dir / name
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
    return {**os.environ, "PATH": str(bin_dir)}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_first_run_creates_the_registry_from_the_example_and_asks_to_fill_it_in(
    tmp_path: Path,
) -> None:
    target = tmp_path / "pack" / "registry.md"
    code, payload, reg = registry.ensure(target)
    assert code == registry.EXIT_CREATED
    assert reg is None
    assert payload["status"] == "created"
    assert read(target) == read(EXAMPLE)


def test_example_values_left_in_place_are_reported(tmp_path: Path) -> None:
    target = tmp_path / "registry.md"
    registry.ensure(target)
    code, payload, _ = registry.ensure(target)
    assert code == registry.EXIT_INCOMPLETE
    assert any("your-github-login" in p for p in payload["problems"])


def test_the_shipped_example_is_complete_apart_from_the_values_a_team_fills_in() -> None:
    """The example must hold every section the parser needs; only its own values may be flagged."""
    reg = registry.parse(read(EXAMPLE))
    found = registry.problems(reg, which=lambda name: f"/usr/bin/{name}")
    assert [p for p in found if "example value" not in p and "local clone" not in p] == []


def test_the_default_registry_sits_beside_its_example() -> None:
    assert registry.REGISTRY == PACK / "registry.md"
    assert registry.EXAMPLE == EXAMPLE


def test_filled_registry_is_ready(filled_registry: Path) -> None:
    code, payload, reg = registry.ensure(filled_registry)
    assert (code, payload["status"]) == (0, "ok")
    assert reg is not None


def test_ensure_never_overwrites_an_existing_registry(filled_registry: Path) -> None:
    before = read(filled_registry)
    registry.ensure(filled_registry)
    assert read(filled_registry) == before


def test_unfilled_github_subsection_does_not_block_a_gitlab_registry(
    filled_registry: Path,
) -> None:
    text = read(filled_registry).replace("- Tracker: `github`", "- Tracker: `gitlab`")
    text = text.replace("- Host: `github.com`", "- Host: `gitlab.com`")
    filled_registry.write_text(text.replace("acme/shop-app", "acme-team/shop-app"))
    code, payload, _ = registry.ensure(filled_registry)
    assert (code, payload["status"]) == (0, "ok")


def test_missing_clone_folder_is_a_problem(filled_registry: Path) -> None:
    clone = filled_registry.parent.parent / "code" / "shop-app"
    clone.rmdir()
    code, payload, _ = registry.ensure(filled_registry)
    assert code == registry.EXIT_INCOMPLETE
    assert any("local clone" in p for p in payload["problems"])


def test_missing_required_lane_is_a_problem(filled_registry: Path) -> None:
    lines = [ln for ln in read(filled_registry).splitlines() if not ln.startswith("| ready ")]
    filled_registry.write_text("\n".join(lines))
    _, payload, _ = registry.ensure(filled_registry)
    assert any("'ready'" in p for p in payload["problems"])


def test_unknown_tracker_is_a_problem(filled_registry: Path) -> None:
    filled_registry.write_text(read(filled_registry).replace("`github`", "`jira`", 1))
    _, payload, _ = registry.ensure(filled_registry)
    assert any("'github' or 'gitlab'" in p for p in payload["problems"])


def test_parse_reads_the_trackers_lane_and_priority_columns(filled_registry: Path) -> None:
    text = read(filled_registry)
    github = registry.parse(text)
    assert github["lanes"]["in_progress"] == "In progress"
    assert github["priorities"][0]["value"] == "P0"
    gitlab = registry.parse(text.replace("- Tracker: `github`", "- Tracker: `gitlab`"))
    assert gitlab["lanes"]["in_progress"] == "status::in-progress"
    assert gitlab["priorities"][1]["value"] == "priority::1"


def test_parse_reads_board_labels_models_and_repos(filled_registry: Path) -> None:
    reg = registry.parse(read(filled_registry))
    assert reg["board"] == registry.GitHubBoard(owner="acme", number="1", name="Engineering")
    assert reg["labels"]["run_worker"]["name"] == "run:worker"
    assert reg["model_labels"]["workhorse"]["label"] == "model:workhorse"
    assert reg["repos"][0]["name"] == "shop-app"
    assert reg["repos"][0]["remote"] == "acme/shop-app"
    assert reg["lane_meaning"]["ready"] == "Groomed and queued"


def test_works_for_is_optional_and_read_from_the_tracker_section(filled_registry: Path) -> None:
    text = read(filled_registry)
    assert registry.parse(text)["works_for"] == ""
    pinned = text.replace("- Host: `github.com`", "- Host: `github.com`\n- Works for: `acme-dev`")
    assert registry.parse(pinned)["works_for"] == "acme-dev"


def as_gitlab(text: str, lanes_line: str | None) -> str:
    """Switch a filled registry to GitLab, with the Board's Lanes line replaced or removed."""
    swaps = {
        "- Tracker: `github`": "- Tracker: `gitlab`",
        "- Host: `github.com`": "- Host: `gitlab.com`",
        "acme/shop-app": "acme-team/shop-app",
        "- Lanes: `labels`\n": "" if lanes_line is None else lanes_line + "\n",
    }
    for old, new in swaps.items():
        assert old in text, f"the test registry no longer holds {old!r}"
        text = text.replace(old, new)
    return text


STATUS_LANES = {
    "`status::backlog`": "`Backlog`",
    "`status::ready`": "`Ready`",
    "`status::in-progress`": "`In progress`",
    "`status::blocked`": "`Blocked`",
    "`status::in-review`": "`In review`",
    "`status::done`": "`Done`",
}


def test_gitlab_lane_mode_defaults_to_labels_when_the_line_is_absent(
    filled_registry: Path,
) -> None:
    filled_registry.write_text(as_gitlab(read(filled_registry), None))
    assert registry.ensure(filled_registry)[0] == 0
    reg = registry.parse(read(filled_registry))
    assert reg["lane_mode"] == "labels"
    assert reg["lanes"]["ready"] == "status::ready"


def test_gitlab_status_mode_reads_status_names_as_lanes(
    filled_registry: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The mode is matched case-insensitively, as a person may write it.
    text = as_gitlab(read(filled_registry), "- Lanes: `Status`")
    for label, status in STATUS_LANES.items():
        text = text.replace(label, status)
    filled_registry.write_text(text)
    code, payload, _ = registry.ensure(filled_registry)
    assert (code, payload["status"]) == (0, "ok")
    assert registry.main(["show", "--registry", str(filled_registry)]) == 0
    assert json.loads(capsys.readouterr().out)["lane_mode"] == "status"
    reg = registry.parse(text)
    assert reg["lanes"]["in_progress"] == "In progress"
    assert reg["priorities"][0]["value"] == "priority::0"


def test_gitlab_status_mode_with_label_lanes_is_a_problem(filled_registry: Path) -> None:
    filled_registry.write_text(as_gitlab(read(filled_registry), "- Lanes: `status`"))
    code, payload, _ = registry.ensure(filled_registry)
    assert code == registry.EXIT_INCOMPLETE
    assert any("'status::ready'" in p and "Status name" in p for p in payload["problems"])


def test_unknown_gitlab_lane_mode_is_a_problem(filled_registry: Path) -> None:
    filled_registry.write_text(as_gitlab(read(filled_registry), "- Lanes: `columns`"))
    _, payload, _ = registry.ensure(filled_registry)
    assert any("'labels' or 'status'" in p for p in payload["problems"])


@pytest.mark.parametrize(("written", "code"), [("Group", 0), ("team", registry.EXIT_INCOMPLETE)])
def test_gitlab_scope_is_read_in_any_case_and_an_unknown_one_is_a_problem(
    filled_registry: Path, written: str, code: int
) -> None:
    text = as_gitlab(read(filled_registry), None)
    filled_registry.write_text(text.replace("- Scope: `group`", f"- Scope: `{written}`"))
    found, payload, _ = registry.ensure(filled_registry)
    assert found == code
    if code:
        assert any("Scope 'team'" in p for p in payload["problems"])


def test_github_has_no_lane_mode(filled_registry: Path) -> None:
    assert registry.parse(read(filled_registry))["lane_mode"] is None


def test_batching_is_off_with_the_default_size_when_the_section_is_absent(
    filled_registry: Path,
) -> None:
    text = read(filled_registry)
    without = text.replace("- Batching: `off`\n", "").replace("- Batch size: `5`\n", "")
    assert without != text
    assert registry.parse(without)["batching"] == {"mode": "off", "size": 5}


@pytest.mark.parametrize(
    ("tracker", "mode", "ok"),
    [
        ("github", "sub-issues", True),
        ("github", "labels", True),
        ("github", "epics", False),
        ("gitlab", "epics", True),
        ("gitlab", "sub-issues", False),
        ("gitlab", "Labels", True),
    ],
)
def test_batching_mode_must_exist_on_the_tracker(
    filled_registry: Path, tracker: str, mode: str, ok: bool
) -> None:
    text = read(filled_registry).replace("- Batching: `off`", f"- Batching: `{mode}`")
    if tracker == "gitlab":
        text = as_gitlab(text, "- Lanes: `labels`")
    filled_registry.write_text(text)
    code, payload, _ = registry.ensure(filled_registry)
    assert (code == 0) is ok, payload
    if ok:
        assert registry.parse(text)["batching"]["mode"] == mode.lower()
    else:
        assert any(f"'{mode}' does not exist" in p for p in payload["problems"])


@pytest.mark.parametrize("value", ["`zero`", "`0`", "`many`"])
def test_bad_batch_size_or_mode_is_a_problem(filled_registry: Path, value: str) -> None:
    text = read(filled_registry).replace("- Batch size: `5`", f"- Batch size: {value}")
    filled_registry.write_text(text.replace("- Batching: `off`", "- Batching: `piles`"))
    _, payload, _ = registry.ensure(filled_registry)
    assert any("Batch size is" in p for p in payload["problems"])
    assert any("Batching is 'piles'" in p for p in payload["problems"])


def test_model_label_weights_are_read_and_optional(filled_registry: Path) -> None:
    text = read(filled_registry)
    tiers = registry.parse(text)["model_labels"]
    assert {tier: row["weight"] for tier, row in tiers.items()} == {
        "fast": 1,
        "workhorse": 3,
        "frontier": 5,
    }
    no_column = text.replace("| Tier | Label | Color | Weight |", "| Tier | Label | Color |")
    no_column = no_column.replace("| --- | --- | --- | --- |", "| --- | --- | --- |", 1)
    for size in (" 1 |", " 3 |", " 5 |"):
        no_column = no_column.replace(f"`ededed` |{size}", "`ededed` |")
    assert all(row["weight"] is None for row in registry.parse(no_column)["model_labels"].values())


def test_a_weight_that_is_not_a_whole_number_is_a_problem(filled_registry: Path) -> None:
    text = read(filled_registry).replace("| `ededed` | 5 |", "| `ededed` | big |")
    filled_registry.write_text(text)
    _, payload, _ = registry.ensure(filled_registry)
    assert any("weight for tier 'frontier' is 'big'" in p for p in payload["problems"])


def test_tilde_in_a_clone_path_expands_against_home(tmp_path: Path) -> None:
    text = filled_registry_text(Path("~/code/my-app"))
    reg = registry.parse(text, home=tmp_path)
    assert reg["repos"][0]["clone"] == str(tmp_path / "code" / "my-app")
    assert reg["repos"][0]["brief"] == str(tmp_path / "code" / "my-app" / "README.md")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/orgs/acme/projects/4/views/2",
            {"kind": "github-project", "owner": "acme", "number": 4},
        ),
        (
            "https://github.com/users/jo/projects/9",
            {"kind": "github-project", "owner": "jo", "number": 9},
        ),
        (
            "https://gitlab.com/groups/acme/sub/-/boards/12?label_name[]=x",
            {"kind": "gitlab-group", "scope": "group", "path": "acme/sub", "board_id": 12},
        ),
        (
            "https://gitlab.com/acme/app/-/boards/7",
            {"kind": "gitlab-project", "scope": "project", "path": "acme/app", "board_id": 7},
        ),
    ],
)
def test_board_urls_resolve(url: str, expected: dict[str, object]) -> None:
    host = url.split("/")[2]
    code, payload = registry.board_url(url, {"host": host})
    assert code == 0
    assert payload == expected


def test_board_url_on_another_host_is_refused() -> None:
    code, payload = registry.board_url(
        "https://gitlab.example.com/groups/a/-/boards/1", {"host": "gitlab.com"}
    )
    assert code == registry.EXIT_HOST_MISMATCH
    assert "gitlab.com" in payload["message"]


def test_unrecognized_url_is_refused_with_the_accepted_shapes() -> None:
    code, payload = registry.board_url("https://example.com/nothing", {"host": "example.com"})
    assert code == registry.EXIT_BAD_INPUT
    assert "Expected" in payload["message"]


def test_command_line_show_prints_json_for_a_ready_registry(
    filled_registry: Path, tmp_path: Path
) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "registry.py"), "show", "--registry", str(filled_registry)],
        capture_output=True,
        text=True,
        check=False,
        env=fake_tools(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    shown: dict[str, Any] = json.loads(proc.stdout)
    assert shown["tracker"] == "github"
    # The skills read the board's keys from this object.
    assert shown["board"] == {"owner": "acme", "number": "1", "name": "Engineering"}


def test_command_line_board_url_checks_the_registry_host(
    filled_registry: Path, tmp_path: Path
) -> None:
    def run(url: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "registry.py"),
                "board-url",
                url,
                "--registry",
                str(filled_registry),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=fake_tools(tmp_path),
        )

    ok = run("https://github.com/orgs/acme/projects/4")
    assert ok.returncode == 0
    assert json.loads(ok.stdout) == {"kind": "github-project", "owner": "acme", "number": 4}
    assert run("https://ghe.example.com/orgs/acme/projects/4").returncode == 5


def test_command_line_exit_code_is_3_on_first_run_whichever_way_the_script_is_reached(
    tmp_path: Path,
) -> None:
    """Through a skill's symlink the pack's example is still found."""
    for script in (
        SCRIPTS / "registry.py",
        PACK / "skills" / "work-tickets" / "scripts" / "registry.py",
    ):
        target = tmp_path / script.parent.parent.name / "registry.md"
        proc = subprocess.run(
            [sys.executable, str(script), "ensure", "--registry", str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 3, proc.stderr
        assert json.loads(proc.stdout)["status"] == "created"
        assert target.is_file()


def test_missing_tracker_cli_is_a_problem_with_an_install_hint(
    filled_registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "gh" else "/bin/x")
    code, payload, _ = registry.ensure(filled_registry)
    assert code == registry.EXIT_INCOMPLETE
    assert any("'gh' is not on PATH" in p and "gh auth login" in p for p in payload["problems"])


def test_gitlab_needs_glab_and_jq(filled_registry: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = read(filled_registry).replace("- Tracker: `github`", "- Tracker: `gitlab`")
    filled_registry.write_text(text.replace("acme/shop-app", "acme-team/shop-app"))
    monkeypatch.setattr(shutil, "which", lambda name: None if name in {"glab", "jq"} else "/bin/x")
    _, payload, _ = registry.ensure(filled_registry)
    missing = [p for p in payload["problems"] if "is not on PATH" in p]
    assert len(missing) == 2


def test_a_pack_without_its_example_is_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry, "EXAMPLE", tmp_path / "missing.md")
    code, payload, reg = registry.ensure(tmp_path / "registry.md")
    assert (code, reg) == (registry.EXIT_BAD_INPUT, None)
    assert "reinstall the pack" in payload["message"]
