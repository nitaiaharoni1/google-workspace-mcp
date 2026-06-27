# google-workspace-mcp

Five aligned MCP servers for Google Workspace: **Gmail**, **Calendar**,
**Sheets**, **Docs**, and **Drive**. They share one credential store and one runtime core, so they behave
identically and support:

- **Persistent auth**: log in once; tokens are reused and access tokens refresh
  silently. Server restarts never re-prompt for consent.
- **Multiple accounts in parallel**: every tool takes an `account` argument
  (email or alias). Calls for different accounts use separate, cached clients and
  never interfere.
- **Many operations**: ~36 Gmail tools, ~22 Calendar tools, ~41 Sheets tools (incl. text editing),
  ~25 Docs tools, ~16 Drive tools, plus shared `list_accounts` / `whoami` /
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

## Install

```bash
pip install google-workspace-suite-mcp
```

This pulls in the shared `google-auth-core` token store and the
`gmail-cli-oauth` / `google-calendar-cli` clients automatically, and installs
the five `*-mcp` console scripts (`gmail-mcp`, `gcal-mcp`, `gsheets-mcp`,
`gdocs-mcp`, `gdrive-mcp`) onto your PATH.

For local development from a clone:

```bash
pip install -e .[dev]
```

## Authenticate (once)

Put your OAuth client (Desktop app) at `~/.google/credentials.json`, then:

```bash
google-auth login you@example.com      # opens a browser, writes a unified token
google-auth alias work you@example.com # optional short alias
google-auth login you@personal.com     # add more accounts
google-auth list                       # show accounts, default, aliases
```

A single login grants Gmail + Calendar + Sheets + Docs + Drive scopes, shared by both the CLIs
and the MCP servers.

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

(On this machine they are registered at user scope with absolute venv paths, so
they are available in every project.)

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

## Testing

```bash
pip install -e .[dev]
pytest                     # unit, protocol (in-memory), isolation, persistence
GOOGLE_MCP_LIVE=1 pytest   # opt-in live smoke tests (needs a real test account)
```

## Notes

- Auth is out-of-band: servers are non-interactive token consumers. If a token
  is missing or scope-short, a tool returns an actionable error
  (`Run: google-auth login <account>`) instead of blocking the protocol.
- The five servers are packaged as one distribution with five console-script
  entry points (a single `pip install`), rather than five separate packages.
  Alignment comes from the shared `core`, not from separate packaging.
