"""Run git on a repository you did not write, without letting its own config run programs.

A repository's `.git/config` can name programs git runs for you: `core.fsmonitor`, `gpg.program`
(and the `gpg.ssh.program`, `gpg.x509.program` forms), `core.hooksPath`, filter and textconv
drivers. Every script that reads a repo it was pointed at starts git through here:

    subprocess.run(git_argv(root, "ls-files", "-z"), env=git_env(), ...)

`git_argv` overrides the three program-running settings on the command line, where they win over
the repository's config, and turns the pager off. `git_env` drops the system config and any
`GIT_DIR`-style redirect, and never prompts. Add `--no-show-signature` to a `git log`, so a
`log.showSignature` in the repo's config does not run gpg either.

`isolated_git_env` is the stricter form for a scanner that keeps no trust in any config at all
(system and user config off too), used with the isolated mirror in security_scan.py.

Standard library only.
"""

from __future__ import annotations

import os
from pathlib import Path

# Settings a repository's config could use to make git start a program. `-c` outranks the
# repository's own config, so these hold whatever `.git/config` says.
HARDENED_CONFIG = (
    "core.fsmonitor=false",
    "gpg.program=false",
    "gpg.openpgp.program=false",
    "gpg.ssh.program=false",
    "gpg.x509.program=false",
    "core.hooksPath=/dev/null",
)

# Variables that would point git at some other repository or index than the one named.
REDIRECTS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def git_argv(root: Path | None, *args: str) -> list[str]:
    """`git` with no pager, the program-running settings off, and `-C root` when given."""
    argv = ["git", "--no-pager"]
    for setting in HARDENED_CONFIG:
        argv += ["-c", setting]
    if root is not None:
        argv += ["-C", str(root)]
    return [*argv, *args]


def git_env() -> dict[str, str]:
    """The caller's environment without redirects or system git config, never prompting. The
    user's own global config stays (it is theirs, and `safe.directory` lives there)."""
    env = {k: v for k, v in os.environ.items() if k not in REDIRECTS}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})
    return env


def isolated_git_env() -> dict[str, str]:
    """`git_env` with the user's config off too and every `GIT_CONFIG_*` override removed: the
    environment for every git process the security scan (or a scanner it runs) starts."""
    env = {k: v for k, v in git_env().items() if not k.startswith("GIT_CONFIG_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
    return env
