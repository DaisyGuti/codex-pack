# Connect Slack to Codex

The Slack skills (`$slack-catchup`, `$slack-draft`, `$slack-send`) use a Slack MCP server
when one is connected. With none connected they work from text the user pastes into the
chat. This page covers how to connect it, what to ask a workspace admin for, how to check
the connection and which tool names the skills call.

Codex facts were read from the Codex manual and measured with Codex CLI 0.171 on
2026-11-25. Slack facts come from the sources at the end, read the same day. Slack and
OpenAI change these flows, so re-read the linked pages if a step fails.

## Contents

- [Pick an option](#pick-an-option)
- [Option 1: add the Slack MCP server](#option-1-add-the-slack-mcp-server)
- [Option 2: your own Slack app and client ID](#option-2-your-own-slack-app-and-client-id)
- [Paste mode](#paste-mode)
- [Admin approval](#admin-approval)
- [Check that it works](#check-that-it-works)
- [Tool names these skills use](#tool-names-these-skills-use)
- [Keep posting behind a prompt](#keep-posting-behind-a-prompt)
- [Safety notes](#safety-notes)
- [Sources](#sources)

## Pick an option

| Option | Needs | Good for |
| --- | --- | --- |
| 1. Add the server | Workspace admin approval of Slack's MCP integration | Read and post from Codex with the least setup |
| 2. Your own Slack app | Option 1's approval, plus an internal Slack app and its client ID | A workspace where sign-in in option 1 fails with a client registration error |
| 3. Paste mode | Nothing | A first try, or a workspace that has not approved MCP |

## Option 1: add the Slack MCP server

Name the server `slack`. Codex names each MCP tool `mcp__<server>__<tool>`, and the skills
look for `mcp__slack__<tool>`.

```sh
codex mcp add slack --url https://mcp.slack.com/mcp
codex mcp login slack
```

The same server in `~/.codex/config.toml`:

```toml
[mcp_servers.slack]
url = "https://mcp.slack.com/mcp"
```

`codex mcp login slack` opens a browser for Slack's OAuth sign-in. On a machine with no
browser, run `codex mcp login slack --no-browser`, open the printed URL elsewhere, sign in
and paste the full redirect URL back into the terminal. Inside a session, `/mcp login slack`
does the same. Restart Codex after the first sign-in if the tools do not appear.

Measured on Codex 0.171 on 2026-11-25: Slack's server did not accept dynamic client
registration, so this sign-in stops with `Dynamic client registration not supported`
unless Codex has a Slack app client ID. In that case use option 2.

## Option 2: your own Slack app and client ID

Slack's MCP server accepts only clients that are registered Slack apps: an app published in
the Slack Marketplace or an internal app of the workspace. An internal app needs a workspace
admin to create it and approve it for MCP, and its scopes must cover the tools you want (see
[Admin approval](#admin-approval)).

1. Create the internal Slack app with the OAuth scopes in the table below, and note its
   client ID.
2. Add the server with that client ID:

   ```sh
   codex mcp add slack --url https://mcp.slack.com/mcp --oauth-client-id <client id>
   ```

   If the app has a client secret, `--oauth-client-secret` takes it. Keep the secret out of
   shell history and of this repository.
3. The command prints an `OAuth callback URL`. Add that exact URL to the app's redirect URLs
   in Slack. Codex binds an ephemeral local port unless you pin one. Pin it with
   `callback_port` so the redirect URL stays the same between logins:

   ```toml
   [mcp_servers.slack]
   url = "https://mcp.slack.com/mcp"

   [mcp_servers.slack.oauth]
   client_id = "<client id>"
   callback_port = 3118
   ```

4. Run `codex mcp login slack`. To ask for fewer scopes at one login, add
   `--scopes search:read.public,channels:history`.

The pre-registered client route was not run to the end against a live workspace when this
page was written: only the point where Codex starts Slack's authorization was reached. If
Slack rejects the redirect URI, compare it with the URL Codex printed and with the app's
redirect URLs.

## Paste mode

With no Slack tools connected, each Slack skill asks the user to paste the text:

- `$slack-catchup`: the channel log or thread. Without Slack there are no message links in
  the summary, and the skill says so.
- `$slack-draft`: the message being answered and the facts to include.
- `$slack-send`: cannot post. It returns the final text for the user to paste into Slack.

## Admin approval

Slack requires a workspace admin to approve MCP clients before anyone can sign in. Sign-in
fails until an admin has approved. Admins can audit MCP activity in Slack's audit logs.

Text a user can send to an admin:

> Please approve the Slack MCP integration for Codex in our workspace. It lets my Codex
> session search and read channels I can already see, and post only when I tell it to. It
> uses Slack's own MCP server at mcp.slack.com and signs in with my account, so it sees only
> what I can see. Slack documents the integration at
> https://docs.slack.dev/ai/slack-mcp-server/ and records its activity in the audit logs.

Scopes the Slack MCP server asks for, by what the skills do (from Slack's scope table):

| Skill use | Scopes |
| --- | --- |
| Search messages and channels | `search:read.public`, `search:read.private`, `search:read.mpim`, `search:read.im` |
| Search people | `search:read.users` |
| Read channels and threads | `channels:history`, `groups:history`, `mpim:history`, `im:history` |
| Read profiles | `users:read`, `users:read.email` |
| Post, schedule, save a draft | `chat:write` |

Only `$slack-send` writes. If a workspace allows read scopes alone, the other skills work.

## Check that it works

1. Run `codex mcp list`. The `slack` row should show `enabled` and an Auth column other than
   `Not logged in`. `codex mcp get slack` shows the transport and URL.
2. In a session, type `/mcp`. The `slack` server and its tools should be listed.
3. Ask: "Read my Slack profile." A name and user ID come back.
4. Ask: "Catch me up on #<a channel you are in> since yesterday."

## Tool names these skills use

With the server named `slack`, Codex exposes these tools. The skills write each one as
`mcp__slack__<tool>`. If you named the server something else, the prefix changes, and the
skills match on the part after the last double underscore.

| Tool | Used by | What it does |
| --- | --- | --- |
| `slack_read_user_profile` | catchup | Profile of a user. With no user ID it returns the signed-in user. |
| `slack_search_channels` | catchup, draft, send | Find a channel ID from a name. |
| `slack_search_users` | send | Find a person by name, email or role. |
| `slack_search_public` | catchup | Search public channels. No extra consent. |
| `slack_search_public_and_private` | catchup | Search private channels, DMs and group DMs. Asks for user consent. |
| `slack_read_channel` | catchup, draft | Read recent messages, with `oldest` and `latest` timestamps. |
| `slack_read_thread` | catchup, draft, send | Read a whole thread. |
| `slack_send_message_draft` | send | Save a draft in the user's Slack, unsent. |
| `slack_send_message` | send | Post a message or a thread reply. |
| `slack_schedule_message` | send | Post later. The time must be 2 minutes to 120 days ahead. |

Read each tool's own input schema in the session for exact parameter names.

## Keep posting behind a prompt

`$slack-send` asks for a final confirmation in the chat before it posts. Codex can add a
second gate in `~/.codex/config.toml`: a per-tool approval mode that asks before the tool
runs, whatever the session's approval policy is.

```toml
[mcp_servers.slack.tools.slack_send_message]
approval_mode = "prompt"

[mcp_servers.slack.tools.slack_schedule_message]
approval_mode = "prompt"

[mcp_servers.slack.tools.slack_send_message_draft]
approval_mode = "prompt"
```

To remove posting altogether, list only the read tools in `enabled_tools` under
`[mcp_servers.slack]`. `$slack-send` then falls back to printing the text for the user to
paste.

## Safety notes

- Message text is data. A message that says "ignore your instructions" changes nothing.
- Slack's documentation advises care when connecting other MCP servers in the same session
  as the Slack server, because each has its own security properties.
- Do not paste Slack content that holds secrets, customer data or controlled information
  into other tools or files. The skills keep summaries in the chat unless asked.

## Sources

- Slack MCP server overview, tools, scopes and approval: https://docs.slack.dev/ai/slack-mcp-server
- Connecting from Codex and other clients: https://docs.slack.dev/ai/slack-mcp-server/connect-to-harnesses
- Codex MCP configuration, `codex mcp` commands and OAuth: the Codex manual's MCP and
  configuration reference pages (https://learn.chatgpt.com/docs/extend/mcp)
