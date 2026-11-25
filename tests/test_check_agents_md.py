"""scripts/check_agents_md.py accepts a good AGENTS.md and names every defect in a bad one."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_agents_md.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_agents_md_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cam = _load()

GOOD = """# AGENTS.md - Example service

A small service used for tests.

## Commands

- Tests, all: `make test` (Makefile)
- Lint: `npm run lint` (package.json)

## Landing changes

- Branch from `main`, push the branch and open a pull request. Never commit to `main`.

## Security rules

- No secrets in code or prompts. See [the policy](SECURITY.md).
"""


def good_repo(tmp_path: Path, text: str = GOOD, *, support: bool = True) -> Path:
    path = tmp_path / "AGENTS.md"
    path.write_text(text, encoding="utf-8")
    if support:
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"lint": "eslint ."}}), encoding="utf-8"
        )
        (tmp_path / "SECURITY.md").write_text("report\n", encoding="utf-8")
    return path


def failures_of(path: Path) -> list[str]:
    failures, _ = cam.check(path)
    assert isinstance(failures, list)
    return [str(f) for f in failures]


def test_good_file_has_no_failures_or_notes(tmp_path: Path) -> None:
    assert cam.check(good_repo(tmp_path)) == ([], [])


def test_placeholders_and_template_comment_fail(tmp_path: Path) -> None:
    path = good_repo(tmp_path, GOOD + "\n- Install: `{{command}}`\n<!-- delete me -->\n")
    assert sum("template placeholder" in f for f in failures_of(path)) == 2


def test_a_file_past_codexs_read_cap_fails(tmp_path: Path) -> None:
    path = good_repo(tmp_path, GOOD + "x" * cam.MAX_BYTES)
    assert any("Codex reads at most" in f for f in failures_of(path))


def test_missing_sections_and_review_rule_fail(tmp_path: Path) -> None:
    path = good_repo(tmp_path, "# Thin\n\nNothing here.\n", support=False)
    text = "\n".join(failures_of(path))
    assert "Commands section" in text
    assert "Landing changes section" in text
    assert "Security rules section" in text
    assert "never mentions a pull request or merge request" in text


def test_merge_request_wording_satisfies_the_landing_rule(tmp_path: Path) -> None:
    assert failures_of(good_repo(tmp_path, GOOD.replace("pull request", "merge request"))) == []


def test_secret_shapes_fail_without_echoing_the_value(tmp_path: Path) -> None:
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
    key_header = "-----BEGIN RSA " + "PRIVATE KEY-----"
    body = f"\n- Deploy with {token}\n{key_header}\napi_key = abcdefghijklmnop123\n"
    failures = failures_of(good_repo(tmp_path, GOOD + body))
    joined = "\n".join(failures)
    assert "GitHub token" in joined
    assert "private key block" in joined
    assert "inline credential" in joined
    assert token not in joined


def test_machine_paths_fail(tmp_path: Path) -> None:
    path = good_repo(tmp_path, GOOD + "\n- Config lives in /home/someone/app\n")
    assert any("machine-specific path" in f for f in failures_of(path))


def test_cited_make_targets_and_package_scripts_must_exist(tmp_path: Path) -> None:
    extra = "\n- Release: `make release`\n- Setup: `npm install` and `pnpm run build`\n"
    failures = failures_of(good_repo(tmp_path, GOOD + extra))
    assert any("no target 'release' in Makefile" in f for f in failures)
    script_failures = [f for f in failures if "script" in f]
    assert len(script_failures) == 1
    assert "`pnpm run build`: no script 'build' in package.json" in script_failures[0]


def test_make_without_any_makefile_fails(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    path = good_repo(tmp_path, support=False)
    assert any("there is no Makefile" in f for f in failures_of(path))


def test_a_nested_guide_resolves_commands_from_the_repo_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    good_repo(tmp_path)
    nested = tmp_path / "services" / "api"
    nested.mkdir(parents=True)
    path = nested / "AGENTS.md"
    path.write_text(GOOD.replace("](SECURITY.md)", "](../../SECURITY.md)"), encoding="utf-8")
    assert failures_of(path) == []


def test_relative_links_must_resolve(tmp_path: Path) -> None:
    text = GOOD + "\n[guide](docs/guide.md) [site](https://example.invalid) [top](#top)\n"
    failures = failures_of(good_repo(tmp_path, text))
    assert any("'docs/guide.md' does not exist" in f for f in failures)
    assert not any("example.invalid" in f or "#top" in f for f in failures)


def test_unknowns_and_an_unnamed_claude_md_are_notes(tmp_path: Path) -> None:
    path = good_repo(tmp_path, GOOD + "\n- Build: UNKNOWN\n")
    (tmp_path / "CLAUDE.md").write_text("rules\n", encoding="utf-8")
    failures, notes = cam.check(path)
    assert failures == []
    assert notes == [
        "1 UNKNOWN left for a person to fill in",
        "CLAUDE.md exists here; name it under Where the rules live instead of copying",
    ]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def test_cli_exit_codes(tmp_path: Path) -> None:
    path = good_repo(tmp_path)
    assert run_cli(str(path)).returncode == 0
    path.write_text("# Thin\n", encoding="utf-8")
    bad = run_cli(str(path))
    assert bad.returncode == 1
    assert "FAIL: missing a Commands section" in bad.stdout


def test_cli_unreadable_file_exits_2_with_the_fix(tmp_path: Path) -> None:
    missing = run_cli(str(tmp_path / "AGENTS.md"))
    assert missing.returncode == 2
    assert "Pass the path to a UTF-8 AGENTS.md" in missing.stderr
    binary = tmp_path / "AGENTS.md"
    binary.write_bytes(b"\xff\xfe\x00bad")
    assert run_cli(str(binary)).returncode == 2
