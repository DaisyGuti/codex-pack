"""scripts/check_skills.py against tiny fixture skills built in tmp, one per rule."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_skills.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_skills_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


cs = _load()

GOOD_DESCRIPTION = (
    "Review a diff for bugs. Use when asked to review code. Not for writing new code."
)


def write_skill(
    root: Path,
    name: str = "demo",
    *,
    description: str | None = GOOD_DESCRIPTION,
    name_line: str | None = None,
    extra: str = "",
    body: str = "# Demo\n\nDo the thing.\n",
    raw: str | None = None,
    directory: str | None = None,
) -> Path:
    """A skill directory under root/skills. `raw` replaces the whole SKILL.md."""
    skill = root / "skills" / (directory or name)
    skill.mkdir(parents=True, exist_ok=True)
    if raw is None:
        lines = [name_line if name_line is not None else f"name: {name}"]
        if description is not None:
            lines.append(f"description: {description}")
        raw = "---\n" + "\n".join([*lines, extra] if extra else lines) + "\n---\n" + body
    (skill / "SKILL.md").write_text(raw, encoding="utf-8")
    return skill


def check(root: Path, codex_home: Path | None = None) -> list[str]:
    """Every finding as 'LEVEL skill RULE', in the order printed."""
    findings, _, _ = cs.check_pack(root / "skills", codex_home or root / "no-codex-home")
    return [f"{f.level} {f.skill} {f.rule}" for f in findings]


def details(root: Path, rule: str) -> str:
    findings, _, _ = cs.check_pack(root / "skills", root / "no-codex-home")
    return " | ".join(f.detail for f in findings if f.rule == rule)


# --- a clean skill ----------------------------------------------------------------------


def test_a_well_formed_skill_has_no_findings(tmp_path: Path) -> None:
    write_skill(tmp_path)
    assert check(tmp_path) == []


def test_a_folded_description_is_measured_after_yaml_folding(tmp_path: Path) -> None:
    write_skill(
        tmp_path,
        raw="---\nname: demo\ndescription: >\n  Review a diff for bugs. Use when asked to review\n"
        "  code. Not for writing new code.\n---\nbody\n",
    )
    assert check(tmp_path) == []


# --- FAIL rules -------------------------------------------------------------------------


def test_t1_a_skill_directory_without_skill_md_fails(tmp_path: Path) -> None:
    (tmp_path / "skills" / "empty").mkdir(parents=True)
    assert check(tmp_path) == ["FAIL empty T1"]


@pytest.mark.parametrize(
    "raw",
    [
        "no frontmatter at all\n",
        "---\nname: demo\ndescription: never closed\n",
        "---\nname: [unclosed\n---\nbody\n",
        "---\n- just\n- a list\n---\nbody\n",
        "---\nname: demo\ndescription: Use this skill when: the user asks about PDFs\n---\nbody\n",
    ],
    ids=["none", "unclosed", "bad-yaml", "not-a-mapping", "unquoted-colon"],
)
def test_t2_frontmatter_that_is_missing_or_does_not_parse_fails(tmp_path: Path, raw: str) -> None:
    write_skill(tmp_path, raw=raw)
    assert check(tmp_path) == ["FAIL demo T2"]


def test_t3_a_missing_name_fails(tmp_path: Path) -> None:
    write_skill(tmp_path, raw=f"---\ndescription: {GOOD_DESCRIPTION}\n---\nbody\n")
    assert check(tmp_path) == ["FAIL demo T3"]


def test_t4_a_name_over_64_characters_fails(tmp_path: Path) -> None:
    long = "a" * 65
    write_skill(tmp_path, long)
    assert "FAIL " + long + " T4" in check(tmp_path)


@pytest.mark.parametrize("bad", ["Demo", "-demo", "demo-", "de--mo", "de_mo", "de mo"])
def test_t5_a_name_outside_the_pattern_fails(tmp_path: Path, bad: str) -> None:
    write_skill(tmp_path, "demo", name_line=f"name: '{bad}'")
    assert "FAIL demo T5" in check(tmp_path)


def test_t5_a_name_that_is_not_a_string_fails(tmp_path: Path) -> None:
    write_skill(tmp_path, "123", name_line="name: 123")
    assert "FAIL 123 T5" in check(tmp_path)


def test_t6_a_name_that_differs_from_its_directory_fails(tmp_path: Path) -> None:
    write_skill(tmp_path, "other", directory="demo")
    assert check(tmp_path) == ["FAIL demo T6"]


@pytest.mark.parametrize("missing", [None, "''"], ids=["absent", "empty"])
def test_t7_a_missing_or_empty_description_fails(tmp_path: Path, missing: str | None) -> None:
    write_skill(tmp_path, description=missing)
    assert check(tmp_path) == ["FAIL demo T7"]


def test_t8_a_description_over_1024_characters_fails_and_exactly_1024_passes(
    tmp_path: Path,
) -> None:
    prefix = "Review a diff. Use when asked to review. Not for new code. "
    write_skill(tmp_path, description=prefix + "x" * (1024 - len(prefix)))
    assert check(tmp_path) == []
    write_skill(tmp_path, description=prefix + "x" * (1025 - len(prefix)))
    assert check(tmp_path) == ["FAIL demo T8"]


@pytest.mark.parametrize(
    ("extra", "rule"),
    [
        ("compatibility: ''", "T9"),
        (f"compatibility: {'c' * 501}", "T9"),
        ("compatibility: 12", "T9"),
        ("metadata: just text", "T10"),
        ("metadata:\n  count: 3", "T10"),
        ("allowed-tools:\n  - Read", "T11"),
    ],
)
def test_t9_to_t11_optional_fields_that_are_present_must_have_the_right_shape(
    tmp_path: Path, extra: str, rule: str
) -> None:
    write_skill(tmp_path, extra=extra)
    assert f"FAIL demo {rule}" in check(tmp_path)


def test_t9_to_t11_well_formed_optional_fields_pass(tmp_path: Path) -> None:
    write_skill(
        tmp_path,
        extra="license: MIT\ncompatibility: needs git\nmetadata:\n  team: core\n"
        "allowed-tools: Bash(git:*) Read",
    )
    assert check(tmp_path) == []


def test_t20_an_openai_yaml_that_does_not_parse_fails(tmp_path: Path) -> None:
    skill = write_skill(tmp_path)
    (skill / "agents").mkdir()
    (skill / "agents" / "openai.yaml").write_text("interface: [unclosed\n", encoding="utf-8")
    assert check(tmp_path) == ["FAIL demo T20"]


def test_t20_a_top_level_key_outside_interface_policy_dependencies_fails(tmp_path: Path) -> None:
    skill = write_skill(tmp_path)
    (skill / "agents").mkdir()
    (skill / "agents" / "openai.yaml").write_text("interface: {}\ncolour: red\n", encoding="utf-8")
    assert check(tmp_path) == ["FAIL demo T20"]
    assert "colour" in details(tmp_path, "T20")


def test_t20_t22_a_valid_openai_yaml_passes_and_a_non_boolean_policy_fails(tmp_path: Path) -> None:
    skill = write_skill(tmp_path)
    (skill / "agents").mkdir()
    path = skill / "agents" / "openai.yaml"
    path.write_text(
        "interface:\n  display_name: Demo\npolicy:\n  allow_implicit_invocation: false\n"
        "dependencies:\n  tools: []\n",
        encoding="utf-8",
    )
    assert check(tmp_path) == []
    path.write_text("policy:\n  allow_implicit_invocation: 'no'\n", encoding="utf-8")
    assert check(tmp_path) == ["FAIL demo T22"]
    path.write_text("policy: nope\n", encoding="utf-8")
    assert check(tmp_path) == ["FAIL demo T22"]


def test_t23_an_icon_path_that_does_not_exist_fails_and_one_that_does_passes(
    tmp_path: Path,
) -> None:
    skill = write_skill(tmp_path)
    (skill / "agents").mkdir()
    (skill / "assets").mkdir()
    (skill / "assets" / "small.svg").write_text("<svg/>", encoding="utf-8")
    path = skill / "agents" / "openai.yaml"
    path.write_text(
        "interface:\n  icon_small: ./assets/small.svg\n  icon_large: ./assets/large.png\n",
        encoding="utf-8",
    )
    assert check(tmp_path) == ["FAIL demo T23"]
    assert "icon_large" in details(tmp_path, "T23")


def test_t29_two_skills_with_the_same_name_fail(tmp_path: Path) -> None:
    write_skill(tmp_path, "alpha", name_line="name: shared")
    write_skill(tmp_path, "beta", name_line="name: shared")
    found = check(tmp_path)
    assert "FAIL alpha, beta T29" in found
    assert "FAIL alpha T6" in found  # the mismatch is reported too


# --- warnings -----------------------------------------------------------------------------


def test_t13_an_unknown_frontmatter_key_warns(tmp_path: Path) -> None:
    write_skill(tmp_path, extra="version: 2")
    assert check(tmp_path) == ["warn demo T13"]


def test_t14_a_body_of_500_lines_warns_and_499_does_not(tmp_path: Path) -> None:
    write_skill(tmp_path, body="line\n" * 499)
    assert check(tmp_path) == []
    write_skill(tmp_path, body="line\n" * 500)
    assert check(tmp_path) == ["warn demo T14"]


def test_t15_a_body_over_about_5000_tokens_warns(tmp_path: Path) -> None:
    write_skill(tmp_path, body=("word " * 3999 + "\n") + "x" * 100)
    assert check(tmp_path) == ["warn demo T15"]


def test_t16_a_broken_markdown_link_or_backticked_path_warns(tmp_path: Path) -> None:
    skill = write_skill(
        tmp_path,
        body="See [notes](references/notes.md) and `scripts/run.py --all` and `assets/x.md`.\n",
    )
    (skill / "references").mkdir()
    (skill / "references" / "notes.md").write_text("n\n", encoding="utf-8")
    assert check(tmp_path) == ["warn demo T16", "warn demo T16"]
    text = details(tmp_path, "T16")
    assert "scripts/run.py" in text and "assets/x.md" in text and "notes.md" not in text


def test_t16_follows_symlinks_and_catches_a_dangling_one(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "good.md").write_text("g\n", encoding="utf-8")
    skill = write_skill(tmp_path, body="Read `references/good.md` and `references/dangling.md`.\n")
    (skill / "references").mkdir()
    (skill / "references" / "good.md").symlink_to(shared / "good.md")
    (skill / "references" / "dangling.md").symlink_to(shared / "gone.md")
    assert check(tmp_path) == ["warn demo T16"]
    assert "dangling.md" in details(tmp_path, "T16")


def test_t16_ignores_urls_anchors_placeholders_globs_and_fenced_examples(tmp_path: Path) -> None:
    write_skill(
        tmp_path,
        body=(
            "[docs](https://example.com/a.md) [top](#top) [mail](mailto:a@b.c)\n"
            "`references/*.md` `references/<name>.md` `scripts/{a,b}.py`\n"
            "```\nSee `references/in-a-fence.md` and [x](assets/nope.md)\n```\n"
        ),
    )
    assert check(tmp_path) == []


def test_t16_strips_an_anchor_before_resolving(tmp_path: Path) -> None:
    skill = write_skill(tmp_path, body="See [part](references/long.md#part-two).\n")
    (skill / "references").mkdir()
    (skill / "references" / "long.md").write_text("x\n", encoding="utf-8")
    assert check(tmp_path) == []


def test_t18_a_script_that_skill_md_never_mentions_warns(tmp_path: Path) -> None:
    skill = write_skill(tmp_path, body="Run `scripts/used.py`.\n")
    (skill / "scripts").mkdir()
    (skill / "scripts" / "used.py").write_text("", encoding="utf-8")
    (skill / "scripts" / "hidden.py").write_text("", encoding="utf-8")
    (skill / "scripts" / ".dotfile").write_text("", encoding="utf-8")
    assert check(tmp_path) == ["warn demo T18"]
    assert "hidden.py" in details(tmp_path, "T18")


def test_t21_t24_an_unknown_interface_key_and_a_bad_brand_color_warn(tmp_path: Path) -> None:
    skill = write_skill(tmp_path)
    (skill / "agents").mkdir()
    (skill / "agents" / "openai.yaml").write_text(
        "interface:\n  display_name: Demo\n  logo: x.png\n  brand_color: red\n", encoding="utf-8"
    )
    assert check(tmp_path) == ["warn demo T21", "warn demo T24"]


def test_t24_a_six_digit_hex_brand_color_passes(tmp_path: Path) -> None:
    skill = write_skill(tmp_path)
    (skill / "agents").mkdir()
    (skill / "agents" / "openai.yaml").write_text(
        'interface:\n  brand_color: "#3B82F6"\n', encoding="utf-8"
    )
    assert check(tmp_path) == []


def test_t26_a_description_that_never_says_when_to_use_it_warns(tmp_path: Path) -> None:
    write_skill(tmp_path, description="Reviews diffs for bugs. Not for new code.")
    assert check(tmp_path) == ["warn demo T26"]


@pytest.mark.parametrize(
    "description",
    [
        "Reviews diffs. Use when asked to review. Not for new code.",
        "Reviews diffs. Use this skill when reviewing. Not for new code.",
        "Reviews diffs. Use for pull requests. Not for new code.",
        "Reviews diffs. Triggers on review requests. Not for new code.",
    ],
)
def test_t26_the_usual_trigger_phrases_pass(tmp_path: Path, description: str) -> None:
    write_skill(tmp_path, description=description)
    assert check(tmp_path) == []


def test_t27_a_first_sentence_over_150_characters_warns(tmp_path: Path) -> None:
    long_first = (
        "Review " + "a very long diff " * 10 + "for bugs. Use when asked. Not for new code."
    )
    write_skill(tmp_path, description=long_first)
    assert check(tmp_path) == ["warn demo T27"]


def test_t28_a_description_with_no_boundary_warns_unless_it_names_a_neighbouring_skill(
    tmp_path: Path,
) -> None:
    write_skill(tmp_path, "alpha", description="Review diffs for bugs. Use when asked to review.")
    write_skill(tmp_path, "beta", description="Fix bugs. Use when told to. Pairs with alpha.")
    assert check(tmp_path) == ["warn alpha T28"]


# --- the catalog budget (T30) --------------------------------------------------------------


def test_t30_the_pack_total_is_name_plus_description_plus_installed_path(tmp_path: Path) -> None:
    write_skill(tmp_path)
    home = tmp_path / "home"
    findings, lines, _ = cs.check_pack(tmp_path / "skills", home)
    path = home / "skills" / "demo" / "SKILL.md"
    expected = len("demo") + len(GOOD_DESCRIPTION) + len(str(path))
    assert findings == []
    assert lines == [f"catalog budget: this pack's 1 skills use {expected:,} of 8,000 characters "
                     "(name + description + path)"]  # fmt: skip


def test_t30_a_pack_over_8000_characters_warns_and_lists_the_heaviest_skills(
    tmp_path: Path,
) -> None:
    filler = "Review diffs for bugs. Use when asked. Not for new code. " + "x" * 900
    for i in range(10):
        write_skill(tmp_path, f"skill-{i}", description=filler)
    found = [f for f in cs.check_pack(tmp_path / "skills", tmp_path / "home")[0] if f.rule == "T30"]
    assert [f.level for f in found] == ["warn"]
    assert "skill-0" in found[0].detail


def test_t30_installed_skills_are_counted_system_ones_too_and_the_packs_own_links_once(
    tmp_path: Path,
) -> None:
    write_skill(tmp_path)
    home = tmp_path / "home"
    (home / "skills" / ".system" / "sys-skill").mkdir(parents=True)
    (home / "skills" / ".system" / "sys-skill" / "SKILL.md").write_text(
        "---\nname: sys-skill\ndescription: " + "s" * 4000 + "\n---\n", encoding="utf-8"
    )
    (home / "skills" / "foreign").mkdir()
    (home / "skills" / "foreign" / "SKILL.md").write_text(
        "---\nname: foreign\ndescription: " + "f" * 4000 + "\n---\n", encoding="utf-8"
    )
    (home / "skills" / "demo").symlink_to(tmp_path / "skills" / "demo")  # the pack's own install
    findings, lines, _ = cs.check_pack(tmp_path / "skills", home)
    assert "with the 2 other skills installed" in lines[1]
    over = [f for f in findings if f.rule == "T30"]
    assert [f.skill for f in over] == ["(installed)"]
    assert over[0].level == "warn"


def test_t30_without_a_codex_home_only_the_pack_line_is_printed(tmp_path: Path) -> None:
    write_skill(tmp_path)
    _, lines, _ = cs.check_pack(tmp_path / "skills", tmp_path / "missing")
    assert len(lines) == 1


# --- the command ---------------------------------------------------------------------------


def test_main_exits_1_on_a_failure_and_prints_the_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_skill(tmp_path, "other", directory="demo")
    code = cs.main(["--skills", str(tmp_path / "skills"), "--codex-home", str(tmp_path / "h")])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL demo T6" in out
    assert "checked 1 skill(s): 1 failure(s), 0 warning(s)" in out


def test_main_exits_0_when_only_warnings_are_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_skill(tmp_path, extra="version: 2")
    code = cs.main(["--skills", str(tmp_path / "skills"), "--codex-home", str(tmp_path / "h")])
    assert code == 0
    assert "warn demo T13" in capsys.readouterr().out


def test_main_without_a_skills_directory_fails(tmp_path: Path) -> None:
    assert cs.main(["--skills", str(tmp_path / "nope")]) == 1
