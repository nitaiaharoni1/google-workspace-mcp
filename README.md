# google-workspace-mcp

Five aligned MCP servers for Google Workspace: **Gmail**, **Calendar**,
**Sheets**, **Docs**, and **Drive**. They share one credential store and one runtime core, so they behave
identically and support:

- **Persistent auth**: log in once; tokens are reused and access tokens refresh
  silently. Server restarts never re-prompt for consent.
- **Multiple accounts in parallel**: every tool takes an `account` argument
  (email or alias). Calls for different accounts use separate, cached clients and
  never interfere.
- **Many operations**: ~43 Gmail tools, ~24 Calendar tools, ~47 Sheets tools (incl. text editing),
  ~32 Docs tools, ~22 Drive tools, plus shared `list_accounts` / `whoami` /
  `auth_status` on every server.

## Architecture

```
google-auth-core      shared ~/.google token store + authorized-service cache
        |                     (also used by gmail-cli and google-calendar-cli)
        v
google_workspace_mcp/
  core/      build_server, account resolution + warm-client cache, error
             mapping, the read-only gate, the response envelope, common tools
  gmail/     wraps gmail_cli.api.GmailAPI            -> gmail-mcp
  calendar/  wraps google_calendar_cli.api.CalendarAPI -> gcal-mcp
  sheets/    SheetsAPI (Sheets API v4)               -> gsheets-mcp
  docs/      DocsAPI (Docs API v1)                   -> gdocs-mcp
  drive/     DriveAPI (Drive API v3)                 -> gdrive-mcp
```

Every tool: takes `account`, resolves it, gets a cached per-account client,
runs the Google call through shared error mapping, and returns
`{"ok": true, "account": "<resolved>", "data": ...}`.

### Docs (`gdocs-mcp`)

- **Markdown in/out** — `create_document_from_markdown`, `append_markdown`, and
  `replace_document_with_markdown` let an agent write plain markdown while Google
  converts it to native headings, lists, links, and tables; `read_document_as_markdown`
  round-trips it back.

### Sheets (`gsheets-mcp`)

- **Human-readable layouts** — `write_table` writes data and formats it as a native
  table (or banded range) in one call; `optimize_layout` sizes every column to its
  content with a width cap, wraps only what must wrap, and auto-fits row heights.
  Header freezing is opt-in.

## Install

```bash
pip install google-workspace-suite-mcp
```

This pulls in the shared `google-auth-core` token store and the
`gmail-cli-oauth` / `google-calendar-cli` clients automatically, and installs
six console scripts onto your PATH: the five servers (`gmail-mcp`, `gcal-mcp`,
`gsheets-mcp`, `gdocs-mcp`, `gdrive-mcp`) plus the `google-auth` CLI used to log
in (see below).

If you prefer an isolated install with [pipx](https://pipx.pypa.io):

```bash
pipx install google-workspace-suite-mcp
```

For local development from a clone:

```bash
pip install -e .[dev]
```

## Authenticate (once)

Auth is **out-of-band**: the servers are non-interactive token consumers. You
log in once with the bundled `google-auth` CLI, which writes a unified token to
`~/.google/`; every server then reads and silently refreshes it.

**Quick start (recommended):**

```bash
google-auth setup you@example.com   # wizard: OAuth client → login → API check → .mcp.json
google-auth doctor                  # verify setup anytime
```

The wizard walks you through creating a Desktop OAuth client in Google Cloud
Console, logging in, confirming the five APIs are enabled, and prints
ready-to-paste `.mcp.json` snippets with absolute paths (required by GUI clients
that do not inherit your shell PATH).

You bring your **own** Google OAuth client. There is no shared client embedded
in the package: Gmail and Drive are Google "restricted" scopes, so a shared
published client would require Google's security assessment. With your own
client used in "testing" mode (you add yourself as a test user) you skip
verification entirely.

### Manual setup (appendix)

**1. Create an OAuth client** in the [Google Cloud Console](https://console.cloud.google.com):

- Create or select a project.
- Enable the APIs you need: Gmail, Google Calendar, Google Sheets, Google Docs,
  Google Drive.
- *APIs & Services → OAuth consent screen* → **External** → add your own Google
  address under **Test users**.
- *APIs & Services → Credentials → Create credentials → OAuth client ID* →
  application type **Desktop app** → **Download JSON**.
- Save that file as `~/.google/credentials.json`.

**2. Log in:**

```bash
google-auth login you@example.com      # opens a browser, writes a unified token
google-auth alias work you@example.com # optional short alias
google-auth login you@personal.com     # add more accounts
google-auth list                       # show accounts, default, aliases
google-auth status                     # show token + scope health
google-auth doctor                     # diagnose setup issues
```

A single login grants Gmail + Calendar + Sheets + Docs + Drive scopes, shared by
both the CLIs and the MCP servers. If a token is ever missing or scope-short, a
tool returns an actionable error (`Run: google-auth login <account>`) rather
than blocking the protocol.

## Register with Claude

`claude mcp add` or a `.mcp.json` like:

```json
{
  "mcpServers": {
    "google-gmail":    { "command": "gmail-mcp" },
    "google-calendar": { "command": "gcal-mcp" },
    "google-sheets":   { "command": "gsheets-mcp" },
    "google-docs":     { "command": "gdocs-mcp" },
    "google-drive":    { "command": "gdrive-mcp" }
  }
}
```

Bare command names work when the install location is on your PATH (e.g. a
`pipx install`, or an activated venv). GUI clients such as Claude Desktop and
Cursor do not inherit your shell PATH, so give them the absolute path to each
script instead (`which gmail-mcp` to find it). Register at user scope to make
the servers available in every project.

Restart Claude after editing.

## Multiple accounts

Pass `account` to any tool (omit it to use the default):

```
list_messages(account="work", query="is:unread")
create_event(account="you@personal.com", summary="Dinner", start_time=..., end_time=...)
read_range(account="work", spreadsheet_id="...", range="Sheet1!A1:C10")
```

## Read-only mode

Set `GOOGLE_MCP_READONLY=1` in a server's environment to hide every mutating
tool (writes, deletes, clears) from that server. Destructive tools are also
clearly marked in their descriptions.

Every tool advertises MCP-native `ToolAnnotations` (`readOnlyHint`,
`destructiveHint`) in `list_tools`, derived from the same flags that drive the
read-only gate. Annotations are hints for well-behaved clients (auto-allow reads,
confirm destructive writes); `GOOGLE_MCP_READONLY` remains the enforcement
mechanism — clients must not rely on annotations alone for security.

## Testing

```bash
pip install -e .[dev]
pytest                     # unit, protocol (in-memory), isolation, persistence
ruff check .               # minimal lint (import order, syntax, pyflakes)
GOOGLE_MCP_LIVE=1 pytest   # opt-in live smoke tests (needs a real test account)
```

## Notes

- Auth is out-of-band: servers are non-interactive token consumers. If a token
  is missing or scope-short, a tool returns an actionable error
  (`Run: google-auth login <account>`) instead of blocking the protocol.
- The five servers are packaged as one distribution with five console-script
  entry points (a single `pip install`), rather than five separate packages.
  Alignment comes from the shared `core`, not from separate packaging.
