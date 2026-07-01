# google-auth setup wizard + doctor: design

**Date:** 2026-07-01
**Status:** Draft, pending review
**Author:** nitai (+ Claude)

## Problem

Bring-your-own OAuth is the product's differentiator (no shared client, no
third party proxying mail, no Google security assessment needed) and also its
funnel killer. Today a new user must: create a GCP project, enable five APIs,
configure the consent screen, add themselves as a test user, create a Desktop
app OAuth client, download the JSON, rename it to `~/.google/credentials.json`,
run `google-auth login`, then hand-write `.mcp.json` with absolute paths
because GUI clients do not inherit shell PATH. That is roughly 30 minutes and
seven distinct failure points before the first successful tool call, and every
failure today surfaces as a raw error with no guided recovery.

## Goal

Two new subcommands on the `google-auth` CLI:

- **`google-auth setup`**: an interactive wizard that walks the user from
  nothing to a working, registered MCP suite: validates or guides creation of
  the OAuth client, runs login, verifies API enablement, and prints
  ready-to-paste client config with absolute paths.
- **`google-auth doctor [account]`**: a non-interactive diagnostic that checks
  every known setup failure mode and prints one pass/warn/fail line per check
  plus the single most important next action.

**Measurable targets:**

- Time from `pip install` to first successful MCP tool call under 10 minutes
  for a user with no existing GCP project.
- `doctor` identifies each of the top setup failure modes (missing/wrong-type
  client, missing token, stale scopes, disabled API, script not on PATH)
  with an actionable one-line fix, so those never need a GitHub issue.

## Non-goals

- **No embedded shared OAuth client.** BYO client stays; the wizard makes it
  cheap, not optional. A shared client for restricted Gmail/Drive scopes would
  require Google's CASA security assessment.
- **No OAuth flow inside the MCP servers.** Servers remain non-interactive
  token consumers; `test_integration.py` continues to assert this.
- **No automation of the Cloud Console itself.** We print deep links and
  instructions; we do not drive a browser or call GCP admin APIs on the
  user's behalf.

## Where this lands

All changes go in the external **`google-auth-core`** package (the
`google-auth` console script), not in this repo's server code:

- `google_auth_core/cli.py`: two new click subcommands, `setup` and `doctor`.
- New `google_auth_core/diagnostics.py`: pure, individually testable check
  functions shared by both commands (the wizard is a thin interactive loop
  over the same checks `doctor` runs).
- Version: `google-auth-core` 0.1.0 -> 0.2.0. This repo bumps its dependency
  to `google-auth-core>=0.2.0` and rewrites the README "Authenticate (once)"
  section to lead with `google-auth setup` (manual steps stay as an appendix).
- Drive-by fix while in `cli.py`: `login` currently echoes
  `Scopes: Gmail, Calendar, Sheets`, which is stale; it should list all five
  services (scopes.py already grants Docs and Drive).

## The checks (shared by setup and doctor)

Each check is a function returning `(status, message, fix)` where status is
`pass` / `warn` / `fail`. All live in `diagnostics.py` with no interactive IO.

| # | Check | pass | fail examples and fix line |
|---|---|---|---|
| 1 | `credentials.json` present | found via `get_credentials_path()` (searches `~/.google/`, cwd, home) | "not found: save your OAuth client JSON as ~/.google/credentials.json" |
| 2 | client parses + is Desktop type | JSON has top-level `"installed"` key | `"web"` key means wrong client type: "recreate as application type Desktop app"; parse error names the file |
| 3 | token store health per account | `check_token_health(acct, "unified", ALL_SCOPES)` returns `valid` | `missing` / `expired` -> "Run: google-auth login <account>"; `scope_mismatch` lists missing scopes and says re-login |
| 4 | silent refresh works | `expired_refreshable` token refreshes successfully via `refresh_token()` | refresh HTTP error -> token revoked or client deleted: re-login |
| 5 | console scripts on PATH | `shutil.which()` finds each of `gmail-mcp`, `gcal-mcp`, `gsheets-mcp`, `gdocs-mcp`, `gdrive-mcp` | any missing is `warn` (google-auth-core is also installed standalone by the CLIs); message names the missing scripts |
| 6 | per-API enablement probe | one cheap authorized call per service succeeds (see below) | 403 `accessNotConfigured` -> "enable <API> at <deep link>" |

**Probe calls (check 6).** One minimal read per service, run only when a valid
token exists (checks 3/4 passed):

- Gmail: `users.getProfile(userId="me")`
- Calendar: `calendarList.list(maxResults=1)`
- Drive: `files.list(pageSize=1)`
- Sheets: `spreadsheets.get` on a sentinel bogus ID; a 404 proves the API is
  enabled and reachable, while 403 `accessNotConfigured` proves it is disabled
  (Sheets has no cheap list endpoint)
- Docs: same bogus-ID technique via `documents.get`

Probes reuse `get_service()` so they exercise the exact code path the servers
use. Each probe result is cached for the run; total cost is five HTTP calls.

**Deep links** (printed in fixes and by the wizard):

- Enable all five APIs in one flow:
  `https://console.cloud.google.com/flows/enableapi?apiid=gmail.googleapis.com,calendar-json.googleapis.com,sheets.googleapis.com,docs.googleapis.com,drive.googleapis.com`
- Consent screen + test users: `https://console.cloud.google.com/apis/credentials/consent`
- Create OAuth client: `https://console.cloud.google.com/apis/credentials`

## `google-auth setup` (wizard)

Interactive; safe to re-run at any time (every step is check-then-skip).

```text
$ google-auth setup

google-auth setup: Google Workspace MCP suite

[1/4] OAuth client
  x  ~/.google/credentials.json not found.

  Create one (about 5 minutes, one time):
    1. Open https://console.cloud.google.com/flows/enableapi?apiid=gmail.googleapis.com,...
       and enable the APIs (create or pick a project when prompted).
    2. Open https://console.cloud.google.com/apis/credentials/consent
       -> External -> add yourself under Test users.
    3. Open https://console.cloud.google.com/apis/credentials
       -> Create credentials -> OAuth client ID -> Desktop app -> Download JSON.
    4. Save the file as ~/.google/credentials.json

  Press Enter when done (or q to quit)...
  ok Found Desktop-app OAuth client (project: my-project-123).

[2/4] Log in
  Enter your Google address: you@example.com
  ok Opened browser... authenticated as you@example.com
  ok Scopes: Gmail, Calendar, Sheets, Docs, Drive

[3/4] API access
  ok Gmail   ok Calendar   ok Drive
  x  Sheets: API not enabled. Enable it at <deep link>, then press Enter to retry.
  ok Docs

[4/4] Register with your MCP client
  Paste into .mcp.json (absolute paths, works in Claude Desktop/Cursor):
  {
    "mcpServers": {
      "google-gmail":    { "command": "/Users/you/.local/bin/gmail-mcp" },
      ...
    }
  }
  Or run:
    claude mcp add --scope user google-gmail /Users/you/.local/bin/gmail-mcp
    ...

Setup complete. Verify anytime with: google-auth doctor
```

Behavior details:

- **Step 1** runs checks 1+2. On failure it prints the instructions above and
  loops on Enter, re-checking, so the user never restarts the wizard.
- **Step 2** is skipped (with an `ok already logged in as ...` line) when
  check 3 passes for the given account; `setup` accepts an optional
  `[account]` argument like `login`. Internally it calls the existing
  `authflow.authenticate()`; no second implementation of the flow.
- **Step 3** runs the probes; on a disabled API it prints the specific deep
  link and offers retry, since enablement takes effect within a minute.
- **Step 4** emits config only for the `*-mcp` scripts actually found by
  `shutil.which()` (check 5), with absolute paths. If none are found it
  prints the pip/pipx install hint instead.
- `--no-browser` is passed through to login, matching the existing flag.

## `google-auth doctor [account]`

Non-interactive; runs every check and never prompts. With no argument it
checks all configured accounts (like `status`); with an argument, just that
account or alias.

```text
$ google-auth doctor work
ok   OAuth client: Desktop app (~/.google/credentials.json)
ok   Token: you@work.com valid, refreshes silently (expires in 3212s)
ok   Scopes: all 5 services covered
warn PATH: gdocs-mcp not found (GUI clients need absolute paths anyway)
ok   APIs: Gmail, Calendar, Sheets, Docs, Drive all enabled
All good. 1 warning.
```

On failure the last line is the single next action, chosen by check order
(earlier checks gate later ones):

```text
fail Token: you@work.com scope_mismatch (missing: documents, drive)
...
Next: google-auth login you@work.com
```

Exit codes: 0 all pass (warnings allowed), 1 any fail, 2 cannot even locate
the store (unreadable `~/.google`). Machine-readable `--json` output is P1.

## Requirements

**P0 (the feature does not ship without these):**

- `setup` takes a fresh machine to a working login with only the Cloud
  Console steps left manual, re-runs idempotently, and prints absolute-path
  client config.
- `doctor` runs checks 1 through 6 non-interactively with per-check
  pass/warn/fail lines, a final next action, and correct exit codes.
- Checks live in `diagnostics.py` as pure functions with no `click` IO.
- `login` output lists all five services.
- README leads with `google-auth setup`.

**P1 (fast follows):**

- `doctor --json` for scripting and bug reports.
- `setup` step 4 also detects Claude Desktop / Cursor config file locations
  and offers the exact file path to edit.
- Probe results cached in the store with a timestamp so repeated `doctor`
  runs within a few minutes skip the five HTTP calls.

**P2 (design headroom, not built now):**

- `doctor --fix` to auto-run the obvious remediations (login, alias repair).
- Per-service scope selection at login (`--services gmail,calendar`), which
  would change what "scope coverage" means in check 3.

## Error handling

- All check functions catch their own exceptions and fold them into a `fail`
  result; `doctor` must never traceback on a broken environment, since a
  broken environment is exactly when it runs.
- Network-down during probes yields `warn` ("could not reach Google APIs"),
  not `fail`, and does not block the wizard's completion.
- The wizard treats Ctrl-C / `q` as clean exit with a "resume anytime with
  google-auth setup" line.

## Testing

In `google-auth-core`'s test suite (mirroring this repo's temp-store pattern
from `tests/conftest.py`: point the store at a temp `~/.google`, write fake
tokens):

- **Unit (`diagnostics.py`):** each check against fixture states: missing
  file, `web`-type client, valid/missing/expired/scope-short token (reusing
  `check_token_health` fixtures), PATH with and without scripts
  (monkeypatched `shutil.which`), probes with mocked `get_service` raising
  403 `accessNotConfigured` vs 404 vs success.
- **CLI (`click.testing.CliRunner`):** `doctor` output lines and exit codes
  per scenario; `setup` driven with `input=` streams, asserting it skips
  completed steps and that `authenticate` is called once (mocked, never a
  real browser).
- **This repo:** one integration test asserting the pinned
  `google-auth-core>=0.2.0` exposes `setup` and `doctor` (import-level, no
  network), so the dependency bump cannot silently regress.

## Out of scope

- Any change to server/tool code or `core/runtime.py` in this repo.
- Windows-specific console behavior beyond click's defaults.
- Telemetry on setup completion (nothing phones home).

## Open questions

- **(nitai)** Should step 1 also offer pasting the OAuth client JSON directly
  into the terminal (write it to `~/.google/credentials.json` for the user)
  instead of requiring a file save? Cheap to add, slightly unusual UX.
- **(engineering)** Is the bogus-ID 404-vs-403 probe for Sheets/Docs
  acceptable long-term, or should we probe via a Drive-created scratch file?
  The bogus-ID call is free and read-only but relies on Google's error
  taxonomy staying stable.
- **(engineering)** Should `warn` on missing PATH scripts become `fail` when
  doctor is invoked from a context that clearly expects the MCP suite
  (e.g. a `--suite` flag)? Non-blocking; default to warn in v1.
