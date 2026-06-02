# Google Workspace MCP servers (Gmail, Calendar, Sheets)

Date: 2026-06-02
Status: Approved design, pending implementation plan
Author: Nitai + Claude (master-engineer mode)

## 1. Goal

Provide three aligned MCP servers (Gmail, Calendar, Sheets) that:

1. Expose many operations per service (not a thin read-only slice).
2. Keep a persistent connection: authenticate once, never re-consent on
   subsequent calls or server restarts. Access tokens refresh silently.
3. Support multiple Google accounts used in parallel without interference.
4. Behave identically across all three services (same account semantics,
   response envelope, error taxonomy, naming, and shared utility tools).

## 2. Non-goals (YAGNI for v1)

- No combined mega-server. One server per service.
- No new full CLI for Sheets (only an ops class). A Sheets CLI can come later.
- No Google Slides / Drive / Docs servers in this iteration (Slides already
  exists as a separate repo and can be migrated to this pattern later).
- No web/SSE transport in v1. stdio only (what Claude Code and Desktop use).
- No interactive OAuth inside the MCP protocol. Auth is out-of-band.

## 3. Current state and reusable assets

Two auth conventions exist today:

- Python CLIs (`gmail-cli`, `google-calendar-cli`) share a mature store at
  `~/.google/`: per-account unified tokens (`tokens/google_<account>.json`
  holding all scopes), `config.json` (accounts, default, aliases),
  `credentials.json` (OAuth client, Desktop type), plus auto-refresh and
  scope-health checks. This already delivers persistence and multi-account.
- `google-slides-mcp` (TypeScript) uses a weaker pattern: a single
  `~/.google-slides-mcp/tokens.json`, a module-level singleton OAuth client
  (not multi-account safe), and env-var client credentials.

We standardize on the stronger Python pattern. We do NOT align down to the
slides MCP singleton.

Reusable code:

- `gmail_cli.api.GmailAPI(account=None)`: about 40 operations, returns plain
  dicts/lists. Multi-account ready.
- `google_calendar_cli.api.CalendarAPI(account=None)`: about 24 operations.
  Multi-account ready.
- `shared_auth.py`: currently duplicated (near-identical) in both CLIs. This
  duplication is removed by extracting `google-auth-core`.
- CLI `retry.py`: backoff helper, reused for the shared retry policy.

Installed and verified locally: `mcp` 1.26.0, `google-api-python-client` 2.190.0.

## 4. Architecture

Two new packages plus migrations of two existing repos.

```
google-auth-core/              # standalone package: single source of truth for ~/.google
  auth.py        # extracted from shared_auth.py (token load/refresh/health, scopes)
  accounts.py    # resolve / list / alias / default-account logic
  service.py     # get_service(api, version, account) + process-level service cache
  errors.py      # exception taxonomy + googleapiclient HttpError mapping

google-workspace-mcp/          # monorepo: scaffolding + three servers
  packages/core/               # mcp-core (depends on google-auth-core)
    server.py    # build_server(name, register_fn): FastMCP + shared tools + readonly gate
    envelope.py  # response shape
    retry.py     # backoff (reuses CLI retry pattern)
    tools_common.py  # list_accounts, whoami, auth_status
  packages/gmail/              # gmail-mcp:  wraps gmail_cli.api.GmailAPI
  packages/calendar/           # gcal-mcp:   wraps google_calendar_cli.api.CalendarAPI
  packages/sheets/             # gsheets-mcp: new SheetsAPI + server
  tests/  (unit, protocol, live)
  .github/workflows/ci.yml

gmail-cli/                     # MIGRATE: import google-auth-core, delete bundled shared_auth.py
google-calendar-cli/           # MIGRATE: same
```

Dependency direction is acyclic:

```
google-auth-core
   ^            ^
   |            |
  CLIs       mcp-core
   ^            ^
   |            |
  (gmail/calendar servers depend on core + the matching CLI for its API class)
  (sheets server depends on core only; SheetsAPI is new)
```

`google-auth-core` depends on nothing of ours, so migrating the CLIs to it
creates no cycle.

## 5. Authentication and persistence

### Token store (unchanged location)

- `~/.google/credentials.json`: OAuth client (Desktop app).
- `~/.google/config.json`: accounts list, default account, aliases.
- `~/.google/tokens/google_<account>.json`: per-account unified token holding
  all scopes (Gmail + Calendar + Sheets).

### Unified scopes

`ALL_SCOPES` in `google-auth-core` gains the Sheets scope:

```
https://www.googleapis.com/auth/spreadsheets
```

(in addition to the existing Gmail and Calendar scopes). A single consent
covers all three services for both the CLIs and the MCP servers.

### Out-of-band auth

MCP servers run over stdio and must not block the protocol with a browser
flow. Therefore:

- A `google-auth` console script (in `google-auth-core`) runs the one-time
  `InstalledAppFlow`, writing a unified token. Subcommands: `login <account>`,
  `list`, `alias <name> <email>`, `status`, `logout <account>`.
- The existing CLIs continue to authenticate too; because scopes are unified,
  any one of them establishes the token the MCPs read.
- MCP servers are strictly token consumers. If a token is missing or
  scope-short for the requested account, the tool returns an actionable error:
  `No valid credentials for <account>. Run: google-auth login <account>`.

### Runtime persistence (the "persistent connection")

- `google-auth-core.service.get_service(api, version, account)` builds an
  authorized `googleapiclient` service and caches it in a process-level dict
  keyed by `(account, api, version)`, guarded by a lock.
- The long-lived stdio server reuses warm clients across tool calls.
- Access tokens refresh silently via the stored refresh token. On a 401 the
  cache entry is invalidated and rebuilt once.
- On server restart the token is reloaded from disk; no re-consent.

## 6. Multi-account in parallel

- Every tool accepts optional `account: str | None`, an email or an alias
  (e.g. `work`, `personal`).
- Resolution precedence (reused from existing logic): explicit arg, then
  service env var, then nearest `.google-account` file walking up the cwd,
  then `config.json` default.
- Each call resolves to that account's own cached service. There is no
  module-level singleton client (the defect in the current slides MCP).
- Concurrent calls for different accounts use different cache entries and
  different credentials, so they cannot interfere. This is enforced by an
  explicit concurrency test (see Testing).

## 7. Alignment contract

All three servers are produced by `mcp-core.build_server()` and therefore share:

- Account parameter and resolution semantics.
- Response envelope: `{ "ok": true, "account": "<resolved>", "data": ... }`,
  with optional `page_token` for paginated reads.
- Error taxonomy mapped from `googleapiclient.HttpError`:
  `AuthError`, `NotFoundError`, `RateLimitError` (429, includes retry hint),
  `InvalidArgumentError`, `UpstreamError`. Raised as MCP errors with a
  consistent message shape.
- Shared exponential backoff for 429 and 5xx (reused from CLI `retry.py`).
- Three common tools present in every server: `list_accounts`, `whoami`,
  `auth_status` (per-account token health).
- Naming convention: `verb_noun` (`list_messages`, `send_message`,
  `list_events`, `create_event`, `read_range`, `update_range`).
- Read-only gate: when `GOOGLE_MCP_READONLY=1`, every mutating tool is hidden
  from `list_tools` and refuses execution. Destructive tools are marked in
  their descriptions.

## 8. Tool surfaces

Curated from existing operations; target 15 to 22 tools per server. Mutating
and destructive tools honor the read-only gate. Destructive tools are flagged.

### Gmail (wraps GmailAPI)
- Read: `list_messages`, `search_messages`, `get_message`, `list_threads`,
  `get_thread`, `list_labels`, `get_profile`.
- Write: `send_message`, `reply_to_message`, `forward_message`,
  `create_draft`, `update_draft`, `list_drafts`, `get_draft`.
- Modify: `modify_labels` (add/remove), `mark_read`, `archive_message`,
  `star_message`, `create_label`, `update_label`, `create_filter`,
  `list_filters`.
- Destructive: `trash_message`, `untrash_message`, `delete_message`
  (permanent), `delete_label`, `delete_filter`, `batch_trash`,
  `batch_delete`.

### Calendar (wraps CalendarAPI)
- Read: `list_calendars`, `get_calendar`, `list_events`, `search_events`,
  `get_event`, `get_recurring_instances`, `freebusy`, `find_available_slots`,
  `get_colors`.
- Write: `create_event`, `update_event`, `quick_add_event`, `move_event`,
  `add_attendees`, `remove_attendees`, `create_calendar`, `update_calendar`.
- Destructive: `delete_event`, `delete_calendar`, `clear_calendar`.

### Sheets (new SheetsAPI)
- Read: `get_spreadsheet` (metadata), `read_range` (values.get),
  `batch_read` (values.batchGet).
- Write: `create_spreadsheet`, `update_range` (values.update),
  `batch_update_values` (values.batchUpdate), `append_rows` (values.append),
  `add_sheet`, `rename_sheet`.
- Destructive: `clear_range` (values.clear), `delete_sheet`.

Sheets defaults: `valueInputOption=USER_ENTERED` for writes,
`valueRenderOption=FORMATTED_VALUE` for reads, both overridable. Ranges use
A1 notation.

## 9. CLI migration

- Create `google-auth-core` from the current `shared_auth.py`, adding the
  Sheets scope and the `get_service` + cache helper.
- Update `gmail-cli` and `google-calendar-cli` to depend on `google-auth-core`
  and delete their bundled `shared_auth.py`. Their `auth.py` keeps the same
  public functions by re-exporting from the package, so the rest of each CLI
  is untouched.
- Re-run each CLI's existing test suite to confirm no regression.
- Existing tokens remain valid; on next auth they gain the Sheets scope.

## 10. Testing strategy

A test pyramid. Items 1 to 5 run in CI with no credentials. Item 6 is opt-in.

1. Unit (mocked Google): patch `googleapiclient.discovery.build` to return a
   mock service whose `.execute()` returns canned payloads. Assert each tool
   builds the correct API call and returns the correct envelope.
2. Auth and resolution: temp `$HOME/.google`. Test default precedence, alias
   resolution, scope-health states (valid, expired-refreshable, scope
   mismatch, missing), and the silent-refresh path (mock `creds.refresh`).
3. Isolation (key requirement): `asyncio.gather` a tool call for account A and
   account B; assert each used only its own credentials and cache entry, and
   that neither read the other's token file.
4. MCP protocol (in-memory): use the SDK in-memory `Client(app)` to
   `list_tools()` and `call_tool()` per server; assert the tool registry
   (names, schemas) and that envelopes round-trip through MCP content. Also
   assert the read-only gate hides mutating tools when `GOOGLE_MCP_READONLY=1`.
5. Persistence: instantiate a server twice against the same temp store; assert
   it loads from disk and never triggers the interactive flow (patched to
   raise if called); assert an expired access token triggers silent refresh,
   not re-consent.
6. Live smoke (opt-in, `GOOGLE_MCP_LIVE=1`, disposable test account):
   - Gmail: list one message, get profile.
   - Calendar: list calendars, list today's events.
   - Sheets: create a temp spreadsheet, write a cell, read it back, delete it.
   - Multi-account live: same read against two configured test accounts,
     assert distinct identities.
7. CI: GitHub Actions runs items 1 to 5. Live tests are manual.
8. Manual end-to-end: register all three via `claude mcp add`, then from the
   agent send a self-email, create and read a sheet, create a calendar event,
   and run one operation against two accounts to confirm isolation.

## 11. Distribution

- Each server is a pip-installable package with a console script entry point
  (`gmail-mcp`, `gcal-mcp`, `gsheets-mcp`) and an stdio `main()`.
- `google-auth` console script ships with `google-auth-core`.
- Document `claude mcp add` snippets for each server.
- Add Homebrew formulae to the existing `homebrew-tools` tap once published.

## 12. Risks and mitigations

- Touching working CLIs during migration: mitigate by keeping each CLI's
  public auth functions as re-exports and re-running their test suites.
- Reusing CLI `api.py` as a library: the classes already take `account=` and
  return plain data, so the coupling is low. If it becomes awkward, extract the
  ops classes into their own packages later.
- Token scope upgrade (adding Sheets) forces a one-time re-consent per account.
  Acceptable and expected; documented in `google-auth login`.
- Rate limits across parallel accounts: shared backoff plus per-call accounts
  keep quota usage attributable and bounded.

## 13. Sequencing (high level; detailed plan via writing-plans)

1. `google-auth-core` (extract, add Sheets scope, add `get_service` + cache).
2. Migrate both CLIs; re-run their tests.
3. `mcp-core` scaffolding (build_server, envelope, errors, retry, common tools,
   readonly gate).
4. Gmail server, then Calendar server (thin wrappers).
5. `SheetsAPI` + Sheets server.
6. Test suite (unit, auth, isolation, protocol, persistence), then CI.
7. Live smoke + manual end-to-end verification.
8. Packaging, docs, Homebrew formulae.
