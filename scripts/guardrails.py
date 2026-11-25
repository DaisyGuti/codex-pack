#!/usr/bin/env python3
"""Guardrails: a Codex PreToolUse hook that blocks risky actions before they run.

Codex runs this script before every shell command (`Bash`, which covers unified exec too) and
every file edit (`apply_patch`), passing the call as JSON on stdin. The script exits 0 to let
the call through. It exits 2 with ONE line on stderr to block it; Codex hands that line to the
model as the reason, so the line says what was blocked and what to do instead.

How a shell command is read
    The command is lexed the way a shell reads it (quotes, escapes, `;` `&&` `||` `|`,
    subshells, heredocs, `$(...)`, backticks, `<(...)`), never matched as a raw substring.
    Wrappers (`sudo`, `env`, `timeout`, `xargs`, ...) are looked through, and the text of
    `sh -c '...'`, `eval`, `$(...)` and heredocs piped into a shell is analysed as a
    command line of its own. So `echo "git push --force origin main"` is text and passes,
    while `FOO=1 sudo -E bash -c 'git push -f origin main'` is a force-push and is blocked.

How a patch is read
    `apply_patch` sends the patch text (`*** Begin Patch`, `*** Add File:`, `*** Update File:`,
    `*** Delete File:`, `*** Move to:`). The content rules read the lines the patch adds; the
    tamper rule reads every path it adds, updates, deletes or moves.

Fail closed, as far as Codex allows
    A guard that cannot decide refuses. Malformed hook input, an internal error, or a
    command nested too deeply to inspect all exit 2. Codex has no setting that blocks when a
    hook itself fails, so a missing `python3` or a hook timeout lets the call through.

Opting out of a rule (people only)
    A person lists rule ids, one per line, in `${CODEX_HOME:-~/.codex}/guardrails-allow/<key>.txt`.
    The key names the repo: `<basename>-<16 hex>`, where the basename is the git root's last
    path component with anything outside `A-Za-z0-9._-` turned into `-`, and the hex is the
    first 16 digits of the SHA-256 of the git root's absolute path with symlinks resolved (the
    session directory outside a repo). `guardrails.py --allow-path [DIR]` prints the file.
    The waiver file lives outside the repo on purpose: a repo's own `.codex/guardrails-allow.txt`
    is ignored (a cloned repo must not switch rules off), and the block message says so.
    Nothing the model can set from inside a session turns a rule off: the allowlist is read by
    this process, never from the command or its environment, and writes to it (patches, shell
    redirects, sed -i, cp, mv, rm and friends) are blocked by the `guardrails-tamper` rule,
    which cannot itself be listed. The same rule guards this script and the git helper it
    imports, the hooks.json files that run it, the block log, and Codex settings that switch
    hooks off.

Logging
    Every block (and every time an allowlisted rule would have fired) appends one JSON
    line to `${CODEX_HOME:-~/.codex}/guardrails/blocks.log`. Secret values are redacted.

Known limits, stated plainly: this reads what is on the command line and in the patch. It does
not see inside a script file that a command runs, a shell variable's value, an alias, MCP tools,
or a program that shells out by itself. It is a seatbelt for reflexes and mistakes; a
determined person can get around it.

Standard library only, plus the pack's `scripts/safe_git.py` (standard library too), through
which every git call on the session repo runs. Written so the file also loads on Python 3.9,
the interpreter that ships with macOS command line tools, because the hook runs under whatever
`python3` is first on the PATH.

CLI (for the guardrails-help skill and for people):
    guardrails.py --list-rules
    guardrails.py --recent [N] [--data-dir DIR]
"""

from __future__ import annotations

import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path

# The session repo is one the model may have cloned, so git runs through the pack's hardened
# helper: its `.git/config` cannot make the hook start a program.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from safe_git import git_argv, git_env  # noqa: E402

# --------------------------------------------------------------------------------------
# The rules. One registry feeds the block message, --list-rules and the help skill.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    id: str
    summary: str  # what is blocked, as a noun phrase
    why: str  # why it is blocked
    instead: str  # what to do instead
    allowlistable: bool = True


RULES: list[Rule] = [
    Rule(
        "git-force-push-protected",
        "force-push to main, master or the repository's default branch",
        "it rewrites history that reviews, releases and teammates build on",
        "Push your own branch (`git push -u origin <branch>`) and open a pull request "
        "(`gh pr create`) or merge request (`glab mr create`).",
    ),
    Rule(
        "git-push-protected",
        "direct push to main, master or the repository's default branch",
        "the team lands work on those branches through reviewed pull or merge requests",
        "Push a feature branch (`git push -u origin <branch>`) and open a pull request "
        "(`gh pr create`) or merge request (`glab mr create`).",
    ),
    Rule(
        "git-no-verify",
        "skipping git hooks (`--no-verify`, `commit -n`, hooks path set to /dev/null)",
        "the hooks run the team's secret scan, lint and tests, and skipping them ships "
        "exactly what they exist to stop",
        "Fix what the hook reports and run the command again without `--no-verify`.",
    ),
    Rule(
        "pipe-to-shell",
        "running downloaded code unread (`curl ... | sh`, `bash <(curl ...)`, `eval $(curl ...)`)",
        "the script runs with your permissions before anyone has read it, and it can "
        "differ on every fetch",
        "Download to a file (`curl -fsSLo install.sh <url>`), read it, check its checksum "
        "or signature, then run it.",
    ),
    Rule(
        "tls-verify-off",
        "turning off TLS certificate verification",
        "it lets anyone on the network path read or change traffic that can carry "
        "credentials and sensitive data",
        "Trust the right CA instead (`curl --cacert`, `REQUESTS_CA_BUNDLE`, "
        "`NODE_EXTRA_CA_CERTS`, `git config http.sslCAInfo`) and fix the certificate chain.",
    ),
    Rule(
        "world-writable-chmod",
        "`chmod -R` that makes files writable by everyone",
        "any local user or compromised process could then change the files",
        "Grant only what is needed, for example `chmod -R u+rwX,g+rX <path>`, or fix "
        "ownership with `chown`.",
    ),
    Rule(
        "gcp-public-access",
        "granting `allUsers` or `allAuthenticatedUsers` on GCP IAM, buckets or services",
        "it exposes the resource to anyone on the internet (or anyone with a Google account)",
        "Grant a named principal (`user:`, `group:` or `serviceAccount:`), or use signed "
        "URLs or an authenticated invoker. Making something public is the user's decision.",
    ),
    Rule(
        "gcp-sa-key-create",
        "creating a user-managed service account key",
        "a downloaded key is a long-lived credential that leaks easily and is tied to no person",
        "Use impersonation (`--impersonate-service-account`), Workload Identity "
        "Federation or an attached service account; locally run "
        "`gcloud auth application-default login`.",
    ),
    Rule(
        "docker-privileged",
        "`--privileged` containers and mounting the Docker socket",
        "either one gives the container control of the host machine",
        "Add only the capability needed (`--cap-add`), or use a rootless build tool or a "
        "remote builder instead of mounting `docker.sock`.",
    ),
    Rule(
        "rm-rf-critical",
        "recursive delete of `/`, the home directory, the repository root or a parent of it",
        "it cannot be undone and takes the whole working tree with it",
        "Delete one named subdirectory (`rm -rf ./build`), or preview with `git clean -n` first.",
    ),
    Rule(
        "secret-in-content",
        "writing credential-shaped text (keys, tokens, key JSON) into a file",
        "committed secrets stay in history and reach everyone with repo access",
        "Read the value from the environment or a secret manager (GCP Secret Manager, CI "
        "variables) and write only a placeholder such as `YOUR_TOKEN_HERE`.",
    ),
    Rule(
        "secret-file-read",
        "reading secret files (`.env`, private keys, cloud credentials) into the conversation",
        "their contents would be sent to the model provider and kept in the transcript",
        "Do not print the file. Ask the user for the one value you need, check existence "
        "with `test -f`, or load it without printing (`set -a; . ./.env; set +a`).",
    ),
    Rule(
        "guardrails-tamper",
        "changing the guardrails allowlist, the hook script, hooks.json or the Codex settings "
        "that switch hooks off",
        "a rule that the agent can switch off mid-session is not a rule",
        "Ask the user to edit their waiver file under `${CODEX_HOME:-~/.codex}/guardrails-allow/` "
        "themselves, or to change the hook settings themselves.",
        allowlistable=False,
    ),
    Rule(
        "cannot-decide",
        "a call the guard could not inspect (malformed input, internal error, nesting too deep)",
        "a guard that cannot decide refuses",
        "Rephrase as simpler, separate commands. If the guard itself is broken, tell the user.",
        allowlistable=False,
    ),
]
RULE_BY_ID: dict[str, Rule] = {r.id: r for r in RULES}

ALLOW_FILE = "guardrails-allow.txt"
ALLOW_DIR = ".codex"  # <project>/.codex/guardrails-allow.txt is a repo-shipped waiver: ignored
ALLOW_STORE = "guardrails-allow"  # under CODEX_HOME: one <key>.txt per repo, a person's own
ALLOW_KEY_HEX = 16  # digits of the project path's SHA-256 in a waiver file's key
LOG_DIR = "guardrails"  # under CODEX_HOME
LOG_NAME = "blocks.log"
HOOKS_FILE = "hooks.json"
SKILL_SCRIPT = os.path.join("skills", "guardrails-help", "scripts", "guardrails.py")
LOG_MAX_BYTES = 1_000_000  # past this the log rolls to blocks.log.1 (one generation)
GIT_TIMEOUT_S = 2  # a git probe that hangs must not eat the hook's whole timeout
MAX_DEPTH = 6  # nested `sh -c` / `$(...)` layers followed; real commands never reach this
MAX_LINE_FOR_GENERIC = 4000  # longer lines skip the generic *_TOKEN= heuristic (minified files)


@dataclass(frozen=True)
class Finding:
    rule: str
    detail: str  # short, never contains a secret value


# --------------------------------------------------------------------------------------
# Shell lexer
# --------------------------------------------------------------------------------------

_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\+?=(.*)$", re.S)
_HEREDOC_RE = re.compile(r"<<(-?)[ \t]*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z0-9_.\-]+))")
# Reserved words that start or end a compound command. Skipped at command position so the
# command after `then` / `do` / `{` is seen as the command it is.
_KEYWORDS = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!"})
_KEYWORDS |= frozenset({"{", "}", "esac"})


@dataclass
class Word:
    text: str  # quotes and escapes removed; substitutions kept as written
    subs: list[str] = field(default_factory=list)  # bodies of $(..), `..`, <(..), >(..)
    procsub: bool = False  # the whole word is <(..) or >(..)


@dataclass
class Command:
    words: list[Word]
    assigns: list[tuple[str, Word]]  # leading NAME=value
    redirects: list[tuple[str, Word]]  # (operator, target)
    heredocs: list[str]  # bodies, in order
    pipeline: int  # commands joined by `|` share this id
    pos: int  # position inside the pipeline


def _heredoc_body(s: str, i: int, delim: str, strip_tabs: bool) -> tuple[str, int]:
    """One heredoc body starting at line start *i*: (text without the terminator, next index)."""
    start = i
    while i < len(s):
        end = s.find("\n", i)
        stop = len(s) if end == -1 else end
        line = s[i:stop].rstrip("\r")
        nxt = len(s) if end == -1 else end + 1
        if (line.lstrip("\t") if strip_tabs else line) == delim:
            return s[start:i], nxt
        i = nxt
    return s[start:], len(s)


def _skip_heredoc_bodies(s: str, i: int, delims: list[tuple[str, bool]]) -> int:
    """Index just past the heredoc bodies that start at line start *i*."""
    for delim, strip_tabs in delims:
        _, i = _heredoc_body(s, i, delim, strip_tabs)
    return i


def _scan_paren(s: str, i: int) -> tuple[str, int]:
    """Body of a `(...)` group whose text starts at *i*, and the index after the `)`.

    Aware of quotes, nested groups and heredoc bodies, because an apostrophe in a heredoc
    inside `$(cat <<'EOF' ... EOF)` (a normal way to write a commit message) must not be
    read as the start of a quote. An unterminated group ends at the end of the text.
    """
    depth = 1
    j = i
    pending: list[tuple[str, bool]] = []
    n = len(s)
    while j < n:
        ch = s[j]
        if ch == "\\":
            j += 2
        elif ch == "'":
            k = s.find("'", j + 1)
            j = n if k == -1 else k + 1
        elif ch == '"':
            j = _skip_dq(s, j + 1)
        elif ch == "`":
            _, j = _scan_backtick(s, j + 1)
        elif ch == "<" and s.startswith("<<", j) and not s.startswith("<<<", j):
            m = _HEREDOC_RE.match(s, j)
            if m:
                pending.append((m.group(2) or m.group(3) or m.group(4), m.group(1) == "-"))
                j = m.end()
            else:
                j += 2
        elif ch == "\n" and pending:
            j = _skip_heredoc_bodies(s, j + 1, pending)
            pending = []
        else:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return s[i:j], j + 1
            j += 1
    return s[i:], n


def _skip_dq(s: str, j: int) -> int:
    """Index after the closing `"` of a double-quoted string whose body starts at *j*."""
    n = len(s)
    while j < n:
        ch = s[j]
        if ch == "\\":
            j += 2
        elif ch == '"':
            return j + 1
        elif ch == "$" and s.startswith("$(", j):
            _, j = _scan_paren(s, j + 2)
        elif ch == "`":
            _, j = _scan_backtick(s, j + 1)
        else:
            j += 1
    return n


def _scan_backtick(s: str, i: int) -> tuple[str, int]:
    """Body of a backtick substitution starting at *i*, and the index after the closer."""
    j = i
    while j < len(s):
        if s[j] == "\\":
            j += 2
        elif s[j] == "`":
            return s[i:j].replace("\\`", "`"), j + 1
        else:
            j += 1
    return s[i:], len(s)


_ANSI_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "a": "\a"}


def _ansi_c(body: str) -> str:
    """Decode the escapes of a $'...' string (enough to undo `$'\\x2d\\x66'` tricks)."""
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\" or i + 1 >= len(body):
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", body[i + 2 :])
            if m:
                out.append(chr(int(m.group(), 16)))
                i += 2 + len(m.group())
                continue
        if nxt in "01234567":
            m = re.match(r"[0-7]{1,3}", body[i + 1 :])
            if m:
                out.append(chr(int(m.group(), 8)))
                i += 1 + len(m.group())
                continue
        out.append(_ANSI_ESC.get(nxt, nxt))
        i += 2
    return "".join(out)


class _Lexer:
    """Single pass over a command line producing `Command`s and `(` / `)` group markers."""

    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.items: list[Command | str] = []
        self.pipeline = 0
        self.pos = 0
        self.buf: list[str] | None = None
        self.subs: list[str] = []
        self.procsub = False
        self.words: list[Word] = []
        self.assigns: list[tuple[str, Word]] = []
        self.redirects: list[tuple[str, Word]] = []
        self.delims: list[tuple[str, bool]] = []
        self.pending_op: str | None = None
        self.waiting_heredocs: list[tuple[Command, list[tuple[str, bool]]]] = []

    # -- word and command bookkeeping ------------------------------------------------
    def add(self, text: str) -> None:
        if self.buf is None:
            self.buf = []
        self.buf.append(text)

    def end_word(self) -> None:
        if self.buf is None:
            return
        word = Word("".join(self.buf), self.subs, self.procsub)
        self.buf, self.subs, self.procsub = None, [], False
        op = self.pending_op
        if op is not None:
            self.pending_op = None
            if op.startswith("<<") and op != "<<<":
                self.delims.append((word.text, op == "<<-"))
            else:
                self.redirects.append((op, word))
            return
        if not self.words:
            m = _ASSIGN_RE.match(word.text)
            if m:
                self.assigns.append((m.group(1), Word(m.group(2), word.subs)))
                return
            if word.text in _KEYWORDS and not word.subs:
                return
        self.words.append(word)

    def end_command(self) -> None:
        self.end_word()
        if self.words or self.assigns or self.redirects or self.delims:
            cmd = Command(self.words, self.assigns, self.redirects, [], self.pipeline, self.pos)
            if self.delims:
                self.waiting_heredocs.append((cmd, self.delims))
            self.items.append(cmd)
        self.words, self.assigns, self.redirects, self.delims = [], [], [], []
        self.pending_op = None

    def next_pipeline(self) -> None:
        self.pipeline += 1
        self.pos = 0

    # -- the scan ---------------------------------------------------------------------
    def lex(self) -> list[Command | str]:
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c in " \t":
                self.end_word()
                self.i += 1
            elif c == "\n":
                self.end_command()
                self.next_pipeline()
                self.i += 1
                if self.waiting_heredocs:
                    self._read_heredocs()
            elif c == "\\":
                self._backslash()
            elif c == "'":
                end = s.find("'", self.i + 1)
                end = n if end == -1 else end
                self.add(s[self.i + 1 : end])
                self.i = end + 1
            elif c == '"':
                self._double_quote()
            elif c == "`":
                body, self.i = _scan_backtick(s, self.i + 1)
                self.subs.append(body)
                self.add("`" + body + "`")
            elif c == "$":
                self._dollar()
            elif c in "<>":
                self._redirect()
            elif c == "&":
                self._ampersand()
            elif c == "|":
                self.end_command()
                if s.startswith("||", self.i):
                    self.next_pipeline()
                    self.i += 2
                else:
                    self.pos += 1
                    self.i += 2 if s.startswith("|&", self.i) else 1
            elif c == ";":
                self.end_command()
                self.next_pipeline()
                self.i += 1
            elif c == "(":
                self.end_command()
                self.items.append("(")
                self.next_pipeline()
                self.i += 1
            elif c == ")":
                self.end_command()
                self.items.append(")")
                self.next_pipeline()
                self.i += 1
            elif c == "#" and self.buf is None:
                end = s.find("\n", self.i)
                self.i = n if end == -1 else end
            else:
                self.add(c)
                self.i += 1
        self.end_command()
        return self.items

    def _backslash(self) -> None:
        s = self.s
        if s.startswith("\\\n", self.i):
            self.i += 2  # line continuation
        elif self.i + 1 < len(s):
            self.add(s[self.i + 1])
            self.i += 2
        else:
            self.i += 1

    def _double_quote(self) -> None:
        s, n = self.s, len(self.s)
        if self.buf is None:
            self.buf = []  # "" is an (empty) argument
        j = self.i + 1
        while j < n:
            ch = s[j]
            if ch == "\\" and j + 1 < n:
                if s[j + 1] in '"\\$`':
                    self.add(s[j + 1])
                elif s[j + 1] != "\n":
                    self.add("\\" + s[j + 1])
                j += 2
            elif ch == '"':
                j += 1
                break
            elif ch == "$" and s.startswith("$((", j):
                end = self._arith_end(j)
                self.add(s[j:end])
                j = end
            elif ch == "$" and s.startswith("$(", j):
                body, nj = _scan_paren(s, j + 2)
                self.subs.append(body)
                self.add(s[j:nj])
                j = nj
            elif ch == "`":
                body, nj = _scan_backtick(s, j + 1)
                self.subs.append(body)
                self.add("`" + body + "`")
                j = nj
            else:
                self.add(ch)
                j += 1
        self.i = j

    def _arith_end(self, j: int) -> int:
        """Index after the `))` that closes `$((` at *j*."""
        _, end = _scan_paren(self.s, j + 2)  # `$(` then a `(...)` group inside it
        return end

    def _dollar(self) -> None:
        s, i = self.s, self.i
        if s.startswith("$((", i):
            end = self._arith_end(i)
            self.add(s[i:end])
            self.i = end
        elif s.startswith("$(", i):
            body, end = _scan_paren(s, i + 2)
            self.subs.append(body)
            self.add(s[i:end])
            self.i = end
        elif s.startswith("${", i):
            depth, j = 1, i + 2
            while j < len(s) and depth:
                depth += (s[j] == "{") - (s[j] == "}")
                j += 1
            self.add(s[i:j])
            self.i = j
        elif s.startswith("$'", i):
            end = i + 2
            while end < len(s) and s[end] != "'":
                end += 2 if s[end] == "\\" else 1
            self.add(_ansi_c(s[i + 2 : end]))
            self.i = end + 1
        elif s.startswith('$"', i):
            self.i += 1  # locale string: read as a plain double-quoted string
        else:
            self.add("$")
            self.i += 1

    def _ampersand(self) -> None:
        s = self.s
        if s.startswith("&&", self.i):
            self.end_command()
            self.next_pipeline()
            self.i += 2
        elif s.startswith("&>", self.i):
            self.end_word()
            self.pending_op = "&>>" if s.startswith("&>>", self.i) else "&>"
            self.i += len(self.pending_op)
        else:
            self.end_command()
            self.next_pipeline()
            self.i += 1

    def _redirect(self) -> None:
        s, i = self.s, self.i
        c = s[i]
        if s.startswith("(", i + 1):
            # process substitution <(...) or >(...)
            body, end = _scan_paren(s, i + 2)
            was_empty = self.buf is None
            self.subs.append(body)
            self.add(s[i:end])
            self.procsub = was_empty
            self.i = end
            return
        # `2>file`: a number glued to the operator names a file descriptor
        if self.buf is not None and not self.subs and "".join(self.buf).isdigit():
            self.buf = None
        else:
            self.end_word()
        for op in ("<<<", "<<-", "<<", "<&", "<>", "<", ">>", ">&", ">|", ">"):
            if op[0] == c and s.startswith(op, i):
                self.pending_op = op
                self.i = i + len(op)
                return

    def _read_heredocs(self) -> None:
        for cmd, delims in self.waiting_heredocs:
            for delim, strip_tabs in delims:
                body, self.i = _heredoc_body(self.s, self.i, delim, strip_tabs)
                cmd.heredocs.append(body)
        self.waiting_heredocs = []


def parse(text: str) -> list[Command | str]:
    """Lex a shell command line into commands and `(` / `)` markers."""
    return _Lexer(text).lex()


# --------------------------------------------------------------------------------------
# Wrapper handling and small argument helpers
# --------------------------------------------------------------------------------------

# name -> (short options with a value, long options with a value, leading positionals)
_WRAPPERS: dict[str, tuple[set[str], set[str], int]] = {
    "sudo": (
        {"-u", "-g", "-h", "-p", "-C", "-T", "-r", "-t", "-U", "-D", "-R"},
        {"--user", "--group", "--host", "--prompt", "--role", "--type", "--chdir"},
        0,
    ),
    "doas": ({"-u", "-C"}, set(), 0),
    "env": ({"-u", "-C", "-S"}, {"--unset", "--chdir", "--split-string"}, 0),
    "nice": ({"-n"}, {"--adjustment"}, 0),
    "ionice": ({"-c", "-n", "-p", "-P", "-u"}, set(), 0),
    "nohup": (set(), set(), 0),
    "time": ({"-f", "-o"}, {"--format", "--output"}, 0),
    "command": (set(), set(), 0),
    "builtin": (set(), set(), 0),
    "exec": ({"-a"}, set(), 0),
    "timeout": ({"-s", "-k"}, {"--signal", "--kill-after"}, 1),
    "xargs": ({"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-J"}, set(), 0),
    "watch": ({"-n"}, {"--interval"}, 0),
    "stdbuf": ({"-i", "-o", "-e"}, set(), 0),
    "setsid": (set(), set(), 0),
    "caffeinate": ({"-t", "-w"}, set(), 0),
    "flock": ({"-w", "-E"}, set(), 1),
}

_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash", "mksh", "fish", "csh", "tcsh"})
_INTERPRETERS = frozenset({"perl", "ruby", "node", "nodejs", "php", "deno", "bun"})
_PY_RE = re.compile(r"^python[0-9.]*$")
_DOWNLOADERS = frozenset({"curl", "wget", "fetch", "http", "https", "xh", "aria2c"})


def _base(token: str) -> str:
    return os.path.basename(token)


def unwrap(words: list[Word]) -> tuple[list[str], list[Word]]:
    """Strip `sudo`, `env`, `timeout`, ... from the front; return (assignments, rest)."""
    assigns: list[str] = []
    i = 0
    while i < len(words):
        spec = _WRAPPERS.get(_base(words[i].text))
        if spec is None:
            break
        name = _base(words[i].text)
        short, long_, positionals = spec
        i += 1
        while i < len(words):
            tok = words[i].text
            if tok == "--":
                i += 1
                break
            if name in ("env", "sudo") and _ASSIGN_RE.match(tok):
                assigns.append(tok)
                i += 1
            elif tok.startswith("-") and len(tok) > 1:
                i += 2 if (tok in short or tok in long_) else 1
            elif positionals > 0:
                positionals -= 1
                i += 1
            else:
                break
    return assigns, words[i:]


def _short_flags(token: str, value_letters: set[str]) -> tuple[list[str], bool]:
    """Letters of a short-option cluster up to the first one that takes a value.

    Returns (letters, value_is_next_token). In `-sSk` every letter is a flag; in `-mk` the
    `m` takes `k` as its value, so `k` is not a flag.
    """
    body = token[1:]
    letters: list[str] = []
    for idx, ch in enumerate(body):
        letters.append(ch)
        if ch in value_letters:
            return letters, idx == len(body) - 1
    return letters, False


def _is_option(tok: str) -> bool:
    return tok.startswith("-") and len(tok) > 1


def _git_parts(argv: list[str]) -> tuple[list[str], list[str], str | None, list[str], bool]:
    """Split `git [global options] <subcommand> <args>`.

    Returns (-c settings, -C directories, subcommand, args, repo_location_unknown). The last
    is true when --git-dir or --work-tree is used, which moves the repository somewhere
    this guard does not follow.
    """
    cfg: list[str] = []
    dirs: list[str] = []
    unknown = False
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok == "-c" and i + 1 < len(argv):
            cfg.append(argv[i + 1])
            i += 2
        elif tok == "-C" and i + 1 < len(argv):
            dirs.append(argv[i + 1])
            i += 2
        elif tok in ("--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"):
            unknown = unknown or tok in ("--git-dir", "--work-tree")
            i += 2
        elif tok.startswith(("--git-dir=", "--work-tree=")):
            unknown = True
            i += 1
        elif tok.startswith("-"):
            i += 1
        else:
            break
    sub = argv[i] if i < len(argv) else None
    return cfg, dirs, sub, argv[i + 1 :], unknown


# --------------------------------------------------------------------------------------
# Context: environment, git probes, allowlist
# --------------------------------------------------------------------------------------


def _real(path: str) -> str:
    return os.path.realpath(path)


def _both(path: str) -> set[str]:
    """A path as written (normalised) and with its symlinks resolved."""
    return {os.path.normpath(path), _real(path)}


class Ctx:
    """What a check needs to know about the machine; every git call is cached."""

    def __init__(self, payload: Mapping[str, object], environ: Mapping[str, str]) -> None:
        cwd = payload.get("cwd")
        self.environ = environ
        self.cwd = _real(cwd if isinstance(cwd, str) and cwd else os.getcwd())
        self.home = _real(environ.get("HOME") or os.path.expanduser("~"))
        self.codex_home = environ.get("CODEX_HOME") or os.path.join(self.home, ".codex")
        self.data_dir = os.path.join(self.codex_home, LOG_DIR)
        self._git: dict[tuple[str, ...], tuple[int, str] | None] = {}
        root = self.repo_root()
        self.project_dir = root or self.cwd
        # Files the tamper rule guards, as written and resolved: this script (also through the
        # skill's link to it), the user hooks.json and the pack file it links to.
        script = _real(__file__)
        self.pack_root = os.path.dirname(os.path.dirname(script))  # scripts/ sits in the pack
        self.guarded_files: set[str] = {script, os.path.join(self.pack_root, "hooks", HOOKS_FILE)}
        self.guarded_files.add(os.path.join(os.path.dirname(script), "safe_git.py"))  # it imports
        self.guarded_files |= _both(os.path.join(self.codex_home, SKILL_SCRIPT))
        self.guarded_files |= _both(os.path.join(self.codex_home, HOOKS_FILE))
        self.guarded_dirs: set[str] = _both(self.data_dir)  # the block log
        self.guarded_dirs |= _both(os.path.join(self.codex_home, ALLOW_STORE))  # the waivers
        # Where Codex keeps hook trust: deleting or truncating it untrusts every hook.
        self.config_files: set[str] = _both(os.path.join(self.codex_home, "config.toml"))

    def git(self, directory: str, *args: str) -> tuple[int, str] | None:
        key = (directory, *args)
        if key not in self._git:
            try:
                proc = subprocess.run(
                    git_argv(Path(directory), *args),
                    capture_output=True,
                    text=True,
                    timeout=GIT_TIMEOUT_S,
                    env=git_env(),
                    stdin=subprocess.DEVNULL,
                )
                self._git[key] = (proc.returncode, proc.stdout.strip())
            except (OSError, subprocess.SubprocessError):
                self._git[key] = None
        return self._git[key]

    def current_branch(self, directory: str) -> str | None:
        """Branch name; "" on a detached HEAD; None when git could not answer."""
        res = self.git(directory, "symbolic-ref", "--short", "-q", "HEAD")
        if res is None:
            return None
        code, out = res
        if code == 0:
            return out
        return "" if code == 1 else None

    def protected_branches(self, directory: str, remote: str | None) -> set[str]:
        """main and master, plus whatever the remote's HEAD points at (the default branch)."""
        names = {"main", "master"}
        for rem in {"origin", remote or "origin"}:
            res = self.git(directory, "symbolic-ref", "--short", "-q", f"refs/remotes/{rem}/HEAD")
            if res and res[0] == 0 and res[1].startswith(rem + "/"):
                names.add(res[1][len(rem) + 1 :])
        return names

    def repo_root(self, directory: str | None = None) -> str | None:
        res = self.git(directory or self.cwd, "rev-parse", "--show-toplevel")
        return _real(res[1]) if res and res[0] == 0 and res[1] else None

    def protected_roots(self, cwd: str | None = None) -> set[str]:
        """`/`, the home directory, the session's project, and the repo a command runs in."""
        roots = {"/", self.home, self.project_dir}
        root = self.repo_root(cwd) if cwd else None
        if root:
            roots.add(root)
        return roots

    def is_guarded(self, forms: Collection[str], *, parents: bool = False) -> bool:
        """Whether a path (given in its written and resolved forms) is one the tamper rule
        guards. With *parents*, a directory holding a guarded file counts too (rm -r, mv)."""
        for path in forms:
            norm = path.replace("\\", "/")
            if os.path.basename(norm) == ALLOW_FILE:
                return True
            if (
                norm.endswith("/" + ALLOW_DIR + "/" + HOOKS_FILE)
                or norm == ALLOW_DIR + "/" + HOOKS_FILE
            ):
                return True  # a project's hooks.json
            if path in self.guarded_files:
                return True
            if any(path == d or path.startswith(d.rstrip("/") + "/") for d in self.guarded_dirs):
                return True
            if parents and os.path.isabs(path):
                prefix = path.rstrip("/") + "/"
                guarded = self.guarded_files | self.guarded_dirs
                if any(g.startswith(prefix) for g in guarded):
                    return True
        return False


def allowlist_key(project_dir: str) -> str:
    """The waiver file's name for a project: `<basename>-<16 hex of sha256(absolute path)>`."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(project_dir.rstrip("/")))
    slug = slug.strip("-.") or "root"
    digest = hashlib.sha256(project_dir.encode("utf-8")).hexdigest()[:ALLOW_KEY_HEX]
    return f"{slug}-{digest}"


def allowlist_path(codex_home: str, project_dir: str) -> str:
    """`<codex_home>/guardrails-allow/<key>.txt`, outside every repo and under the tamper rule."""
    return os.path.join(codex_home, ALLOW_STORE, allowlist_key(project_dir) + ".txt")


def load_allowlist(codex_home: str, project_dir: str) -> set[str]:
    """Rule ids a person listed in the project's waiver file under *codex_home*. A file the
    repo ships is never read."""
    path = allowlist_path(codex_home, project_dir)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return set()
    ids = set()
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line in RULE_BY_ID and RULE_BY_ID[line].allowlistable:
            ids.add(line)
    return ids


# --------------------------------------------------------------------------------------
# Content patterns (credentials, TLS, containers)
# --------------------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private key",
        re.compile(
            r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----(?:\\r|\\n|\s)*[A-Za-z0-9+/]{40}"
        ),
    ),
    ("AWS access key ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "AWS secret access key",
        re.compile(r"(?i)aws_?secret_?access_?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40}\b"),
    ),
    (
        "GitHub token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    ),
    (
        "GitLab token",
        re.compile(r"\bgl(?:pat|oas|dt|rtr|rt|cbt|ptt|ft|imt|agent|soat|ffct)-[A-Za-z0-9_\-]{20,}"),
    ),
    (
        "Slack token",
        re.compile(r"\b(?:xox[abeoprs]-[A-Za-z0-9\-]{10,}|xapp-\d-[A-Za-z0-9\-]{10,})"),
    ),
    (
        "Slack webhook URL",
        re.compile(r"https://hooks\.slack\.com/(?:services|workflows)/[A-Za-z0-9/_\-]{20,}"),
    ),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Google OAuth client secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{20,}")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
]
_SA_TYPE_RE = re.compile(r'"type"\s*:\s*"service_account"')
_SA_KEY_RE = re.compile(r'"private_key(?:_id)?"\s*:')

# NAME = value, where NAME contains a secret-ish word. The lookbehind makes the scan start
# only at the beginning of an identifier, which keeps it linear on long base64 runs.
_GENERIC_RE = re.compile(
    r"""(?<![A-Za-z0-9_.\-])
    (?P<name>[A-Za-z0-9_.\-]*?(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_\-]?KEY|PRIVATE[_\-]?KEY
        |ACCESS[_\-]?KEY|CREDENTIALS?|AUTH[_\-]?KEY)[A-Za-z0-9_.\-]*)
    ["']?\s*(?::=|=|:)\s*["']?
    (?P<value>[^\s"'`,;)\]}]{20,})""",
    re.I | re.X,
)
# Names ending in these hold a reference or a setting.
_NON_SECRET_SUFFIXES = (
    "_name", "_id", "_path", "_file", "_url", "_uri", "_endpoint", "_arn", "_ref", "_version",
    "_env", "_length", "_ttl", "_expiry", "_expires", "_type", "_header", "_prefix", "_dir",
)  # fmt: skip
_PLACEHOLDER_WORDS = (
    "example", "changeme", "change-me", "change_me", "your", "xxxx", "placeholder", "dummy",
    "sample", "redacted", "todo", "fake", "insert", "replace", "foobar", "12345", "abcdef",
)  # fmt: skip
_SEPARATED_WORDS_RE = re.compile(r"^[a-z]+(?:[-_.][a-z0-9]+)+$")


def _entropy(value: str) -> float:
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum(c / len(value) * math.log2(c / len(value)) for c in counts.values())


def _looks_like_secret_value(value: str) -> bool:
    low = value.lower()
    if value[0] in "$<{%(/.~@" or low.startswith(("http://", "https://")):
        return False  # reference, template, path or URL
    if any(w in low for w in _PLACEHOLDER_WORDS) or len(set(value)) < 8:
        return False
    if _SEPARATED_WORDS_RE.match(value):
        return False  # my-service-name-2 is an identifier
    has_digit = any(c.isdigit() for c in value)
    has_alpha = any(c.isalpha() for c in value)
    if not (has_digit and has_alpha):
        return False
    hexish = re.fullmatch(r"[0-9a-fA-F]+", value) is not None
    return _entropy(value) >= (3.2 if hexish and len(value) >= 32 else 3.5)


def is_placeholder_name(name: str) -> bool:
    """`.env.example`, `config.sample.yaml`, `example.env`: files meant to hold placeholders."""
    parts = name.lower().split(".")
    return any(p in ("example", "sample", "template", "dist", "tmpl") for p in parts)


def scan_secrets(text: str, filename: str = "") -> list[str]:
    """Kinds of credential-shaped text in *text* (never the values themselves)."""
    kinds: list[str] = []
    for kind, pattern in _SECRET_PATTERNS:
        for m in pattern.finditer(text):
            if "EXAMPLE" not in m.group().upper():
                kinds.append(kind)
                break
    if _SA_TYPE_RE.search(text) and _SA_KEY_RE.search(text):
        kinds.append("GCP service account key")
    if not (filename and is_placeholder_name(os.path.basename(filename))):
        for line in text.split("\n"):
            if len(line) > MAX_LINE_FOR_GENERIC:
                continue
            for m in _GENERIC_RE.finditer(line):
                if m.group("name").lower().endswith(_NON_SECRET_SUFFIXES):
                    continue
                if _looks_like_secret_value(m.group("value")):
                    kinds.append("secret assignment (NAME=value)")
                    break
            if kinds and kinds[-1] == "secret assignment (NAME=value)":
                break
    return kinds


def redact(text: str) -> str:
    """Blank out credential-shaped text so a log line never stores it."""
    for _, pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return _GENERIC_RE.sub(
        lambda m: (
            m.group().replace(m.group("value"), "[redacted]")
            if _looks_like_secret_value(m.group("value"))
            else m.group()
        ),
        text,
    )


# Codex settings that stop hooks from running: the `hooks` feature (and its old alias
# `codex_hooks`) set false, the per-hook trust and enabled state Codex keeps under
# `[hooks.state."<key>"]` in config.toml, and the managed-only switch.
_SETTINGS_FILES = ("config.toml",)
_HOOK_OFF_RE = re.compile(
    r"(?<![\w-])(?:codex_)?hooks\s*=\s*false\b|hooks\.state|trusted_hash|allow_managed_hooks_only"
)
_HOOK_STATE_OFF_RE = re.compile(r"(?<![\w-])enabled\s*=\s*false\b")
_DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt", ".adoc")

_TLS_CONTENT = [
    re.compile(p)
    for p in (
        r"\bverify(?:_ssl)?\s*=\s*False\b",
        r"\bssl\._create_unverified_context\b",
        r"\bssl\.CERT_NONE\b",
        r"\bcheck_hostname\s*=\s*False\b",
        r"\brejectUnauthorized\s*:\s*false\b",
        r"\bNODE_TLS_REJECT_UNAUTHORIZED\s*[=:]\s*[\"']?0\b",
        r"\bInsecureSkipVerify\s*:\s*true\b",
        r"\bCURLOPT_SSL_VERIFY(?:PEER|HOST)\W+(?i:false)\b|\bCURLOPT_SSL_VERIFY(?:PEER|HOST)\W+0\b",
        r"(?i:\bsslVerify\s*=\s*false\b)",  # git config keys ignore case
        r"\bstrict-ssl\s*=\s*false\b",
        r"\bPYTHONHTTPSVERIFY\s*=\s*0\b",
        r"\bGIT_SSL_NO_VERIFY\b",
        r"\binsecure-skip-tls-verify\s*:\s*true\b",
    )
]
_DOCKER_CONTENT = [
    re.compile(p)
    for p in (
        r"(?<![\w-])--privileged\b(?!=false)",
        r"[\"']?\bprivileged[\"']?\s*[:=]\s*true\b",
        r"docker\.sock\s*:",
        r":(?!//)/\S*docker\.sock",
        r"(?:source|src)=\S*docker\.sock",
    )
]


def _code_lines(text: str) -> str:
    """Drop full-line comments so a warning in a comment does not trip a code pattern."""
    return "\n".join(
        ln for ln in text.split("\n") if not ln.lstrip().startswith(("#", "//", "*", "/*"))
    )


def content_findings(text: str, path: str) -> list[Finding]:
    """Rules that read what is being written, for Write/Edit and for shell writes."""
    findings: list[Finding] = []
    where = os.path.basename(path) if path else "a file"
    for kind in scan_secrets(text, path):
        findings.append(Finding("secret-in-content", f"writing a {kind} into {where}"))
    if not path.lower().endswith(_DOC_SUFFIXES):
        code = _code_lines(text)
        if any(p.search(code) for p in _TLS_CONTENT):
            findings.append(Finding("tls-verify-off", f"writing TLS verification off into {where}"))
        if any(p.search(code) for p in _DOCKER_CONTENT):
            findings.append(
                Finding(
                    "docker-privileged",
                    f"writing a privileged container or socket mount into {where}",
                )
            )
    return findings


# --------------------------------------------------------------------------------------
# Secret file paths
# --------------------------------------------------------------------------------------

_KEY_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".p8", ".ppk")
_SECRET_NAMES = frozenset(
    {".netrc", "_netrc", ".git-credentials", ".pgpass", ".pypirc", ".dockercfg"}
)
_SECRET_PATH_SUFFIXES = (
    "/.aws/credentials",
    "/.kube/config",
    "/.docker/config.json",
    "/.config/gh/hosts.yml",
    "/.config/glab-cli/config.yml",
)
_PUBLIC_SSH = ("known_hosts", "config", "authorized_keys")


def is_secret_path(path: str, home: str) -> bool:
    """Whether reading *path* would put credentials into the conversation."""
    if path.startswith("~/"):
        path = home + path[1:]
    for var in ("$HOME", "${HOME}"):
        if path.startswith(var + "/"):
            path = home + path[len(var) :]
    norm = path.replace("\\", "/")
    name = os.path.basename(norm).lower()
    if not name or is_placeholder_name(name):
        return False
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return True
    if name in _SECRET_NAMES or name.endswith(_KEY_SUFFIXES):
        return True
    if name == ".npmrc" and os.path.dirname(norm) == home.replace("\\", "/"):
        return True  # only the home-level one; a project .npmrc is usually registry config
    if re.fullmatch(r"id_(?:rsa|dsa|ecdsa|ed25519)(?:_.*)?", name) and not name.endswith(".pub"):
        return True
    if name.endswith(".json") and re.search(
        r"service[-_]?account|credentials|sa[-_]key|client[-_]secret", name
    ):
        return True
    if any(norm.endswith(s) for s in _SECRET_PATH_SUFFIXES):
        return True
    if "/gcloud/legacy_credentials/" in norm:
        return True
    if "/gcloud/" in norm and (
        "credentials" in name or name in ("access_tokens.db", "credentials.db")
    ):
        return True
    return "/.ssh/" in norm and not (name.endswith(".pub") or name in _PUBLIC_SSH)


# --------------------------------------------------------------------------------------
# The Bash analyser
# --------------------------------------------------------------------------------------


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_READERS = _words(
    "cat bat batcat less more most head tail tac nl od xxd hexdump strings base64 sed awk gawk "
    "cut sort uniq tr paste column fold fmt rev diff grep egrep fgrep zgrep rg ag ack jq yq"
)
_GREP_FAMILY = frozenset({"grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack"})
_GIT_READERS = frozenset({"show", "diff", "blame", "cat-file", "grep"})
_WRITERS = _words("rm mv cp tee touch ln truncate dd install rsync chmod chown unlink shred")
_PATCH_COMMANDS = frozenset({"apply_patch", "applypatch"})
_INLINE_CODE = frozenset({"python", "python3", "perl", "ruby", "node", "nodejs", "php"})
_CONTENT_PRODUCERS = frozenset(
    {"echo", "printf", "tee", "cat", "sed", "awk", "perl", "ruby", "node", "dd"}
)
_MATCH_ALL_GLOBS = frozenset({"*", ".*", ".[!.]*", ".??*", "[!.]*", ".[^.]*"})
_SYSTEM_DIR_NAMES = _words(
    "/bin /boot /dev /etc /lib /lib64 /opt /proc /root /sbin /srv /sys /usr /var /System "
    "/Library /Applications /private /Volumes /home /Users"
)
# Compared after symlinks are resolved, so macOS's /var -> /private/var counts too.
_SYSTEM_DIRS = frozenset(_SYSTEM_DIR_NAMES) | frozenset(
    os.path.realpath(d) for d in _SYSTEM_DIR_NAMES
)
_CURL_VALUE_SHORT = set("AbcCdDeEFHKmoPQrTuUwxXyYzt")
_CURL_VALUE_LONG = _words(
    "--header --data --data-raw --data-binary --data-urlencode --form --user --user-agent "
    "--request --referer --cookie --cookie-jar --cert --key --cacert --capath --proxy --output "
    "--max-time --connect-timeout --retry --retry-delay --write-out --upload-file --url "
    "--config --range --resolve --oauth2-bearer --json --dump-header --limit-rate"
)
_FALSEY = frozenset({"false", "0", "no", "off"})
_TLS_ENV_RE = re.compile(
    r"(?:^|[=,\s])(GIT_SSL_NO_VERIFY|NODE_TLS_REJECT_UNAUTHORIZED|PYTHONHTTPSVERIFY"
    r"|NPM_CONFIG_STRICT_SSL)=([^,\s]*)",
    re.I,
)
_PUBLIC_MEMBER_RE = re.compile(
    r"^(?:--[\w-]+=)?(?:entity=)?all(?:authenticated)?users(?::[\w.\-]+)?(?:,.*)?$", re.I
)
_PUBLIC_ACL = frozenset({"public-read", "public-read-write", "publicread", "publicreadwrite"})
_VAR_RE = re.compile(r"\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})")
_BRANCH_SUBST_RE = re.compile(
    r"(?:\$\(|`)\s*git\s+(?:branch\s+--show-current|rev-parse\s+--abbrev-ref\s+HEAD"
    r"|symbolic-ref\s+(?:-q\s+)?(?:--short\s+)?(?:-q\s+)?HEAD)\s*(?:\)|`)"
)
_SYMBOLIC_MODE_RE = re.compile(r"^([ugoa]*)([-+=])([rwxXst]*|[ugo])$")


class Analyzer:
    """Walks one command line (and the command lines nested inside it)."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx
        self.findings: list[Finding] = []
        # Shell variables assigned earlier in this command line (`BR=main; git push origin $BR`)
        self.vars: dict[str, str] = {}
        # Branch a repo is on after a `git checkout` / `git switch` earlier in the same line
        self.sim_branch: dict[str, str | None] = {}

    def add(self, rule: str, detail: str) -> None:
        finding = Finding(rule, detail)
        if finding not in self.findings:
            self.findings.append(finding)

    # -- driver -----------------------------------------------------------------------
    def run(self, line: str, cwd: str | None, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            self.add("cannot-decide", "a command nested too deeply to inspect")
            return
        items = parse(line)
        pipelines: dict[int, list[Command]] = {}
        stack: list[str | None] = []
        for item in items:
            if item == "(":
                stack.append(cwd)
            elif item == ")":
                cwd = stack.pop() if stack else cwd
            elif isinstance(item, Command):
                pipelines.setdefault(item.pipeline, []).append(item)
                cwd = self.command(item, cwd, depth)
        for stages in pipelines.values():
            self.pipeline_rules(stages, cwd, depth)
        self.write_rules(items, line)

    def command(self, cmd: Command, cwd: str | None, depth: int) -> str | None:
        # nested command lines inside substitutions run first, with the cwd as it is now
        for word in self._all_words(cmd):
            for sub in word.subs:
                self.run(sub, cwd, depth + 1)
        cmd = self._expanded(cmd, cwd)
        wrapper_assigns, words = unwrap(cmd.words)
        assigns = [f"{n}={w.text}" for n, w in cmd.assigns] + wrapper_assigns
        if not cmd.words:  # a bare `NAME=value` sets a shell variable for later commands
            for n, w in cmd.assigns:
                self.vars[n] = w.text
        self.check_tls_assignments(assigns, [w.text for w in words])
        self.check_tamper_redirects(cmd, cwd)
        if not words:
            return cwd
        argv = [w.text for w in words]
        name = _base(argv[0])

        if name in ("export", "declare", "typeset", "readonly", "local"):
            for arg in argv[1:]:
                m = _ASSIGN_RE.match(arg)
                if m:
                    self.vars[m.group(1)] = m.group(2)
        elif name == "unset":
            for arg in argv[1:]:
                self.vars.pop(arg, None)
        if name in ("cd", "pushd"):
            return self._cd(argv, cwd)
        if name == "popd":
            return None

        self._nested_shells(argv, cmd, cwd, depth)
        if name == "git":
            self.check_git(argv, assigns, cwd)
        elif name == "rm":
            self.check_rm(argv, cwd)
        elif name == "chmod":
            self.check_chmod(argv)
        elif name in ("gcloud", "gsutil"):
            self.check_gcloud(name, argv)
        elif name in ("docker", "podman"):
            self.check_docker(argv)
        elif name in ("gh", "glab"):
            self.check_forge_api(argv)
        self.check_tls_command(name, argv)
        self.check_downloaded_code(name, argv, words, cmd)
        self.check_secret_read(name, argv, cmd, cwd)
        self.check_tamper_command(name, argv, cwd)
        if name in _PATCH_COMMANDS:
            self.check_patch_command(argv, cmd, cwd)
        return cwd

    # -- variables and branch simulation -----------------------------------------------
    def branch_now(self, directory: str) -> str | None:
        """Branch *directory* is on, counting earlier checkouts in this command line."""
        if directory in self.sim_branch:
            return self.sim_branch[directory]
        return self.ctx.current_branch(directory)

    def expand(self, text: str, cwd: str | None) -> str:
        """Fill in variables set earlier on the line and `$(git branch --show-current)`."""
        if "$" not in text and "`" not in text:
            return text
        text = _VAR_RE.sub(lambda m: self.vars.get(m.group(1) or m.group(2), m.group(0)), text)
        if cwd and _BRANCH_SUBST_RE.search(text):
            branch = self.branch_now(cwd)
            if branch:
                text = _BRANCH_SUBST_RE.sub(lambda _: branch, text)
        return text

    def _expanded(self, cmd: Command, cwd: str | None) -> Command:
        def ex(word: Word) -> Word:
            text = self.expand(word.text, cwd)
            return word if text == word.text else Word(text, word.subs, word.procsub)

        return Command(
            [ex(w) for w in cmd.words],
            [(n, ex(w)) for n, w in cmd.assigns],
            [(op, ex(t)) for op, t in cmd.redirects],
            cmd.heredocs,
            cmd.pipeline,
            cmd.pos,
        )

    def _git_switch(self, args: list[str], dirs: list[str], cwd: str | None) -> None:
        """Remember the branch a `git checkout` / `git switch` moves to."""
        directory = self._git_dir(dirs, cwd)
        if directory is None or "--" in args:
            return  # `git checkout <tree> -- <paths>` restores files, it does not switch
        if any(a in ("-d", "--detach", "--orphan") for a in args):
            self.sim_branch[directory] = None
            return
        target = None
        creates = False
        i = 0
        while i < len(args) and target is None:
            if args[i] in ("-b", "-B", "-c", "-C") and i + 1 < len(args):
                target, creates = args[i + 1], True
            elif not args[i].startswith("-"):
                target = args[i]
            i += 1
        if target is None:
            return
        if target == "-":
            self.sim_branch[directory] = None
        elif creates or not os.path.exists(os.path.join(directory, target)):
            self.sim_branch[directory] = target  # a file of that name means a path checkout

    @staticmethod
    def _all_words(cmd: Command) -> list[Word]:
        words = list(cmd.words) + [w for _, w in cmd.assigns] + [w for _, w in cmd.redirects]
        return words

    # -- directory tracking -----------------------------------------------------------
    def _cd(self, argv: list[str], cwd: str | None) -> str | None:
        args = [a for a in argv[1:] if a not in ("-L", "-P", "--")]
        if not args:
            return self.ctx.home
        if args[0] == "-":
            return None
        return self.resolve(args[0], cwd)

    def resolve(self, text: str, cwd: str | None) -> str | None:
        """Absolute real path for *text*, or None when it depends on something unknown."""
        if "$(" in text or "`" in text:
            return None
        home = self.ctx.home
        if text == "~" or text.startswith("~/"):
            text = home + text[1:]
        elif text.startswith("~"):
            return None
        for var in ("$HOME", "${HOME}"):
            if text == var or text.startswith(var + "/"):
                text = home + text[len(var) :]
        if "$" in text:
            return None
        if not os.path.isabs(text):
            if cwd is None:
                return None
            text = os.path.join(cwd, text)
        return os.path.realpath(text)

    # -- nested command text ----------------------------------------------------------
    def _nested_shells(self, argv: list[str], cmd: Command, cwd: str | None, depth: int) -> None:
        """Analyse `sh -c '...'`, `eval ...`, and heredoc / here-string input to a shell."""
        if _base(argv[0]) == "eval":
            self.run(" ".join(argv[1:]), cwd, depth + 1)
        for idx, tok in enumerate(argv):
            if _base(tok) not in _SHELLS:
                continue
            code_arg = self._code_arg(argv, idx)
            if code_arg is not None:
                self.run(code_arg, cwd, depth + 1)
            elif idx == 0:
                for body in cmd.heredocs:
                    self.run(body, cwd, depth + 1)
                for op, target in cmd.redirects:
                    if op == "<<<":
                        self.run(target.text, cwd, depth + 1)

    @staticmethod
    def _code_arg(argv: list[str], start: int) -> str | None:
        """The string after a `-c` flag of the interpreter at argv[start], if any."""
        for j in range(start + 1, len(argv)):
            tok = argv[j]
            if tok == "--":
                return None
            if _is_option(tok) and not tok.startswith("--") and "c" in tok[1:]:
                return argv[j + 1] if j + 1 < len(argv) else None
            if not _is_option(tok):
                return None
        return None

    # -- git --------------------------------------------------------------------------
    def check_git(self, argv: list[str], assigns: list[str], cwd: str | None) -> None:
        cfg, dirs, sub, args, unknown_repo = _git_parts(argv)
        for item in cfg:
            key, _, val = item.partition("=")
            low = key.lower()
            if re.fullmatch(r"http(\..+)?\.sslverify", low) and val.lower() in _FALSEY:
                self.add("tls-verify-off", f"`git -c {key}={val}`")
            if low == "core.hookspath" and val in ("/dev/null", "", "nul"):
                self.add("git-no-verify", "`git -c core.hooksPath=/dev/null`")
        if sub == "config":
            self._git_config_tls(args)
        if sub in ("checkout", "switch"):
            self._git_switch(args, dirs, cwd)
        if sub in ("commit", "push", "merge", "rebase"):
            self._git_no_verify(sub, args, assigns)
        if sub == "push":
            self._git_push(args, dirs, cwd, unknown_repo)

    def _git_config_tls(self, args: list[str]) -> None:
        for i, tok in enumerate(args[:-1]):
            if (
                re.fullmatch(r"http(\..+)?\.sslverify", tok, re.I)
                and args[i + 1].lower() in _FALSEY
            ):
                self.add("tls-verify-off", "`git config http.sslVerify false`")

    def _git_no_verify(self, sub: str, args: list[str], assigns: list[str]) -> None:
        value_short = set("mFCctSu") if sub == "commit" else {"o"}
        value_long = {
            "--message", "--file", "--reuse-message", "--reedit-message", "--fixup", "--squash",
            "--author", "--date", "--cleanup", "--template", "--pathspec-from-file", "--trailer",
            "--exec", "--onto", "--strategy", "--strategy-option", "--push-option", "--repo",
        }  # fmt: skip
        i = 0
        while i < len(args):
            tok = args[i]
            if tok == "--":
                break
            if tok.startswith("--"):
                flag = tok.split("=", 1)[0]
                if flag == "--no-verify":
                    self.add("git-no-verify", f"`git {sub} --no-verify`")
                if flag in value_long and "=" not in tok:
                    i += 1
            elif _is_option(tok):
                letters, takes_next = _short_flags(tok, value_short)
                if sub == "commit" and "n" in letters:
                    self.add("git-no-verify", "`git commit -n` (short for --no-verify)")
                if takes_next:
                    i += 1
            i += 1
        for a in assigns:
            name, _, val = a.partition("=")
            if name == "HUSKY" and val == "0" and sub in ("commit", "push"):
                self.add("git-no-verify", f"`HUSKY=0 git {sub}` (switches hooks off)")

    def _git_push(
        self, args: list[str], dirs: list[str], cwd: str | None, unknown_repo: bool
    ) -> None:
        force = all_branches = tags = delete = dry = False
        positional: list[str] = []
        i = 0
        while i < len(args):
            tok = args[i]
            if tok == "--":
                positional += args[i + 1 :]
                break
            if tok.startswith("--"):
                flag = tok.split("=", 1)[0]
                force |= flag in ("--force", "--force-with-lease", "--force-if-includes")
                force |= flag == "--mirror"
                all_branches |= flag in ("--all", "--branches", "--mirror")
                tags |= flag == "--tags"
                delete |= flag == "--delete"
                dry |= flag == "--dry-run"
                if (
                    flag in ("--repo", "--receive-pack", "--exec", "--push-option")
                    and "=" not in tok
                ) or (
                    flag == "--recurse-submodules"
                    and "=" not in tok
                    and i + 1 < len(args)
                    and args[i + 1] in ("check", "on-demand", "only", "no")
                ):
                    i += 1
            elif _is_option(tok):
                letters, takes_next = _short_flags(tok, {"o"})
                force |= "f" in letters
                delete |= "d" in letters
                dry |= "n" in letters
                if takes_next:
                    i += 1
            else:
                positional.append(tok)
            i += 1
        if dry:
            return  # nothing is sent
        directory = self._git_dir(dirs, cwd)
        remote = positional[0] if positional else None
        refspecs = positional[1:]
        protected = (
            self.ctx.protected_branches(directory, remote) if directory else {"main", "master"}
        )
        shown = "`git push" + (" --force" if force else "") + "`"
        hits_force: list[str] = []
        hits_direct: list[str] = []
        undecided = False

        def current() -> str | None:
            if directory is None or unknown_repo:
                return None
            return self.branch_now(directory)

        if all_branches:
            hits_direct.append("all branches")
            if force:
                hits_force.append("all branches")
        for spec in refspecs:
            if "$" in spec or "`" in spec:
                undecided = True  # the branch name is computed when the command runs
                continue
            plus = spec.startswith("+")
            body = spec.lstrip("+")
            if ":" in body and not delete:
                _, dst = body.split(":", 1)
            else:
                dst = body
            dst = dst.removeprefix("refs/heads/")
            if dst == "HEAD":
                head = current() if directory else None
                if head is None:
                    undecided = True
                    continue
                dst = head
            if "*" in dst or "?" in dst:
                matched = [b for b in protected if fnmatch.fnmatch(b, dst)]
                dst = matched[0] if matched else dst
            if dst in protected:
                hits_direct.append(dst)
                if force or plus:
                    hits_force.append(dst)
        if not refspecs and not all_branches and not tags:
            branch = current()
            if branch is None:
                undecided = True
            elif branch in protected:
                hits_direct.append(branch)
                if force:
                    hits_force.append(branch)
        if hits_force:
            self.add("git-force-push-protected", f"{shown} to {', '.join(sorted(set(hits_force)))}")
        if hits_direct:
            self.add("git-push-protected", f"`git push` to {', '.join(sorted(set(hits_direct)))}")
        if undecided and not (hits_force or hits_direct):
            self.add(
                "cannot-decide",
                "`git push` whose target branch could not be determined (detached HEAD or "
                "not a repository)",
            )

    def _git_dir(self, dirs: list[str], cwd: str | None) -> str | None:
        base = cwd
        for d in dirs:
            base = self.resolve(d, base)
            if base is None:
                return None
        return base

    def check_forge_api(self, argv: list[str]) -> None:
        """`gh api` / `glab api` changing a protected branch ref is a push in disguise."""
        if len(argv) < 3 or argv[1] != "api":
            return
        args = argv[2:]
        if not any(re.search(r"git/refs/heads/(?:main|master)\b", a) for a in args):
            return
        method = ""
        for i, a in enumerate(args):
            if a in ("-X", "--method") and i + 1 < len(args):
                method = args[i + 1].upper()
            elif a.startswith("--method="):
                method = a.split("=", 1)[1].upper()
            elif a in ("-f", "-F", "--field", "--raw-field", "--input") and not method:
                method = "POST"  # field flags make gh and glab send a POST
        if method in ("PATCH", "POST", "PUT", "DELETE"):
            self.add("git-push-protected", f"`{argv[0]} api` changing a protected branch ref")

    # -- rm ---------------------------------------------------------------------------
    def check_rm(self, argv: list[str], cwd: str | None) -> None:
        recursive = no_preserve = False
        targets: list[str] = []
        end_opts = False
        for tok in argv[1:]:
            if end_opts or not _is_option(tok):
                targets.append(tok)
            elif tok == "--":
                end_opts = True
            elif tok.startswith("--"):
                recursive |= tok == "--recursive"
                no_preserve |= tok == "--no-preserve-root"
            else:
                recursive |= any(c in "rR" for c in tok[1:])
        if no_preserve:
            self.add("rm-rf-critical", "`rm --no-preserve-root`")
            return
        if not recursive:
            return
        roots = self.ctx.protected_roots(cwd)
        for target in targets:
            if self._rm_target_is_critical(target, cwd, roots):
                self.add("rm-rf-critical", f"`rm -r {target}`")

    def _rm_target_is_critical(self, target: str, cwd: str | None, roots: set[str]) -> bool:
        if not target:
            return False  # `rm -rf ""` removes nothing
        stripped = target.rstrip("/") or "/"
        leaf = os.path.basename(stripped)
        if any(ch in leaf for ch in "*?["):
            if leaf not in _MATCH_ALL_GLOBS:
                return False
            stripped = os.path.dirname(stripped) or "."
        resolved = self.resolve(stripped, cwd)
        if resolved is None:
            # Cannot say where "." or "*" points (an unknown `cd` came before it).
            return cwd is None and stripped in (".", "..", "*", "./*", ".*")
        if resolved == "/" or resolved in roots or resolved in _SYSTEM_DIRS:
            return True
        prefix = resolved.rstrip("/") + "/"
        return any(r.startswith(prefix) for r in roots)  # a parent of the repo or home

    # -- chmod ------------------------------------------------------------------------
    def check_chmod(self, argv: list[str]) -> None:
        recursive = False
        mode = ""
        for tok in argv[1:]:
            if tok.startswith("--"):
                recursive |= tok == "--recursive"
            elif _is_option(tok):
                recursive |= "R" in tok[1:]
            elif not mode:
                mode = tok
        if recursive and mode and self._grants_world_write(mode):
            self.add("world-writable-chmod", f"`chmod -R {mode}`")

    @staticmethod
    def _grants_world_write(mode: str) -> bool:
        if re.fullmatch(r"[0-7]{1,4}", mode):
            return bool(int(mode, 8) & 0o002)
        for clause in mode.split(","):
            m = _SYMBOLIC_MODE_RE.match(clause)
            if m and m.group(2) in "+=" and "w" in m.group(3) and set(m.group(1)) & set("ao"):
                return True
        return False

    # -- GCP --------------------------------------------------------------------------
    def check_gcloud(self, name: str, argv: list[str]) -> None:
        args = argv[1:]
        # `remove-iam-policy-binding` and `--remove-acl-grant` take access away, so they pass.
        removing = name == "gcloud" and any(
            a.startswith(("remove-iam", "remove-invoker", "--remove-")) for a in args
        )
        skip_next = False
        for a in args:
            if removing:
                break
            if skip_next:
                skip_next = False  # the member after gsutil's `-d` is being deleted
                continue
            if name == "gsutil" and a == "-d":
                skip_next = True
                continue
            low = a.lower()
            if (
                _PUBLIC_MEMBER_RE.match(a)
                or low in _PUBLIC_ACL
                or low.split("=", 1)[-1] in _PUBLIC_ACL
                or low in ("--allow-unauthenticated", "--allow-unauthenticated=true")
            ):
                self.add("gcp-public-access", f"`{name}` granting public access")
                break
        if name == "gcloud":
            positionals = self._gcloud_positionals(args)
            if positionals[:1] in (["alpha"], ["beta"]):
                positionals = positionals[1:]
            if positionals[:4] == ["iam", "service-accounts", "keys", "create"]:
                self.add("gcp-sa-key-create", "`gcloud iam service-accounts keys create`")

    @staticmethod
    def _gcloud_positionals(args: list[str]) -> list[str]:
        value_flags = {
            "--project", "--account", "--format", "--configuration", "--billing-project",
            "--impersonate-service-account", "--verbosity", "--flags-file",
        }  # fmt: skip
        out: list[str] = []
        i = 0
        while i < len(args):
            tok = args[i]
            if tok in value_flags:
                i += 1
            elif not tok.startswith("-"):
                out.append(tok)
            i += 1
        return out

    # -- docker -----------------------------------------------------------------------
    def check_docker(self, argv: list[str]) -> None:
        args = argv[1:]
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-H", "--host", "-c", "--context", "--config", "-l") else 1
        if i >= len(args):
            return
        sub, rest = args[i], args[i + 1 :]
        if sub == "container" and rest:
            sub, rest = rest[0], rest[1:]
        if sub not in ("run", "create", "exec"):
            return
        for j, tok in enumerate(rest):
            if tok in ("--privileged", "--privileged=true"):
                self.add("docker-privileged", f"`{argv[0]} {sub} --privileged`")
            value = None
            if tok in ("-v", "--volume") and j + 1 < len(rest):
                value = rest[j + 1].split(":", 1)[0]
            elif tok.startswith("--volume="):
                value = tok[len("--volume=") :].split(":", 1)[0]
            elif tok.startswith("-v") and len(tok) > 2:
                value = tok[2:].split(":", 1)[0]
            elif tok in ("--mount",) and j + 1 < len(rest):
                value = rest[j + 1]
            elif tok.startswith("--mount="):
                value = tok[len("--mount=") :]
            if value is not None and "docker.sock" in value:
                self.add("docker-privileged", f"`{argv[0]} {sub}` mounting docker.sock")

    # -- TLS --------------------------------------------------------------------------
    def check_tls_assignments(self, assigns: list[str], words: list[str]) -> None:
        for text in assigns:
            self._tls_env(text)
        # `export X=0`, `docker run -e X=0`, `--set-env-vars=X=0`; but not `grep X=0 file`
        if words and _base(words[0]) not in _READERS and _base(words[0]) not in ("echo", "printf"):
            for tok in words:
                self._tls_env(tok)

    def _tls_env(self, text: str) -> None:
        for m in _TLS_ENV_RE.finditer(text):
            name, val = m.group(1).upper(), m.group(2).strip("'\"")
            bad = (
                name == "GIT_SSL_NO_VERIFY"  # git honours any value, even an empty one
                or (name in ("NODE_TLS_REJECT_UNAUTHORIZED", "PYTHONHTTPSVERIFY") and val == "0")
                or (name == "NPM_CONFIG_STRICT_SSL" and val.lower() in _FALSEY)
            )
            if bad:
                self.add("tls-verify-off", f"`{name}` set to switch verification off")

    def check_tls_command(self, name: str, argv: list[str]) -> None:
        args = argv[1:]
        if name == "curl":
            i = 0
            while i < len(args):
                tok = args[i]
                if tok == "--":
                    break
                if tok.startswith("--"):
                    flag = tok.split("=", 1)[0]
                    if flag in ("--insecure", "--proxy-insecure", "--doh-insecure"):
                        self.add("tls-verify-off", "`curl --insecure`")
                    if flag in _CURL_VALUE_LONG and "=" not in tok:
                        i += 1
                elif _is_option(tok):
                    letters, takes_next = _short_flags(tok, _CURL_VALUE_SHORT)
                    if "k" in letters:
                        self.add("tls-verify-off", "`curl -k`")
                    if takes_next:
                        i += 1
                i += 1
        elif name == "wget":
            if any(
                a.startswith("--no-check-certificate")
                or re.search(r"check[-_]certificate\s*=\s*(?:off|0|no)", a, re.I)
                for a in args
            ):
                self.add("tls-verify-off", "`wget --no-check-certificate`")
        elif name in ("http", "https", "xh"):
            for i, a in enumerate(args):
                if a.lower() in ("--verify=no", "--verify=false") or (
                    a == "--verify" and i + 1 < len(args) and args[i + 1].lower() in _FALSEY
                ):
                    self.add("tls-verify-off", f"`{name} --verify=no`")
        elif name in ("kubectl", "helm", "oc", "k3s"):
            for a in args:
                if a in ("--insecure-skip-tls-verify", "--insecure-skip-tls-verify=true"):
                    self.add("tls-verify-off", f"`{name} --insecure-skip-tls-verify`")
        elif name in ("npm", "yarn", "pnpm"):
            low = [a.lower() for a in args]
            if "--no-strict-ssl" in low or "--strict-ssl=false" in low:
                self.add("tls-verify-off", f"`{name} --strict-ssl=false`")
            for i, a in enumerate(low[:-1]):
                if a in ("strict-ssl", "enablestrictssl") and low[i + 1] in _FALSEY:
                    self.add("tls-verify-off", f"`{name} config set strict-ssl false`")
        elif name == "gcloud":
            for i, a in enumerate(args[:-1]):
                if a == "auth/disable_ssl_validation" and args[i + 1].lower() not in _FALSEY:
                    self.add("tls-verify-off", "`gcloud config set auth/disable_ssl_validation`")

    # -- downloaded code --------------------------------------------------------------
    def _downloads(self, text: str, depth: int = 0) -> bool:
        """Whether a command line (a substitution body) runs a downloader."""
        if depth > MAX_DEPTH:
            return True  # too deep to follow: treat as risky rather than clean
        for item in parse(text):
            if not isinstance(item, Command):
                continue
            _, words = unwrap(item.words)
            if words and _base(words[0].text) in _DOWNLOADERS:
                return True
            for w in self._all_words(item):
                if any(self._downloads(sub, depth + 1) for sub in w.subs):
                    return True
        return False

    @staticmethod
    def _reads_stdin_program(argv: list[str]) -> bool:
        """Whether a shell or interpreter would take its program from standard input."""
        name = _base(argv[0])
        is_shell = name in _SHELLS
        if not (is_shell or name in _INTERPRETERS or _PY_RE.match(name)):
            return False
        value_opts = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"} if is_shell else set()
        i = 1
        while i < len(argv):
            tok = argv[i]
            if tok == "--":
                return i + 1 >= len(argv)  # a script named after `--` is a file path
            if tok == "-":
                return True
            if tok in value_opts:
                i += 2
                continue
            if _is_option(tok):
                body = tok[1:] if not tok.startswith("--") else ""
                if is_shell:
                    if "c" in body:
                        return False
                    if "s" in body:
                        return True
                elif tok in ("-c", "-m", "-e", "-E", "-p", "-r"):
                    return False
                i += 1
                continue
            return False  # a script file or module was named
        return True

    def pipeline_rules(self, stages: list[Command], cwd: str | None, depth: int) -> None:
        argvs = [[w.text for w in unwrap(c.words)[1]] for c in stages]
        self._text_into_shell(stages, argvs, cwd, depth)
        seen_download = False
        for argv in argvs:
            if not argv:
                continue
            if seen_download and self._reads_stdin_program(argv):
                self.add("pipe-to-shell", f"a download piped into `{_base(argv[0])}`")
                return
            if _base(argv[0]) in _DOWNLOADERS:
                seen_download = True

    def _text_into_shell(
        self, stages: list[Command], argvs: list[list[str]], cwd: str | None, depth: int
    ) -> None:
        """`echo '<command>' | sh` and `cat <<EOF | bash`: the piped text is a command line."""
        for idx in range(1, len(argvs)):
            shell = argvs[idx]
            if not shell or _base(shell[0]) not in _SHELLS or not self._reads_stdin_program(shell):
                continue
            feeder = argvs[idx - 1]
            if feeder and _base(feeder[0]) in ("echo", "printf"):
                args = [a for a in feeder[1:] if not a.startswith("-")]
                self.run(" ".join(args), cwd, depth + 1)
            for body in stages[idx - 1].heredocs:
                self.run(body, cwd, depth + 1)

    def check_downloaded_code(
        self, name: str, argv: list[str], words: list[Word], cmd: Command
    ) -> None:
        is_runner = name in _SHELLS or name in _INTERPRETERS or _PY_RE.match(name) is not None
        if name in ("eval", "source", "."):
            if any(self._downloads(s) for w in words[1:] for s in w.subs):
                self.add("pipe-to-shell", f"`{name}` of downloaded text")
        elif is_runner:
            code_arg = self._code_arg_word(words)
            candidates = [w for w in words[1:] if w.procsub] + [
                t for op, t in cmd.redirects if op in ("<", "<<<") and t.procsub
            ]
            if code_arg is not None:
                candidates.append(code_arg)
            if any(self._downloads(s) for w in candidates for s in w.subs):
                self.add("pipe-to-shell", f"`{name}` running downloaded text")

    @staticmethod
    def _code_arg_word(words: list[Word]) -> Word | None:
        for j in range(1, len(words)):
            tok = words[j].text
            if _is_option(tok) and not tok.startswith("--") and any(c in tok[1:] for c in "ce"):
                return words[j + 1] if j + 1 < len(words) else None
            if not _is_option(tok):
                return None
        return None

    # -- secrets: reading --------------------------------------------------------------
    def _secret_token(self, token: str, cwd: str | None) -> bool:
        """Whether a command-line token names (or globs to) a secret file."""
        candidates = {token, token.split("=", 1)[-1], token.rsplit(":", 1)[-1]}
        for cand in candidates:
            if not cand or cand.startswith("-"):
                continue
            if is_secret_path(cand, self.ctx.home):
                return True
            if any(ch in cand for ch in "*?[") and cwd:
                resolved = self.resolve(cand, cwd) if "[" not in cand else None
                pattern = resolved if resolved else os.path.join(cwd, cand)
                for hit in glob.glob(pattern)[:200]:
                    if is_secret_path(hit, self.ctx.home):
                        return True
        return False

    def check_secret_read(self, name: str, argv: list[str], cmd: Command, cwd: str | None) -> None:
        args = argv[1:]
        reader = name in _READERS
        if name == "git":
            _, _, sub, args, _ = _git_parts(argv)
            reader = sub in _GIT_READERS
        if not reader:
            return
        if name in _GREP_FAMILY and self._quiet_grep(args):
            return
        if name == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
            return  # edits in place and prints nothing
        if name == "diff" and any(a in ("-q", "--brief") for a in args):
            return
        skip_next = False
        for tok in args:
            if skip_next:
                skip_next = False
                continue
            if name in _GREP_FAMILY and tok in ("-g", "--glob", "--include", "--exclude"):
                skip_next = True  # the value is a filter
                continue
            if tok.startswith((":!", ":^", ":(exclude)")) or (
                name in _GREP_FAMILY and tok.startswith(("--include=", "--exclude", "--glob="))
            ):
                continue  # a pathspec or filter that leaves the file out
            if self._secret_token(tok, cwd):
                self.add("secret-file-read", f"`{name}` on {os.path.basename(tok.split('=')[-1])}")
                return
        for op, target in cmd.redirects:
            if op == "<" and self._secret_token(target.text, cwd):
                self.add("secret-file-read", f"`{name}` fed {os.path.basename(target.text)}")
                return

    @staticmethod
    def _quiet_grep(args: list[str]) -> bool:
        for a in args:
            if a in (
                "--quiet",
                "--silent",
                "--count",
                "--files-with-matches",
                "--files-without-match",
            ):
                return True
            if _is_option(a) and not a.startswith("--") and any(c in a[1:] for c in "qclL"):
                return True
        return False

    # -- secrets: writing --------------------------------------------------------------
    @staticmethod
    def _write_targets(items: list[Command | str]) -> list[str]:
        """File names written by redirects (not /dev/null or a file descriptor)."""
        targets: list[str] = []
        for it in items:
            if isinstance(it, Command):
                for op, target in it.redirects:
                    if op in (">", ">>", ">|", "&>", "&>>") and not target.text.startswith("/dev/"):
                        targets.append(target.text)
        return targets

    def write_rules(self, items: list[Command | str], line: str) -> None:
        """Judge content a command line writes: heredocs, `echo ... > file`, `tee`, `sed -i`.

        Only text that a content-producing command carries is judged, so a commit message
        that mentions a token format is not mistaken for a file being written.
        """
        targets = self._write_targets(items)
        produced: list[str] = []
        writes = bool(targets)
        for it in items:
            if not isinstance(it, Command):
                continue
            _, words = unwrap(it.words)
            name = _base(words[0].text) if words else ""
            in_place = any(
                w.text == "--in-place" or (_is_option(w.text) and "i" in w.text[1:])
                for w in words[1:]
            )
            if name == "tee" or (name in ("sed", "perl") and in_place):
                writes = True
            if name in _CONTENT_PRODUCERS or _PY_RE.match(name):
                produced += [w.text for w in words[1:]]
            produced += it.heredocs + [t.text for op, t in it.redirects if op == "<<<"]
        if not writes or not produced:
            return
        path = targets[0] if targets else ""
        text = "\n".join(produced)
        if any(os.path.basename(t) in _SETTINGS_FILES for t in targets) and _HOOK_OFF_RE.search(
            text
        ):
            self.add("guardrails-tamper", "a config.toml edit that switches hooks off")
        for finding in content_findings(text, path):
            self.add(finding.rule, finding.detail)

    # -- tamper -----------------------------------------------------------------------
    def check_tamper_redirects(self, cmd: Command, cwd: str | None) -> None:
        for op, target in cmd.redirects:
            if op not in (">", ">>", ">|", "&>", "&>>"):
                continue
            name = os.path.basename(target.text)
            truncates = op in (">", ">|", "&>")
            if self._is_guarded_path(target.text, cwd, removal=truncates) or (
                name in _SETTINGS_FILES and any(_HOOK_OFF_RE.search(w.text) for w in cmd.words)
            ):
                self.add("guardrails-tamper", f"a redirect into {name}")

    def _path_forms(self, text: str, cwd: str | None) -> set[str]:
        """*text* as a path: written (made absolute, `~` and $HOME filled in) and resolved."""
        if not text:
            return set()
        forms = {text}
        home = self.ctx.home
        expanded = text
        if expanded == "~" or expanded.startswith("~/"):
            expanded = home + expanded[1:]
        for var in ("$HOME", "${HOME}"):
            if expanded == var or expanded.startswith(var + "/"):
                expanded = home + expanded[len(var) :]
        for var in ("$CODEX_HOME", "${CODEX_HOME}"):
            if expanded == var or expanded.startswith(var + "/"):
                expanded = self.ctx.codex_home + expanded[len(var) :]
        if "$" not in expanded and "`" not in expanded:
            if not os.path.isabs(expanded) and cwd is not None:
                expanded = os.path.join(cwd, expanded)
            if os.path.isabs(expanded):
                forms |= _both(expanded)
        return forms

    def _is_guarded_path(self, text: str, cwd: str | None, *, removal: bool = False) -> bool:
        if ALLOW_FILE in text:
            return True
        forms = self._path_forms(text, cwd)
        if self.ctx.is_guarded(forms, parents=removal):
            return True
        return removal and bool(forms & self.ctx.config_files)

    def _mentions_guarded(self, code: str) -> bool:
        """Whether inline code (`python3 -c '...'`) names the allowlist, a hooks.json, this
        script or the block log."""
        names = (ALLOW_STORE, HOOKS_FILE, _real(__file__), os.path.join(LOG_DIR, LOG_NAME))
        return any(n in code for n in names)

    @staticmethod
    def _inline_code(argv: list[str]) -> str | None:
        """The program text after `-c` / `-e` / `-E` / `-r` of an interpreter, if any."""
        for j in range(1, len(argv) - 1):
            tok = argv[j]
            if tok in ("-c", "-e", "-E", "-r", "--eval") or (
                _is_option(tok) and not tok.startswith("--") and tok[-1] in "ceE"
            ):
                return argv[j + 1]
        return None

    def _check_codex_cli(self, argv: list[str], cwd: str | None) -> None:
        """`codex features disable hooks`, `--disable hooks`, `-c features.hooks=false`, and
        the pack's own `install.sh --uninstall`, which removes the hook."""
        if _base(argv[0]) in _SHELLS and len(argv) > 1 and _base(argv[1]) == "install.sh":
            argv = argv[1:]  # `bash install.sh --uninstall`
        name, args = _base(argv[0]), argv[1:]
        if name == "install.sh" and "--uninstall" in args:
            where = self.resolve(argv[0], cwd)
            if where is not None and os.path.dirname(where) == self.ctx.pack_root:
                self.add("guardrails-tamper", "`install.sh --uninstall` (removes the hook)")
            return
        if name != "codex":
            return
        feature_names = ("hooks", "codex_hooks")
        if args[:2] == ["features", "disable"] and any(a in feature_names for a in args[2:]):
            self.add("guardrails-tamper", "`codex features disable hooks`")
        for i, tok in enumerate(args):
            value = None
            if tok in ("--disable", "-c", "--config") and i + 1 < len(args):
                value = args[i + 1]
            elif tok.startswith(("--disable=", "--config=")):
                value = tok.split("=", 1)[1]
            elif tok.startswith("-c") and len(tok) > 2:
                value = tok[2:]
            if value is None:
                continue
            if (tok.startswith("--disable") and value in feature_names) or (
                not tok.startswith("--disable") and _HOOK_OFF_RE.search(value)
            ):
                self.add("guardrails-tamper", "a `codex` run with hooks switched off")

    def check_tamper_command(self, name: str, argv: list[str], cwd: str | None) -> None:
        args = argv[1:]
        self._check_codex_cli(argv, cwd)
        in_place = any(a.startswith("-i") or a == "--in-place" for a in args)
        if (
            in_place
            and any(os.path.basename(a) in _SETTINGS_FILES for a in args)
            and any(_HOOK_OFF_RE.search(a) for a in args)
        ):
            self.add("guardrails-tamper", "an in-place config.toml edit that switches hooks off")

        paths = [a for a in args if not a.startswith("-") or "=" in a]
        hit = False
        if name in ("cp", "rsync", "install"):
            # copying FROM a guarded file is a read; only the destination (last path) is a write
            hit = bool(paths) and self._is_guarded_path(paths[-1], cwd)
        elif name in _WRITERS:
            removal = name in ("rm", "mv", "unlink", "shred")
            hit = any(
                self._is_guarded_path(a.split("=", 1)[-1], cwd, removal=removal) for a in paths
            )
        elif name in ("sed", "perl", "awk"):
            hit = in_place and any(self._is_guarded_path(a, cwd) for a in paths)
        elif name == "git":
            sub = _git_parts(argv)[2]
            hit = sub in ("rm", "checkout", "restore", "mv", "stash") and any(
                self._is_guarded_path(a, cwd) for a in paths
            )
        elif name in _INLINE_CODE or _PY_RE.match(name):
            code = self._inline_code(argv)
            hit = code is not None and self._mentions_guarded(code)  # a script file is fine
        if hit:
            self.add("guardrails-tamper", f"`{name}` on a guardrails file or hook setting")

    # -- apply_patch run from the shell ---------------------------------------------------
    def check_patch_command(self, argv: list[str], cmd: Command, cwd: str | None) -> None:
        """`apply_patch <<'EOF' ... EOF` or `apply_patch "$PATCH"`: judge the patch text."""
        texts = list(cmd.heredocs) + [t.text for op, t in cmd.redirects if op == "<<<"]
        texts += [a for a in argv[1:] if PATCH_BEGIN in a]
        for text in texts:
            for finding in evaluate_patch(text, cwd or self.ctx.cwd, self.ctx):
                self.add(finding.rule, finding.detail)


# --------------------------------------------------------------------------------------
# Tool-level entry points
# --------------------------------------------------------------------------------------


PATCH_BEGIN = "*** Begin Patch"
_PATCH_FILE_RE = re.compile(r"^\*\*\* (Add File|Update File|Delete File|Move to): (.+?)\s*$")


@dataclass
class PatchFile:
    """One file a patch touches: what happens to it and the lines it gains and loses."""

    action: str  # "add", "update" or "delete"
    path: str
    move_to: str | None = None
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)


def parse_patch(text: str) -> list[PatchFile] | None:
    """The files of an apply_patch text, or None when it has no `*** Begin Patch` line."""
    lines = text.replace("\r\n", "\n").split("\n")
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == PATCH_BEGIN)
    except StopIteration:
        return None
    files: list[PatchFile] = []
    current: PatchFile | None = None
    for line in lines[start + 1 :]:
        if line.strip() == "*** End Patch":
            break
        m = _PATCH_FILE_RE.match(line)
        if m:
            kind, path = m.group(1), m.group(2)
            if kind == "Move to":
                if current is not None:
                    current.move_to = path
                continue
            current = PatchFile(
                {"Add File": "add", "Update File": "update"}.get(kind, "delete"), path
            )
            files.append(current)
            continue
        if current is None or line.startswith(("@@", "*** ")):
            continue
        if line.startswith("+"):
            current.added.append(line[1:])
        elif line.startswith("-"):
            current.removed.append(line[1:])
        else:
            current.context.append(line[1:] if line.startswith(" ") else line)
    return files


def evaluate_patch(text: str, cwd: str, ctx: Ctx) -> list[Finding]:
    """Findings for one patch: content rules on added lines, tamper on every path touched."""
    files = parse_patch(text)
    if files is None:
        return [Finding("cannot-decide", "an apply_patch call with no `*** Begin Patch` line")]
    findings: list[Finding] = []

    def add(finding: Finding) -> None:
        if finding not in findings:
            findings.append(finding)

    for pf in files:
        targets = [pf.path] + ([pf.move_to] if pf.move_to else [])
        for target in targets:
            path = target if os.path.isabs(target) else os.path.join(cwd, target)
            forms = _both(path)
            removal = pf.action == "delete" or (pf.move_to is not None and target == pf.path)
            if ctx.is_guarded(forms, parents=removal) or (removal and forms & ctx.config_files):
                add(Finding("guardrails-tamper", f"a patch to {os.path.basename(target)}"))
        added = "\n".join(pf.added)
        name = os.path.basename(pf.move_to or pf.path)
        if name in _SETTINGS_FILES:
            changed = "\n".join(pf.added + pf.removed)
            hunk = "\n".join(pf.context + pf.added + pf.removed)
            if _HOOK_OFF_RE.search(changed) or (
                "hooks.state" in hunk and _HOOK_STATE_OFF_RE.search(added)
            ):
                add(Finding("guardrails-tamper", f"a {name} edit that switches hooks off"))
        for finding in content_findings(added, pf.move_to or pf.path):
            add(finding)
    return findings


def _command_text(tool_input: Mapping[str, object]) -> str | None:
    """`tool_input.command` as one command line: a string as is, an argv list joined."""
    value = tool_input.get("command")
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return shlex.join(value)
    return None


def evaluate(payload: Mapping[str, object], environ: Mapping[str, str]) -> list[Finding]:
    """All findings for one tool call, before the allowlist is applied."""
    tool = payload.get("tool_name")
    if tool not in ("Bash", "apply_patch"):
        return []
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return [Finding("cannot-decide", f"a {tool} call with no readable tool_input")]
    ctx = Ctx(payload, environ)
    command = _command_text(tool_input)
    if command is None:
        return [Finding("cannot-decide", f"a {tool} call with no readable command")]
    cwd = ctx.cwd
    workdir = tool_input.get("workdir")
    if isinstance(workdir, str) and workdir:
        if workdir == "~" or workdir.startswith("~/"):
            workdir = ctx.home + workdir[1:]
        cwd = _real(os.path.join(ctx.cwd, workdir))
    if tool == "apply_patch":
        return evaluate_patch(command, cwd, ctx)
    analyzer = Analyzer(ctx)
    analyzer.run(command, cwd)
    return analyzer.findings


# --------------------------------------------------------------------------------------
# Decision, message, log
# --------------------------------------------------------------------------------------


def message_for(finding: Finding, extra: int) -> str:
    rule = RULE_BY_ID[finding.rule]
    more = f" (+{extra} more)" if extra else ""
    return (
        f"guardrails[{rule.id}]: {redact(finding.detail)} is blocked{more} because {rule.why}. "
        f"{rule.instead} Do not retry it another way; if it is truly needed, tell the user "
        f"and let them run it."
    )


def log_event(data_dir: str, event: dict[str, object]) -> None:
    """Append one JSON line to blocks.log; logging problems never change the decision."""
    if not data_dir:
        return
    try:
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, LOG_NAME)
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except OSError:
        pass


def decide(raw: str, environ: Mapping[str, str]) -> tuple[int, str]:
    """(exit code, stderr text) for one hook payload."""
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return 2, message_for(
            Finding("cannot-decide", "a hook payload that is not a JSON object"), 0
        )
    event = payload.get("hook_event_name")
    if event not in (None, "PreToolUse"):
        return 0, ""
    findings = evaluate(payload, environ)
    if not findings:
        return 0, ""

    ctx = Ctx(payload, environ)
    allowed = load_allowlist(ctx.codex_home, ctx.project_dir)
    live = [f for f in findings if f.rule not in allowed]
    waived = [f for f in findings if f.rule in allowed]
    tool_input = payload.get("tool_input")
    command = _command_text(tool_input) if isinstance(tool_input, dict) else None
    data_dir = ctx.data_dir
    base = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": payload.get("tool_name"),
        "session": payload.get("session_id"),
        "cwd": payload.get("cwd"),
        "command": redact(command)[:300] if isinstance(command, str) else None,
    }
    if waived:
        log_event(
            data_dir, {**base, "event": "allowed-by-config", "rules": [f.rule for f in waived]}
        )
    if not live:
        return 0, ""
    log_event(
        data_dir,
        {
            **base,
            "event": "block",
            "rules": [f.rule for f in live],
            "detail": redact(live[0].detail),
        },
    )
    text = message_for(live[0], len(live) - 1)
    if os.path.isfile(os.path.join(ctx.project_dir, ALLOW_DIR, ALLOW_FILE)):
        text += (
            f" This repo ships {ALLOW_DIR}/{ALLOW_FILE}; repo-shipped waivers are ignored. "
            f"Waivers are read from {allowlist_path(ctx.codex_home, ctx.project_dir)}."
        )
    return 2, text


def default_data_dir(environ: Mapping[str, str]) -> str:
    """`${CODEX_HOME:-~/.codex}/guardrails`, where the hook writes its block log."""
    home = environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(environ.get("CODEX_HOME") or os.path.join(home, ".codex"), LOG_DIR)


def list_rules() -> str:
    lines = []
    for r in RULES:
        flag = "" if r.allowlistable else "  (cannot be allowlisted)"
        lines.append(
            f"{r.id}{flag}\n  blocks:  {r.summary}\n  why:     {r.why}\n  instead: {r.instead}"
        )
    return "\n".join(lines)


def recent(data_dir: str, count: int) -> str:
    path = os.path.join(data_dir, LOG_NAME)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()[-count:]
    except OSError:
        return f"No guardrails log yet at {path} (nothing has been blocked)."
    return "\n".join(lines) if lines else "The guardrails log is empty."


def _read_stdin() -> str:
    """Standard input as text; stray bytes are replaced instead of crashing the hook."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        data: bytes = buffer.read()
        return data.decode("utf-8", errors="replace")
    return sys.stdin.read()


def _emit(text: str) -> None:
    """Write the block message to stderr as UTF-8 whatever the terminal locale is."""
    buffer = getattr(sys.stderr, "buffer", None)
    if buffer is not None:
        buffer.write((text + "\n").encode("utf-8", errors="replace"))
        buffer.flush()
    else:
        print(text, file=sys.stderr)


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        if argv[1] == "--list-rules":
            print(list_rules())
            return 0
        if argv[1] == "--recent":
            count = int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else 20
            data_dir = ""
            if "--data-dir" in argv:
                idx = argv.index("--data-dir")
                data_dir = argv[idx + 1] if idx + 1 < len(argv) else ""
            print(recent(data_dir or default_data_dir(os.environ), count))
            return 0
        if argv[1] == "--allow-path":
            ctx = Ctx({"cwd": argv[2] if len(argv) > 2 else os.getcwd()}, os.environ)
            print(allowlist_path(ctx.codex_home, ctx.project_dir))
            return 0
        print(
            "usage: guardrails.py [--list-rules | --recent [N] [--data-dir DIR] | "
            "--allow-path [DIR]]",
            file=sys.stderr,
        )
        return 64
    try:
        code, text = decide(_read_stdin(), os.environ)
    except Exception as exc:  # a guard that crashes refuses; it never waves a call through
        code = 2
        text = message_for(Finding("cannot-decide", f"an internal error ({type(exc).__name__})"), 0)
    if text:
        _emit(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
