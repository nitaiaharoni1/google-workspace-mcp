# Envelope v2: pagination cursors + field selection (design)

**Date:** 2026-07-01
**Status:** Draft, pending review
**Author:** nitai (+ Claude)

## Problem

Agents cannot walk a large collection. Every list/search tool takes
`max_results` / `page_size` and returns only the first page: the underlying
Google API's `nextPageToken` is either dropped by the wrapper (Gmail,
Calendar return bare lists) or returned but unusable (Drive returns the token
inside `data` but no tool accepts a `page_token` input). A 40k-message inbox,
a 3k-file folder, or a year of calendar events is silently truncated at the
default page size, and the agent has no signal that truncation happened, let
alone a way to continue.

Separately, the heavy readers vary in token efficiency. Some are already
good (`get_spreadsheet` defaults `include_grid_data=False`; Gmail readers
expose `format`), but `get_message(format="full")` returns base64url body
parts the model cannot read, and Docs `get_document` returns the entire raw
document JSON. Agents burn context on payloads designed for programs, not
models.

## Goals

1. Every list/search tool can enumerate an arbitrarily large collection:
   repeated calls with `page_token` eventually visit every item, on all five
   servers.
2. Truncation is always visible: whenever the API reports another page, the
   response envelope carries `next_page_token`.
3. Existing consumers keep working: no existing envelope key changes meaning,
   no existing tool param is removed, default response shapes stay the same
   (one documented exception in Drive, below).
4. A message can be read as decoded text without base64 payloads in context.

## Non-goals

- **No streaming or partial responses.** Tools stay single request/response.
- **No server-side cursor state.** Page tokens are opaque strings returned to
  the agent and round-tripped by the agent. The server stores nothing; this
  preserves the stateless, restart-safe server model.
- **No auto-pagination.** No `fetch_all=True` that loops until exhaustion; an
  unbounded loop hides cost from the agent. The agent decides when to stop.
- **No response-size hard caps or token budgeting.** Worth its own spec.

## Design

### 1. Envelope: `ok()` grows optional meta keys

`core/runtime.py`:

```python
def ok(account: str, data: Any, **meta: Any) -> dict:
    """Standard success envelope shared by all tools.

    Extra keyword args are added to the envelope only when not None. The only
    meta key defined today is next_page_token.
    """
    out = {"ok": True, "account": account, "data": data}
    out.update({k: v for k, v in meta.items() if v is not None})
    return out
```

- Fully backward compatible: `ok(resolved, data)` produces exactly today's
  shape. `{"ok": True, "account": ..., "data": ...}` is unchanged.
- `next_page_token` appears **only** when the Google API returned one, so
  its presence is itself the "there is more" signal.
- Convention for tools:

```python
@register(mcp)
def list_messages(account=None, query=None, label_ids=None,
                  max_results=10, page_token=None) -> dict:
    """List messages... Pass page_token from a previous response's
    next_page_token to fetch the next page."""
    api, resolved = _api(account)
    page = run_tool(lambda: api.list_messages_page(
        max_results=max_results, label_ids=label_ids, query=query,
        page_token=page_token))
    return ok(resolved, page["items"], next_page_token=page.get("nextPageToken"))
```

### 2. Pagination: per-server inventory and wrapper changes

`page_token: str | None = None` is appended as the **last** param of each
affected tool (never first; `account` stays first per the core contract).

| Server | Tool | Wrapper layer | Today | Change |
|---|---|---|---|---|
| Gmail | `list_messages` | `gmail_cli.GmailAPI.list_messages` (external) | returns bare `messages` list, token dropped | new upstream page method |
| Gmail | `search_messages` | `gmail_cli.GmailAPI.search_with_details` (external) | built on `list_messages`, token dropped | thread token through |
| Gmail | `list_threads` | `gmail_cli.GmailAPI.list_threads` (external) | bare list, token dropped | new upstream page method |
| Gmail | `list_drafts` | `gmail_cli.GmailAPI.list_drafts` (external) | bare list, token dropped | new upstream page method |
| Calendar | `list_events` | `google_calendar_cli.CalendarAPI.list_events` (external) | bare `items` list, token dropped | new upstream page method |
| Calendar | `search_events` | same (external) | bare list, token dropped | new upstream page method |
| Calendar | `get_recurring_event_instances` | same (external) | bare list, token dropped | new upstream page method |
| Calendar | `list_calendars` | same (external) | bare list, token dropped | new upstream page method (P1) |
| Drive | `search_files` | repo-local `DriveAPI` | raw dict **includes** `nextPageToken`, no input param | add `page_token` param; lift token to envelope |
| Drive | `list_files` | repo-local `DriveAPI` | same as `search_files` | same |

Not paginated by the API, no change: Gmail `list_labels` / `list_filters`,
Sheets (`read_range` / `batch_read` are range reads, not lists), Docs (no
list endpoints). Drive `list_permissions` supports paging upstream but a
file's ACL is small; P2.

**External wrappers are first-party siblings** (`~/REPOS/gmail-cli`,
`~/REPOS/google-calendar-cli`, same author), so upstream changes are
coordinated releases, not negotiations:

- `gmail-cli-oauth`: add `list_messages_page`, `list_threads_page`,
  `list_drafts_page`, and a `page_token=None` param on
  `search_with_details`. Each `_page` method returns
  `{"items": [...], "nextPageToken": <str or absent>}` and leaves the
  existing bare-list methods untouched (the CLI keeps using those).
- `google-calendar-cli`: same pattern for `list_events_page`,
  `search_events_page`, `instances_page`, `list_calendars_page`.
- `pyproject.toml` here pins the new minimums (`gmail-cli-oauth>=1.6`,
  `google-calendar-cli>=1.7`, exact versions set at release time).

**Interim handling if upstream cannot ship first:** none needed; the sibling
repos release first and this repo bumps pins in the same change. If that
ordering ever breaks, the fallback is a `getattr(api, "list_messages_page",
None)` check that degrades to the old bare-list call with no
`next_page_token` (never a direct service call in a tool; that would violate
the `_api`/`get_api` contract).

**Drive data-shape note (the one intentional break):** today Drive list
tools return `data = {"files": [...], "nextPageToken": ...}`. The tool will
`pop("nextPageToken")` out of `data` and pass it to `ok()` so the token
lives in exactly one place, the envelope. `data` stays a dict with `files`.
This is the only observable shape change and it is called out in the
changelog.

### 3. Field selection / verbosity on heavy readers

Verified current state, then the ladder:

- **Gmail**: `get_message` / `get_thread` / `search_messages` already expose
  `format` (`full` / `metadata` / `minimal` / `raw`); `search_messages`
  already defaults to `metadata`. No signature change. Docstrings gain one
  line steering agents: use `metadata` unless the body is needed.
- **Gmail body decoding (P1)**: `get_message(format="full")` returns
  base64url `body.data` parts. Add a decoded projection: new upstream
  `gmail_cli` method `get_message_text(message_id)` returning
  `{id, threadId, labelIds, subject, from, to, cc, date, snippet,
  body_text, attachments: [{filename, mimeType, size, attachmentId}]}`
  (prefer `text/plain` part, fall back to stripped `text/html`). Exposed as
  the existing tool's `format="text"` pseudo-format, handled before the API
  passthrough. Raw payloads remain available via `format="full"`, which is
  the `raw=True` style escape hatch.
- **Docs**: the verbosity ladder already exists and just needs signposting:
  `read_document` (plain text) < `get_content_map` (structure + indexes) <
  `get_document` (full raw JSON). Change: docstring cross-references on all
  three ("for edits use get_content_map; get_document returns the full raw
  document and is rarely needed"). P2: `fields` mask passthrough on
  `documents.get` (the Docs fields grammar is awkward and the ladder already
  covers the real cases).
- **Sheets**: `get_spreadsheet` already defaults `include_grid_data=False`
  (verified in `sheets_api.py`). No change. P2: `fields` mask passthrough.
- **Drive**: `get_file` uses the fixed `FILE_METADATA_FIELDS` projection,
  which is already trimmed. P2: optional `fields` param passthrough for
  extra metadata (permissions, capabilities) without a second call.
- **Calendar**: `get_event` returns a full event resource (moderate size).
  P2: `fields` mask passthrough on `events.list` / `events.get`.

## Requirements

**P0 (ship first, one release)**
- `ok()` meta mechanism in `core/runtime.py` with `next_page_token`.
- Gmail pagination: `list_messages`, `search_messages`, `list_threads`,
  `list_drafts` (upstream `gmail-cli-oauth` release + pin bump).
- Drive pagination: `search_files`, `list_files` (repo-local only).
- Docstring line on every paginated tool: "Pass page_token from a previous
  response's next_page_token to continue."

**P1**
- Calendar pagination: `list_events`, `search_events`,
  `get_recurring_event_instances`, `list_calendars` (upstream
  `google-calendar-cli` release + pin bump).
- Gmail `format="text"` decoded projection via upstream `get_message_text`.
- Docs verbosity-ladder docstring cross-references.

**P2 (future, keep the door open)**
- `fields` mask passthrough on Drive `get_file`, Calendar list/get, Sheets
  `get_spreadsheet`, Docs `get_document`.
- Drive `list_permissions` pagination.

Acceptance criteria (P0):
- Given a mailbox with more messages than `max_results`, when the agent
  calls `list_messages`, then the envelope contains `next_page_token`; when
  it passes that token back, then it receives the next page; when the last
  page is reached, then the key is absent.
- Given any tool call that returns fewer items than one page, then the
  envelope is byte-identical in shape to today's (no new keys).
- Given `GOOGLE_MCP_READONLY=1`, pagination params change nothing about the
  read-only gate (all affected tools are reads).

## Error handling

- An invalid or expired `page_token` makes Google return HTTP 400; this
  flows through `run_tool` into the `GoogleCoreError` taxonomy unchanged.
  The docstring convention warns: tokens are opaque, tied to the exact query
  (changing `query`/`label_ids`/`calendar_id` mid-walk invalidates them),
  and should not be persisted across sessions.
- Wrapper `_page` methods never synthesize tokens; absence of
  `nextPageToken` in the API reply means absence in the envelope.

## Testing

- **Unit (wrappers):** repo-local `DriveAPI.search_files`/`list_files` pass
  `pageToken` through and preserve `nextPageToken` in the reply. Upstream
  `_page` methods get equivalent tests in their own repos.
- **Server-level:** FakeAPI signatures **must** gain the new
  `page_token`/`_page` shapes in lockstep (this repo already ate one
  signature-drift bug with Gmail's html/cc params; treat FakeAPI parity as
  part of the definition of done). Tests: token present in envelope when the
  fake returns one; absent otherwise; token passed through to the fake
  verbatim; `ok()` meta mechanism drops None.
- **Core:** `ok()` unit tests: no meta, one meta, None meta.
- **Live smoke (`GOOGLE_MCP_LIVE=1`):** list with `max_results=1` twice
  using the returned token; assert the two pages differ and the walk
  terminates.

## Out of scope

- Response streaming, chunked reads, token budgets.
- Auto-pagination / exhaustive fetch helpers.
- Any change to mutating tools.
- Unifying the Drive `page_size` vs Gmail/Calendar `max_results` naming
  (renaming params breaks existing agent prompts; revisit only on a major).

## Tool count

Adds **0 tools**. Changes params on 10 existing tools and the shared
envelope.
