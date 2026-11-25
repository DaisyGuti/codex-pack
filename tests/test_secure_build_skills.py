"""Content rules for the secure-build skills: references that cite their sources, rules that are
documented, templates that stay pinned and keyless, and scripts that stay standard-library only.

The skill format itself (frontmatter, description, size, links) is checked by
scripts/check_skills.py and scripts/check_pack.py.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
SKILLS = ("ci-harden", "dockerfile-harden", "gcp-review", "gitlab-migration", "image-supply-chain")
GCP = SKILLS_DIR / "gcp-review"
MIGRATION = SKILLS_DIR / "gitlab-migration"


def _load(skill: str, filename: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SKILLS_DIR / skill / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rules = _load("gcp-review", "gcp_rules.py", "gcp_rules")
collect = _load("gcp-review", "gcp_collect.py", "gcp_collect_for_skill_rules")
wrapper = sys.modules["gcloud_readonly"]


def _markdown(skill: str) -> list[Path]:
    return sorted(p for p in (SKILLS_DIR / skill).rglob("*.md") if not p.is_symlink())


def _script_files() -> list[Path]:
    return sorted(
        p
        for skill in SKILLS
        for p in (SKILLS_DIR / skill / "scripts").iterdir()
        if p.is_symlink() and p.suffix in {".py", ".sh"}
    )


# --- scripts ------------------------------------------------------------------


def test_every_script_is_linked_into_its_skill_and_runnable() -> None:
    scripts = _script_files()
    assert {s.name for s in scripts} >= {
        "ci_audit.py",
        "dockerfile_check.py",
        "gcloud_readonly.py",
        "gcp_analyze.py",
        "gcp_collect.py",
        "gcp_rules.py",
        "inventory_github_repo.py",
        "render_cutover_checklist.py",
        "image_evidence.sh",
        "summarize_evidence.py",
        "verify_image.sh",
    }
    for link in scripts:
        target = link.resolve()
        assert target.parent == ROOT / "scripts", f"{link} must point into scripts/"
        assert os.access(target, os.X_OK), f"{target.name} must be executable"
        assert target.read_text(encoding="utf-8").startswith("#!"), target.name


def test_python_scripts_use_only_the_standard_library() -> None:
    stdlib = set(sys.stdlib_module_names)
    for link in _script_files():
        if link.suffix != ".py":
            continue
        tree = ast.parse(link.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module.split(".")[0])
        own = {p.stem for p in (ROOT / "scripts").glob("*.py")}
        assert modules <= stdlib | own, (link.name, modules - stdlib - own)


@pytest.mark.parametrize("skill", SKILLS)
def test_every_file_a_skill_names_exists(skill: str) -> None:
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    named = set(re.findall(r"(?<![\w/-])(?:references|templates|scripts)/[\w./-]+\w", text))
    assert named, f"{skill} names no bundled files"
    for name in named:
        assert (SKILLS_DIR / skill / name).exists(), f"{skill}: {name} is named but missing"


# --- house rules for the prose --------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_no_claim_of_compliance_and_no_secret_shaped_value(skill: str) -> None:
    secret = re.compile(
        r"(ghp_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
        r"|-----BEGIN [A-Z ]*PRIVATE)"
    )
    for path in _markdown(skill):
        text = path.read_text(encoding="utf-8")
        assert not secret.search(text), path.name
        lowered = text.lower()
        for phrase in ("is fedramp compliant", "is fedramp ready", "will be authorized"):
            assert phrase not in lowered, (path.name, phrase)


# --- gcp-review -----------------------------------------------------------------


def _gcp_references() -> list[Path]:
    return sorted((GCP / "references").glob("*.md"))


@pytest.mark.parametrize("path", _gcp_references(), ids=lambda p: p.name)
def test_gcp_references_cite_sources_and_a_fetch_date(path: Path) -> None:
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:25])
    assert "https://" in head and re.search(r"fetched 20\d\d-\d\d-\d\d", head), path.name


@pytest.mark.parametrize("path", _gcp_references(), ids=lambda p: p.name)
def test_long_gcp_references_have_a_table_of_contents(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > 100:
        assert any(line.startswith("## Contents") for line in lines[:40]), path.name


def test_every_gcp_rule_is_documented() -> None:
    text = (GCP / "references/checks.md").read_text(encoding="utf-8")
    for rule in rules.RULES:
        if re.fullmatch(r"GCP-ORG-\d+", rule):
            continue  # documented as a range plus the constraint table
        assert rule in text, rule


def test_every_org_policy_check_and_constraint_name_is_documented() -> None:
    text = (GCP / "references/checks.md").read_text(encoding="utf-8")
    for check, names in collect.ORG_POLICY_CONSTRAINTS.items():
        assert f"| {check} |" in text, check
        for name in names:
            assert f"`{name}`" in text, name
    for rule, _constraint in rules.ORG_CHECKS.values():
        assert rule in text, rule


def test_the_gcloud_commands_the_skill_relies_on_are_allowlisted() -> None:
    for call_args in (
        "projects get-iam-policy",
        "org-policies describe",
        "assured workloads list",
        "container binauthz policy export",
        "artifacts repositories get-iam-policy",
    ):
        assert tuple(call_args.split()) in wrapper.ALLOWED_COMMANDS, call_args


def test_a_verified_benchmark_edition_is_recorded_with_its_source() -> None:
    text = (GCP / "references/checks.md").read_text(encoding="utf-8")
    flat = " ".join(text.split()).lower()
    assert "5.0.0" in text and "Prowler" in text and "confirm each id" in flat


def test_the_default_benchmark_map_is_found_through_the_skill_folder() -> None:
    analyze = _load("gcp-review", "gcp_analyze.py", "gcp_analyze_for_skill_rules")
    assert analyze.DEFAULT_BENCHMARK_MAP == GCP / "references" / "cis-gcp-map.json"
    assert analyze.DEFAULT_BENCHMARK_MAP.is_file()


# --- gitlab-migration -----------------------------------------------------------


def test_the_migration_skill_has_plan_and_execute_modes_with_a_second_confirmation() -> None:
    body = (MIGRATION / "SKILL.md").read_text(encoding="utf-8")
    assert "## PLAN mode" in body and "## EXECUTE mode" in body
    assert "Second confirmation" in body


def test_the_migration_skill_links_every_reference() -> None:
    body = (MIGRATION / "SKILL.md").read_text(encoding="utf-8")
    on_disk = {p.name for p in (MIGRATION / "references").glob("*.md")}
    assert set(re.findall(r"references/([\w-]+\.md)", body)) == on_disk


def test_migration_references_cite_a_fetch_date_and_a_source() -> None:
    for path in sorted((MIGRATION / "references").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if len(text.splitlines()) > 100:
            assert "## Contents" in text, f"{path.name} needs a table of contents"
        if path.name == "execute-commands.md":
            continue  # drafted commands, not a record of fetched facts
        assert re.search(r"\b\d{4}-\d{2}-\d{2}\b", text), path.name
        assert "https://" in text, path.name


def test_the_migration_sources_file_separates_verified_from_unverified() -> None:
    text = (MIGRATION / "references/sources.md").read_text(encoding="utf-8")
    assert "## Verified against the pages" in text and "## Not verified" in text


def test_the_renovate_template_lives_in_ci_harden_only() -> None:
    shared = SKILLS_DIR / "ci-harden/templates/renovate.json"
    assert json.loads(shared.read_text(encoding="utf-8"))["extends"] == ["config:best-practices"]
    assert not (MIGRATION / "templates/renovate.json").exists()


# --- ci-harden and dockerfile-harden templates ----------------------------------


def test_pinned_digests_and_shas_in_templates_are_well_formed() -> None:
    for path in SKILLS_DIR.glob("*/templates/**/*"):
        if not path.is_file() or path.name in {"CODEOWNERS", "dockerignore"}:
            continue
        text = path.read_text(encoding="utf-8")
        for digest in re.findall(r"sha256:([0-9a-f]+)", text):
            assert len(digest) == 64, f"{path.name}: malformed digest sha256:{digest}"
        for sha in re.findall(r"uses:\s*\S+@([0-9a-f]{7,})\b", text):
            assert len(sha) == 40, f"{path.name}: action pinned to a short SHA {sha}"


def test_the_github_template_pins_every_action_and_grants_nothing_by_default() -> None:
    path = SKILLS_DIR / "ci-harden/templates/.github/workflows/secure-build.yml"
    text = path.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*(?:-\s+)?uses:\s*(\S+)", text, re.M)
    assert uses
    assert all(re.search(r"@[0-9a-f]{40}$", u) for u in uses)
    assert re.search(r"^permissions:\s*\{\}\s*$", text, re.M)
    assert "pull_request_target" not in text
    assert "credentials_json" not in text


def test_the_gitlab_template_uses_oidc_and_no_stored_key() -> None:
    text = (SKILLS_DIR / "ci-harden/templates/.gitlab-ci.yml").read_text(encoding="utf-8")
    assert "id_tokens:" in text
    assert "SIGSTORE_ID_TOKEN" in text
    assert not re.search(r"GCP_SA_KEY|GOOGLE_APPLICATION_CREDENTIALS|--key-file", text)
    assert "dind" not in text.replace("Docker-in-Docker", "")
