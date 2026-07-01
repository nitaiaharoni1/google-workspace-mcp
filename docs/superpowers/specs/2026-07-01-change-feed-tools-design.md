# Change-feed tools: what changed since I last ran (design)

**Date:** 2026-07-01
**Status:** Draft, pending review
**Author:** nitai (+ Claude)

## Problem

Scheduled and looping agents (cron agents, /loop-style pollers, inbox triage
bots) currently have no cheap way to ask "what changed since my last run".
Their only option is re-listing everything (messages, files, events) and
diffing client-side, which burns quota, tokens, and wall-clock on every tick.
Google already exposes incremental change feeds for exactly this: Gmail
`users.history.list`, Drive `changes.list`, and Calendar `events.list` with
`syncToken`. None of them is surfaced by the suite today, and no competing
Workspace MCP server surfaces them either.

Polling fits this suite's model perfectly: the servers are non-interactive
stdio token consumers with no server-side state and no public endpoint, so
push channels (watch/webhooks) are structurally out of reach, but "give me a
token, hand it back next time" needs nothing but the existing tool contract.

## Goals

- A recurring agent can poll each of Gmail, Drive, and Calendar with one
  cheap call per tick and get only the delta since its last run.
- Change tokens are opaque values the agent stores and round-trips; the
  servers never persist anything between calls.
- All new tools are read-only (bare `@register`), so they remain available
  under `GOOGLE_MCP_READONLY=1`, where a monitoring agent is most likely to
  live.
- Expired or invalid tokens fail with an actionable message that tells the
  agent exactly how to re-baseline, matching the `Run: google-auth login`
  error style.
- Tool names stay aligned across services (`get_changes_start_token` /
  `list_changes`), per the suite's alignment principle.

## Non-goals

- **Push notifications** (Gmail `users.watch` + Pub/Sub, Drive/Calendar
  `channels`): requires a public HTTPS endpoint or a Pub/Sub topic plus
  channel renewal state. Wrong shape for a local stdio server.
- **Server-side token persistence**: no "last seen" bookkeeping in
  `~/.google/` or anywhere else. The agent owns its cursor.
- **A cross-service unified feed**: each server exposes its own feed; a
  combining loop belongs in the agent, not in `core/`.
- **Sheets/Docs content diffs**: covered indirectly at the file level by the
  Drive feed; revision-level diffs are a P2 (see Requirements).

## Design summary

Three services, one pattern: a start-token call establishes a baseline, a
list call takes the token and returns normalized change entries plus the next
token to save. Tokens are returned in `data`, held by the agent, and passed
back as plain string params. Every tool follows the standard contract
(`account` first, `_api(account)`, `run_tool`, `ok(resolved, data)`).

| Service | Baseline | Incremental | Token expiry signal |
|---|---|---|---|
| Gmail | `get_changes_start_token` (profile `historyId`) | `list_changes(start_history_token)` | HTTP 404 |
| Drive | `get_changes_start_token` (`changes.getStartPageToken`) | `list_changes(page_token)` | HTTP 400 (invalid token) |
| Calendar | first `list_event_changes` call without `sync_token` | `list_event_changes(sync_token=...)` | HTTP 410 |

## Where the code lives (key decision)

The upstream wrappers cannot host this cleanly:

- `gmail_cli.api.GmailAPI` and `google_calendar_cli.api.CalendarAPI` have no
  history/syncToken support today, and both catch `HttpError` and re-raise a
  generic `Exception("Failed to ...: <error>")`. That destroys the HTTP
  status the change feed must react to (404 expired history id, 410 expired
  sync token); `core.map_exception` can only regex the status back out of the
  message, which is too fragile to build re-baseline behavior on.
- Adding methods upstream means releasing new `gmail-cli-oauth` and
  `google-calendar-cli` versions and bumping pins before this repo can ship.

So the change-feed methods live in this repo:

- **Gmail**: a small repo-local subclass,
  `google_workspace_mcp/gmail/changes_api.py`:

  ```python
  class GmailChangesAPI(GmailAPI):
      """GmailAPI plus the history-based change feed."""
  ```

  `gmail/server.py` switches its factory to the subclass
  (`_api = get_api("gmail", GmailChangesAPI, account)`). Every existing tool
  keeps working (pure inheritance), there is still exactly one warm client
  per account under the `("gmail", account)` cache key, and default-account
  resolution via `GMAIL_ACCOUNT` is preserved because the `service_name`
  stays `"gmail"`. The new methods use the inherited `self.service` directly
  and let raw `HttpError` propagate (or translate it, see per-service
  sections), instead of adopting the upstream generic-`Exception` style.

- **Calendar**: same pattern, `google_workspace_mcp/calendar/changes_api.py`
  with `class CalendarChangesAPI(CalendarAPI)`, and `calendar/server.py`
  switches its factory.

- **Drive**: `DriveAPI` is already repo-local, so the two methods are added
  to `google_workspace_mcp/drive/drive_api.py` directly.

Rejected alternative: a separate `GmailChangesAPI` built on
`core.get_service("gmail", "v1", ...)` registered under a distinct cache key
such as `"gmail-changes"`. It doubles the warm clients per account and, worse,
`get_default_account("gmail-changes")` would skip the `GMAIL_ACCOUNT` env
var, so `list_changes()` and `list_messages()` could silently resolve to
different accounts. The subclass avoids both problems.

## Gmail (P0)

Verified API surface: `users.getProfile` returns the mailbox's current
`historyId`; `users.history.list` takes `userId`, `startHistoryId`,
`historyTypes` (any of `messageAdded`, `messageDeleted`, `labelAdded`,
`labelRemoved`), `labelId`, `maxResults`, `pageToken` and returns `history[]`
records plus `nextPageToken` and the mailbox's current `historyId`. A
`startHistoryId` that is too old or invalid fails with HTTP 404 (Google keeps
history for a limited window, typically at least a week on active mailboxes).

### API methods

```python
def get_changes_start_token(self):
    # users.getProfile -> {"start_history_token": profile["historyId"],
    #                       "email": profile["emailAddress"]}

def list_changes(self, start_history_token, history_types=None,
                 label_id=None, max_results=100, page_token=None):
    # users.history.list(userId="me", startHistoryId=start_history_token,
    #                    historyTypes=history_types or None,
    #                    labelId=label_id, maxResults=max_results,
    #                    pageToken=page_token)
    # 404 -> ValueError (see error handling)
    # -> {"changes": [<normalized>], "next_page_token": ...,
    #     "new_history_token": <response historyId>}
```

Normalization flattens each `history[]` record into typed entries:

```python
{"type": "message_added",  "message_id": ..., "thread_id": ..., "label_ids": [...]}
{"type": "message_deleted", "message_id": ..., "thread_id": ...}
{"type": "labels_added",   "message_id": ..., "label_ids": [...]}
{"type": "labels_removed", "message_id": ..., "label_ids": [...]}
```

The raw `history[]` shape (nested `messages` stubs inside four parallel
arrays, plus a redundant top-level `messages` list) is a poor fit for an
agent; the flat list keeps token cost low and is trivial to iterate. Entries
carry ids only; the agent fetches bodies with the existing `get_message`.

### MCP tools

```python
@register(mcp)
def get_changes_start_token(account: str | None = None) -> dict:
    """Get a change-feed baseline token for the mailbox. Save the returned
    start_history_token and pass it to list_changes on the next run to get
    only what changed in between."""

@register(mcp)
def list_changes(account: str | None = None, start_history_token: str = "",
                 history_types: list[str] | None = None,
                 label_id: str | None = None, max_results: int = 100,
                 page_token: str | None = None) -> dict:
    """List mailbox changes since start_history_token (from
    get_changes_start_token or a previous list_changes). Returns typed
    entries (message_added / message_deleted / labels_added / labels_removed)
    plus new_history_token to save for the next poll. Page through
    next_page_token before saving the new token. history_types filters to
    e.g. ['messageAdded']; label_id filters to one label (e.g. 'INBOX')."""
```

Polling loop the docstrings teach: call `list_changes(start_history_token)`,
follow `next_page_token` until absent, then persist `new_history_token` as
the next run's `start_history_token`.

## Drive (P0)

Verified API surface: `changes.getStartPageToken` returns
`{"startPageToken": ...}`; `changes.list` takes `pageToken` (required),
`pageSize`, `includeRemoved`, `restrictToMyDrive`, `spaces`, `fields` and
returns `changes[]` plus **exactly one of** `nextPageToken` or
`newStartPageToken`.

**The two-token model, precisely:** within one poll, `changes.list` may
paginate; while there are more pages the response carries `nextPageToken`,
which is passed back to fetch the next page of the same poll. When the feed
is fully drained the final page instead carries `newStartPageToken`, which is
the cursor for the *next* poll. So `next_page_token` means "keep calling now"
and `new_start_token` means "you are caught up; save this and stop". A
response never contains both, and Drive page tokens do not expire on a
practical timescale (an invalid one fails with HTTP 400).

### API methods

```python
def get_changes_start_token(self):
    # changes.getStartPageToken -> {"start_page_token": ...}

def list_changes(self, page_token, page_size=100, include_removed=True,
                 restrict_to_my_drive=False):
    # changes.list(pageToken=page_token, pageSize=page_size,
    #              includeRemoved=include_removed,
    #              restrictToMyDrive=restrict_to_my_drive,
    #              fields="nextPageToken, newStartPageToken, "
    #                     "changes(fileId, removed, time, "
    #                     "file(id, name, mimeType, modifiedTime, trashed, parents))")
    # -> {"changes": [<normalized>], "next_page_token": ...,
    #     "new_start_token": ...}
```

Normalized entry: `{"file_id": ..., "removed": bool, "time": ...,
"file": {id, name, mimeType, modifiedTime, trashed, parents} | None}`.
`removed=True` (or `file.trashed=True`) means the file left the user's view;
`file` is `None` for hard-removed items.

### MCP tools

```python
@register(mcp)
def get_changes_start_token(account: str | None = None) -> dict:
    """Get a change-feed baseline token for Drive. Save the returned
    start_page_token and pass it to list_changes on the next run."""

@register(mcp)
def list_changes(account: str | None = None, page_token: str = "",
                 page_size: int = 100, include_removed: bool = True,
                 restrict_to_my_drive: bool = False) -> dict:
    """List Drive changes since page_token. Returns change entries plus
    exactly one of next_page_token (more pages now: call again with it) or
    new_start_token (caught up: save it for the next poll)."""
```

## Calendar (P1)

Verified API surface: `events.list` accepts `syncToken`; the last page of a
listing includes `nextSyncToken`. A `syncToken` cannot be combined with
`iCalUID`, `orderBy`, `privateExtendedProperty`, `q`, `sharedExtendedProperty`,
`timeMin`, `timeMax`, or `updatedMin` (HTTP 400 if combined). An expired or
invalidated token fails with HTTP 410 GONE, which mandates a full re-sync.
Deleted events arrive as `status: "cancelled"` items, so `showDeleted=True`
is always set. There is no separate start-token endpoint: the baseline listing
itself yields the first `nextSyncToken`, which is why Calendar gets one tool,
not two.

The existing `CalendarAPI.list_events` cannot be reused: it returns only the
bare `items` list, dropping `nextPageToken`/`nextSyncToken`, and it always
sets `orderBy`, which is illegal with `syncToken`.

### API method

```python
def list_event_changes(self, calendar_id="primary", sync_token=None,
                       page_token=None, max_results=250,
                       single_events=False):
    # params = {calendarId, maxResults, showDeleted: True,
    #           singleEvents: single_events}
    # + syncToken / pageToken when given (never orderBy/timeMin/timeMax)
    # 410 -> ValueError (see error handling)
    # -> {"events": [<trimmed>], "next_page_token": ..., "new_sync_token": ...}
```

First call without `sync_token` walks the full event list (baseline) and ends
with a `new_sync_token`; subsequent calls with the token return only changed
events. Same drain rule as Drive: follow `next_page_token` within a poll;
`new_sync_token` appears only on the final page. Events are trimmed to
`{id, status, summary, start, end, updated, organizer, recurringEventId}`;
`status == "cancelled"` means deleted. `single_events=False` by default so a
recurring series changes as one master event instead of an unbounded
expansion.

### MCP tool

```python
@register(mcp)
def list_event_changes(account: str | None = None,
                       calendar_id: str = "primary",
                       sync_token: str | None = None,
                       page_token: str | None = None,
                       max_results: int = 250) -> dict:
    """List events changed since sync_token. First call without sync_token
    establishes a baseline (full walk) and returns new_sync_token to save;
    later calls with it return only changes (status 'cancelled' = deleted).
    Follow next_page_token within a poll; save new_sync_token for the next
    poll. If the token has expired the error says to re-baseline."""
```

## Requirements

- **P0**: Gmail `get_changes_start_token` + `list_changes`; Drive
  `get_changes_start_token` + `list_changes`. These cover the two highest
  value agent loops (inbox watchers, folder watchers).
- **P1**: Calendar `list_event_changes`.
- **P2** (design for, do not build): Sheets/Docs revision awareness via the
  Drive `revisions` API, layered on the Drive feed ("file X changed; list its
  revisions"). No schema reserved; it composes as separate tools later.

## Error handling

- Gmail HTTP 404 on `history.list` is caught in `GmailChangesAPI.list_changes`
  and re-raised as
  `ValueError("start_history_token expired or invalid; call get_changes_start_token for a fresh baseline, then do a full listing to resynchronize")`.
  Left unmapped it would surface as a generic `NotFoundError`, which reads as
  "mailbox not found" and would mislead the agent.
- Calendar HTTP 410 on `events.list` is caught in
  `CalendarChangesAPI.list_event_changes` and re-raised as
  `ValueError("sync_token expired; call list_event_changes without sync_token to re-baseline")`.
- Drive invalid `page_token` (HTTP 400) passes through `run_tool` unmodified;
  the API's own message names the bad parameter, and 400 here does not need a
  special re-baseline hint because `get_changes_start_token` never expires.
- Empty required token params (`start_history_token`, `page_token`) raise
  `ValueError` naming the parameter, per the existing guard style.
- Everything else flows through `run_tool` and `core.map_exception` as usual.

## Testing

Match the existing test layout:

- **Unit (normalization)**: pure-function tests for the Gmail history
  flattener and Drive change normalizer against canned API payloads,
  including a history record containing all four change arrays, an empty
  `history` response (no changes since token), a hard-removed Drive change
  with no `file`, and a cancelled Calendar event.
- **Server-level (FakeAPI)**: extend the FakeAPI in
  `tests/test_gmail_server.py` with the two new methods (signatures must
  match `GmailChangesAPI`, per the FakeAPI drift rule) and assert the tools
  pass params through and wrap results in `ok(...)`. Same for Calendar's
  FakeAPI and for Drive via the `patch("google_auth_core.get_service", ...)`
  style used in `tests/test_drive_server.py`.
- **Token-expiry paths**: FakeAPI raises the mapped `HttpError` equivalents;
  assert the actionable `ValueError` messages surface.
- **Read-only gate**: assert all five tools are present under
  `GOOGLE_MCP_READONLY=1` (they are the primary read-only-mode use case).
- **Live smoke (opt-in, `GOOGLE_MCP_LIVE=1`)**: baseline token, send-and-poll
  is too invasive for Gmail, so Gmail live coverage stops at "baseline token
  parses and an immediate list_changes returns zero changes". Drive: create a
  scratch file, poll, assert it appears, clean up. Calendar: baseline walk
  returns a sync token.

## Out of scope

- `users.watch` / Pub/Sub / webhook channels of any kind.
- Persisting cursors server-side or in `~/.google/`.
- A unified cross-service change feed.
- Fetching changed content (bodies, file text) inside the feed tools; the
  feed returns ids, existing read tools fetch content.

## Tool count

Adds **5 tools**: Gmail +2 (get_changes_start_token, list_changes), Drive +2
(get_changes_start_token, list_changes), Calendar +1 (list_event_changes).
All read-only, all available in read-only mode.

## Open questions

- **Gmail history retention** is documented only as "typically at least a
  week"; is that window acceptable for the target cron cadences, or should
  the docstring recommend a maximum poll interval (owner: product/nitai)?
- **Shared drives**: should Drive `list_changes` expose
  `supportsAllDrives`/`includeItemsFromAllDrives` now or wait for the first
  request (owner: product/nitai)? The suite currently ignores shared drives
  everywhere, so the default answer is "wait", but the changes feed is where
  shared-drive users will notice first.
- **Calendar `single_events` default**: `False` keeps payloads bounded but
  agents must understand recurring masters; is that the right trade for the
  P1 cut (owner: engineering, decide at implementation)?
