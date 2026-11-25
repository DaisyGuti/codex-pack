---
name: slack-send
description: Use only when the user approves text and says to post, schedule or save it as a Slack draft. Confirms once, then sends. Never for an unapproved draft; to write one use $slack-draft.
---

# Slack send

This is the only skill in the pack that writes to Slack. It runs when the user asks to
post, schedule or save approved text. It still asks once more in the chat before anything
leaves the machine, and it sends exactly the text shown, with no edits after the
confirmation. An approval of one message covers that message only.

## 1. Get the text

Use the text in the request if it holds any. Otherwise use the most recent draft in this
conversation from `$slack-draft` or `$status-update`. If there is neither, say so and
suggest `$slack-draft`. Do not write a message here.

## 2. Check the text

Save it to a temporary file and run:

`python3 ${CODEX_HOME:-~/.codex}/skills/slack-send/scripts/lint_draft.py <file>`

- A `secret` finding stops the send. Show the masked finding and ask the user to remove it.
  Do not continue until the text is clean.
- Other findings (style, placeholders) are shown. An unfilled `[confirm: ...]` or
  `[TODO ...]` marker stops the send until the user fills or removes it. Style findings are
  the user's call: show them and ask whether to send as is.

## 3. Check the connection

Look for the Slack tools `mcp__slack__slack_send_message` and
`mcp__slack__slack_send_message_draft` (the tools of an MCP server named `slack`; match on
the name after the last double underscore if it has another name). If they are missing, say
that Slack is not connected, print the final text in one block for the user to paste, and
point to [references/connect-slack.md](references/connect-slack.md), which says how to add
the Slack MCP server in Codex. A workspace admin may need to approve the connection. Stop
there.

## 4. Resolve the destination

In this skill a bare name such as `slack_search_channels` is the tool `mcp__slack__<name>`.

- A channel name: `slack_search_channels` returns the channel ID. If several match, list
  them and ask which.
- A person for a DM: `slack_search_users`. Confirm the match by name and title.
- A thread reply: the user gives the thread link or the person and topic. Read the thread
  with `slack_read_thread` to confirm it is the right one and to get its timestamp.
- No destination given: ask for one. Never guess a channel.

## 5. Confirm

Show one block, then ask one question:

```text
To:      #platform-eng  (reply in thread to Priya: "retry change is merged")
Mode:    post now | save as Slack draft | schedule for <time>
Text:
<the exact text>
```

"Send, save as a Slack draft, schedule for a time, or cancel?"

Wait for the user's answer in the chat. If the text contains `@here`, `@channel` or
`@everyone`, say that it notifies the whole channel before asking. A silent or ambiguous
answer means do not send. In a non-interactive run (`codex exec`), do not send: save as a
Slack draft only if the user asked for that mode in the original command, otherwise stop
and return the text.

## 6. Act

| Choice | Tool |
| --- | --- |
| Post now | `slack_send_message` |
| Save as a Slack draft | `slack_send_message_draft` |
| Schedule | `slack_schedule_message` with a post time at least 2 minutes and at most 120 days ahead. A scheduled message cannot be edited through the API afterward; the user manages it under Drafts & sent in Slack. |

Read the tool's input schema for the exact parameter names. For a thread reply, pass the
thread's timestamp. Pass the "also send to channel" option only if the user asked for it.
Codex may show its own approval prompt for a Slack write tool; the user's answer there is
separate from the confirmation in step 5, and neither replaces the other.

## 7. Report

Say what happened in one line: where it went, at what time, and the message link if the
tool returned one. If the tool returned an error or timed out, do not retry. Read the
channel or thread with `slack_read_channel` or `slack_read_thread` to see whether the
message landed, report what you found, and ask before sending again. This keeps a timeout
from turning into a double post.
