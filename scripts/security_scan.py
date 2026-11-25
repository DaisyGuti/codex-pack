#!/usr/bin/env python3
"""Run the free security scanners that are installed and merge their output into one report.

Roles and tools (each is optional; a missing tool is reported, never installed):
  secrets       gitleaks
  dependencies  osv-scanner, grype, trivy (vulnerability scan)
  code (SAST)   semgrep
  infra as code trivy (misconfiguration scan), checkov

Usage:
    security_scan.py detect [--json]
    security_scan.py run   [--repo DIR] [--out DIR] [--tools a,b] [--semgrep-config CFG]
                           [--timeout SECONDS] [--fail-on SEVERITY]
    security_scan.py merge --raw DIR [--repo DIR] [--out DIR] [--fail-on SEVERITY]

`run` executes every selected installed tool, keeps each tool's raw output under
<out>/raw/, then normalizes, de-duplicates and writes SECURITY-SCAN.md and findings.json.
`merge` does the last half on raw files from an earlier run or from CI artifacts.

Exit codes: 0 report written; 1 a finding at or above --fail-on exists; 2 usage error, or
no tool produced a result (the message says which tools to install).

Secret values never reach the report: the gitleaks normalizer reads only the rule, the
file, the line and the commit, never the `Secret` or `Match` fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info", "unknown"]
RANK = {name: index for index, name in enumerate(SEVERITY_ORDER)}
# Within one severity, an exposed credential comes first because it needs no exploit.
KIND_ORDER = {"secret": 0, "code": 1, "iac": 2, "dependency": 3}

# A scan of a large repository can legitimately take minutes (semgrep rule download, the
# first trivy or grype database fetch). Ten minutes is long enough for those and short
# enough that a hung tool does not block the whole run.
DEFAULT_TIMEOUT_SECONDS = 600

# Semgrep's curated default ruleset. It is fetched from the Semgrep registry; pass
# --semgrep-config with a local rules directory for an air-gapped or policy-restricted run.
DEFAULT_SEMGREP_CONFIG = "p/default"

# A committed credential has no severity in gitleaks. It is rated high because anyone who
# can read the repository can use it.
SECRET_SEVERITY = "high"

# A failed infrastructure-as-code check from checkov carries no severity without a paid
# account. Medium keeps it visible without outranking scored vulnerabilities; the finding
# says the severity was assumed.
IAC_DEFAULT_SEVERITY = "medium"

# Semgrep rates a rule ERROR, WARNING or INFO. They read as high, medium and low.
SEMGREP_SEVERITY = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}

# The first dotted number in a tool's version output, e.g. "8.30.1" from "gitleaks 8.30.1".
VERSION_PATTERN = re.compile(r"\d+\.\d+(?:\.\d+)?")

# The Markdown report gives full detail for this many findings and a one-line table for the
# rest, so a repository with thousands of dependency findings still opens as a readable report.
# findings.json always holds every finding in full.
MAX_DETAILED_FINDINGS = 200

# Files a scanner can read from the repository that can hide findings from this report. The
# report lists any that exist so a reviewer reads them, including those of the scanners that run
# on built-in defaults (trivy, grype) or are skipped over them (checkov). The match is on the
# file name.
SUPPRESSION_FILES = {
    ".gitleaks.toml",
    ".gitleaksignore",
    ".semgrepignore",
    ".trivyignore",
    ".trivyignore.yaml",
    ".grype.yaml",
    "osv-scanner.toml",
    ".checkov.yaml",
    ".checkov.yml",
}
# Directories never searched for those files.
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "__pycache__"}

# Maximum characters of tool stderr kept when a tool fails.
STDERR_TAIL = 500


@dataclass
class Finding:
    """One normalized finding. `tools` lists every scanner that reported it."""

    kind: str  # secret | dependency | code | iac
    severity: str
    title: str
    file: str = ""
    line: int | None = None
    rule: str = ""
    fix: str = ""
    package: str = ""
    version: str = ""
    ids: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    note: str = ""
    finding_id: str = ""
    commits: list[str] = field(default_factory=list)  # full ids, from the history pass

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.finding_id,
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "package": self.package,
            "version": self.version,
            "ids": self.ids,
            "fix": self.fix,
            "tools": self.tools,
            "note": self.note,
            "commits": self.commits,
        }


@dataclass
class ToolStatus:
    """What happened to one tool in this run, shown in the report's Coverage table."""

    name: str
    role: str
    status: str  # ran | not installed | failed | no input | not run | skipped
    version: str = ""
    detail: str = ""
    count: int = 0


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------


def severity_from_label(label: Any) -> str:
    """Map a vendor severity word to one of SEVERITY_ORDER."""
    word = str(label or "").strip().lower()
    table = {
        "critical": "critical",
        "high": "high",
        "error": "high",
        "medium": "medium",
        "moderate": "medium",
        "warning": "medium",
        "low": "low",
        "negligible": "info",
        "info": "info",
        "informational": "info",
    }
    return table.get(word, "unknown")


def severity_from_cvss(score: Any) -> str:
    """Map a CVSS base score to the qualitative bands in the FIRST CVSS specification."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if value >= 9.0:
        return "critical"
    if value >= 7.0:
        return "high"
    if value >= 4.0:
        return "medium"
    if value > 0.0:
        return "low"
    return "info"


def worst(a: str, b: str) -> str:
    return a if RANK[a] <= RANK[b] else b


# ---------------------------------------------------------------------------
# Normalizers: raw tool output -> list[Finding]
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path} as JSON: {exc}") from exc


def _rel(path_text: str, repo: Path, rooted: bool = False) -> str:
    """Return a repo-relative path.

    Tools report absolute paths, paths relative to the scan root, or (grype, checkov) paths
    that start with `/` but mean "from the scan root". Pass rooted=True for the last kind.
    """
    if not path_text:
        return ""
    try:
        return Path(path_text).resolve().relative_to(repo.resolve()).as_posix()
    except (ValueError, OSError):
        pass
    if rooted and path_text.startswith("/"):
        return path_text.lstrip("/")
    return path_text


def parse_gitleaks(path: Path, repo: Path) -> list[Finding]:
    data = _load_json(path)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list from gitleaks")
    findings = []
    for item in data:
        full_commit = str(item.get("Commit") or "")
        commit = full_commit[:12]
        findings.append(
            Finding(
                kind="secret",
                severity=SECRET_SEVERITY,
                title=str(item.get("Description") or item.get("RuleID") or "Secret detected"),
                file=_rel(str(item.get("File") or ""), repo),
                line=item.get("StartLine") or None,
                rule=str(item.get("RuleID") or ""),
                fix="Revoke the credential, remove it from the code, and load it from a secret "
                "manager or environment variable. Rewrite history only after revoking.",
                note=f"found in commit {commit}" if commit else "",
                tools=["gitleaks"],
                commits=[full_commit] if full_commit else [],
            )
        )
    return findings


def _fixed_versions(vulns: list[dict[str, Any]], ids: set[str]) -> list[str]:
    fixed: list[str] = []
    for vuln in vulns:
        if vuln.get("id") not in ids and not ids.intersection(vuln.get("aliases", [])):
            continue
        for affected in vuln.get("affected", []):
            for rng in affected.get("ranges", []):
                if rng.get("type") != "ECOSYSTEM":
                    continue
                for event in rng.get("events", []):
                    if "fixed" in event and event["fixed"] not in fixed:
                        fixed.append(str(event["fixed"]))
    return fixed


def parse_osv(path: Path, repo: Path) -> list[Finding]:
    data = _load_json(path)
    findings = []
    for result in (data or {}).get("results", []):
        source = _rel(str((result.get("source") or {}).get("path") or ""), repo)
        for pkg in result.get("packages", []):
            meta = pkg.get("package") or {}
            vulns = pkg.get("vulnerabilities", [])
            for group in pkg.get("groups", []):
                ids = sorted(set(group.get("ids", [])) | set(group.get("aliases", [])))
                severity = severity_from_cvss(group.get("max_severity"))
                if severity == "unknown":
                    for vuln in vulns:
                        if vuln.get("id") in ids:
                            label = (vuln.get("database_specific") or {}).get("severity")
                            severity = severity_from_label(label)
                            break
                fixed = _fixed_versions(vulns, set(ids))
                name, version = str(meta.get("name", "")), str(meta.get("version", ""))
                cves = [i for i in ids if i.startswith("CVE-")]
                label = cves[0] if cves else (ids[0] if ids else "vulnerability")
                findings.append(
                    Finding(
                        kind="dependency",
                        severity=severity,
                        title=f"{name} {version}: {label}",
                        file=source,
                        package=name,
                        version=version,
                        ids=ids,
                        fix=f"Upgrade {name} to {' or '.join(fixed)}." if fixed else "",
                        tools=["osv-scanner"],
                    )
                )
    return findings


def parse_grype(path: Path, repo: Path) -> list[Finding]:
    data = _load_json(path)
    findings = []
    for match in (data or {}).get("matches", []):
        vuln = match.get("vulnerability") or {}
        art = match.get("artifact") or {}
        ids = {str(vuln.get("id", ""))}
        related = match.get("relatedVulnerabilities") or []
        ids.update(str(r.get("id", "")) for r in related)
        ids.discard("")
        locations = art.get("locations") or [{}]
        versions = (vuln.get("fix") or {}).get("versions") or []
        name, version = str(art.get("name", "")), str(art.get("version", ""))
        sorted_ids = sorted(ids)
        cves = [i for i in sorted_ids if i.startswith("CVE-")]
        label = cves[0] if cves else str(vuln.get("id", "vulnerability"))
        findings.append(
            Finding(
                kind="dependency",
                severity=severity_from_label(vuln.get("severity")),
                title=f"{name} {version}: {label}",
                file=_rel(str(locations[0].get("path") or ""), repo, rooted=True),
                package=name,
                version=version,
                ids=sorted_ids,
                fix=f"Upgrade {name} to {' or '.join(versions)}." if versions else "",
                tools=["grype"],
            )
        )
    return findings


REDACTED = "[REDACTED]"
# A metavariable value shorter than this is not a credential, and replacing it would mangle the
# message it sits in. A rule tagged as a secrets rule has every value redacted regardless.
MIN_REDACTED_LENGTH = 4


def _is_secrets_rule(item: dict[str, Any], meta: dict[str, Any]) -> bool:
    """True when the rule is a secrets rule: a tag, technology or category says so, or its id
    has a path segment that starts with "secret" (generic.secrets.security....)."""
    labels: list[str] = []
    for key in ("tags", "technology", "category", "subcategory"):
        value = meta.get(key) or []
        labels += [value] if isinstance(value, str) else [str(v) for v in value]
    if any("secret" in label.lower() for label in labels):
        return True
    return any(
        seg.lower().startswith("secret") for seg in str(item.get("check_id") or "").split(".")
    )


def _redact_metavars(text: str, extra: dict[str, Any], secrets_rule: bool) -> str:
    """Replace the values semgrep bound to metavariables, longest first, so a credential that
    the rule's message or autofix quotes never reaches the report."""
    values = {
        str((mv or {}).get("abstract_content") or "")
        for mv in (extra.get("metavars") or {}).values()
        if isinstance(mv, dict)
    }
    for value in sorted(values, key=len, reverse=True):
        if value and (secrets_rule or len(value) >= MIN_REDACTED_LENGTH):
            text = text.replace(value, REDACTED)
    return text


def parse_semgrep(path: Path, repo: Path) -> list[Finding]:
    data = _load_json(path)
    findings = []
    for item in (data or {}).get("results", []):
        extra = item.get("extra") or {}
        meta = extra.get("metadata") or {}
        cwe = meta.get("cwe") or []
        if isinstance(cwe, str):
            cwe = [cwe]
        cwe_ids = [str(c).split(":")[0].strip() for c in cwe]
        secrets_rule = _is_secrets_rule(item, meta)
        message = _redact_metavars(str(extra.get("message") or ""), extra, secrets_rule)
        fix = "" if secrets_rule else _redact_metavars(str(extra.get("fix") or ""), extra, False)
        # The matched source lines are not copied, metavariable values are redacted and a secrets
        # rule gets no autofix text: all of them can hold a credential.
        findings.append(
            Finding(
                kind="code",
                severity=SEMGREP_SEVERITY.get(
                    str(extra.get("severity", "")).upper(),
                    severity_from_label(extra.get("severity")),
                ),
                title=message or str(item.get("check_id") or "Semgrep finding"),
                file=_rel(str(item.get("path") or ""), repo),
                line=(item.get("start") or {}).get("line"),
                rule=str(item.get("check_id") or ""),
                ids=cwe_ids,
                fix=fix,
                tools=["semgrep"],
            )
        )
    return findings


def parse_trivy(path: Path, repo: Path) -> list[Finding]:
    data = _load_json(path)
    findings = []
    for result in (data or {}).get("Results", []):
        target = _rel(str(result.get("Target") or ""), repo)
        for vuln in result.get("Vulnerabilities") or []:
            name, version = str(vuln.get("PkgName", "")), str(vuln.get("InstalledVersion", ""))
            fixed = str(vuln.get("FixedVersion") or "")
            findings.append(
                Finding(
                    kind="dependency",
                    severity=severity_from_label(vuln.get("Severity")),
                    title=f"{name} {version}: {vuln.get('VulnerabilityID', 'vulnerability')}",
                    file=target,
                    package=name,
                    version=version,
                    ids=[str(vuln.get("VulnerabilityID", ""))],
                    fix=f"Upgrade {name} to {fixed}." if fixed else "",
                    tools=["trivy"],
                )
            )
        for conf in result.get("Misconfigurations") or []:
            if str(conf.get("Status", "FAIL")).upper() != "FAIL":
                continue
            cause = conf.get("CauseMetadata") or {}
            findings.append(
                Finding(
                    kind="iac",
                    severity=severity_from_label(conf.get("Severity")),
                    title=str(conf.get("Title") or conf.get("ID") or "Misconfiguration"),
                    file=target,
                    line=cause.get("StartLine") or None,
                    rule=str(conf.get("ID") or ""),
                    ids=[str(conf["AVDID"])] if conf.get("AVDID") else [],
                    fix=str(conf.get("Resolution") or ""),
                    tools=["trivy"],
                )
            )
    return findings


def parse_checkov(path: Path, repo: Path) -> list[Finding]:
    data = _load_json(path)
    # Checkov prints one object per framework, or a bare object when only one ran.
    blocks = data if isinstance(data, list) else [data]
    findings = []
    for block in blocks:
        for failed in ((block or {}).get("results") or {}).get("failed_checks") or []:
            sev = failed.get("severity")
            line_range = failed.get("file_line_range") or []
            findings.append(
                Finding(
                    kind="iac",
                    severity=severity_from_label(sev) if sev else IAC_DEFAULT_SEVERITY,
                    title=str(failed.get("check_name") or failed.get("check_id") or "IaC check"),
                    file=_rel(str(failed.get("file_path") or ""), repo, rooted=True),
                    line=line_range[0] if line_range else None,
                    rule=str(failed.get("check_id") or ""),
                    fix=f"See {failed['guideline']}" if failed.get("guideline") else "",
                    note="" if sev else "severity not provided by checkov; assumed medium",
                    tools=["checkov"],
                )
            )
    return findings


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------


def _merge(into: Finding, other: Finding) -> None:
    into.severity = worst(into.severity, other.severity)
    into.tools = sorted(set(into.tools) | set(other.tools))
    into.ids = sorted(set(into.ids) | set(other.ids))
    into.commits = sorted(set(into.commits) | set(other.commits))
    if not into.fix and other.fix:
        into.fix = other.fix
    if not into.note and other.note:
        into.note = other.note
    if not into.file and other.file:
        into.file = other.file


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Merge findings that describe the same problem reported by more than one tool.

    Dependencies merge when the package, version and at least one vulnerability id (CVE,
    GHSA or other alias) match. Secrets merge on file and line. Code and IaC findings merge
    on kind, file, line and rule, so one tool reporting twice does not double-count.
    """
    merged: list[Finding] = []
    index: dict[tuple[object, ...], list[Finding]] = {}
    for finding in findings:
        if finding.kind == "dependency":
            key: tuple[object, ...] = (finding.kind, finding.package.lower(), finding.version)
        elif finding.kind == "secret":
            key = (finding.kind, finding.file, finding.line)
        else:
            key = (finding.kind, finding.file, finding.line, finding.rule)
        target = None
        for existing in index.get(key, []):
            # Dependencies in the same bucket still need a shared vulnerability id to merge.
            if finding.kind != "dependency" or set(existing.ids) & set(finding.ids):
                target = existing
                break
        if target is None:
            merged.append(finding)
            index.setdefault(key, []).append(finding)
        else:
            _merge(target, finding)
    merged.sort(key=lambda f: (RANK[f.severity], KIND_ORDER[f.kind], f.file, f.line or 0, f.title))
    return number(merged)


def number(findings: list[Finding]) -> list[Finding]:
    for index, finding in enumerate(findings, start=1):
        finding.finding_id = f"SS-{index:03d}"
    return findings


def find_suppression_files(repo: Path) -> list[str]:
    """Return repo-relative paths of files that tell a scanner to ignore findings."""
    found = []
    for folder, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name in SUPPRESSION_FILES:
                found.append((Path(folder) / name).relative_to(repo).as_posix())
    return sorted(found)


def normalize_path(name: str) -> str | None:
    """A repo-relative POSIX path in one canonical spelling, or None when `name` is empty,
    absolute or points outside the repository (so it cannot be matched against a changed file)."""
    if not name:
        return None
    path = posixpath.normpath(name)
    if path in (".", "..") or path.startswith(("/", "../")):
        return None
    return path


# ---------------------------------------------------------------------------
# git, never against the scanned repository's own config
# ---------------------------------------------------------------------------
#
# A repository's config can name programs git runs (core.fsmonitor, filter and textconv drivers,
# gpg.program, hooks, submodule settings), and a list of those keeps growing. So git never reads
# the scanned repository's config at all: one isolated copy is made first (`git clone --mirror
# --no-local`, which carries objects and refs and none of the config), and every later git call
# runs on that copy with the system and user config switched off.


def isolated_git_env() -> dict[str, str]:
    """The environment for every git process this script (or a scanner) starts."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(name, None)
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


@dataclass(frozen=True)
class Mirror:
    """An isolated bare copy of the scanned repository."""

    git_dir: Path
    prefix: str  # the scan root's path below the git root: "" or "svc/"


def find_git_root(path: Path) -> Path | None:
    """The nearest folder at or above `path` that holds `.git`, found without running git."""
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            return folder
    return None


def make_mirror(repo: Path, parent: Path) -> Mirror:
    """Clone the repository into `parent` without its config. Raises ValueError on failure."""
    root = find_git_root(repo)
    if root is None:
        raise ValueError(f"{repo} is not inside a git repository")
    git_dir = parent / "mirror.git"
    proc = subprocess.run(
        [
            "git",
            "--no-pager",
            "clone",
            "-q",
            "--mirror",
            "--no-local",
            "--",
            str(root),
            str(git_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=isolated_git_env(),
        cwd=parent,
    )
    if proc.returncode != 0:
        raise ValueError(
            f"could not make an isolated copy of the repository: {proc.stderr.strip()}"
        )
    relative = repo.relative_to(root).as_posix()
    return Mirror(git_dir, "" if relative == "." else relative + "/")


def run_git(mirror: Mirror, *args: str, work_tree: Path | None = None) -> str:
    """The one way this script runs git on a scanned repository: on the isolated copy."""
    argv = ["git", "--no-pager", "--git-dir", str(mirror.git_dir)]
    if work_tree is not None:
        argv += ["--work-tree", str(work_tree)]
    proc = subprocess.run(
        [*argv, *args],
        capture_output=True,
        text=True,
        check=False,
        env=isolated_git_env(),
        cwd=work_tree,
    )
    if proc.returncode != 0:
        raise ValueError(f"`git {' '.join(args)}` failed: {proc.stderr.strip()}")
    return proc.stdout


@dataclass(frozen=True)
class Changes:
    """What changed since the base: every file any commit since it touched plus the working-tree
    differences, and the ids of those commits."""

    files: set[str]
    commits: set[str]


def _blob_id(path: Path, algorithm: str) -> str | None:
    """The git blob id of the file on disk as it is, with no filter applied (what
    `git hash-object --no-filters` prints), or None when there is no file or link."""
    digest = hashlib.new(algorithm)
    try:
        if path.is_symlink():
            data = os.readlink(path).encode()
            digest.update(b"blob %d\0" % len(data) + data)
        elif path.is_file():
            digest.update(b"blob %d\0" % path.stat().st_size)
            with path.open("rb") as handle:
                while chunk := handle.read(1 << 20):
                    digest.update(chunk)
        else:
            return None
    except OSError:
        return None
    return digest.hexdigest()


def working_tree_changes(repo: Path, mirror: Mirror) -> set[str]:
    """Files on disk that differ from HEAD's tree, or are not in it, relative to `repo`.

    The comparison hashes the bytes on disk and checks them against the tree: no git index, no
    filter driver, no stat cache. Names git ignores (.gitignore, read as data) are left out."""
    algorithm = (
        "sha256"
        if run_git(mirror, "rev-parse", "--show-object-format").strip() == "sha256"
        else "sha1"
    )
    tracked: set[str] = set()
    changed: set[str] = set()
    for entry in run_git(mirror, "ls-tree", "-r", "-z", "HEAD").split("\0"):
        if not entry:
            continue
        meta, _, name = entry.partition("\t")
        mode, kind, blob = meta.split()
        if kind != "blob" or not name.startswith(mirror.prefix):
            continue  # a submodule's commit, or a file outside the scan root
        relative = name[len(mirror.prefix) :]
        tracked.add(relative)
        if _blob_id(repo / relative, algorithm) != blob:
            changed.add(relative)
    listing = run_git(mirror, "ls-files", "-z", "--others", "--exclude-standard", work_tree=repo)
    for name in listing.split("\0"):
        if name and not name.endswith("/") and name not in tracked:
            changed.add(name)
    return changed


def changed_files(repo: Path, mirror: Mirror, ref: str) -> Changes:
    """What changed since `ref` branched off: every file any commit in `base..HEAD` touched (a
    change that was later reverted still counts), the working-tree differences, and the commits.

    Paths come from git NUL-separated, so a name with a newline, a quote or non-ASCII characters
    arrives as it is on disk, and each is made relative to `repo`, which is what a finding's file
    is relative to.
    """
    if ref.startswith("-"):
        raise ValueError(f"{ref!r} starts with '-', so git would read it as an option")
    base = run_git(mirror, "merge-base", ref, "HEAD").strip()
    names = set(
        run_git(
            mirror, "log", "-z", "--name-only", "--no-renames", "--format=", f"{base}..HEAD"
        ).split("\0")
    )
    names = {n[len(mirror.prefix) :] for n in names if n.startswith(mirror.prefix)}
    names |= working_tree_changes(repo, mirror)
    commits = set(run_git(mirror, "rev-list", f"{base}..HEAD").split())
    return Changes({n for n in map(normalize_path, names) if n}, commits)


def in_changed_set(finding: Finding, changes: Changes) -> bool:
    """Keep a finding when its file changed or its commit is one of the new ones, and also when
    its path cannot be matched at all: a finding the filter cannot place is shown, not dropped."""
    path = normalize_path(finding.file)
    return path is None or path in changes.files or bool(set(finding.commits) & changes.commits)


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@dataclass
class Tool:
    name: str
    role: str
    binary: str
    version_args: list[str]
    install: str
    # Each command: (raw file name, argv, True when the tool writes JSON to stdout).
    # Called as commands(repo, raw, semgrep_config, mirror=<isolated copy or None>,
    # allow_remote=<the opt-in flag>).
    commands: Callable[..., list[tuple[str, list[str], bool]]]
    ok_codes: tuple[int, ...]
    no_input_codes: tuple[int, ...]
    parser: Callable[[Path, Path], list[Finding]]


def _defaults_file(raw: Path) -> Path:
    """An empty YAML config for scanners that would otherwise search for one near the scan.

    trivy, grype and checkov read config from the working directory or the repository, and
    checkov can load check code from it. Naming this file makes each use its built-in defaults.
    """
    path = raw / "scanner-defaults.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    return path


def _grype_commands(
    repo: Path, raw: Path, _c: str, **_options: Any
) -> list[tuple[str, list[str], bool]]:
    argv = ["grype", f"dir:{repo}", "-c", str(_defaults_file(raw)), "-o", "json", "-q"]
    return [("grype.json", argv, True)]


def _trivy_commands(
    repo: Path, raw: Path, _c: str, *, allow_remote: bool = False, **_options: Any
) -> list[tuple[str, list[str], bool]]:
    # Default: vulnerabilities only, with no lookups that go beyond the vulnerability database.
    # trivy's misconfiguration scan resolves Terraform modules from remote sources, so it runs
    # only behind --allow-remote-resolution.
    argv = [
        "trivy",
        "fs",
        "--config",
        str(_defaults_file(raw)),
        *([] if allow_remote else ["--offline-scan"]),
        "--format",
        "json",
        "--scanners",
        "vuln,misconfig" if allow_remote else "vuln",
        "--quiet",
        "--output",
        str(raw / "trivy.json"),
        str(repo),
    ]
    return [("trivy.json", argv, False)]


def _checkov_commands(
    repo: Path, raw: Path, _c: str, **_options: Any
) -> list[tuple[str, list[str], bool]]:
    # An empty --config-file and an empty --external-checks-dir keep the built-in checks the only
    # ones that run. checkov still finds a .checkov.yaml in the scan root on its own, which is why
    # cmd_run() skips checkov when the repository has one (REPO_CONFIG_BLOCKS).
    empty_checks = raw / "empty-checks"
    empty_checks.mkdir(parents=True, exist_ok=True)
    argv = [
        "checkov",
        "-d",
        str(repo),
        "--config-file",
        str(_defaults_file(raw)),
        "--external-checks-dir",
        str(empty_checks),
        "-o",
        "json",
        "--quiet",
    ]
    return [("checkov.json", argv, True)]


def _gitleaks_commands(
    repo: Path, raw: Path, _cfg: str, *, mirror: Mirror | None = None, **_options: Any
) -> list[tuple[str, list[str], bool]]:
    base = ["--redact", "--report-format", "json", "--exit-code", "0", "--no-banner"]
    commands = [
        (
            "gitleaks-dir.json",
            ["gitleaks", "dir", str(repo), *base, "--report-path", str(raw / "gitleaks-dir.json")],
            False,
        )
    ]
    if mirror is not None:  # the history pass reads the isolated copy, never the repository's .git
        commands.append(
            (
                "gitleaks-git.json",
                [
                    "gitleaks",
                    "git",
                    str(mirror.git_dir),
                    *base,
                    "--report-path",
                    str(raw / "gitleaks-git.json"),
                ],
                False,
            )
        )
    return commands


TOOLS: dict[str, Tool] = {
    "gitleaks": Tool(
        name="gitleaks",
        role="secrets",
        binary="gitleaks",
        version_args=["version"],
        install="brew install gitleaks   (other platforms: https://github.com/gitleaks/gitleaks#installing)",
        commands=_gitleaks_commands,
        ok_codes=(0,),
        no_input_codes=(),
        parser=parse_gitleaks,
    ),
    "osv-scanner": Tool(
        name="osv-scanner",
        role="dependencies",
        binary="osv-scanner",
        version_args=["--version"],
        install="brew install osv-scanner   (v2 or later; https://google.github.io/osv-scanner/installation/)",
        commands=lambda repo, raw, _c, **_o: [
            (
                "osv-scanner.json",
                [
                    "osv-scanner",
                    "scan",
                    "source",
                    "-r",
                    "--format",
                    "json",
                    "--output-file",
                    str(raw / "osv-scanner.json"),
                    str(repo),
                ],
                False,
            )
        ],
        ok_codes=(0, 1),
        no_input_codes=(128,),
        parser=parse_osv,
    ),
    "grype": Tool(
        name="grype",
        role="dependencies",
        binary="grype",
        version_args=["version"],
        install="brew install grype   (https://oss.anchore.com/docs/installation/grype/)",
        commands=_grype_commands,
        ok_codes=(0,),
        no_input_codes=(),
        parser=parse_grype,
    ),
    "semgrep": Tool(
        name="semgrep",
        role="code",
        binary="semgrep",
        version_args=["--version"],
        install="brew install semgrep   or   pipx install semgrep   (https://semgrep.dev/docs/getting-started/)",
        commands=lambda repo, raw, cfg, **_o: [
            (
                "semgrep.json",
                [
                    "semgrep",
                    "scan",
                    "--json",
                    "--quiet",
                    "--metrics",
                    "off",
                    "--disable-version-check",
                    "--config",
                    cfg or DEFAULT_SEMGREP_CONFIG,
                    str(repo),
                ],
                True,
            )
        ],
        ok_codes=(0,),
        no_input_codes=(),
        parser=parse_semgrep,
    ),
    "trivy": Tool(
        name="trivy",
        role="dependencies and IaC",
        binary="trivy",
        version_args=["--version"],
        install="brew install trivy   (https://trivy.dev/latest/getting-started/installation/)",
        commands=_trivy_commands,
        ok_codes=(0,),
        no_input_codes=(),
        parser=parse_trivy,
    ),
    "checkov": Tool(
        name="checkov",
        role="IaC",
        binary="checkov",
        version_args=["--version"],
        install="pipx install checkov   or   brew install checkov   (https://www.checkov.io/2.Basics/Installing%20Checkov.html)",
        commands=_checkov_commands,
        ok_codes=(0, 1),
        no_input_codes=(),
        parser=parse_checkov,
    ),
}

# Raw file name prefix -> tool name, so `merge` can find each tool's output.
RAW_PREFIXES = {name: name for name in TOOLS}


def tool_version(tool: Tool) -> str:
    """Best-effort one-line version string; empty when the tool does not answer."""
    try:
        proc = subprocess.run(
            [tool.binary, *tool.version_args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    match = VERSION_PATTERN.search(proc.stdout or proc.stderr)
    return match.group(0) if match else ""


def detect(only: list[str] | None = None) -> list[ToolStatus]:
    statuses = []
    for name, tool in TOOLS.items():
        if only is not None and name not in only:
            continue
        if shutil.which(tool.binary):
            statuses.append(ToolStatus(name, tool.role, "installed", tool_version(tool)))
        else:
            statuses.append(ToolStatus(name, tool.role, "not installed", detail=tool.install))
    return statuses


# ---------------------------------------------------------------------------
# Running and merging
# ---------------------------------------------------------------------------


# Repository files a scanner reads by itself even when handed an empty config, and which can make
# it run code from the repository. The scanner is skipped, and the report says why.
REPO_CONFIG_BLOCKS = {"checkov": {".checkov.yaml", ".checkov.yml"}}


def blocked_by_repo_config(name: str, repo: Path) -> str:
    """Why `name` must not run on this repository, or an empty string."""
    names = REPO_CONFIG_BLOCKS.get(name, set())
    found = [f for f in find_suppression_files(repo) if Path(f).name in names]
    if not found:
        return ""
    return (
        f"skipped: the repository has {', '.join(found)}, which {name} reads and which can load "
        f"code from the repository. Review the file, then run {name} yourself or remove it."
    )


def run_tool(
    tool: Tool,
    repo: Path,
    raw: Path,
    semgrep_config: str,
    timeout: int,
    *,
    mirror: Mirror | None = None,
    allow_remote: bool = False,
) -> ToolStatus:
    """Run each of the tool's commands. A later command may fail without losing the first.

    gitleaks, for example, scans the working tree and then the git history. If the history pass
    fails (a shallow clone, an empty repository) the working-tree result is still reported, and
    the Coverage table says which pass was lost.
    """
    status = ToolStatus(tool.name, tool.role, "ran", tool_version(tool))
    for stale in raw.glob(f"{RAW_PREFIXES[tool.name]}*.json"):
        stale.unlink()  # a re-run into the same --out must not mix in an older result
    finished = 0
    env = isolated_git_env()  # a scanner that starts git gets no system or user git config
    commands = tool.commands(repo, raw, semgrep_config, mirror=mirror, allow_remote=allow_remote)
    for raw_name, argv, to_stdout in commands:
        problem = ""
        try:
            # The scan root is an argument. The working directory is a fresh empty folder, so a
            # scanner's search of the current directory for config or plugins finds nothing the
            # repository controls.
            with tempfile.TemporaryDirectory(prefix="security-scan-cwd-") as cwd:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=cwd,
                    check=False,
                    env=env,
                )
        except subprocess.TimeoutExpired:
            problem = f"timed out after {timeout} seconds"
        except OSError as exc:
            problem = str(exc)
        else:
            if proc.returncode in tool.no_input_codes:
                if finished == 0:
                    status.status, status.detail = "no input", "nothing the tool can scan"
                    return status
                continue
            if proc.returncode not in tool.ok_codes:
                tail = (proc.stderr or proc.stdout).strip()[-STDERR_TAIL:]
                problem = f"exit code {proc.returncode}: {tail}"
            elif to_stdout:
                (raw / raw_name).write_text(proc.stdout)
        if problem:
            if finished == 0:
                status.status, status.detail = "failed", problem
            else:
                status.detail = f"{raw_name} pass lost: {problem}"
            return status
        finished += 1
    return status


def collect(tool: Tool, repo: Path, raw: Path, status: ToolStatus) -> list[Finding]:
    """Parse every raw file this tool left behind; a parse failure marks the tool failed."""
    findings: list[Finding] = []
    files = sorted(raw.glob(f"{RAW_PREFIXES[tool.name]}*.json"))
    if not files:
        if status.status == "ran":
            status.status, status.detail = "failed", "the tool left no output file"
        return findings
    for path in files:
        try:
            findings.extend(tool.parser(path, repo))
        except ValueError as exc:
            status.status, status.detail = "failed", str(exc)
            return []
    status.status = "ran"
    status.count = len(findings)
    return findings


# Newlines, tabs and every other control character, plus the Unicode line and paragraph
# separators: anything that could end a Markdown line or hide text.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def md_text(value: object) -> str:
    """Untrusted text for one Markdown line: control characters become spaces."""
    return _CONTROL.sub(" ", str(value))


def md_cell(value: object) -> str:
    """Untrusted text for a table cell: one line, with pipes escaped."""
    return md_text(value).replace("|", "\\|")


def md_code(value: object) -> str:
    """Untrusted text as an inline code span. The fence is one backtick longer than the longest
    run of backticks in the value, so the value cannot close the span; a value that starts or
    ends with a backtick gets a padding space on each side, which Markdown strips again."""
    text = md_text(value)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def render_markdown(
    repo: Path,
    statuses: list[ToolStatus],
    findings: list[Finding],
    generated: str,
    filter_note: str = "",
    suppressions: list[str] | None = None,
) -> str:
    counts = {sev: sum(1 for f in findings if f.severity == sev) for sev in SEVERITY_ORDER}
    lines = [
        "# Security scan report",
        "",
        f"- Repository: {md_code(repo.name)}",
        f"- Generated: {generated}",
        "- Scope: the scanners listed under Coverage. A scanner that is not listed as `ran` "
        "did not look at the code, so its absence is not a clean result.",
        *([f"- Filter: {md_text(filter_note)}"] if filter_note else []),
        "",
        "## Coverage",
        "",
        "| Tool | Role | Status | Findings | Version or detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in statuses:
        detail = md_cell(f"{s.version} {s.detail}".strip())
        lines.append(f"| {s.name} | {s.role} | {s.status} | {s.count} | {detail} |")
    if suppressions:
        lines += [
            "",
            "Suppression files in the repository. gitleaks, semgrep and osv-scanner read these "
            "from the scan root and leave out the findings they match; trivy and grype run on "
            "built-in defaults and ignore them; checkov is skipped when the repository has a "
            "`.checkov.yaml` or `.checkov.yml`, and Coverage says so. Read each one:",
            "",
            *[f"- {md_code(path)}" for path in suppressions],
        ]
    lines += ["", "## Summary", "", "| Severity | Findings |", "| --- | --- |"]
    lines += [f"| {sev} | {counts[sev]} |" for sev in SEVERITY_ORDER if counts[sev]]
    if not findings:
        lines += ["", "No findings from the tools that ran."]
        return "\n".join(lines) + "\n"
    lines += ["", "## Findings", ""]
    for f in findings[:MAX_DETAILED_FINDINGS]:
        where = f"{f.file}:{f.line}" if f.line else f.file
        lines.append(f"### {f.finding_id} [{f.severity}] {f.kind}: {md_text(f.title)}")
        lines.append(f"- Location: {md_code(where)}" if where else "- Location: not reported")
        if f.rule:
            lines.append(f"- Rule: {md_text(f.rule)}")
        if f.ids:
            lines.append(f"- IDs: {md_text(', '.join(f.ids))}")
        lines.append(f"- Fix: {md_text(f.fix)}" if f.fix else "- Fix: no fix reported by the tool")
        if f.note:
            lines.append(f"- Note: {md_text(f.note)}")
        lines.append(f"- Found by: {', '.join(f.tools)}")
        lines.append("")
    rest = findings[MAX_DETAILED_FINDINGS:]
    if rest:
        lines += [
            f"## Remaining {len(rest)} finding(s), lower in the ranking",
            "",
            "Full detail for each is in `findings.json`.",
            "",
            "| ID | Severity | Kind | Location | Title |",
            "| --- | --- | --- | --- | --- |",
        ]
        for f in rest:
            where = f"{f.file}:{f.line}" if f.line else f.file
            lines.append(
                f"| {f.finding_id} | {f.severity} | {f.kind} | {md_code(md_cell(where))} | "
                f"{md_cell(f.title)} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_outputs(
    repo: Path,
    out: Path,
    statuses: list[ToolStatus],
    findings: list[Finding],
    filter_note: str = "",
    suppressions: list[str] | None = None,
) -> None:
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out.mkdir(parents=True, exist_ok=True)
    (out / "SECURITY-SCAN.md").write_text(
        render_markdown(repo, statuses, findings, generated, filter_note, suppressions)
    )
    payload = {
        "generated": generated,
        "repo": repo.name,
        "filter": filter_note,
        "suppression_files": suppressions or [],
        "tools": [s.__dict__ for s in statuses],
        "findings": [f.as_dict() for f in findings],
    }
    (out / "findings.json").write_text(json.dumps(payload, indent=2) + "\n")


def exit_for_threshold(findings: list[Finding], fail_on: str | None) -> int:
    if fail_on and any(RANK[f.severity] <= RANK[fail_on] for f in findings):
        return 1
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    statuses = detect()
    if args.json:
        print(json.dumps([s.__dict__ for s in statuses], indent=2))
        return 0
    for s in statuses:
        extra = s.version if s.status == "installed" else f"install: {s.detail}"
        print(f"{s.name:12} {s.role:22} {s.status:14} {extra}")
    return 0


def _selected(tools_arg: str | None) -> list[str]:
    if not tools_arg:
        return list(TOOLS)
    names = [t.strip() for t in tools_arg.split(",") if t.strip()]
    unknown = [n for n in names if n not in TOOLS]
    if unknown:
        raise SystemExit(
            f"error: unknown tool(s) {', '.join(unknown)}; choose from {', '.join(TOOLS)}"
        )
    return names


def _default_out(repo: Path) -> Path:
    """Default report directory: in the system temp directory, outside the repository.

    The directory is created with a random name and mode 0700, so another user of the machine
    cannot pre-create it or read the report. An existing directory is reused only when --out
    names it.

    Keeping reports out of the repository stops the next scan from reading the last one and
    keeps raw tool output, which can hold matched source lines, away from `git add`.
    """
    return Path(tempfile.mkdtemp(prefix=f"security-scan-{repo.name}-"))


def _warn_if_inside(repo: Path, out: Path) -> None:
    if out.is_relative_to(repo):
        print(
            f"warning: {out} is inside the repository. The next scan will read these files, and "
            "the raw tool output can contain matched source lines. Use --out outside the repo.",
            file=sys.stderr,
        )


def _changes_since(repo: Path, ref: str, mirror: Mirror | None) -> Changes:
    if mirror is not None:
        return changed_files(repo, mirror, ref)
    with tempfile.TemporaryDirectory(prefix="security-scan-mirror-") as scratch:
        return changed_files(repo, make_mirror(repo, Path(scratch)), ref)


def finish(
    repo: Path,
    out: Path,
    statuses: list[ToolStatus],
    findings: list[Finding],
    fail_on: str | None,
    changed_since: str | None = None,
    mirror: Mirror | None = None,
) -> int:
    findings = dedupe(findings)
    filter_note = ""
    if changed_since:
        try:
            changes = _changes_since(repo, changed_since, mirror)
        except ValueError as exc:
            print(f"error: --changed-since {changed_since}: {exc}", file=sys.stderr)
            return 2
        kept = [f for f in findings if in_changed_set(f, changes)]
        filter_note = (
            f"only findings in the {len(changes.files)} file(s) changed since {changed_since}, "
            f"or found in one of its {len(changes.commits)} commit(s); "
            f"{len(findings) - len(kept)} finding(s) elsewhere in the repository are not shown"
        )
        findings = number(kept)
    write_outputs(repo, out, statuses, findings, filter_note, find_suppression_files(repo))
    ran = [s for s in statuses if s.status == "ran"]
    print(f"report: {out / 'SECURITY-SCAN.md'}")
    print(f"findings: {out / 'findings.json'}")
    for s in statuses:
        if s.status != "ran":
            print(f"{s.name}: {s.status}" + (f" - {s.detail}" if s.detail else ""), file=sys.stderr)
    if not ran:
        print(
            "error: no scanner produced a result. Install at least one (see lines above) "
            "and run again.",
            file=sys.stderr,
        )
        return 2
    summary = ", ".join(
        f"{sum(1 for f in findings if f.severity == sev)} {sev}"
        for sev in SEVERITY_ORDER
        if any(f.severity == sev for f in findings)
    )
    print(f"summary: {summary or 'no findings'} (from {', '.join(s.name for s in ran)})")
    return exit_for_threshold(findings, fail_on)


def cmd_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: --repo {args.repo} is not a directory", file=sys.stderr)
        return 2
    out = Path(args.out).resolve() if args.out else _default_out(repo)
    _warn_if_inside(repo, out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    statuses: list[ToolStatus] = []
    findings: list[Finding] = []
    with tempfile.TemporaryDirectory(prefix="security-scan-mirror-") as scratch:
        mirror: Mirror | None = None
        mirror_problem = ""
        if find_git_root(repo) is not None:
            try:
                mirror = make_mirror(repo, Path(scratch))
            except ValueError as exc:
                mirror_problem = str(exc)
        for name in _selected(args.tools):
            tool = TOOLS[name]
            if not shutil.which(tool.binary):
                statuses.append(ToolStatus(name, tool.role, "not installed", detail=tool.install))
                continue
            reason = blocked_by_repo_config(name, repo)
            if reason:
                statuses.append(ToolStatus(name, tool.role, "skipped", detail=reason))
                continue
            status = run_tool(
                tool,
                repo,
                raw,
                args.semgrep_config,
                args.timeout,
                mirror=mirror,
                allow_remote=args.allow_remote_resolution,
            )
            if status.status == "ran":
                findings.extend(collect(tool, repo, raw, status))
                if name == "trivy" and not args.allow_remote_resolution:
                    status.detail = (
                        "vulnerabilities only, offline; the IaC scan resolves remote Terraform "
                        "modules and needs --allow-remote-resolution"
                    )
                if name == "gitleaks" and mirror_problem:
                    status.detail = f"history pass not run: {mirror_problem}"
            statuses.append(status)
        return finish(repo, out, statuses, findings, args.fail_on, args.changed_since, mirror)


def cmd_merge(args: argparse.Namespace) -> int:
    raw = Path(args.raw).resolve()
    if not raw.is_dir():
        print(f"error: --raw {args.raw} is not a directory of tool outputs", file=sys.stderr)
        return 2
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve() if args.out else _default_out(repo)
    statuses: list[ToolStatus] = []
    findings: list[Finding] = []
    for name, tool in TOOLS.items():
        if not list(raw.glob(f"{RAW_PREFIXES[name]}*.json")):
            statuses.append(ToolStatus(name, tool.role, "not run", detail="no raw output given"))
            continue
        status = ToolStatus(name, tool.role, "ran")
        findings.extend(collect(tool, repo, raw, status))
        statuses.append(status)
    return finish(repo, out, statuses, findings, args.fail_on, args.changed_since)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect", help="list scanners, whether installed, install hints")
    p_detect.add_argument("--json", action="store_true")
    p_detect.set_defaults(func=cmd_detect)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", default=".", help="repository to scan (default: current dir)")
        p.add_argument("--out", help="output directory (default: a new directory in the temp dir)")
        p.add_argument("--fail-on", choices=SEVERITY_ORDER[:4], help="exit 1 at or above this")
        p.add_argument(
            "--changed-since",
            metavar="REF",
            help="show only findings in files changed since REF branched off (for example "
            "origin/main); use it to review a pull request or merge request",
        )

    p_run = sub.add_parser("run", help="run installed scanners and write the merged report")
    common(p_run)
    p_run.add_argument("--tools", help="comma list; default is every tool in the registry")
    p_run.add_argument("--semgrep-config", default=DEFAULT_SEMGREP_CONFIG)
    p_run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    p_run.add_argument(
        "--allow-remote-resolution",
        action="store_true",
        help="let trivy run its IaC scan, which downloads remote Terraform modules, and drop "
        "its --offline-scan; off by default",
    )
    p_run.set_defaults(func=cmd_run)

    p_merge = sub.add_parser("merge", help="merge raw tool outputs without running anything")
    common(p_merge)
    p_merge.add_argument("--raw", required=True, help="directory holding <tool>*.json outputs")
    p_merge.set_defaults(func=cmd_merge)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
