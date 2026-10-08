"""The .personal-strings check in scripts/validate_skills.sh, run in a throwaway git repo.

The script is copied into the repo (it finds the pack as its own parent directory), `uv` is a
stub that succeeds, and CODEX_HOME holds no validator. The other checks therefore fail or
find nothing; each test reads only the lines the personal-strings check prints.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "validate_skills.sh"
SECRET = "Zorblax"  # an invented string, standing in for something private


class Pack:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPT, root / "scripts" / "validate_skills.sh")
        (root / "bin").mkdir()
        stub = root / "bin" / "uv"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        self.git("init", "-q")
        self.write(".gitignore", "ignored.md\n/bin/\n/codex-home/\n/.personal-strings\n")

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def track(self, name: str, text: str) -> None:
        self.write(name, text)
        self.git("add", name)

    def run(self) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.root / 'bin'}:/usr/bin:/bin",
            "HOME": str(self.root / "home"),
            "CODEX_HOME": str(self.root / "codex-home"),
        }
        return subprocess.run(
            ["/bin/bash", str(self.root / "scripts" / "validate_skills.sh")],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )


@pytest.fixture
def pack(tmp_path: Path) -> Pack:
    return Pack(tmp_path)


def test_without_a_personal_strings_file_the_check_is_skipped_not_failed(pack: Pack) -> None:
    done = pack.run()
    assert "skip: no .personal-strings file" in done.stdout
    assert "match .personal-strings" not in done.stderr


def test_a_file_with_only_comments_and_blank_lines_is_skipped(pack: Pack) -> None:
    pack.write(".personal-strings", "# nothing yet\n\n   \n")
    pack.track("notes.md", f"{SECRET} everywhere\n")
    done = pack.run()
    assert "skip: .personal-strings holds no strings" in done.stdout
    assert "notes.md" not in done.stderr


def test_a_tracked_file_that_holds_a_string_fails_with_a_count_and_never_the_string(
    pack: Pack,
) -> None:
    pack.write(".personal-strings", f"# private\n\n{SECRET}\n")
    pack.track("notes.md", f"one {SECRET.upper()}\nclean\ntwo {SECRET.lower()} here\n")
    pack.track("clean.md", "nothing to see\n")
    done = pack.run()
    assert done.returncode == 1
    assert "FAIL: notes.md: 2 line(s) match .personal-strings" in done.stderr
    assert "clean.md" not in done.stderr
    assert SECRET.lower() not in (done.stdout + done.stderr).lower()


def test_an_untracked_file_that_is_not_ignored_is_scanned_and_an_ignored_one_is_not(
    pack: Pack,
) -> None:
    pack.write(".personal-strings", f"{SECRET}\n")
    pack.write("draft.md", f"{SECRET}\n")
    pack.write("ignored.md", f"{SECRET}\n")
    done = pack.run()
    assert "FAIL: draft.md: 1 line(s)" in done.stderr
    assert "ignored.md" not in done.stderr
    # The strings file lists the string by definition; it is ignored by the pack's own rules.
    assert ".personal-strings:" not in done.stderr


def test_license_text_and_third_party_notices_are_not_scanned(pack: Pack) -> None:
    pack.write(".personal-strings", f"{SECRET}\n")
    pack.track("LICENSE.txt", f"{SECRET}\n")
    pack.track("skills/demo/LICENSE-MIT.txt", f"{SECRET}\n")
    pack.track("THIRD_PARTY_NOTICES.md", f"{SECRET}\n")
    done = pack.run()
    assert "ok: none of the .personal-strings appear" in done.stdout
    assert "LICENSE" not in done.stderr and "NOTICES" not in done.stderr


def test_a_symlink_is_not_counted_a_second_time(pack: Pack) -> None:
    pack.write(".personal-strings", f"{SECRET}\n")
    pack.track("scripts/shared.py", f"# {SECRET}\n")
    (pack.root / "link.py").symlink_to(pack.root / "scripts" / "shared.py")
    pack.git("add", "link.py")
    done = pack.run()
    assert "FAIL: scripts/shared.py: 1 line(s)" in done.stderr
    assert "link.py" not in done.stderr


def test_a_clean_pack_passes_and_says_so(pack: Pack) -> None:
    pack.write(".personal-strings", f"{SECRET}\n")
    pack.track("a.md", "fine\n")
    done = pack.run()
    assert "ok: none of the .personal-strings appear in the" in done.stdout
    assert "match .personal-strings" not in done.stderr


def test_the_strings_file_is_ignored_by_git_in_this_repo() -> None:
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/.personal-strings" in lines
