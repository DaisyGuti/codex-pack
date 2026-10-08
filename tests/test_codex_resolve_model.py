"""scripts/resolve_model.py and install.sh, driven as a user would run them.

Every run gets a throwaway CODEX_HOME and HOME, and the resolver runs with a PATH that
holds no `codex` and with BUNDLED_CODEX_APP pointed at a file that does not exist (a machine
with the desktop app installed has the real binary there), so nothing here can read the real
~/.codex or the real model catalog.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "resolve_model.py"
INSTALLER = REPO / "install.sh"

ALL_EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"]
NO_ULTRA = ALL_EFFORTS[:-1]


def _entry(
    slug: str,
    efforts: list[str],
    *,
    visibility: str = "list",
    description: str | None = None,
    priority: int | None = None,
    upgrade: dict[str, str] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "slug": slug,
        "visibility": visibility,
        "default_reasoning_level": efforts[0] if efforts else None,
        "supported_reasoning_levels": [{"effort": e, "description": ""} for e in efforts],
        "upgrade": upgrade,
    }
    if description is not None:
        entry["description"] = description
    if priority is not None:
        entry["priority"] = priority
    return entry


def _catalog(models: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "fetched_at": "2026-10-06T00:00:00Z",
        "client_version": "0.0.0",
        "models": [_entry(slug, efforts) for slug, efforts in models.items()],
    }


# The catalog as `codex debug models` printed it on 2026-10-08, trimmed to the fields the
# resolver reads: (slug, visibility, priority, description, efforts, upgrade).
_LIVE: list[tuple[str, str, int, str, list[str], dict[str, str] | None]] = [
    ("gpt-6.1-sol", "list", 1, "Latest workhorse model for coding and everyday work.",
     ALL_EFFORTS, None),
    ("gpt-6-astra", "list", 2, "Frontier intelligence for the most demanding work.",
     ALL_EFFORTS, None),
    ("gpt-6-sol", "list", 3, "Previous generation workhorse model.", ALL_EFFORTS, None),
    ("gpt-6-luna", "list", 4, "Fast and affordable model for easier tasks.", NO_ULTRA, None),
    ("gpt-reserve", "hide", 4, "Fast and affordable agentic coding model.", NO_ULTRA, None),
    ("gpt-5.6-sol", "list", 5, "Older generation workhorse model.", ALL_EFFORTS, None),
    ("gpt-5.6-terra", "list", 8, "Older balanced model for straightforward work.",
     ALL_EFFORTS, None),
    ("gpt-5.6-luna", "list", 9, "Older fast and efficient model.", NO_ULTRA, None),
    ("gpt-5.5", "hide", 13, "Legacy coding model.", ALL_EFFORTS[:4],
     {"model": "gpt-6.1-sol"}),
    ("codex-auto-review", "hide", 43, "Automatic approval review model for Codex.",
     NO_ULTRA, None),
]  # fmt: skip


def _live_entries() -> list[dict[str, Any]]:
    return [
        _entry(slug, efforts, visibility=vis, description=desc, priority=prio, upgrade=upgrade)
        for slug, vis, prio, desc, efforts, upgrade in _LIVE
    ]


def _described(*extra: dict[str, Any], drop: tuple[str, ...] = ()) -> dict[str, Any]:
    """The live catalog with some entries removed and some added."""
    entries = [e for e in _live_entries() if e["slug"] not in drop]
    return {"fetched_at": "2026-10-08T00:00:00Z", "client_version": "0.0.0",
            "models": [*extra, *entries]}  # fmt: skip


# Runs the script with its BUNDLED_CODEX_APP constant replaced: argv[1] is the script,
# argv[2] the path to use for the bundled binary, the rest are the script's own arguments.
_RUNNER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("resolve_model", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules["resolve_model"] = module  # @dataclass looks its module up here
spec.loader.exec_module(module)
module.BUNDLED_CODEX_APP = module.Path(sys.argv[2])
sys.exit(module.main(sys.argv[3:]))
"""


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("resolve_model_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


# A catalog shaped like today's account: astra, sol and luna, but no gpt-6.1-sol yet.
TODAY = {
    "gpt-6-astra": ALL_EFFORTS,
    "gpt-6-sol": ALL_EFFORTS,
    "gpt-6-luna": NO_ULTRA,
    "gpt-5.5": ["low", "medium", "high", "xhigh"],
}


class Sandbox:
    """A CODEX_HOME plus an environment in which no `codex` binary can be found."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "codex-home"
        self.home.mkdir()
        (root / "home").mkdir()
        (root / "empty-bin").mkdir()

    @property
    def env(self) -> dict[str, str]:
        return {
            "CODEX_HOME": str(self.home),
            "HOME": str(self.root / "home"),
            "PATH": str(self.root / "empty-bin"),
        }

    def write_cache(self, payload: object) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        (self.home / "models_cache.json").write_text(text, encoding="utf-8")

    def make_codex(self, body: str, name: str = "fake-codex") -> Path:
        binary = self.root / name
        binary.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        return binary

    def fake_codex(self, body: str) -> dict[str, str]:
        """An executable standing in for `codex`, reachable the way Codex sessions expose it."""
        return {**self.env, "CODEX_CLI_PATH": str(self.make_codex(body))}

    def run(
        self, *args: str, env: dict[str, str] | None = None, bundled: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        bundled = bundled or self.root / "no-such-bundled-codex"
        return subprocess.run(
            [sys.executable, "-c", _RUNNER, str(SCRIPT), str(bundled), *args],
            capture_output=True,
            text=True,
            env=env or self.env,
            check=False,
        )

    def resolve(
        self, *args: str, env: dict[str, str] | None = None, bundled: Path | None = None
    ) -> dict[str, Any]:
        done = self.run(*args, env=env, bundled=bundled)
        assert done.returncode == 0, done.stderr
        result: dict[str, Any] = json.loads(done.stdout)
        return result

    def agent(self, name: str, toml: str) -> str:
        path = self.root / f"{name}.toml"
        path.write_text(toml, encoding="utf-8")
        return str(path)


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


# --- resolving a tier -------------------------------------------------------------------


def test_workhorse_prefers_the_newest_listed_slug_when_the_account_has_it(box: Sandbox) -> None:
    box.write_cache(_catalog({**TODAY, "gpt-6.1-sol": ALL_EFFORTS}))
    result = box.resolve("workhorse")
    assert result["model"] == "gpt-6.1-sol"
    assert result["source"] == "models_cache"
    assert result["notes"] == []


def test_workhorse_falls_back_to_the_next_slug_and_says_so(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    result = box.resolve("workhorse")
    assert result["model"] == "gpt-6-sol"
    assert result["notes"] == ["gpt-6.1-sol not available on this account; using gpt-6-sol"]


@pytest.mark.parametrize(
    ("given", "tier", "model"),
    [
        ("fast", "fast", "gpt-6-luna"),
        ("model:fast", "fast", "gpt-6-luna"),
        ("Model:Fast", "fast", "gpt-6-luna"),
        ("workhorse", "workhorse", "gpt-6-sol"),
        ("model:workhorse", "workhorse", "gpt-6-sol"),
        ("frontier", "frontier", "gpt-6-astra"),
        ("model:frontier", "frontier", "gpt-6-astra"),
        ("haiku", "fast", "gpt-6-luna"),
        ("model:haiku", "fast", "gpt-6-luna"),
        ("sonnet", "workhorse", "gpt-6-sol"),
        ("model:sonnet", "workhorse", "gpt-6-sol"),
        ("opus", "frontier", "gpt-6-astra"),
        ("model:opus", "frontier", "gpt-6-astra"),
        ("Model:Opus", "frontier", "gpt-6-astra"),
    ],
)
def test_aliases_and_ticket_labels_resolve_to_their_tier(
    box: Sandbox, given: str, tier: str, model: str
) -> None:
    box.write_cache(_catalog(TODAY))
    result = box.resolve(given)
    assert (result["tier"], result["model"]) == (tier, model)


def test_an_unknown_tier_exits_2_and_lists_the_valid_values(box: Sandbox) -> None:
    done = box.run("turbo")
    assert done.returncode == 2
    valid_values = (
        "fast",
        "workhorse",
        "frontier",
        "haiku",
        "sonnet",
        "opus",
        "model:fast",
        "model:workhorse",
        "model:frontier",
        "model:haiku",
        "model:sonnet",
        "model:opus",
    )
    for valid in valid_values:
        assert valid in done.stderr


@pytest.mark.parametrize(
    "args", [[], ["workhorse", "--list"], ["--effort", "low"], ["--effort", "turbo", "fast"]]
)
def test_a_malformed_invocation_exits_2(box: Sandbox, args: list[str]) -> None:
    assert box.run(*args).returncode == 2


@pytest.mark.parametrize(
    ("tier", "effort"), [("frontier", "low"), ("workhorse", "medium"), ("fast", "high")]
)
def test_each_tier_starts_at_its_documented_effort(box: Sandbox, tier: str, effort: str) -> None:
    box.write_cache(_catalog(TODAY))
    result = box.resolve(tier)
    assert result["effort"] == effort
    assert not any("effort" in note for note in result["notes"])


def test_a_requested_effort_the_model_supports_is_used_as_is(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    assert box.resolve("frontier", "--effort", "xhigh")["effort"] == "xhigh"


def test_an_unsupported_effort_clamps_to_the_nearest_level_and_says_so(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    result = box.resolve("fast", "--effort", "ultra")
    assert result["effort"] == "max"
    assert result["supported_efforts"] == NO_ULTRA
    assert any("ultra" in note and "max" in note for note in result["notes"])


def test_a_tie_between_two_supported_levels_goes_to_the_lower_one(box: Sandbox) -> None:
    box.write_cache(_catalog({"gpt-6-luna": ["low", "high"]}))
    assert box.resolve("fast", "--effort", "medium")["effort"] == "low"


def test_a_tiers_default_effort_is_clamped_too_when_the_model_lacks_it(box: Sandbox) -> None:
    box.write_cache(_catalog({"gpt-6-luna": ["low", "medium"]}))
    result = box.resolve("fast")
    assert result["effort"] == "medium"
    assert any("default effort high" in note for note in result["notes"])


def test_a_real_catalog_with_no_model_for_the_tier_exits_3(box: Sandbox) -> None:
    box.write_cache(_catalog({"gpt-5.5": ["low", "medium"]}))
    done = box.run("frontier")
    assert done.returncode == 3
    assert "gpt-6-astra" in done.stderr
    assert "models_cache" in done.stderr
    assert done.stdout == ""


# --- picking the newest model per tier from the catalog -----------------------------------


def test_todays_real_catalog_resolves_every_tier_with_no_notes(box: Sandbox) -> None:
    box.write_cache(_described())
    result = box.resolve("--all")
    assert {t: result[t]["model"] for t in result} == {
        "frontier": "gpt-6-astra",
        "workhorse": "gpt-6.1-sol",
        "fast": "gpt-6-luna",
    }
    assert all(result[t]["notes"] == [] for t in result)


def test_a_new_release_in_a_tier_wins_with_no_edit_and_a_note_says_so(box: Sandbox) -> None:
    new = _entry(
        "gpt-6.2-sol",
        ALL_EFFORTS,
        description="Latest workhorse model for coding and everyday work.",
        priority=1,
    )
    box.write_cache(_described(new))
    result = box.resolve("workhorse")
    assert result["model"] == "gpt-6.2-sol"
    assert result["notes"] == [
        "catalog picks gpt-6.2-sol for tier workhorse; the hard-coded list leads with gpt-6.1-sol"
    ]
    assert box.resolve("--all")["workhorse"]["model"] == "gpt-6.2-sol"


def test_the_newest_version_beats_a_better_catalog_priority(box: Sandbox) -> None:
    newer = _entry("gpt-6.2-luna", NO_ULTRA, description="Fast and affordable model.", priority=40)
    box.write_cache(_described(newer))
    assert box.resolve("fast")["model"] == "gpt-6.2-luna"


def test_equal_versions_go_to_latest_then_to_the_lower_priority(box: Sandbox) -> None:
    plain = _entry("gpt-7-sol", ALL_EFFORTS, description="Workhorse model.", priority=1)
    latest = _entry("gpt-7-terra", ALL_EFFORTS, description="Latest workhorse.", priority=9)
    box.write_cache(_described(plain, latest))
    assert box.resolve("workhorse")["model"] == "gpt-7-terra"
    lower = _entry("gpt-7-nova", ALL_EFFORTS, description="Workhorse model.", priority=2)
    box.write_cache(_described(plain, lower))
    assert box.resolve("workhorse")["model"] == "gpt-7-sol"


@pytest.mark.parametrize("wording", ["Older generation", "Previous generation", "Legacy"])
def test_an_older_previous_or_legacy_description_is_never_picked(
    box: Sandbox, wording: str
) -> None:
    old = _entry("gpt-9-sol", ALL_EFFORTS, description=f"{wording} workhorse model.", priority=1)
    box.write_cache(_described(old))
    assert box.resolve("workhorse")["model"] == "gpt-6.1-sol"


def test_a_hidden_model_is_never_picked(box: Sandbox) -> None:
    hidden = _entry(
        "gpt-9-luna", NO_ULTRA, visibility="hide", description="Fast and affordable model."
    )
    box.write_cache(_described(hidden))
    assert box.resolve("fast")["model"] == "gpt-6-luna"


def test_a_model_the_catalog_is_upgrading_away_is_skipped(box: Sandbox) -> None:
    retiring = _entry(
        "gpt-6.3-sol",
        ALL_EFFORTS,
        description="Latest workhorse model for coding and everyday work.",
        priority=1,
        upgrade={"model": "gpt-6.1-sol"},
    )
    box.write_cache(_described(retiring))
    result = box.resolve("workhorse")
    assert result["model"] == "gpt-6.1-sol"
    assert result["notes"] == []


def test_an_unclassifiable_description_falls_back_to_the_hard_coded_list_and_says_so(
    box: Sandbox,
) -> None:
    # The new release words its description in a way that names no tier, and the catalog
    # holds no other current workhorse: the hard-coded list answers, and the odd one is flagged.
    odd = _entry("gpt-6.2-sol", ALL_EFFORTS, description="Balanced everyday model.", priority=1)
    box.write_cache(_described(odd, drop=("gpt-6.1-sol", "gpt-6-sol")))
    result = box.resolve("workhorse")
    assert result["model"] == "gpt-5.6-sol"  # the hard-coded list, via the catalog's membership
    assert (
        "unclassified visible model gpt-6.2-sol: its description names no tier" in result["notes"]
    )
    assert any("names no current model for tier workhorse" in n for n in result["notes"])


def test_a_catalog_without_descriptions_uses_the_hard_coded_lists_quietly(box: Sandbox) -> None:
    box.write_cache(_catalog({"gpt-6-sol": ALL_EFFORTS, "gpt-6.1-sol": ALL_EFFORTS}))
    result = box.resolve("workhorse")
    assert result["model"] == "gpt-6.1-sol"
    assert result["notes"] == []


def test_list_tiers_a_new_release_from_its_description(box: Sandbox) -> None:
    new = _entry("gpt-6.2-sol", ALL_EFFORTS, description="Latest workhorse model.", priority=1)
    box.write_cache(_described(new))
    line = next(r for r in box.run("--list").stdout.splitlines() if r.startswith("gpt-6.2-sol"))
    assert "workhorse" in line


def test_check_warns_that_an_agent_on_the_old_sol_is_stale_when_a_release_is_only_in_the_catalog(
    box: Sandbox,
) -> None:
    new = _entry("gpt-6.2-sol", ALL_EFFORTS, description="Latest workhorse model.", priority=1)
    box.write_cache(_described(new))
    path = box.agent("a", 'model = "gpt-6.1-sol"\n')
    done = box.run("--check", path)
    assert done.returncode == 0
    assert f"{path}: warning: stale: gpt-6.2-sol is now available for tier workhorse" in done.stdout


# --- where the catalog comes from -------------------------------------------------------


def test_with_no_catalog_anywhere_it_returns_the_first_preference_unverified(box: Sandbox) -> None:
    result = box.resolve("workhorse")
    assert result["source"] == "fallback"
    assert result["model"] == "gpt-6.1-sol"
    assert result["effort"] == "medium"
    assert any("unverified" in note for note in result["notes"])


def test_fallback_mode_never_exits_3(box: Sandbox) -> None:
    assert box.run("frontier").returncode == 0


@pytest.mark.parametrize("contents", ["{not json", "[]", '{"models": "nope"}', '{"models": []}'])
def test_a_corrupt_or_unexpected_cache_falls_through_instead_of_crashing(
    box: Sandbox, contents: str
) -> None:
    box.write_cache(contents)
    result = box.resolve("fast")
    assert result["source"] == "fallback"
    assert any("models_cache.json" in note for note in result["notes"])


def test_a_catalog_entry_missing_its_slug_or_levels_is_skipped(box: Sandbox) -> None:
    payload = _catalog({"gpt-6-luna": NO_ULTRA})
    odd_level = {"slug": "gpt-5.5", "supported_reasoning_levels": [{"effort": ["low"]}]}
    payload["models"] += [{"visibility": "list"}, "junk", _entry("gpt-6-astra", []), odd_level]
    box.write_cache(payload)
    assert box.resolve("fast")["model"] == "gpt-6-luna"
    assert box.run("frontier").returncode == 3


def test_the_codex_binary_is_asked_when_it_is_reachable_and_wins_over_the_cache(
    box: Sandbox,
) -> None:
    box.write_cache(_catalog({"gpt-5.6-sol": ALL_EFFORTS}))
    live = box.root / "live.json"
    live.write_text(json.dumps(_catalog({"gpt-6-sol": ALL_EFFORTS})), encoding="utf-8")
    env = box.fake_codex(f'[ "$1 $2" = "debug models" ] && /bin/cat "{live}"')
    result = box.resolve("workhorse", env=env)
    assert result["source"] == "codex_debug_models"
    assert result["model"] == "gpt-6-sol"


def test_a_codex_binary_that_fails_falls_through_to_the_cache(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    result = box.resolve("frontier", env=box.fake_codex("exit 1"))
    assert result["source"] == "models_cache"
    assert any("debug models" in note for note in result["notes"])


def test_the_desktop_apps_bundled_cli_is_used_when_nothing_else_is_reachable(
    box: Sandbox,
) -> None:
    box.write_cache(_catalog({"gpt-5.6-sol": ALL_EFFORTS}))  # the stale cache a Codex shell sees
    live = box.root / "live.json"
    live.write_text(json.dumps(_catalog(TODAY)), encoding="utf-8")
    bundled = box.make_codex(f'/bin/cat "{live}"', name="bundled-codex")
    result = box.resolve("frontier", "--effort", "low", bundled=bundled)
    assert result["source"] == "codex_debug_models"
    assert (result["model"], result["effort"]) == ("gpt-6-astra", "low")


def test_without_the_bundled_cli_a_codex_shell_falls_to_the_stale_cache(box: Sandbox) -> None:
    box.write_cache(_catalog({"gpt-5.6-sol": ALL_EFFORTS}))
    assert box.run("frontier").returncode == 3


class TestBinaryLookupOrder:
    """_codex_binary: PATH, then $CODEX_CLI_PATH, then the bundled app; only if runnable."""

    @staticmethod
    def _exe(path: Path) -> str:
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def test_path_beats_the_env_override_which_beats_the_bundled_app(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_script()
        (tmp_path / "bin").mkdir()
        on_path = self._exe(tmp_path / "bin" / "codex")
        env_cli = self._exe(tmp_path / "env-codex")
        bundled = Path(self._exe(tmp_path / "bundled-codex"))
        monkeypatch.setattr(module, "BUNDLED_CODEX_APP", bundled)
        monkeypatch.setenv("CODEX_CLI_PATH", env_cli)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        assert module._codex_binary() == on_path
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        assert module._codex_binary() == env_cli
        monkeypatch.delenv("CODEX_CLI_PATH")
        assert module._codex_binary() == str(bundled)

    def test_a_missing_or_non_executable_bundled_app_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_script()
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
        monkeypatch.setattr(module, "BUNDLED_CODEX_APP", tmp_path / "absent")
        assert module._codex_binary() is None
        plain = tmp_path / "plain-file"
        plain.write_text("not executable", encoding="utf-8")
        plain.chmod(0o644)
        monkeypatch.setattr(module, "BUNDLED_CODEX_APP", plain)
        assert module._codex_binary() is None
        monkeypatch.setattr(module, "BUNDLED_CODEX_APP", tmp_path)  # a directory
        assert module._codex_binary() is None


# --- --list -----------------------------------------------------------------------------


def test_list_shows_every_model_with_its_tier_and_efforts(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    done = box.run("--list")
    assert done.returncode == 0
    line = next(row for row in done.stdout.splitlines() if row.startswith("gpt-6-luna"))
    assert "fast" in line
    assert "low,medium,high,xhigh,max" in line
    assert "gpt-5.5" in done.stdout


# --- --check ----------------------------------------------------------------------------


def test_check_flags_an_unknown_slug_as_an_error(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    path = box.agent("a", 'model = "gpt-9-imaginary"\n')
    done = box.run("--check", path)
    assert done.returncode == 1
    assert f"{path}: error: unknown model 'gpt-9-imaginary'" in done.stdout


def test_check_flags_an_effort_the_model_does_not_support(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    path = box.agent("a", 'model = "gpt-6-luna"\nmodel_reasoning_effort = "ultra"\n')
    done = box.run("--check", path)
    assert done.returncode == 1
    assert f"{path}: error: effort 'ultra' is not supported by gpt-6-luna" in done.stdout


def test_check_warns_about_a_stale_slug_but_still_exits_0(box: Sandbox) -> None:
    box.write_cache(_catalog({**TODAY, "gpt-6.1-sol": ALL_EFFORTS}))
    path = box.agent("a", 'model = "gpt-6-sol"\nmodel_reasoning_effort = "medium"\n')
    done = box.run("--check", path)
    assert done.returncode == 0
    assert f"{path}: warning: stale: gpt-6.1-sol is now available for tier workhorse" in done.stdout


def test_check_is_quiet_about_a_current_slug_and_a_file_that_sets_neither_field(
    box: Sandbox,
) -> None:
    box.write_cache(_catalog(TODAY))
    current = box.agent("a", 'model = "gpt-6-sol"\nmodel_reasoning_effort = "high"\n')
    neither = box.agent("b", 'name = "reviewer"\ndescription = "reads code"\n')
    done = box.run("--check", current, neither)
    assert done.returncode == 0
    assert ": error:" not in done.stdout
    assert ": warning:" not in done.stdout
    assert "checked 2 file(s): 0 error(s), 0 warning(s)" in done.stdout


def test_check_reports_every_file_and_exits_1_if_any_has_an_error(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    bad = box.agent("bad", 'model = "nope"\n')
    good = box.agent("ok", 'model = "gpt-6-astra"\n')
    done = box.run("--check", good, bad)
    assert done.returncode == 1
    assert "checked 2 file(s): 1 error(s)" in done.stdout


def test_check_reports_a_file_that_is_not_valid_toml(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))
    path = box.agent("a", "model = = broken\n")
    done = box.run("--check", path)
    assert done.returncode == 1
    assert f"{path}: error: cannot read as TOML" in done.stdout


def test_check_without_a_catalog_says_so_and_does_not_judge(box: Sandbox) -> None:
    path = box.agent("a", 'model = "gpt-9-imaginary"\n')
    done = box.run("--check", path)
    assert done.returncode == 0
    assert "fallback" in done.stdout
    assert ": error:" not in done.stdout


# --- --all ------------------------------------------------------------------------------


def test_all_resolves_the_three_tiers_at_their_default_efforts_in_one_object(box: Sandbox) -> None:
    box.write_cache(_catalog({**TODAY, "gpt-6.1-sol": ALL_EFFORTS}))
    result = box.resolve("--all")
    assert set(result) == {"fast", "workhorse", "frontier"}
    assert [
        (result[t]["model"], result[t]["effort"]) for t in ("fast", "workhorse", "frontier")
    ] == [
        ("gpt-6-luna", "high"),
        ("gpt-6.1-sol", "medium"),
        ("gpt-6-astra", "low"),
    ]
    assert result["workhorse"]["tier"] == "workhorse"
    assert result["workhorse"]["source"] == "models_cache"


def test_all_gives_each_tier_its_own_fallback_and_notes(box: Sandbox) -> None:
    box.write_cache(_catalog(TODAY))  # no gpt-6.1-sol
    result = box.resolve("--all")
    assert result["workhorse"]["model"] == "gpt-6-sol"
    assert result["workhorse"]["notes"] == [
        "gpt-6.1-sol not available on this account; using gpt-6-sol"
    ]
    assert result["frontier"]["notes"] == []


def test_all_without_a_catalog_is_unverified_for_every_tier_and_still_exits_0(
    box: Sandbox,
) -> None:
    result = box.resolve("--all")
    assert {tier: result[tier]["source"] for tier in result} == dict.fromkeys(result, "fallback")
    assert result["fast"]["model"] == "gpt-6-luna"


def test_all_fails_as_a_whole_when_one_tier_has_no_model_and_prints_nothing_on_stdout(
    box: Sandbox,
) -> None:
    box.write_cache(_catalog({"gpt-6-luna": NO_ULTRA, "gpt-6-sol": ALL_EFFORTS}))  # no astra
    done = box.run("--all")
    assert done.returncode == 3
    assert "gpt-6-astra" in done.stderr
    assert done.stdout == ""


@pytest.mark.parametrize(
    "args",
    [
        ["--all", "fast"],
        ["--all", "--list"],
        ["--all", "--effort", "low"],
        ["--all", "--check", "x"],
    ],
)
def test_all_does_not_combine_with_another_mode_or_an_effort(box: Sandbox, args: list[str]) -> None:
    assert box.run(*args).returncode == 2


# --- install.sh -------------------------------------------------------------------------


class Pack:
    """A copy of the installer and resolver with its own skills/agents, so this repo's real
    skills/ directory (which the installer would otherwise link) is never involved. The
    copied resolver has the desktop app's path blanked, so no real Codex binary is run."""

    def __init__(self, box: Sandbox) -> None:
        self.box = box
        self.root = box.root / "codex-pack"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(INSTALLER, self.root / "install.sh")
        resolver = SCRIPT.read_text(encoding="utf-8")
        desktop_app = "/Applications/ChatGPT.app"
        assert desktop_app in resolver
        (self.root / "scripts" / "resolve_model.py").write_text(
            resolver.replace(desktop_app, str(box.root / "no-such-app")), encoding="utf-8"
        )
        (self.root / "skills" / "alpha").mkdir(parents=True)
        (self.root / "skills" / "alpha" / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
        (self.root / "agents").mkdir()
        self.agent_src.write_text('model = "gpt-6-sol"\n', encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# pack rules\n", encoding="utf-8")
        (self.root / "registry.example.md").write_text("# example registry\n", encoding="utf-8")

    @property
    def agent_src(self) -> Path:
        return self.root / "agents" / "alpha.toml"

    @property
    def agent(self) -> Path:
        """Where the installed copy of alpha lands."""
        return self.box.home / "agents" / "alpha.toml"

    @property
    def marker(self) -> str:
        return (
            "# Installed by codex-pack/install.sh from agents/alpha.toml. "
            "Edit the repo copy, then rerun install.sh."
        )

    def make_other_pack(self, name: str = "other-pack") -> Path:
        """A second pack checkout (install.sh + skills/ + AGENTS.md + agents/) beside this one."""
        other = self.box.root / name
        (other / "skills" / "alpha").mkdir(parents=True)
        (other / "skills" / "alpha" / "SKILL.md").write_text("# other alpha\n", encoding="utf-8")
        (other / "agents").mkdir()
        (other / "agents" / "alpha.toml").write_text('model = "other"\n', encoding="utf-8")
        (other / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (other / "AGENTS.md").write_text("# other rules\n", encoding="utf-8")
        return other

    def install(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**self.box.env, "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin"}
        return subprocess.run(
            ["/bin/bash", str(self.root / "install.sh"), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def tree(self) -> dict[str, str]:
        """Every path under the Codex home with what it is, to prove a run changed nothing."""
        out: dict[str, str] = {}
        for path in sorted(self.box.home.rglob("*")):
            if path.is_symlink():
                out[str(path)] = f"link:{os.readlink(path)}"
            elif path.is_file():
                out[str(path)] = f"{path.stat().st_mtime_ns}:{path.read_text(encoding='utf-8')}"
            else:
                out[str(path)] = "dir"
        return out


@pytest.fixture
def pack(box: Sandbox) -> Pack:
    return Pack(box)


def test_install_links_skills_and_agents_md_and_copies_agents_into_codex_home(pack: Pack) -> None:
    done = pack.install()
    assert done.returncode == 0, done.stdout + done.stderr
    home = pack.box.home
    assert (home / "skills" / "alpha").resolve() == (pack.root / "skills" / "alpha").resolve()
    assert (home / "AGENTS.md").is_symlink()
    assert (home / "AGENTS.md").read_text(encoding="utf-8") == "# pack rules\n"
    assert "linked:" in done.stdout
    # Codex refuses a symlinked agent, so this one is a real file.
    assert pack.agent.is_file() and not pack.agent.is_symlink()
    assert pack.agent.read_text(encoding="utf-8") == pack.marker + '\nmodel = "gpt-6-sol"\n'
    assert f"copied: {pack.agent}" in done.stdout


def test_an_installed_agent_is_still_valid_toml_for_codex(pack: Pack) -> None:
    import tomllib

    pack.install()
    assert tomllib.loads(pack.agent.read_text(encoding="utf-8")) == {"model": "gpt-6-sol"}


def test_install_twice_changes_nothing_the_second_time(pack: Pack) -> None:
    pack.install()
    before = pack.tree()
    again = pack.install()
    assert again.returncode == 0
    assert "already linked" in again.stdout
    assert f"already current: {pack.agent}" in again.stdout
    assert not any(
        line.split(":")[0] in {"linked", "copied", "updated"} for line in again.stdout.splitlines()
    )
    assert pack.tree() == before


def test_a_change_to_the_repo_agent_is_copied_on_the_next_install(pack: Pack) -> None:
    pack.install()
    pack.agent_src.write_text('model = "gpt-6-luna"\n', encoding="utf-8")
    done = pack.install()
    assert done.returncode == 0
    assert f"updated: {pack.agent}" in done.stdout
    assert pack.agent.read_text(encoding="utf-8").endswith('model = "gpt-6-luna"\n')


def test_a_local_edit_to_an_installed_copy_is_overwritten_because_it_carries_the_marker(
    pack: Pack,
) -> None:
    pack.install()
    pack.agent.write_text(pack.marker + '\nmodel = "edited"\n', encoding="utf-8")
    assert pack.install().returncode == 0
    assert pack.agent.read_text(encoding="utf-8") == pack.marker + '\nmodel = "gpt-6-sol"\n'


def test_the_old_symlink_install_is_replaced_by_a_copy(pack: Pack) -> None:
    (pack.box.home / "agents").mkdir(parents=True)
    pack.agent.symlink_to(pack.agent_src)
    done = pack.install()
    assert done.returncode == 0
    assert "replaced symlink with a copy" in done.stdout
    assert pack.agent.is_file() and not pack.agent.is_symlink()
    # Writing through the old link would have clobbered the repo's own file.
    assert pack.agent_src.read_text(encoding="utf-8") == 'model = "gpt-6-sol"\n'


def test_a_dangling_symlink_is_replaced_but_a_foreign_one_is_refused(pack: Pack) -> None:
    (pack.box.home / "agents").mkdir(parents=True)
    pack.agent.symlink_to(pack.box.root / "gone.toml")
    assert pack.install().returncode == 0
    assert pack.agent.is_file() and not pack.agent.is_symlink()

    pack.agent.unlink()
    elsewhere = pack.box.root / "mine.toml"
    elsewhere.write_text('model = "mine"\n', encoding="utf-8")
    pack.agent.symlink_to(elsewhere)
    done = pack.install()
    assert done.returncode == 1
    assert "refused:" in done.stdout
    assert pack.agent.is_symlink()


def test_a_regular_agent_without_the_marker_is_refused_and_left_intact(pack: Pack) -> None:
    (pack.box.home / "agents").mkdir(parents=True)
    pack.agent.write_text('name = "my own alpha"\n', encoding="utf-8")
    done = pack.install()
    assert done.returncode == 1
    assert f"refused: {pack.agent}" in done.stdout
    assert pack.agent.read_text(encoding="utf-8") == 'name = "my own alpha"\n'
    assert (pack.box.home / "skills" / "alpha").is_symlink()  # the rest still installed


def test_install_refuses_to_overwrite_a_real_skill_directory_and_installs_the_rest(
    pack: Pack,
) -> None:
    home = pack.box.home
    (home / "skills" / "alpha").mkdir(parents=True)
    (home / "skills" / "alpha" / "mine.md").write_text("keep me\n", encoding="utf-8")
    done = pack.install()
    assert done.returncode == 1
    assert "refused:" in done.stdout
    assert (home / "skills" / "alpha" / "mine.md").read_text(encoding="utf-8") == "keep me\n"
    assert not (home / "skills" / "alpha").is_symlink()
    assert pack.agent.is_file()


def test_install_leaves_a_non_empty_agents_md_alone_and_adopts_an_empty_one(pack: Pack) -> None:
    home = pack.box.home
    home.mkdir(exist_ok=True)
    (home / "AGENTS.md").write_text("", encoding="utf-8")
    assert pack.install().returncode == 0
    assert (home / "AGENTS.md").is_symlink()

    (home / "AGENTS.md").unlink()
    (home / "AGENTS.md").write_text("my own rules\n", encoding="utf-8")
    done = pack.install()
    assert done.returncode == 0
    assert "left alone" in done.stdout
    assert (home / "AGENTS.md").read_text(encoding="utf-8") == "my own rules\n"


def test_uninstall_removes_the_packs_links_and_agent_copies_and_nothing_else(pack: Pack) -> None:
    pack.install()
    home = pack.box.home
    elsewhere = pack.box.root / "elsewhere"
    elsewhere.mkdir()
    (home / "skills" / "foreign").symlink_to(elsewhere)
    (home / "skills" / "real").mkdir()
    (home / "agents" / "mine.toml").write_text('name = "mine"\n', encoding="utf-8")
    (home / "agents" / "other-link.toml").symlink_to(elsewhere)

    done = pack.install("--uninstall")

    assert done.returncode == 0
    assert not (home / "skills" / "alpha").exists()
    assert not pack.agent.exists()
    assert not (home / "AGENTS.md").is_symlink()
    assert (home / "skills" / "foreign").is_symlink()
    assert (home / "skills" / "real").is_dir()
    assert (home / "agents" / "mine.toml").read_text(encoding="utf-8") == 'name = "mine"\n'
    assert (home / "agents" / "other-link.toml").is_symlink()


def test_install_tolerates_an_empty_pack(pack: Pack) -> None:
    shutil.rmtree(pack.root / "skills")
    shutil.rmtree(pack.root / "agents")
    (pack.root / "AGENTS.md").unlink()
    (pack.root / "registry.example.md").unlink()
    done = pack.install()
    assert done.returncode == 0
    assert done.stdout.count("skipped:") == 4  # skills, agents, AGENTS.md, registry


def test_an_unknown_option_exits_2(pack: Pack) -> None:
    assert pack.install("--nope").returncode == 2


def test_two_modes_at_once_exit_2(pack: Pack) -> None:
    assert pack.install("--check", "--uninstall").returncode == 2
    assert not (pack.box.home / "skills").exists()


# --- install.sh --check -----------------------------------------------------------------


def test_check_on_a_fresh_home_reports_everything_missing_and_changes_nothing(pack: Pack) -> None:
    done = pack.install("--check")
    assert done.returncode == 1
    assert f"missing: {pack.agent} is not installed" in done.stdout
    assert f"missing: {pack.box.home / 'skills' / 'alpha'} is not linked" in done.stdout
    assert f"missing: {pack.box.home / 'AGENTS.md'} is not linked" in done.stdout
    assert not (pack.box.home / "agents").exists()
    assert not (pack.box.home / "skills").exists()


def test_check_after_an_install_is_clean_and_exits_0(pack: Pack) -> None:
    pack.install()
    before = pack.tree()
    done = pack.install("--check")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "everything is installed and current" in done.stdout
    assert pack.tree() == before


def test_check_reports_a_repo_change_as_drift_without_fixing_it(pack: Pack) -> None:
    pack.install()
    pack.agent_src.write_text('model = "gpt-6-luna"\n', encoding="utf-8")
    before = pack.tree()
    done = pack.install("--check")
    assert done.returncode == 1
    assert f"drift: {pack.agent} differs from {pack.agent_src}" in done.stdout
    assert pack.tree() == before


def test_check_reports_a_hand_edited_copy_and_a_regressed_symlink_as_drift(pack: Pack) -> None:
    pack.install()
    pack.agent.write_text(pack.marker + "\nedited\n", encoding="utf-8")
    assert "drift:" in pack.install("--check").stdout

    pack.agent.unlink()
    pack.agent.symlink_to(pack.agent_src)
    done = pack.install("--check")
    assert done.returncode == 1
    assert "is a symlink, which Codex refuses" in done.stdout


def test_check_reports_a_foreign_agent_and_a_skill_linked_elsewhere(pack: Pack) -> None:
    pack.install()
    pack.agent.unlink()
    pack.agent.write_text('name = "mine"\n', encoding="utf-8")
    skill = pack.box.home / "skills" / "alpha"
    skill.unlink()
    skill.symlink_to(pack.box.root)
    done = pack.install("--check")
    assert done.returncode == 1
    assert f"foreign: {pack.agent} was not installed by this pack" in done.stdout
    assert f"drift: {skill} points to {pack.box.root}" in done.stdout


def test_check_does_not_fail_on_an_agents_md_that_holds_the_users_own_content(pack: Pack) -> None:
    pack.install()
    agents_md = pack.box.home / "AGENTS.md"
    agents_md.unlink()
    agents_md.write_text("my own rules\n", encoding="utf-8")
    done = pack.install("--check")
    assert done.returncode == 0
    assert "left alone" in done.stdout


# --- a link into a different pack checkout -----------------------------------------------


def _link_into_other_pack(pack: Pack, other: Path) -> None:
    """Point the skill, AGENTS.md and agent in the Codex home at `other`, the way a machine
    that installed from another checkout looks."""
    home = pack.box.home
    (home / "skills").mkdir(parents=True)
    (home / "agents").mkdir()
    (home / "skills" / "alpha").symlink_to(other / "skills" / "alpha")
    (home / "AGENTS.md").symlink_to(other / "AGENTS.md")
    (home / "agents" / "alpha.toml").symlink_to(other / "agents" / "alpha.toml")


def test_links_into_another_pack_are_reported_and_refused_by_default(pack: Pack) -> None:
    other = pack.make_other_pack()
    _link_into_other_pack(pack, other)
    done = pack.install()
    home = pack.box.home
    assert done.returncode == 1
    assert done.stdout.count("another pack checkout") == 3
    assert str(other.resolve()) in done.stdout
    assert "--replace-other-pack" in done.stdout
    # Nothing was touched: the links still lead to the other pack, its agent file is intact.
    assert (home / "skills" / "alpha").resolve() == (other / "skills" / "alpha").resolve()
    assert (home / "AGENTS.md").resolve() == (other / "AGENTS.md").resolve()
    assert (home / "agents" / "alpha.toml").is_symlink()
    assert (other / "agents" / "alpha.toml").read_text(encoding="utf-8") == 'model = "other"\n'


def test_replace_other_pack_takes_over_the_links_and_leaves_the_other_pack_alone(
    pack: Pack,
) -> None:
    other = pack.make_other_pack()
    _link_into_other_pack(pack, other)
    done = pack.install("--replace-other-pack")
    home = pack.box.home
    assert done.returncode == 0, done.stdout + done.stderr
    assert (home / "skills" / "alpha").resolve() == (pack.root / "skills" / "alpha").resolve()
    assert (home / "AGENTS.md").resolve() == (pack.root / "AGENTS.md").resolve()
    assert pack.agent.is_file() and not pack.agent.is_symlink()
    assert pack.agent.read_text(encoding="utf-8") == pack.marker + '\nmodel = "gpt-6-sol"\n'
    # Replacing a link removes the link, never the file it led to.
    assert (other / "agents" / "alpha.toml").read_text(encoding="utf-8") == 'model = "other"\n'
    assert (other / "skills" / "alpha" / "SKILL.md").is_file()


def test_replace_other_pack_still_refuses_a_symlink_that_is_not_a_pack(pack: Pack) -> None:
    mine = pack.box.root / "my-skill"
    mine.mkdir()
    skill = pack.box.home / "skills" / "alpha"
    skill.parent.mkdir(parents=True)
    skill.symlink_to(mine)
    done = pack.install("--replace-other-pack")
    assert done.returncode == 1
    assert f"refused: {skill} is a symlink to {mine}" in done.stdout
    assert skill.resolve() == mine.resolve()


def test_check_reports_a_link_into_another_pack_and_changes_nothing(pack: Pack) -> None:
    other = pack.make_other_pack()
    _link_into_other_pack(pack, other)
    before = pack.tree()
    done = pack.install("--check")
    assert done.returncode == 1
    assert done.stdout.count("other-pack:") == 3
    assert pack.tree() == before


def test_uninstall_leaves_links_into_another_pack_alone(pack: Pack) -> None:
    other = pack.make_other_pack()
    _link_into_other_pack(pack, other)
    pack.install("--uninstall")
    assert (pack.box.home / "skills" / "alpha").is_symlink()
    assert (pack.box.home / "AGENTS.md").is_symlink()
    assert (pack.box.home / "agents" / "alpha.toml").is_symlink()


# --- the marker an installed agent carries ----------------------------------------------


def test_a_look_alike_marker_is_not_ours(pack: Pack) -> None:
    (pack.box.home / "agents").mkdir(parents=True)
    pack.agent.write_text("# Installed by somebody-else/install.sh\nmodel = 1\n", encoding="utf-8")
    done = pack.install()
    assert done.returncode == 1
    assert f"refused: {pack.agent}" in done.stdout


# --- registry.md --------------------------------------------------------------------------


def test_install_creates_registry_md_from_the_example_and_says_to_fill_it_in(pack: Pack) -> None:
    done = pack.install()
    assert done.returncode == 0, done.stdout + done.stderr
    registry = pack.root / "registry.md"
    assert registry.read_text(encoding="utf-8") == "# example registry\n"
    assert f"created: {registry} from registry.example.md" in done.stdout
    assert "replace the example rows with your own repos" in done.stdout


def test_install_never_overwrites_an_existing_registry_md(pack: Pack) -> None:
    registry = pack.root / "registry.md"
    registry.write_text("# my repos\n", encoding="utf-8")
    done = pack.install()
    assert done.returncode == 0
    assert f"already present: {registry}" in done.stdout
    assert registry.read_text(encoding="utf-8") == "# my repos\n"


def test_check_reports_a_missing_registry_md_but_does_not_create_it(pack: Pack) -> None:
    pack.install()
    (pack.root / "registry.md").unlink()
    done = pack.install("--check")
    assert done.returncode == 1
    assert f"missing: {pack.root / 'registry.md'}" in done.stdout
    assert not (pack.root / "registry.md").exists()


def test_check_is_clean_once_registry_md_exists(pack: Pack) -> None:
    pack.install()
    done = pack.install("--check")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "registry.md exists" in done.stdout


def test_uninstall_keeps_registry_md(pack: Pack) -> None:
    pack.install()
    pack.install("--uninstall")
    assert (pack.root / "registry.md").is_file()


def test_registry_md_is_gitignored_in_this_repo() -> None:
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/registry.md" in lines
