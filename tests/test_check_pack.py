"""scripts/check_pack.py against tiny fixture packs, one per rule, plus the real pack.

Invisible characters and secret-shaped strings are built at run time, so this file holds
neither and passes its own scan.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_pack.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_pack_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


cp = _load()

ZERO_WIDTH_SPACE = chr(0x200B)
RIGHT_TO_LEFT_OVERRIDE = chr(0x202E)
TAG_LETTER_A = chr(0xE0061)
BYTE_ORDER_MARK = chr(0xFEFF)


def agent_toml(
    name: str, extra: str = "", *, body: str = 'developer_instructions = "Do it."\n'
) -> str:
    return f'name = "{name}"\ndescription = "Does a thing."\n{extra}{body}'


def make_pack(root: Path) -> Path:
    """A minimal pack that passes every check: five agents, one skill, one named path."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "agents").mkdir()
    for name in ("eng", "ticket_worker", "prompt_optimizer"):
        (root / "agents" / f"{name}.toml").write_text(agent_toml(name), encoding="utf-8")
    for name in cp.READ_ONLY_AGENTS:
        (root / "agents" / f"{name}.toml").write_text(
            agent_toml(name, 'sandbox_mode = "read-only"\n'), encoding="utf-8"
        )
    (root / "skills" / "eng" / "references").mkdir(parents=True)
    (root / "skills" / "eng" / "references" / "guide.md").write_text("A guide.\n", encoding="utf-8")
    (root / "skills" / "eng" / "SKILL.md").write_text("# Eng\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "Read `${CODEX_HOME:-~/.codex}/skills/eng/references/guide.md` first.\n", encoding="utf-8"
    )
    return root


def rules(findings: list[object]) -> list[str]:
    return [f"{f.rule} {f.where}" for f in findings]  # type: ignore[attr-defined]


# --- a clean pack ------------------------------------------------------------------------


def test_a_well_formed_pack_has_no_findings(tmp_path: Path) -> None:
    findings, summary = cp.run(make_pack(tmp_path))
    assert findings == []
    assert "5 agent file(s), 1 named path(s)" in summary[0]


def test_the_real_pack_passes() -> None:
    findings, _ = cp.run(REPO)
    assert [f.line() for f in findings] == []


# --- agent files -------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["description", "developer_instructions"])
def test_a_missing_required_key_fails(tmp_path: Path, key: str) -> None:
    pack = make_pack(tmp_path)
    text = (pack / "agents" / "eng.toml").read_text(encoding="utf-8")
    kept = [ln for ln in text.splitlines() if not ln.startswith(key)]
    (pack / "agents" / "eng.toml").write_text("\n".join(kept) + "\n", encoding="utf-8")
    findings, _ = cp.check_agents(pack)
    assert rules(findings) == ["agent-shape agents/eng.toml"]
    assert key in findings[0].detail


def test_an_empty_developer_instructions_fails(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    body = 'developer_instructions = "   "\n'
    (pack / "agents" / "eng.toml").write_text(agent_toml("eng", body=body), encoding="utf-8")
    findings, _ = cp.check_agents(pack)
    assert rules(findings) == ["agent-shape agents/eng.toml"]


def test_a_name_that_differs_from_the_file_name_fails(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "agents" / "eng.toml").write_text(agent_toml("engineer"), encoding="utf-8")
    findings, _ = cp.check_agents(pack)
    assert rules(findings) == ["agent-shape agents/eng.toml"]
    assert "file name" in findings[0].detail


@pytest.mark.parametrize("line", ['model = "x"\n', 'model_reasoning_effort = "high"\n'])
def test_an_agent_that_pins_a_model_or_effort_fails(tmp_path: Path, line: str) -> None:
    pack = make_pack(tmp_path)
    (pack / "agents" / "eng.toml").write_text(agent_toml("eng", line), encoding="utf-8")
    findings, _ = cp.check_agents(pack)
    assert rules(findings) == ["agent-shape agents/eng.toml"]
    assert line.split(" ")[0] in findings[0].detail


def test_a_file_that_is_not_toml_fails_once(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "agents" / "eng.toml").write_text("name = \n", encoding="utf-8")
    findings, count = cp.check_agents(pack)
    assert rules(findings) == ["agent-shape agents/eng.toml"]
    assert count == 5


@pytest.mark.parametrize("name", list(cp.READ_ONLY_AGENTS))
def test_a_read_only_agent_that_loses_its_sandbox_fails(tmp_path: Path, name: str) -> None:
    pack = make_pack(tmp_path)
    (pack / "agents" / f"{name}.toml").write_text(agent_toml(name), encoding="utf-8")
    findings, _ = cp.check_agents(pack)
    assert rules(findings) == [f"read-only agents/{name}.toml"]


def test_a_read_only_agent_with_another_sandbox_fails(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    extra = 'sandbox_mode = "workspace-write"\n'
    (pack / "agents" / "reviewer.toml").write_text(agent_toml("reviewer", extra), encoding="utf-8")
    findings, _ = cp.check_agents(pack)
    assert rules(findings) == ["read-only agents/reviewer.toml"]


def test_a_deleted_read_only_agent_fails(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "agents" / "forward_tester.toml").unlink()
    findings, _ = cp.check_agents(pack)
    assert rules(findings) == ["read-only agents/forward_tester.toml"]


# --- paths named in instructions ---------------------------------------------------------


def test_a_named_path_that_does_not_exist_fails_with_file_and_line(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "AGENTS.md").write_text(
        "intro\nRead `${CODEX_HOME:-~/.codex}/skills/eng/references/gone.md`.\n", encoding="utf-8"
    )
    findings, examined = cp.check_paths(pack)
    assert rules(findings) == ["path AGENTS.md:2"]
    assert "skills/eng/references/gone.md" in findings[0].detail
    assert examined == 1


def test_sentence_punctuation_after_a_path_is_not_part_of_it(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "AGENTS.md").write_text(
        "See ${CODEX_HOME:-~/.codex}/skills/eng/references/guide.md, then stop.\n"
        "Or ${CODEX_HOME:-~/.codex}/skills/eng/references/guide.md.\n",
        encoding="utf-8",
    )
    findings, examined = cp.check_paths(pack)
    assert findings == []
    assert examined == 2


def test_the_tilde_form_in_an_agent_file_is_checked(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    body = 'developer_instructions = "Read ~/.codex/skills/eng/MISSING.md first."\n'
    (pack / "agents" / "eng.toml").write_text(agent_toml("eng", body=body), encoding="utf-8")
    findings, _ = cp.check_paths(pack)
    assert rules(findings) == ["path agents/eng.toml:3"]


def test_a_path_in_a_skill_file_is_checked(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "skills" / "eng" / "SKILL.md").write_text(
        "Run ${CODEX_HOME:-~/.codex}/skills/eng/scripts/nope.py now.\n", encoding="utf-8"
    )
    findings, _ = cp.check_paths(pack)
    assert rules(findings) == ["path skills/eng/SKILL.md:1"]


def test_a_path_that_resolves_through_a_symlink_passes(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "references").mkdir()
    (pack / "references" / "shared.md").write_text("shared\n", encoding="utf-8")
    (pack / "skills" / "eng" / "references" / "shared.md").symlink_to(
        pack / "references" / "shared.md"
    )
    (pack / "AGENTS.md").write_text(
        "${CODEX_HOME:-~/.codex}/skills/eng/references/shared.md\n", encoding="utf-8"
    )
    findings, examined = cp.check_paths(pack)
    assert (findings, examined) == ([], 1)


def test_codex_system_skills_and_placeholders_are_not_the_packs_to_resolve(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "AGENTS.md").write_text(
        "${CODEX_HOME:-~/.codex}/skills/.system/skill-creator/scripts/quick_validate.py\n"
        "${CODEX_HOME:-~/.codex}/skills/<name>/SKILL.md and ${CODEX_HOME:-~/.codex}/skills/*/x\n",
        encoding="utf-8",
    )
    assert cp.check_paths(pack) == ([], 0)


# --- hidden characters -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("char", "code"),
    [
        (ZERO_WIDTH_SPACE, "U+200B"),
        (RIGHT_TO_LEFT_OVERRIDE, "U+202E"),
        (TAG_LETTER_A, "U+E0061"),
        (BYTE_ORDER_MARK, "U+FEFF"),
    ],
)
def test_an_invisible_character_fails_with_its_code_and_line(
    tmp_path: Path, char: str, code: str
) -> None:
    pack = make_pack(tmp_path)
    (pack / "notes.md").write_text(f"fine\nlook{char}here\n", encoding="utf-8")
    findings = cp.check_text(pack, [pack / "notes.md"])
    assert [f.line() for f in findings] == [f"FAIL hidden-char notes.md:2: contains {code}"]
    assert char not in findings[0].line()


def test_ordinary_non_ascii_text_passes(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "notes.md").write_text("café — über → \U0001f600\n", encoding="utf-8")
    assert cp.check_text(pack, [pack / "notes.md"]) == []


# --- secrets -----------------------------------------------------------------------------

FAKE_SECRETS = {
    "private key header": "-----" + "BEGIN OPENSSH PRIVATE KEY" + "-----",
    "sk- API key": "sk-" + "proj-" + "a1B2c3D4" * 4,
    "GitHub token": "ghp_" + "a1B2c3D4e5" * 4,
    "GitLab token": "glpat-" + "a1B2c3D4e5" * 3,
}


@pytest.mark.parametrize("kind", list(FAKE_SECRETS))
def test_each_secret_shape_fails_and_is_never_echoed(tmp_path: Path, kind: str) -> None:
    pack = make_pack(tmp_path)
    secret = FAKE_SECRETS[kind]
    (pack / "notes.md").write_text(f"ok\ntoken = {secret}\n", encoding="utf-8")
    findings = cp.check_text(pack, [pack / "notes.md"])
    assert [f.line() for f in findings] == [f"FAIL secret notes.md:2: looks like a {kind}"]
    assert secret not in findings[0].line()


def test_the_new_style_github_token_is_caught(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "notes.md").write_text("github_pat_" + "A1b2C3d4E5" * 3 + "\n", encoding="utf-8")
    assert rules(cp.check_text(pack, [pack / "notes.md"])) == ["secret notes.md:1"]


def test_prose_that_mentions_keys_without_holding_one_passes(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "notes.md").write_text(
        "Set an API key (sk-... style) in .env.\nThe task-runner skill is sk-short.\n"
        "A token starts with ghp_ then letters.\n",
        encoding="utf-8",
    )
    assert cp.check_text(pack, [pack / "notes.md"]) == []


def test_a_binary_file_is_skipped(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "image.png").write_bytes(b"\x89PNG\0" + FAKE_SECRETS["sk- API key"].encode())
    assert cp.check_text(pack, [pack / "image.png"]) == []


# --- listing and the driver --------------------------------------------------------------


def test_listing_covers_tracked_and_unignored_untracked_files_and_skips_ignored_ones(
    tmp_path: Path,
) -> None:
    pack = make_pack(tmp_path)
    (pack / ".gitignore").write_text("secret.env\n", encoding="utf-8")
    (pack / "secret.env").write_text("x\n", encoding="utf-8")
    (pack / "tracked.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.md"], cwd=pack, check=True)
    names = {p.relative_to(pack).as_posix() for p in cp.listed_files(pack)}
    assert {"tracked.md", "AGENTS.md", ".gitignore"} <= names
    assert "secret.env" not in names


def test_a_secret_in_an_untracked_file_fails_the_run(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    (pack / "draft.md").write_text(FAKE_SECRETS["sk- API key"] + "\n", encoding="utf-8")
    findings, _ = cp.run(pack)
    assert rules(findings) == ["secret draft.md:1"]


def test_a_check_that_examined_nothing_fails(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    findings, _ = cp.run(tmp_path)
    assert [f.detail for f in findings if f.rule == "blind"] == [
        "no agent file was examined",
        "no named path was examined",
        "no text file was examined",
    ]


def test_main_prints_findings_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pack = make_pack(tmp_path)
    (pack / "agents" / "eng.toml").write_text(agent_toml("eng", 'model = "x"\n'), encoding="utf-8")
    assert cp.main(["--root", str(pack)]) == 1
    out = capsys.readouterr().out
    assert "FAIL agent-shape agents/eng.toml" in out
    assert "1 failure(s)" in out


def test_main_exits_zero_on_a_clean_pack(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cp.main(["--root", str(make_pack(tmp_path))]) == 0
    assert "0 failure(s)" in capsys.readouterr().out


def test_main_refuses_when_git_cannot_list_the_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "agents").mkdir()  # not a git repository
    assert cp.main(["--root", str(tmp_path)]) == 1
    assert "nothing was checked" in capsys.readouterr().out


# --- the reviewer outcome is named where the agent and the skill both need it -----------


def test_the_could_not_review_outcome_is_named_by_the_agent_and_the_skill() -> None:
    for relative in ("agents/reviewer.toml", "skills/eng/SKILL.md"):
        assert "could not review" in (REPO / relative).read_text(encoding="utf-8"), relative
