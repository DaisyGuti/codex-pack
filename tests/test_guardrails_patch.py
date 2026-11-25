"""apply_patch calls: the content rules on the lines a patch adds, and the tamper rule on every
path it adds, updates, deletes or moves. Codex sends file edits as one patch text in
`tool_input.command`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from test_guardrails_support import (
    GITHUB,
    HOOKS_JSON,
    RANDOM_VALUE,
    SCRIPT,
    World,
    add_file,
    build_template,
    delete_file,
    make_world,
    update_file,
)

# Credential-shaped values built from parts, so this file holds no literal a scanner would flag.
GITHUB_FINE = "github" + "_pat_" + "11ABCDEFG0" + "abcdefghij" + "_ABCDEFGHIJ" + "klmnop"
GITLAB = "gl" + "pat-" + "AbCdEfGhIjKlMnOpQrSt"
SLACK = "xo" + "xb-" + "1234567890-abcdefghijkl"
SLACK_APP = "xa" + "pp-1-A0123456789-1234567890-" + "abcdef0123456789"
SLACK_HOOK = (
    "https://hooks.slack" + ".com/services/T01234567/B01234567/" + "abcdefghijklmnopqrstuvwx"
)
AWS = "AK" + "IA" + "QWERTYUIOPASDFGH"
AWS_SECRET = 'aws_secret_access_key = "' + "wJalrXUtnFEMI/K7MDENG/bPxRfiCY" + 'QWERTYUIOP12"'
GOOGLE_KEY = "AI" + "za" + "SyA-1234567890abcdefghijklmnopqrstu"
GOOGLE_SECRET = "GOC" + "SPX-" + "abcdefghijklmnopqrstuvwxyz12"
ANTHROPIC = "sk-" + "ant-" + "api03-abcdefghijklmnopqrstuvwx"
PEM_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj"
PRIVATE_KEY = "-----BEGIN " + "PRIVATE KEY-----\n" + PEM_BODY + "\n-----END PRIVATE KEY-----\n"
OPENSSH_KEY = "-----BEGIN OPENSSH " + "PRIVATE KEY-----\n" + PEM_BODY + "\n"
SA_JSON = (
    '{"type": "service_account", "project_id": "p", "private_key_id": "abc123",\n'
    ' "private_key": "-----BEGIN '
    + "PRIVATE KEY-----\\n"
    + PEM_BODY
    + '\\n-----END PRIVATE KEY-----\\n",\n'
    ' "client_email": "sa@p.iam.gserviceaccount.com"}\n'
)
SA_JSON_NO_BEGIN = '{"type": "service_account", "private_key_id": "abc123", "private_key": "x"}'

SECRET_CONTENT: list[tuple[str, str]] = [
    ("private key block", PRIVATE_KEY),
    ("openssh private key", OPENSSH_KEY),
    ("GCP service account key JSON", SA_JSON),
    ("GCP service account JSON, key id only", SA_JSON_NO_BEGIN),
    ("AWS access key id", f'AWS_ACCESS_KEY_ID = "{AWS}"\n'),
    ("AWS secret access key", AWS_SECRET + "\n"),
    ("GitHub classic token", f"token: {GITHUB}\n"),
    ("GitHub fine-grained token", f"export GH={GITHUB_FINE}\n"),
    ("GitLab token", f"CI_TOKEN={GITLAB}\n"),
    ("Slack bot token", f'SLACK = "{SLACK}"\n'),
    ("Slack app token", f"{SLACK_APP}\n"),
    ("Slack webhook", f"url = '{SLACK_HOOK}'\n"),
    ("Google API key", f'key: "{GOOGLE_KEY}"\n'),
    ("Google OAuth client secret", f"client_secret: {GOOGLE_SECRET}\n"),
    ("Anthropic key", f"KEY={ANTHROPIC}\n"),
    ("generic _SECRET", f"APP_SECRET={RANDOM_VALUE}\n"),
    ("generic _TOKEN quoted", f'API_TOKEN = "{RANDOM_VALUE}"\n'),
    ("generic password in yaml", f"db_password: {RANDOM_VALUE}\n"),
    ("generic json", f'{{"apiKey": "{RANDOM_VALUE}"}}\n'),
    ("generic export", f"export STRIPE_SECRET_KEY={RANDOM_VALUE}\n"),
    ("secret in the middle of a file", "a = 1\n" * 20 + f"AUTH_TOKEN={RANDOM_VALUE}\n" + "b = 2\n"),
]

SAFE_CONTENT: list[tuple[str, str]] = [
    ("plain code", "def add(a, b):\n    return a + b\n"),
    ("env read", 'TOKEN = os.environ["API_TOKEN"]\n'),
    ("env read in js", "const token = process.env.API_TOKEN;\n"),
    ("template", "API_TOKEN=${API_TOKEN}\n"),
    ("ci secret reference", "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n"),
    ("placeholder value", "API_TOKEN=your-token-here-please-replace\n"),
    ("angle placeholder", "API_TOKEN=<paste-your-token-here-1234>\n"),
    ("short value", "PASSWORD_MIN_LENGTH=12\n"),
    ("path value", "GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/key-2024.json\n"),
    ("url value", "TOKEN_ENDPOINT=https://auth.example.test/oauth2/token\n"),
    ("name-like value", "SECRET_NAME=projects/123456/secrets/db-password/versions/latest\n"),
    ("kebab identifier", "token_bucket: my-service-token-bucket-2\n"),
    ("key reference", "api_key_file: ./keys/dev-key-2.json\n"),
    ("header name", "AUTH_TOKEN_HEADER=X-Auth-Token-Value-1\n"),
    ("repeated characters", "TOKEN=aaaaaaaaaaaaaaaaaaaaaaaa1\n"),
    ("aws docs example", "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"),
    ("pem header with no body", "const HEADER = '-----BEGIN " + "PRIVATE KEY-----';\n"),
    ("public key", "-----BEGIN PUBLIC KEY-----\n" + PEM_BODY + "\n"),
    ("long minified line", "x=" + "a1" * 5000 + "\n"),
    ("git sha in a name", "release_sha: 0123456789abcdef0123456789abcdef01234567\n"),
    ("comment about tls", "# never set verify=False in production\n"),
    ("verify true", "requests.get(url, verify=True)\n"),
    ("unrelated VERIFY variable", "VERIFY=false ./deploy.sh\n"),
    ("compose without privilege", "services:\n  web:\n    image: nginx\n    privileged: false\n"),
    ("docker host env", "DOCKER_HOST: unix:///var/run/docker.sock\n"),
]

TLS_CONTENT: list[str] = [
    "requests.get(url, verify=False)\n",
    "client = httpx.Client(verify=False)\n",
    "ctx = ssl._create_unverified_context()\n",
    "ctx.check_hostname = False\nctx.verify_mode = ssl.CERT_NONE\n",
    "const agent = new https.Agent({ rejectUnauthorized: false });\n",
    "process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';\n",
    "tls := &tls.Config{InsecureSkipVerify: true}\n",
    "curl_setopt($c, CURLOPT_SSL_VERIFYPEER, false);\n",
    "[http]\n\tsslVerify = false\n",
    "export GIT_SSL_NO_VERIFY=1\n",
    "clusters:\n- cluster:\n    insecure-skip-tls-verify: true\n",
]

DOCKER_CONTENT: list[str] = [
    "services:\n  ci:\n    privileged: true\n",
    "services:\n  ci:\n    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock\n",
    "services:\n  ci:\n    volumes:\n      - ${SOCK}:/var/run/docker.sock\n",
    '{"privileged": true}\n',
    "docker run --privileged -it alpine\n",
    "docker run \\\n  --privileged \\\n  img\n",
]


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_template(tmp_path_factory.mktemp("template"))


@pytest.fixture
def world(tmp_path: Path, template: Path) -> World:
    return make_world(tmp_path, template)


def lines(text: str) -> list[str]:
    return text.rstrip("\n").split("\n")


@pytest.mark.parametrize(("label", "text"), SECRET_CONTENT, ids=[c[0] for c in SECRET_CONTENT])
def test_adding_a_file_with_a_credential_is_blocked(world: World, label: str, text: str) -> None:
    assert "secret-in-content" in world.patch(add_file("config.txt", *lines(text)))


@pytest.mark.parametrize(("label", "text"), SAFE_CONTENT, ids=[c[0] for c in SAFE_CONTENT])
def test_adding_ordinary_content_passes(world: World, label: str, text: str) -> None:
    assert world.patch(add_file("config.txt", *lines(text))) == []


def test_added_lines_are_scanned_and_removed_lines_are_not(world: World) -> None:
    adding = update_file("app.py", f" x = 1\n-T = ''\n+T = '{GITHUB}'")
    assert world.patch(adding) == ["secret-in-content"]
    removing = update_file("app.py", f" x = 1\n-T = '{GITHUB}'\n+T = ''")
    assert world.patch(removing) == []
    context = update_file("app.py", f" T = '{GITHUB}'\n-a = 1\n+a = 2")
    assert world.patch(context) == []


def test_every_file_in_a_patch_is_scanned(world: World) -> None:
    text = (
        "*** Begin Patch\n*** Add File: a.py\n+print('a')\n"
        f"*** Update File: b.py\n@@\n-x\n+T = '{GITHUB}'\n"
        "*** Delete File: c.py\n*** End Patch"
    )
    assert world.patch(text) == ["secret-in-content"]


def test_a_patch_with_windows_line_endings_is_read(world: World) -> None:
    assert world.patch(add_file("a.txt", f"T={GITHUB}").replace("\n", "\r\n")) == [
        "secret-in-content"
    ]


@pytest.mark.parametrize(
    "name", [".env.example", ".env.sample", ".env.template", "example.env", "config.sample.yaml"]
)
def test_generic_assignments_are_allowed_in_placeholder_files(world: World, name: str) -> None:
    assert world.patch(add_file(name, f"API_TOKEN={RANDOM_VALUE}")) == []


def test_a_move_judges_content_by_the_new_name(world: World) -> None:
    text = update_file("notes.txt", f"-x\n+API_TOKEN={RANDOM_VALUE}", move_to=".env.example")
    assert world.patch(text) == []


def test_specific_token_formats_are_still_blocked_in_placeholder_files(world: World) -> None:
    assert world.patch(add_file(".env.example", f"TOKEN={GITHUB}")) == ["secret-in-content"]


@pytest.mark.parametrize("text", TLS_CONTENT)
def test_tls_off_in_code_is_blocked(world: World, text: str) -> None:
    assert "tls-verify-off" in world.patch(add_file("client.cfg", *lines(text)))


def test_tls_off_mentioned_in_docs_is_allowed(world: World) -> None:
    assert world.patch(add_file("docs.md", "Never pass `verify=False`.")) == []


@pytest.mark.parametrize("text", DOCKER_CONTENT)
def test_privileged_container_in_files_is_blocked(world: World, text: str) -> None:
    assert "docker-privileged" in world.patch(add_file("compose.yaml", *lines(text)))


def test_secret_in_docs_is_still_blocked(world: World) -> None:
    assert "secret-in-content" in world.patch(add_file("README.md", f"key {GITHUB}"))


@pytest.mark.parametrize(
    "text",
    ["", "just some text", "--- a/x\n+++ b/x\n@@\n+y", "*** Add File: x\n+y"],
    ids=["empty", "text", "unified diff", "no begin line"],
)
def test_text_that_is_not_a_patch_cannot_be_judged(world: World, text: str) -> None:
    assert world.patch(text) == ["cannot-decide"]


# --- guardrails' own files ----------------------------------------------------------


def test_adding_the_allowlist_is_tamper(world: World) -> None:
    assert world.patch(add_file(".codex/guardrails-allow.txt", "git-push-protected")) == [
        "guardrails-tamper"
    ]
    absolute = str(world.repo / ".codex" / "guardrails-allow.txt")
    assert world.patch(update_file(absolute, "-a\n+b")) == ["guardrails-tamper"]
    elsewhere = str(world.home / "elsewhere" / "guardrails-allow.txt")
    assert world.patch(add_file(elsewhere, "x")) == ["guardrails-tamper"]


def test_deleting_or_moving_onto_or_off_the_allowlist_is_tamper(world: World) -> None:
    assert world.patch(delete_file(".codex/guardrails-allow.txt")) == ["guardrails-tamper"]
    onto = update_file("notes.txt", "-a\n+b", move_to=".codex/guardrails-allow.txt")
    assert world.patch(onto) == ["guardrails-tamper"]
    off = update_file(".codex/guardrails-allow.txt", "-a\n+a", move_to="notes.txt")
    assert world.patch(off) == ["guardrails-tamper"]


def test_the_hook_script_and_hooks_files_are_tamper(world: World) -> None:
    installed = world.codex_home / "skills" / "guardrails-help" / "scripts" / "guardrails.py"
    for path in (
        SCRIPT,
        installed,
        HOOKS_JSON,
        world.codex_home / "hooks.json",
        world.repo / ".codex" / "hooks.json",
        world.repo / "sub" / ".codex" / "hooks.json",
        world.data / "blocks.log",
    ):
        assert world.patch(update_file(str(path), "-a\n+b")) == ["guardrails-tamper"], path


def test_relative_paths_resolve_against_the_session_directory(world: World) -> None:
    assert world.patch(add_file("hooks.json", "{}")) == []
    assert world.patch(add_file("hooks.json", "{}"), cwd=world.codex_home) == ["guardrails-tamper"]


def test_a_link_to_a_guarded_file_is_that_file(world: World) -> None:
    link = world.repo / "notes.txt"
    link.symlink_to(world.codex_home / "hooks.json")
    assert world.patch(update_file("notes.txt", "-a\n+b")) == ["guardrails-tamper"]


@pytest.mark.parametrize(
    "hunk",
    [
        "+[features]\n+hooks = false",
        " [features]\n-hooks = true\n+hooks = false",
        "+[features]\n+codex_hooks = false",
        '+[hooks.state."user:pre_tool_use:0:0"]\n+enabled = false',
        ' [hooks.state."user:pre_tool_use:0:0"]\n+enabled = false',
        ' [hooks.state."user:pre_tool_use:0:0"]\n-trusted_hash = "sha256:abc"',
        "+allow_managed_hooks_only = true",
    ],
    ids=["feature off", "flip", "old alias", "state disabled", "state in context", "untrust",
         "managed only"],
)  # fmt: skip
def test_config_toml_edits_that_switch_hooks_off_are_tamper(world: World, hunk: str) -> None:
    for path in (world.codex_home / "config.toml", world.repo / ".codex" / "config.toml"):
        assert world.patch(update_file(str(path), hunk)) == ["guardrails-tamper"], path


def test_ordinary_config_toml_edits_pass(world: World) -> None:
    path = str(world.codex_home / "config.toml")
    assert world.patch(update_file(path, ' model = "a"\n-effort = "low"\n+effort = "high"')) == []
    assert world.patch(update_file(path, " [features]\n+memories = false")) == []


def test_deleting_codex_config_toml_is_tamper(world: World) -> None:
    assert world.patch(delete_file(str(world.codex_home / "config.toml"))) == ["guardrails-tamper"]
    assert world.patch(delete_file(str(world.repo / "config.toml"))) == []


# --- apply_patch through the shell --------------------------------------------------


def test_a_patch_fed_to_apply_patch_in_the_shell_is_judged(world: World) -> None:
    secret = f"apply_patch <<'EOF'\n{add_file('x.txt', f'TOKEN={GITHUB}')}\nEOF"
    assert world.bash(secret) == ["secret-in-content"]
    tamper = f"apply_patch <<'EOF'\n{add_file('.codex/guardrails-allow.txt', 'x')}\nEOF"
    assert world.bash(tamper) == ["guardrails-tamper"]
    assert world.bash(f"apply_patch <<'EOF'\n{add_file('x.txt', 'hello')}\nEOF") == []


def test_the_hook_matcher_selects_shell_and_patch_calls_only() -> None:
    matcher = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0][
        "matcher"
    ]
    for tool in ("Bash", "apply_patch"):
        assert re.search(matcher, tool), tool
    for tool in ("mcp__fs__write_file", "update_plan", "Bash2", "my_apply_patch"):
        assert not re.search(matcher, tool), tool


def test_other_tools_are_ignored(world: World) -> None:
    assert world.rules("mcp__fs__read_file", path=str(world.repo / ".env")) == []
    assert world.rules("update_plan", plan=[]) == []
