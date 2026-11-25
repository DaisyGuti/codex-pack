"""Tests for security_scan.py on fixture outputs and stub scanners.

The files in fixtures/raw are real tool outputs from small synthetic projects (a fake API key,
requests 2.19.0, a Dockerfile and a Terraform bucket), trimmed and with paths replaced.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/security_scan.py"
RAW = Path(__file__).parent / "fixtures" / "security" / "raw"
FAKE_REPO = Path("/work/repo")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("security_scan", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["security_scan"] = module
    spec.loader.exec_module(module)
    return module


ss = _load()


# --- severity ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        ("9.8", "critical"),
        ("9.0", "critical"),
        ("7.5", "high"),
        ("6.1", "medium"),
        ("3.9", "low"),
        ("0", "info"),
        ("", "unknown"),
        (None, "unknown"),
        ("n/a", "unknown"),
    ],
)
def test_cvss_bands(score: str | None, expected: str) -> None:
    assert ss.severity_from_cvss(score) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("CRITICAL", "critical"),
        ("High", "high"),
        ("ERROR", "high"),
        ("WARNING", "medium"),
        ("MODERATE", "medium"),
        ("Negligible", "info"),
        ("weird", "unknown"),
        (None, "unknown"),
    ],
)
def test_label_mapping(label: str | None, expected: str) -> None:
    assert ss.severity_from_label(label) == expected


# --- normalizers -------------------------------------------------------------


def test_gitleaks_reports_location_and_never_the_secret(tmp_path: Path) -> None:
    raw = tmp_path / "gitleaks-dir.json"
    raw.write_text(
        json.dumps(
            [
                {
                    "RuleID": "generic-api-key",
                    "Description": "Detected a Generic API Key",
                    "StartLine": 7,
                    "File": "/work/repo/app/config.py",
                    "Secret": "FAKE-SECRET-VALUE-0000",
                    "Match": "api_key = 'FAKE-SECRET-VALUE-0000'",
                    "Commit": "abcdef1234567890",
                }
            ]
        )
    )
    (finding,) = ss.parse_gitleaks(raw, FAKE_REPO)
    assert (finding.kind, finding.severity) == ("secret", "high")
    assert (finding.file, finding.line, finding.rule) == ("app/config.py", 7, "generic-api-key")
    assert "abcdef123456" in finding.note
    assert "FAKE-SECRET-VALUE-0000" not in json.dumps(finding.as_dict())


def test_gitleaks_real_output_fixture() -> None:
    (finding,) = ss.parse_gitleaks(RAW / "gitleaks-dir.json", FAKE_REPO)
    assert finding.file == "app/config.py"
    assert finding.line == 1


def test_osv_groups_become_findings_with_fix_versions() -> None:
    findings = ss.parse_osv(RAW / "osv-scanner.json", FAKE_REPO)
    by_cve = {next(i for i in f.ids if i.startswith("CVE-")): f for f in findings}
    assert set(by_cve) == {"CVE-2018-18074", "CVE-2023-32681"}
    high = by_cve["CVE-2018-18074"]
    assert high.severity == "high"
    assert by_cve["CVE-2023-32681"].severity == "medium"
    assert high.file == "requirements.txt"
    assert (high.package, high.version) == ("requests", "2.19.0")
    assert "2.20.0" in high.fix
    assert {"PYSEC-2018-28", "GHSA-x84v-xcm2-53pg"} <= set(high.ids)


def test_osv_falls_back_to_database_severity_label(tmp_path: Path) -> None:
    raw = tmp_path / "osv-scanner.json"
    raw.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "source": {"path": "go.mod"},
                        "packages": [
                            {
                                "package": {"name": "m", "version": "1"},
                                "groups": [{"ids": ["GHSA-aaaa"], "aliases": []}],
                                "vulnerabilities": [
                                    {
                                        "id": "GHSA-aaaa",
                                        "database_specific": {"severity": "CRITICAL"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )
    )
    (finding,) = ss.parse_osv(raw, FAKE_REPO)
    assert finding.severity == "critical"
    assert finding.fix == ""


def test_grype_paths_are_scan_root_relative_and_cves_are_collected() -> None:
    findings = ss.parse_grype(RAW / "grype.json", FAKE_REPO)
    first = findings[0]
    assert first.file == "requirements.txt"
    assert "CVE-2018-18074" in first.ids
    assert first.title.endswith("CVE-2018-18074")
    assert first.fix == "Upgrade requests to 2.20.0."


def test_semgrep_maps_severity_and_cwe_and_drops_source_lines(tmp_path: Path) -> None:
    (finding,) = ss.parse_semgrep(RAW / "semgrep.json", FAKE_REPO)
    assert (finding.kind, finding.severity) == ("code", "high")
    assert (finding.file, finding.line, finding.rule) == ("app.py", 3, "demo-shell-true")
    assert finding.ids == ["CWE-78"]
    raw = tmp_path / "semgrep.json"
    raw.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "check_id": "r",
                        "path": "a.py",
                        "start": {"line": 1},
                        "extra": {
                            "message": "m",
                            "severity": "INFO",
                            "lines": "token=FAKE-LINE-0001",
                        },
                    }
                ]
            }
        )
    )
    (info,) = ss.parse_semgrep(raw, FAKE_REPO)
    assert info.severity == "low"
    assert "FAKE-LINE-0001" not in json.dumps(info.as_dict())


def test_trivy_reports_dependencies_and_failed_misconfigurations_only(tmp_path: Path) -> None:
    findings = ss.parse_trivy(RAW / "trivy.json", FAKE_REPO)
    kinds = {f.kind for f in findings}
    assert kinds == {"dependency", "iac"}
    dep = next(f for f in findings if f.kind == "dependency")
    assert dep.package == "requests" and "2.20.0" in dep.fix
    iac = next(f for f in findings if f.rule == "AWS-0086")
    assert (iac.file, iac.line, iac.severity) == ("main.tf", 1, "high")
    raw = tmp_path / "trivy.json"
    raw.write_text(
        json.dumps(
            {"Results": [{"Target": "x", "Misconfigurations": [{"ID": "X", "Status": "PASS"}]}]}
        )
    )
    assert ss.parse_trivy(raw, FAKE_REPO) == []


def test_checkov_list_output_assumes_severity_and_strips_root_slash() -> None:
    findings = ss.parse_checkov(RAW / "checkov.json", FAKE_REPO)
    assert findings
    assert {f.kind for f in findings} == {"iac"}
    assert all(f.severity == "medium" and "assumed" in f.note for f in findings)
    assert {f.file for f in findings} <= {"main.tf", "Dockerfile"}
    assert next(f for f in findings if f.file == "main.tf").line == 1


def test_checkov_accepts_a_single_object_and_a_real_severity(tmp_path: Path) -> None:
    raw = tmp_path / "checkov.json"
    raw.write_text(
        json.dumps(
            {
                "check_type": "terraform",
                "results": {
                    "failed_checks": [
                        {
                            "check_id": "CKV_X",
                            "check_name": "n",
                            "file_path": "/a.tf",
                            "file_line_range": [3, 9],
                            "severity": "HIGH",
                        }
                    ]
                },
            }
        )
    )
    (finding,) = ss.parse_checkov(raw, FAKE_REPO)
    assert (finding.severity, finding.line, finding.note) == ("high", 3, "")


def test_unreadable_json_raises_a_clear_error(tmp_path: Path) -> None:
    raw = tmp_path / "semgrep.json"
    raw.write_text("not json")
    with pytest.raises(ValueError, match="semgrep.json"):
        ss.parse_semgrep(raw, FAKE_REPO)


# --- de-duplication ----------------------------------------------------------


def _all_fixture_findings() -> list[Any]:
    findings: list[Any] = (
        ss.parse_gitleaks(RAW / "gitleaks-dir.json", FAKE_REPO)
        + ss.parse_osv(RAW / "osv-scanner.json", FAKE_REPO)
        + ss.parse_grype(RAW / "grype.json", FAKE_REPO)
        + ss.parse_semgrep(RAW / "semgrep.json", FAKE_REPO)
        + ss.parse_trivy(RAW / "trivy.json", FAKE_REPO)
        + ss.parse_checkov(RAW / "checkov.json", FAKE_REPO)
    )
    return findings


def test_three_dependency_scanners_collapse_to_one_finding() -> None:
    merged = ss.dedupe(_all_fixture_findings())
    hits = [f for f in merged if "CVE-2018-18074" in f.ids and f.package == "requests"]
    assert len(hits) == 1
    assert hits[0].tools == ["grype", "osv-scanner", "trivy"]
    assert hits[0].fix.startswith("Upgrade requests")
    assert merged[0].severity == "high"


def test_dedupe_keeps_different_versions_apart_and_numbers_by_severity() -> None:
    a = ss.Finding("dependency", "low", "t", package="p", version="1", ids=["CVE-1"], tools=["a"])
    b = ss.Finding("dependency", "high", "t", package="p", version="2", ids=["CVE-1"], tools=["b"])
    merged = ss.dedupe([a, b])
    assert [f.version for f in merged] == ["2", "1"]
    assert [f.finding_id for f in merged] == ["SS-001", "SS-002"]


def test_dedupe_merges_the_same_secret_seen_by_two_gitleaks_passes() -> None:
    a = ss.Finding("secret", "high", "k", file="a.py", line=1, tools=["gitleaks"])
    b = ss.Finding("secret", "high", "k", file="a.py", line=1, tools=["gitleaks"], note="commit 1")
    (only,) = ss.dedupe([a, b])
    assert only.note == "commit 1"


def test_dedupe_takes_the_worse_severity_when_tools_disagree() -> None:
    a = ss.Finding(
        "dependency", "medium", "t", package="p", version="1", ids=["CVE-9"], tools=["a"]
    )
    b = ss.Finding(
        "dependency", "critical", "t", package="P", version="1", ids=["CVE-9"], tools=["b"]
    )
    (only,) = ss.dedupe([a, b])
    assert only.severity == "critical"


# --- merge command -----------------------------------------------------------


def test_merge_writes_report_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    code = ss.main(["merge", "--raw", str(RAW), "--repo", str(FAKE_REPO), "--out", str(out)])
    assert code == 0
    report = (out / "SECURITY-SCAN.md").read_text()
    assert "## Coverage" in report and "SS-001" in report
    assert "app/config.py:1" in report
    data = json.loads((out / "findings.json").read_text())
    assert {t["name"]: t["status"] for t in data["tools"]}["gitleaks"] == "ran"
    assert data["findings"][0]["severity"] in {"high", "critical"}
    assert "FAKE" not in report


def test_merge_marks_tools_without_raw_output_as_not_run(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(RAW / "semgrep.json", raw / "semgrep.json")
    out = tmp_path / "out"
    assert ss.main(["merge", "--raw", str(raw), "--repo", str(FAKE_REPO), "--out", str(out)]) == 0
    status = {
        t["name"]: t["status"] for t in json.loads((out / "findings.json").read_text())["tools"]
    }
    assert status["semgrep"] == "ran"
    assert status["osv-scanner"] == "not run"


def test_merge_with_a_corrupt_file_marks_that_tool_failed_and_keeps_the_rest(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(RAW / "semgrep.json", raw / "semgrep.json")
    (raw / "trivy.json").write_text("{broken")
    out = tmp_path / "out"
    assert ss.main(["merge", "--raw", str(raw), "--repo", str(FAKE_REPO), "--out", str(out)]) == 0
    tools = {t["name"]: t for t in json.loads((out / "findings.json").read_text())["tools"]}
    assert tools["trivy"]["status"] == "failed"
    assert "trivy.json" in tools["trivy"]["detail"]
    assert tools["semgrep"]["count"] == 1


def test_fail_on_sets_exit_code_one_only_at_or_above_the_threshold(tmp_path: Path) -> None:
    args = ["merge", "--raw", str(RAW), "--repo", str(FAKE_REPO)]
    assert ss.main([*args, "--out", str(tmp_path / "a"), "--fail-on", "high"]) == 1
    assert ss.main([*args, "--out", str(tmp_path / "b"), "--fail-on", "critical"]) == 0


def test_merge_without_a_raw_directory_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = ss.main(["merge", "--raw", str(tmp_path / "missing"), "--repo", str(tmp_path)])
    assert code == 2
    assert "not a directory" in capsys.readouterr().err


def test_unknown_tool_name_is_rejected_with_the_valid_choices(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        ss.main(["run", "--repo", str(tmp_path), "--tools", "nessus"])
    assert "unknown tool" in str(exc.value) and "gitleaks" in str(exc.value)


# --- run command with stub scanners -------------------------------------------


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _stub_bin_dir(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # gitleaks: copy the fixture to the --report-path argument.
    _stub(
        bin_dir,
        "gitleaks",
        f'''[ "$1" = "version" ] && {{ echo "8.0-stub"; exit 0; }}
while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && dest="$2"; shift; done
/bin/cp "{RAW}/gitleaks-dir.json" "$dest"
''',
    )
    # semgrep: print the fixture to stdout.
    _stub(
        bin_dir,
        "semgrep",
        f'''[ "$1" = "--version" ] && {{ echo "1.0-stub"; exit 0; }}
/bin/cat "{RAW}/semgrep.json"
''',
    )
    # grype: crash.
    _stub(
        bin_dir, "grype", '[ "$1" = "version" ] && { echo stub; exit 0; }\necho boom >&2\nexit 3\n'
    )
    return bin_dir


def test_run_uses_installed_tools_and_reports_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(scratch))
    monkeypatch.setenv("PATH", str(_stub_bin_dir(tmp_path)))
    assert ss.main(["run", "--repo", str(repo), "--tools", "gitleaks,semgrep,grype,trivy"]) == 0
    captured = capsys.readouterr()
    assert "trivy: not installed" in captured.err
    assert "grype: failed" in captured.err and "boom" in captured.err
    (scan_dir,) = list(scratch.iterdir())  # the report lands outside the repository
    assert scan_dir.name.startswith("security-scan-repo-")
    assert list(repo.iterdir()) == []
    data = json.loads((scan_dir / "findings.json").read_text())
    status = {t["name"]: t["status"] for t in data["tools"]}
    assert status == {
        "gitleaks": "ran",
        "semgrep": "ran",
        "grype": "failed",
        "trivy": "not installed",
    }
    assert {f["kind"] for f in data["findings"]} == {"secret", "code"}
    assert "2 high" in captured.out  # the fake key and the shell=True finding


def test_an_out_directory_inside_the_repository_is_warned_about(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("PATH", str(_stub_bin_dir(tmp_path)))
    ss.main(["run", "--repo", str(repo), "--tools", "semgrep", "--out", str(repo / "reports")])
    assert "inside the repository" in capsys.readouterr().err


def test_a_failed_history_pass_keeps_the_working_tree_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "gitleaks",
        f"""[ "$1" = "version" ] && {{ echo "8.0-stub"; exit 0; }}
[ "$1" = "git" ] && {{ echo "fatal: no commits" >&2; exit 1; }}
while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && dest="$2"; shift; done
/bin/cp "{RAW}/gitleaks-dir.json" "$dest"
""",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    out = tmp_path / "out"
    assert ss.main(["run", "--repo", str(repo), "--tools", "gitleaks", "--out", str(out)]) == 0
    tool = json.loads((out / "findings.json").read_text())["tools"][0]
    assert tool["status"] == "ran" and tool["count"] == 1
    assert "gitleaks-git.json pass lost" in tool["detail"] and "no commits" in tool["detail"]
    assert "pass lost" in (out / "SECURITY-SCAN.md").read_text()


def test_a_long_report_details_the_top_findings_and_tables_the_rest(tmp_path: Path) -> None:
    findings = [
        ss.Finding("code", "low", f"issue {i}", file=f"f{i}.py", line=1, rule=f"r{i}")
        for i in range(ss.MAX_DETAILED_FINDINGS + 5)
    ]
    merged = ss.dedupe(findings)
    text = ss.render_markdown(Path("/work/repo"), [], merged, "now")
    assert text.count("### SS-") == ss.MAX_DETAILED_FINDINGS
    assert "Remaining 5 finding(s)" in text and "| SS-205 |" in text


def test_run_with_no_tools_installed_exits_two_with_install_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    code = ss.main(["run", "--repo", str(tmp_path), "--out", str(tmp_path / "out")])
    assert code == 2
    err = capsys.readouterr().err
    assert "brew install gitleaks" in err
    assert "no scanner produced a result" in err


def test_run_times_out_a_hung_tool_and_keeps_going(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "semgrep", '[ "$1" = "--version" ] && { echo v; exit 0; }\n/bin/sleep 30\n')
    _stub(
        bin_dir,
        "checkov",
        '[ "$1" = "--version" ] && { echo v; exit 0; }\necho "[]"\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/bin")
    repo = tmp_path / "repo"
    repo.mkdir()
    code = ss.main(
        [
            "run",
            "--repo",
            str(repo),
            "--out",
            str(tmp_path / "o"),
            "--tools",
            "semgrep,checkov",
            "--timeout",
            "1",
        ]
    )
    assert code == 0
    assert "timed out after 1 seconds" in capsys.readouterr().err


def test_detect_lists_every_tool_with_install_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert ss.main(["detect", "--json"]) == 0
    tools = json.loads(capsys.readouterr().out)
    assert {t["name"] for t in tools} == set(ss.TOOLS)
    assert all(t["status"] == "not installed" and t["detail"] for t in tools)


def test_semgrep_never_sends_metrics_and_accepts_a_local_rule_directory(tmp_path: Path) -> None:
    (_, argv, _) = ss.TOOLS["semgrep"].commands(tmp_path, tmp_path, "rules/")[0]
    assert argv[argv.index("--metrics") + 1] == "off"
    assert argv[argv.index("--config") + 1] == "rules/"
    (_, default_argv, _) = ss.TOOLS["semgrep"].commands(tmp_path, tmp_path, "")[0]
    assert default_argv[default_argv.index("--config") + 1] == ss.DEFAULT_SEMGREP_CONFIG


def test_a_secret_sorts_before_a_dependency_of_the_same_severity() -> None:
    dep = ss.Finding("dependency", "high", "d", file="a", package="p", version="1", ids=["CVE-1"])
    secret = ss.Finding("secret", "high", "s", file="z.py", line=1)
    assert [f.kind for f in ss.dedupe([dep, secret])] == ["secret", "dependency"]


def test_version_is_the_first_dotted_number_in_the_tool_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "grype", 'echo "Application:  grype"\necho "Version:  0.120.1"\n')
    monkeypatch.setenv("PATH", str(bin_dir))
    assert ss.tool_version(ss.TOOLS["grype"]) == "0.120.1"


# --- --changed-since ---------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


@pytest.fixture
def branch_repo(tmp_path: Path) -> tuple[Path, Path]:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("x = 1\n")
    (repo / "b.py").write_text("y = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "a.py").write_text("x = 2\n")
    _git(repo, "commit", "-qam", "change a")
    (repo / "c.py").write_text("z = 1\n")  # untracked
    raw = tmp_path / "raw"
    raw.mkdir()
    results = [
        {
            "check_id": "r",
            "path": name,
            "start": {"line": 1},
            "extra": {"message": "m", "severity": "ERROR"},
        }
        for name in ("a.py", "b.py", "c.py")
    ]
    (raw / "semgrep.json").write_text(json.dumps({"results": results}))
    return repo, raw


def test_changed_since_keeps_committed_and_untracked_changes_only(
    branch_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, raw = branch_repo
    out = tmp_path / "out"
    code = ss.main(
        [
            "merge",
            "--raw",
            str(raw),
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--changed-since",
            "main",
        ]
    )
    assert code == 0
    data = json.loads((out / "findings.json").read_text())
    assert [f["file"] for f in data["findings"]] == ["a.py", "c.py"]
    assert [f["id"] for f in data["findings"]] == ["SS-001", "SS-002"]
    assert "1 finding(s) elsewhere" in data["filter"]
    assert "- Filter:" in (out / "SECURITY-SCAN.md").read_text()


def test_changed_since_with_an_unknown_ref_refuses_instead_of_showing_everything(
    branch_repo: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, raw = branch_repo
    code = ss.main(
        [
            "merge",
            "--raw",
            str(raw),
            "--repo",
            str(repo),
            "--out",
            str(tmp_path / "o"),
            "--changed-since",
            "no-such-ref",
        ]
    )
    assert code == 2
    assert "--changed-since no-such-ref" in capsys.readouterr().err
    assert not (tmp_path / "o" / "findings.json").exists()


# --- suppression files ---------------------------------------------------------


def test_suppression_files_are_listed_so_a_reviewer_reads_them(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "svc").mkdir(parents=True)
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / ".gitleaksignore").write_text("a:b:1\n")
    (repo / "svc" / ".semgrepignore").write_text("tests/\n")
    (repo / "node_modules" / "x" / ".trivyignore").write_text("CVE-1\n")
    assert ss.find_suppression_files(repo) == [".gitleaksignore", "svc/.semgrepignore"]
    out = tmp_path / "out"
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(RAW / "semgrep.json", raw / "semgrep.json")
    assert ss.main(["merge", "--raw", str(raw), "--repo", str(repo), "--out", str(out)]) == 0
    assert "- `svc/.semgrepignore`" in (out / "SECURITY-SCAN.md").read_text()
    data = json.loads((out / "findings.json").read_text())
    assert data["suppression_files"] == [".gitleaksignore", "svc/.semgrepignore"]


# --- scanner config in the repository cannot run code ---------------------------


def _recording_stub(bin_dir: Path, name: str, log: Path, version_arg: str) -> None:
    _stub(
        bin_dir,
        name,
        f'''[ "$1" = "{version_arg}" ] && {{ echo "1.0-stub"; exit 0; }}
{{ echo "$PWD"; for a in "$@"; do echo "$a"; done; }} > "{log}"
echo '{{}}'
''',
    )


@pytest.mark.parametrize(
    ("tool", "version_arg", "config_flag"),
    [
        ("checkov", "--version", "--config-file"),
        ("trivy", "--version", "--config"),
        ("grype", "version", "-c"),
    ],
)
def test_scanners_run_from_an_empty_directory_with_an_empty_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    version_arg: str,
    config_flag: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".checkov.yaml").write_text("external-checks-dir: [evil]\n")
    (repo / "trivy.yaml").write_text("scan: {}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "argv.log"
    _recording_stub(bin_dir, tool, log, version_arg)
    monkeypatch.setenv("PATH", str(bin_dir))
    raw = tmp_path / "raw"
    raw.mkdir()
    status = ss.run_tool(ss.TOOLS[tool], repo, raw, "", 30)
    assert status.status == "ran", status.detail
    cwd, *argv = log.read_text().splitlines()
    assert Path(cwd).resolve() != repo.resolve() and not Path(cwd).resolve().is_relative_to(repo)
    assert str(repo) in " ".join(argv)  # the scan root is an argument
    config = Path(argv[argv.index(config_flag) + 1])
    assert config.read_text().strip() == "{}"
    if tool == "checkov":  # built-in checks only: external checks come from an empty folder
        checks = Path(argv[argv.index("--external-checks-dir") + 1])
        assert checks.is_dir() and list(checks.iterdir()) == [] and not checks.is_relative_to(repo)
    else:
        assert not any(a.startswith("--external-checks") for a in argv)
    assert not config.is_relative_to(repo)


# --- the default report directory -------------------------------------------------


def test_default_report_directory_is_random_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(tmp_path))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    first, second = ss._default_out(repo), ss._default_out(repo)
    assert first != second
    for out in (first, second):
        assert out.name.startswith("security-scan-myrepo-") and out.parent == tmp_path
        assert out.stat().st_mode & 0o777 == 0o700


def test_an_existing_out_directory_is_reused_and_no_default_one_is_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("x")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    ss.main(["run", "--repo", str(repo), "--out", str(out), "--tools", "gitleaks"])
    assert (out / "keep.txt").exists() and (out / "SECURITY-SCAN.md").exists()
    assert list((tmp_path / "tmp").iterdir()) == []


# --- the changed-file filter ---------------------------------------------------


def _changes(repo: Path, tmp_path: Path, ref: str = "main") -> Any:
    scratch = Path(tempfile.mkdtemp(dir=tmp_path))
    return ss.changed_files(repo, ss.make_mirror(repo, scratch), ref)


def test_changed_files_keeps_names_git_would_quote_and_names_with_newlines(
    branch_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = branch_repo
    (repo / "ünï.py").write_text("a = 1\n")
    (repo / "two\nlines.py").write_text("b = 1\n")
    (repo / 'quo"te.py').write_text("c = 1\n")
    changes = _changes(repo, tmp_path)
    assert {"a.py", "c.py", "ünï.py", "two\nlines.py", 'quo"te.py'} <= changes.files


def test_changed_files_are_relative_to_a_scan_root_below_the_git_root(
    branch_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = branch_repo
    (repo / "svc").mkdir()
    (repo / "svc" / "x.py").write_text("x = 1\n")
    _git(repo, "add", "svc/x.py")
    (repo / "svc" / "y.py").write_text("y = 1\n")  # untracked
    assert _changes(repo / "svc", tmp_path).files == {"x.py", "y.py"}


def test_a_file_changed_in_a_branch_commit_and_reverted_still_counts(
    branch_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = branch_repo
    (repo / "b.py").write_text("y = 2\n")
    _git(repo, "commit", "-qam", "change b")
    (repo / "b.py").write_text("y = 1\n")  # back to the base content: no net diff
    _git(repo, "commit", "-qam", "revert b")
    changes = _changes(repo, tmp_path)
    assert "b.py" in changes.files
    assert len(changes.commits) == 3


def test_working_tree_changes_are_found_by_content_and_ignored_names_are_left_out(
    branch_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = branch_repo
    _git(repo, "add", "c.py")
    _git(repo, "commit", "-qm", "add c")
    (repo / ".gitignore").write_text("*.log\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore logs")
    (repo / "b.py").write_text("y = 99\n")  # edited, same name
    (repo / "debug.log").write_text("noise\n")  # ignored
    (repo / "a.py").unlink()  # deleted
    files = _changes(repo, tmp_path).files
    assert {"b.py", "a.py"} <= files
    assert "debug.log" not in files and ".gitignore" in files  # .gitignore is a branch change


def test_a_finding_whose_path_cannot_be_matched_is_kept() -> None:
    changes = ss.Changes({"a.py"}, set())

    def keep(file: str, commits: list[str] | None = None) -> bool:
        finding = ss.Finding(kind="code", severity="low", title="t", file=file)
        finding.commits = commits or []
        return bool(ss.in_changed_set(finding, changes))

    assert keep("a.py") and keep("./a.py")
    assert not keep("b.py")
    for unplaceable in ("", "/etc/passwd", "../outside.py"):
        assert keep(unplaceable)


def test_a_history_secret_is_kept_when_its_commit_is_new_even_if_its_file_is_not_changed(
    branch_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = branch_repo
    (repo / "b.py").write_text("y = 2\n")
    _git(repo, "commit", "-qam", "add a secret to b")
    new_commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "b.py").write_text("y = 1\n")  # the working tree no longer holds it
    _git(repo, "commit", "-qam", "remove it")
    old_commit = "0" * 40
    changes = _changes(repo, tmp_path)
    assert new_commit in changes.commits and old_commit not in changes.commits

    def finding(commit: str, file: str) -> Any:
        found = ss.Finding(kind="secret", severity="high", title="s", file=file, line=1)
        found.commits = [commit]
        return found

    assert ss.in_changed_set(finding(new_commit, "gone.py"), changes)
    assert not ss.in_changed_set(finding(old_commit, "gone.py"), changes)


# --- semgrep messages and fixes can quote a credential ----------------------------


def _semgrep_raw(tmp_path: Path, check_id: str, meta: dict[str, Any]) -> Path:
    raw = tmp_path / "semgrep.json"
    raw.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "check_id": check_id,
                        "path": "a.py",
                        "start": {"line": 1},
                        "extra": {
                            "message": "Hardcoded key FAKE-KEY-0001 and FAKE-KEY-0001 again",
                            "fix": "load('FAKE-KEY-0001')",
                            "severity": "ERROR",
                            "metadata": meta,
                            "metavars": {"$KEY": {"abstract_content": "FAKE-KEY-0001"}},
                        },
                    }
                ]
            }
        )
    )
    return raw


def test_semgrep_metavariable_values_are_redacted_from_message_and_fix(tmp_path: Path) -> None:
    raw = _semgrep_raw(tmp_path, "python.lang.hardcoded", {})
    (finding,) = ss.parse_semgrep(raw, FAKE_REPO)
    assert "FAKE-KEY-0001" not in json.dumps(finding.as_dict())
    assert finding.title == "Hardcoded key [REDACTED] and [REDACTED] again"
    assert finding.fix == "load('[REDACTED]')"


@pytest.mark.parametrize(
    ("check_id", "meta"),
    [
        ("generic.secrets.security.detected-key", {}),
        ("custom.rule", {"tags": ["secrets"]}),
        ("custom.rule", {"technology": ["secrets"]}),
        ("custom.rule", {"category": "secret"}),
    ],
)
def test_a_secrets_rule_loses_its_fix_text(
    tmp_path: Path, check_id: str, meta: dict[str, Any]
) -> None:
    (finding,) = ss.parse_semgrep(_semgrep_raw(tmp_path, check_id, meta), FAKE_REPO)
    assert finding.fix == ""
    assert "FAKE-KEY-0001" not in json.dumps(finding.as_dict())


# --- git never reads the scanned repository's own config ---------------------------


def _marker_script(tmp_path: Path, name: str) -> tuple[Path, Path]:
    marker = tmp_path / f"{name}-ran"
    script = tmp_path / f"{name}.sh"
    script.write_text(f'#!/bin/sh\necho ran >> "{marker}"\ncat 2>/dev/null\n')
    script.chmod(0o755)
    return script, marker


def test_no_program_named_in_the_repository_config_runs_for_any_git_call(
    branch_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = branch_repo
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    markers = []
    for key in ("core.fsmonitor", "filter.demo.clean", "filter.demo.smudge", "gpg.program",
                "diff.demo.textconv", "diff.external", "core.pager", "core.hooksPath"):  # fmt: skip
        script, marker = _marker_script(tmp_path, key.replace(".", "-"))
        markers.append(marker)
        _git(repo, "config", key, str(hook_dir if key == "core.hooksPath" else script))
    (hook_dir / "reference-transaction").write_text(f'#!/bin/sh\necho ran >> "{markers[0]}"\n')
    (hook_dir / "reference-transaction").chmod(0o755)
    _git(repo, "config", "log.showSignature", "true")
    _git(repo, "config", "submodule.recurse", "true")
    (repo / ".gitattributes").write_text("*.py filter=demo diff=demo\n")
    (repo / "b.py").write_text("y = 2\n")  # edited, so a status or hash-object would filter it
    changes = _changes(repo, tmp_path)
    mirror = ss.make_mirror(repo, Path(tempfile.mkdtemp(dir=tmp_path)))
    log = ss.run_git(mirror, "log", "-p", "--all")  # what gitleaks' history pass runs
    assert {"a.py", "b.py", "c.py"} <= changes.files and "+x = 2" in log
    assert [m for m in markers if m.exists()] == [], "git ran a program the repository named"


def test_the_mirror_carries_no_config_from_the_repository(
    branch_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = branch_repo
    _git(repo, "config", "core.fsmonitor", "/bin/true")
    mirror = ss.make_mirror(repo, Path(tempfile.mkdtemp(dir=tmp_path)))
    config = (mirror.git_dir / "config").read_text()
    assert "fsmonitor" not in config and "bare = true" in config


def test_git_gets_neither_system_nor_user_config(
    branch_repo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    env = ss.isolated_git_env()
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert "GIT_DIR" not in env and "GIT_CONFIG_COUNT" not in env


def test_the_gitleaks_history_pass_reads_the_mirror_not_the_repository(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    plain = ss.TOOLS["gitleaks"].commands(tmp_path, raw, "")
    assert [name for name, _, _ in plain] == ["gitleaks-dir.json"]
    mirror = ss.Mirror(tmp_path / "m.git", "")
    both = ss.TOOLS["gitleaks"].commands(tmp_path, raw, "", mirror=mirror)
    assert [name for name, _, _ in both] == ["gitleaks-dir.json", "gitleaks-git.json"]
    (history,) = [argv for name, argv, _ in both if name == "gitleaks-git.json"]
    assert str(mirror.git_dir) in history and str(tmp_path) not in history[2:3]
    assert all("--redact" in argv for _, argv, _ in both)


def test_a_repository_that_cannot_be_mirrored_loses_only_the_history_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)  # looks like a repository, is not one
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "gitleaks",
        f"""[ "$1" = "version" ] && {{ echo "8.0-stub"; exit 0; }}
[ "$1" = "git" ] && {{ echo history ran > "{tmp_path}/history"; exit 0; }}
while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && dest="$2"; shift; done
/bin/cp "{RAW}/gitleaks-dir.json" "$dest"
""",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    out = tmp_path / "out"
    assert ss.main(["run", "--repo", str(repo), "--tools", "gitleaks", "--out", str(out)]) == 0
    tool = json.loads((out / "findings.json").read_text())["tools"][0]
    assert tool["status"] == "ran" and tool["count"] == 1
    assert tool["detail"].startswith("history pass not run:")
    assert not (tmp_path / "history").exists()


@pytest.mark.parametrize("ref", ["--output=out.txt", "-x", "--help"])
def test_a_ref_that_looks_like_an_option_is_refused(
    branch_repo: tuple[Path, Path], tmp_path: Path, ref: str
) -> None:
    repo, raw = branch_repo
    with pytest.raises(ValueError, match="starts with '-'"):
        _changes(repo, tmp_path, ref)
    assert not (repo / "out.txt").exists()
    code = ss.main(
        [
            "merge", "--raw", str(raw), "--repo", str(repo),
            "--out", str(tmp_path / "o"), f"--changed-since={ref}",
        ]
    )  # fmt: skip
    assert code == 2


# --- trivy: no remote resolution unless asked ---------------------------------------


def test_trivy_runs_vulnerabilities_only_and_offline_unless_remote_resolution_is_allowed(
    tmp_path: Path,
) -> None:
    ((_, argv, _),) = ss.TOOLS["trivy"].commands(tmp_path, tmp_path / "raw", "")
    assert "--offline-scan" in argv and argv[argv.index("--scanners") + 1] == "vuln"
    ((_, remote, _),) = ss.TOOLS["trivy"].commands(
        tmp_path, tmp_path / "raw", "", allow_remote=True
    )
    assert (
        "--offline-scan" not in remote
        and remote[remote.index("--scanners") + 1] == "vuln,misconfig"
    )


# --- the report treats file names, titles and rules as untrusted text ------------


def _hostile_finding(**fields: Any) -> Any:
    base: dict[str, Any] = {
        "kind": "code",
        "severity": "high",
        "title": "t",
        "file": "a.py",
        "line": 1,
        "rule": "r",
        "tools": ["semgrep"],
    }
    return ss.Finding(**{**base, **fields})


def test_the_report_cannot_be_broken_by_newlines_or_backticks_in_a_finding(
    tmp_path: Path,
) -> None:
    evil = _hostile_finding(
        title="x\n## Injected heading\r\n- [ ] fake item",
        file="we`ird``name\n# not a heading.py",
        rule="rule\nSecond line",
        note="note\x1b[31m red\nnext",
        fix="fix more",
    )
    text = ss.render_markdown(
        tmp_path, [ss.ToolStatus("semgrep", "code", "ran", "1.0")], [evil], "now"
    )
    for line in text.splitlines():
        assert not line.startswith(("## Injected", "- [ ] fake", "# not a heading", "Second line"))
    assert "\x1b" not in text and " " not in text
    (location,) = [ln for ln in text.splitlines() if ln.startswith("- Location:")]
    # the value holds a run of two backticks, so the fence is three
    assert location.startswith("- Location: ```we`ird``name") and location.endswith(":1```")


def test_the_overflow_table_keeps_each_row_on_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ss, "MAX_DETAILED_FINDINGS", 0)
    evil = _hostile_finding(title="a | b\n| injected | row |", file="x|y`z\nw.py")
    text = ss.render_markdown(
        tmp_path, [ss.ToolStatus("semgrep", "code", "ran", "1.0")], [evil], "now"
    )
    rows = [ln for ln in text.splitlines() if ln.startswith("| ")]
    assert not any(ln.startswith("| injected") for ln in rows)
    (row,) = [ln for ln in rows if "SS-" in ln or "x\\|y" in ln]
    assert "``x\\|y`z w.py:1``" in row


# --- checkov reads .checkov.yaml itself, so it is skipped when the repository has one ------


@pytest.mark.parametrize("name", [".checkov.yaml", ".checkov.yml"])
def test_checkov_is_skipped_and_reported_when_the_repository_has_its_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    repo = tmp_path / "repo"
    (repo / "infra").mkdir(parents=True)
    (repo / "infra" / name).write_text("external-checks-dir: [evil]\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ran = tmp_path / "checkov-ran"
    _stub(bin_dir, "checkov", f'echo ran > "{ran}"\necho {{}}\n')
    _stub(
        bin_dir,
        "gitleaks",
        'while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && dest="$2"; shift; done\n'
        'echo "[]" > "$dest"\n',
    )
    monkeypatch.setenv("PATH", str(bin_dir))
    out = tmp_path / "out"
    ss.main(["run", "--repo", str(repo), "--out", str(out), "--tools", "checkov,gitleaks"])
    assert not ran.exists(), "checkov ran on a repository with its own config"
    data = json.loads((out / "findings.json").read_text())
    (checkov,) = [t for t in data["tools"] if t["name"] == "checkov"]
    assert checkov["status"] == "skipped" and f"infra/{name}" in checkov["detail"]
    assert "| checkov | IaC | skipped |" in (out / "SECURITY-SCAN.md").read_text()


# --- review findings: case-insensitive names, osv-scanner offline, no stdout in failures ----


def test_a_differently_cased_checkov_config_still_skips_checkov(tmp_path: Path) -> None:
    (tmp_path / ".Checkov.YAML").write_text("external-checks-dir: [evil]\n")
    assert ".Checkov.YAML" in ss.blocked_by_repo_config("checkov", tmp_path)
    assert ".Checkov.YAML" in ss.find_suppression_files(tmp_path)
    (tmp_path / ".GitLeaks.TOML").write_text("")
    assert ".GitLeaks.TOML" in ss.find_suppression_files(tmp_path)


def test_osv_scanner_resolves_nothing_over_the_network_unless_remote_resolution_is_allowed(
    tmp_path: Path,
) -> None:
    ((_, argv, _),) = ss.TOOLS["osv-scanner"].commands(tmp_path, tmp_path / "raw", "")
    assert "--no-resolve" in argv and "--offline-vulnerabilities" in argv
    ((_, remote, _),) = ss.TOOLS["osv-scanner"].commands(
        tmp_path, tmp_path / "raw", "", allow_remote=True
    )
    assert "--no-resolve" not in remote and "--offline-vulnerabilities" not in remote


def test_an_unexpected_exit_reports_stderr_and_the_code_never_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "grype",
        '[ "$1" = "version" ] && { echo stub; exit 0; }\necho SECRET-IN-STDOUT\nexit 3\n',
    )
    monkeypatch.setenv("PATH", str(bin_dir))
    raw = tmp_path / "raw"
    raw.mkdir()
    status = ss.run_tool(ss.TOOLS["grype"], tmp_path, raw, "", 30)
    assert status.status == "failed"
    assert "exit code 3" in status.detail and "SECRET-IN-STDOUT" not in status.detail
