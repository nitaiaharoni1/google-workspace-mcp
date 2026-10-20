# Remote hosting (claude.ai web + mobile): design

**Date:** 2026-10-20
**Status:** Draft, pending review. Design only; nothing implemented.
**Author:** nitai (+ Claude)

## Problem

All five servers run only over stdio (`mcp.run()` in each `server.py:main`),
so they work in Claude Code, Claude Desktop, Cursor and anything else that can
spawn a local process. claude.ai on the web and the iOS/Android apps cannot
spawn processes: they only accept **remote custom connectors**, which means
an HTTPS URL speaking MCP streamable HTTP and, for anything private, the MCP
authorization flow (OAuth 2.1 with protected resource metadata and dynamic
client registration). Today there is no way to reach Gmail/Calendar/Sheets/
Docs/Drive from the phone through this suite.

## Goal

The maintainer can add the suite to claude.ai as custom connectors and use it
from the web and the phone, with:

- the same tools, envelope, multi-account behaviour and error messages as
  stdio (one shared `core/`, no forked tool code);
- nobody but the owner able to use the connectors, even if the URL leaks;
- writes and destructive tools off unless the owner turns them on;
- stdio behaviour unchanged for every existing user.

## Non-goals

- **No hosted multi-tenant service** in this spec (Option B below is
  analysed and deferred).
- **No shared/embedded Google OAuth client.** Bring-your-own client stays
  (same non-goal as the setup-wizard spec).
- **No Google token pass-through** to or from claude.ai (see "Rejected").
- **No change to stdio defaults.** HTTP is a new, opt-in entry point.

## Findings that shape the design

1. **SDK support.** The mcp 2.x migration (`claude/optimistic-pare-ee4da7`,
   commit `029e148`, pins `mcp>=2,<3`; venv has 2.3.0) moves us from
   `FastMCP` to `MCPServer`. 2.x `MCPServer` provides
   `streamable_http_app(streamable_http_path=..., stateless_http=...,
   transport_security=...)` returning a Starlette app, and full auth support:
   either `token_verifier=` (resource-server only) or
   `auth_server_provider=` (an `OAuthAuthorizationServerProvider` the SDK wraps
   with `/authorize`, `/token`, `/register` (DCR), `/revoke`, RFC 8414 metadata
   and RFC 9728 protected resource metadata). `AuthSettings` has
   `resource_server_url` and `validate_token_resource` (RFC 8707 audience
   binding). `get_access_token()` exposes the caller's token inside a tool.
   Sync tool functions run via `anyio.to_thread.run_sync`, so tools execute
   concurrently in worker threads. **This spec targets 2.x and lands after
   that branch merges.**
2. **No existing web OAuth flow.** Nothing in this repo or in
   `~/REPOS/google-auth-core` references `mcp-oauth-web.json` or a web
   redirect flow; `google_auth_core.authflow.authenticate` uses
   `InstalledAppFlow` (desktop client, loopback redirect) only.
   `~/.google/mcp-oauth-web.json` is a Google **Web application** client
   (project from the same GCP setup) whose redirect URIs include
   `https://claude.ai/api/mcp/auth_callback`, a Cursor callback,
   `http://localhost:8787/callback` and `http://localhost`. It looks like an
   earlier experiment with Google as the connector's authorization server.
   We reuse the **client** (for owner sign-in, below), not that redirect
   pattern.
3. **Thread safety gap (arrives with 2.x, worse over HTTP).** `get_api`
   caches one API wrapper per `(service, account)`, and
   `google_auth_core.get_service` separately caches one `googleapiclient`
   service per `(account, api, version)`; Gmail and Calendar wrappers
   (`gmail_cli/api.py`, `google_calendar_cli/api.py`) call `build(...)`
   themselves. Every wrapper stores `self.service` once in `__init__`. All of
   these use `httplib2`, which is not thread-safe. Docs and Drive even share the same cached `drive v3` client
   (`docs/docs_api.py` `_drive`, `drive/drive_api.py`). Under 2.x's threaded
   tool execution, concurrent calls on one account share one `Http` object.
   Over HTTP with several connectors and a phone retrying, this becomes
   likely. Must be fixed before remote ships (see Core changes).
4. **Token refresh writes to disk, non-atomically.**
   `google_auth_core.get_credentials` refreshes and rewrites the unified token
   file with `open(path, "w")`, no lock, no atomic replace. One file per
   account is shared by all five services and by stdio processes, so a
   concurrent reader can see a truncated file and report a false
   "Run: google-auth login". On a read-only or ephemeral filesystem (Cloud
   Run) it also needs a writable copy.

## Decision summary

| Question | Recommendation |
|---|---|
| Transport | Streamable HTTP, `stateless_http=True` |
| Process layout | **One process**, one path per service (`/gmail/mcp`, `/calendar/mcp`, `/sheets/mcp`, `/docs/mcp`, `/drive/mcp`), five claude.ai connectors |
| Auth model | **Option A: single-user self-hosted.** The server is its own OAuth 2.1 authorization server for MCP clients; the owner proves identity by Google sign-in (openid/email only) against an allowlist |
| Where it runs | Phase 1: the owner's Mac + **Tailscale Funnel** (TLS ends on the Mac). Phase 3 (optional): Cloud Run on the `personal` GCP profile |
| Write access | Remote defaults to **read-only**; writes and destructive tools are separate opt-ins, later per-token scopes |

## Transport

Streamable HTTP is the only transport claude.ai custom connectors need; SSE
is deprecated and not offered.

- **Stateless mode** (`stateless_http=True`). Our tools hold no per-session
  state (everything is keyed by `account` and served from `get_api`'s cache),
  so server-side MCP sessions buy nothing and cost us: restarts and
  Cloud Run instance changes would drop sessions and force clients to
  re-initialize. Streaming of a single response (progress/status events added
  in `44ccd91`) still works inside one request. Server-initiated requests
  outside a tool call (sampling, list-changed notifications) are not used
  today; if they are added later, revisit.
- **Bind to `127.0.0.1` only**; the tunnel or Cloud Run front end provides
  the public HTTPS. `TransportSecuritySettings` with
  `allowed_hosts=[<public host>, "127.0.0.1:<port>"]` keeps DNS-rebinding
  protection on.
- Request body cap stays at the SDK default; uploads go through Drive tools
  that already take paths or base64 with output caps.

### One process, path per service (vs five processes, vs one combined server)

- **Five processes**: five ports, five tunnel routes, five authorization
  servers with five client registries. Rejected: five times the ops for no
  isolation we can't get otherwise.
- **One combined server** with all ~200 tools: one connector, one login, but
  every chat loads every tool (tool-selection quality drops, context cost
  rises), and 11 names collide (`list_accounts`, `whoami`, `auth_status` in
  all five; `add_comment`/`list_comments`/`reply_to_comment`/`delete_comment`
  in Sheets, Docs and Drive; `batch_update`, `get_profile`, `get_changes_start_token`,
  `list_changes` across others). Rejected.
- **Chosen: one Starlette app** mounting the five existing `mcp` instances at
  `/<service>/mcp`, plus one shared authorization server at the root.
  The owner adds five connectors and enables only the ones a chat needs,
  exactly like the five stdio entries today. Each connector is a separate
  RFC 8707 resource, so a token minted for `/gmail/mcp` is rejected by
  `/drive/mcp`. With our own wrapping, that check happens only because each
  child's `BearerAuthBackend` gets `resource_server_url=https://<host>/<service>/mcp`
  and our token store always returns `AccessToken.resource` (a missing
  resource would be accepted). `AuthSettings.validate_token_resource` is only
  read by the SDK's own `streamable_http_app` wiring, so it does not apply. A leaked Calendar token
  cannot send mail.

Mounting mechanics (checked against mcp 2.3.0):

- **Auth is a constructor concern, not an app-builder one.** `auth`,
  `token_verifier` and `auth_server_provider` are `MCPServer.__init__`
  params; `streamable_http_app()` takes none. The module-level `mcp` objects
  are built without auth, so `remote.py` mounts the **unauthenticated** child
  apps and wraps each one itself with the SDK's public pieces:
  `AuthenticationMiddleware(BearerAuthBackend(verifier, resource_server_url=...))`,
  `AuthContextMiddleware`, and `RequireAuthMiddleware(app, scopes,
  resource_metadata_url)`. (Alternative: `build_server` reads auth config
  from env, like `READONLY`. Rejected for now: it couples every stdio
  server to remote config.)
- **Metadata routes live on the parent.** If a child owned its protected
  resource metadata route, mounting it at `/gmail` would serve it at
  `/gmail/.well-known/...` while `WWW-Authenticate` points at the root path,
  which would 404. And five children mounted at `/` don't work (Starlette
  takes the first match). So the parent registers
  `create_protected_resource_routes(...)` once per service at
  `/.well-known/oauth-protected-resource/<service>/mcp`, and
  `create_auth_routes(...)` once at root (one `/register`, one `/token`).
- **Lifespans.** Each child's session manager has a `run()` lifespan that may
  be entered only once; the parent lifespan enters all five through an
  `AsyncExitStack`.

New entry point (console script), stdio scripts unchanged:

```
gworkspace-mcp-remote serve --public-url https://<host> [--port 8787]
                            [--services gmail,calendar,...]
                            [--allow-writes] [--allow-destructive]
                            [--allow-tools send_message,share_file,...]
                            [--accounts nitai@handi.co.il,...]
```

## Auth for remote clients

There are two separate OAuth relationships, and keeping them separate is the
core of the design:

1. **Server to Google (data access).** Unchanged: the server reads refresh
   tokens from `~/.google/tokens/`, written out of band by
   `google-auth login`. The server never runs a Google data-consent flow.
2. **claude.ai to server (who may call the tools).** New: the server acts as
   an OAuth 2.1 authorization server for MCP clients, per the MCP
   authorization spec.

What claude.ai does when you add a connector URL: calls it, gets `401` with
`WWW-Authenticate: Bearer resource_metadata=...`, fetches
`/.well-known/oauth-protected-resource/<service>/mcp`, follows
`authorization_servers` to `/.well-known/oauth-authorization-server`,
registers itself via DCR at `/register` (or uses a client ID/secret pasted in
the connector's advanced settings), then runs authorization code + PKCE
(S256) against `/authorize` and `/token` with
`redirect_uri=https://claude.ai/api/mcp/auth_callback` and
`resource=https://<host>/<service>/mcp`. Tokens are refreshed by claude.ai
via the refresh grant.

### Option A: single-user self-hosted (recommended)

The server holds the owner's existing `~/.google` store. Only the owner can
complete `/authorize`.

**Owner gate at `/authorize`.** The SDK calls our provider's `authorize()`,
which redirects the browser to an owner sign-in, then on success issues the
code back to claude.ai. Owner sign-in, in order of preference:

- **Google sign-in, identity only** (default). Use the existing web client in
  `~/.google/mcp-oauth-web.json`, scopes `openid email` only, redirect
  `https://<host>/owner/callback` (add it to the client's redirect URIs; it is
  a one-time Console edit). Verify the ID token (issuer, audience = that
  client ID, `email_verified`), and require the email to be in the owner
  allowlist, which defaults to the accounts already in `~/.google/config.json`
  (`list_accounts()`). The Google tokens from this step are discarded after
  verifying the ID token; nothing is written to `~/.google/tokens/`. Benefit:
  no new password, and Google's 2FA protects the gate.
  - **CSRF and replay:** the outbound Google request carries a `state` bound
    to a server-side pending-authorize record (single use, 5 min TTL), a
    `nonce` checked in the ID token, and PKCE to Google.
  - Pin the Google `sub` of each allowlisted account on first sign-in, not
    only the email.
  - The callback redirect URI is built from `--public-url`, never from the
    `Host` header.
- **Passphrase fallback** (`--owner-passphrase-file`), for users without a web
  client. **Deferred out of Phase 1**: the web client already exists, and a
  passphrase gate behind Funnel is hard to rate-limit (see Security). If
  added later: Argon2id hash on disk, rate limit plus lockout keyed on a
  verified client address.

**Consent page.** After sign-in it shows the registering client's name,
redirect host and requested tier. The name is attacker-chosen (any DCR
client can call itself "Claude"); the page labels the **redirect host** as
the thing to check, and that host is already allowlisted. Allow is a POST carrying a CSRF token; the
page sends `Content-Security-Policy: frame-ancestors 'none'` and
`X-Frame-Options: DENY` against clickjacking. `/authorize` is rejected when
`resource` is missing or isn't one of the five service URLs. (Phase 2 adds
the tier choice here.)

**DCR rules.** Registration is open (claude.ai needs it), but registration
alone grants nothing. The SDK ships both DCR and revocation **off**
(`ClientRegistrationOptions.enabled` and `RevocationOptions.enabled` default
to False), so `remote.py` passes `enabled=True` for both. Registered `redirect_uris` must be on an allowlist:
`https://claude.ai/api/mcp/auth_callback` (current) and
`https://claude.com/api/mcp/auth_callback` (documented by Anthropic as a
possible future value), plus loopback URIs for Claude Code/Desktop testing.
claude.ai registers a **new client on every fresh connection**, so no hard
count cap (it would lock the owner out). Instead evict clients that never
complete an authorization within 1 hour, and clients with no live grant
after 30 days. Rate-limit `/register` per verified client address.

**Deferred alternative: CIMD instead of DCR.** Claude prefers a Client ID
Metadata Document when the AS metadata advertises
`client_id_metadata_document_supported: true` and `"none"` in
`token_endpoint_auth_methods_supported`. Accepting only Anthropic's CIMD
URLs would remove open `/register` (and with it eviction and its rate
limit). mcp 2.3.0 has no server-side CIMD support, so it would be custom
code; revisit once the SDK adds it or if open DCR proves noisy.

**Our tokens.** Opaque random 256-bit strings, never JWTs (nothing to verify
offline, nothing to leak in claims). Only SHA-256 hashes are stored. Access
tokens live 1 hour; refresh tokens rotate on every use with reuse detection
(a replayed old refresh token revokes the whole grant). Because claude.ai
refreshes ahead of expiry and again on a 401, one lost refresh response
would otherwise look like a replay and force a re-login on the phone, so the
immediately previous refresh token stays valid for a 60 s grace window. Each token records
`client_id`, `resource` (one service), `scopes` (tier), `subject` (owner
email), timestamps. Store: `~/.google/mcp-remote/auth.sqlite3`, mode 0600,
alongside but separate from the Google token store.

**Owner CLI** (in the same console script):
`gworkspace-mcp-remote grants` (list), `revoke <id>|--all`, `rotate-keys`.

### Option B: multi-user, Google as identity provider

Each visitor signs in with Google, grants Gmail/Drive/... scopes to a client
the operator owns, and the server stores that user's Google refresh token
(envelope-encrypted with Cloud KMS, in Firestore). `account` resolves only
within the caller's own tokens.

Why not now:

- **Google verification.** Gmail (`gmail.modify`, `gmail.send`) and full
  `drive` are restricted scopes. Serving users outside the operator's own
  Workspace means app verification plus an annual third-party security
  assessment (CASA), with real cost and weeks to months of lead time. In
  "Testing" status it is capped at 100 named test users and refresh tokens
  expire after 7 days, which breaks a connector weekly. (The 7-day expiry
  also applies to Option A if the owner's own BYO consent screen is
  External + Testing: remote use makes it worse, because the owner can't run
  `google-auth login` from the phone. The README for remote mode must tell
  the owner to publish their consent screen to "In production"; unverified
  apps for personal use work there with the warning screen. Tokens minted
  while the app was in Testing keep their 7-day expiry, so re-run
  `google-auth login` after publishing. Workspace accounts such as
  handi.co.il may also be blocked by their admin's third-party app access
  controls.)
- **It reverses the product's position.** BYO client ("no third party
  proxying your mail") is the differentiator; B makes the maintainer that
  third party, holding many people's mail and Drive keys. One breach exposes
  every user.
- **Much more surface:** tenant isolation in `get_api`'s cache (key by
  `(subject, service, account)`), per-user quotas, deletion/export, privacy
  policy, abuse handling, incident response.
- Effort: roughly 3 to 6 weeks of engineering plus verification lead time.

B is a separate product decision. Option A's design does not block it: the
provider, token store and `subject` field are the same building blocks.

**Recommendation: A.** It solves the actual need (the owner on the phone),
keeps the trust boundary where it is today (the owner's tokens, the owner's
machine), needs no Google verification, and reuses the existing store,
`get_api`, and the web client already created.

### Rejected: Google as the connector's authorization server (pass-through)

The redirect URIs on `mcp-oauth-web.json` suggest this was tried: point the
protected resource metadata at Google, have claude.ai get Google tokens
directly, and use the incoming bearer token for API calls. Rejected because:
Google does not support DCR, so it only works with a pasted client
ID/secret; claude.ai would then hold a refresh token with full Gmail/Drive
scope for the owner's account; the MCP security best-practices explicitly
forbid token pass-through (the server cannot tell a token meant for it from
one meant for another app); it bypasses the multi-account store entirely
(one Google login per connector, no aliases); and it makes the read-only gate
unenforceable at the token level.

## Where it runs

| | Mac + Tailscale Funnel | Mac + Cloudflare Tunnel | Cloud Run |
|---|---|---|---|
| Availability | Only while the Mac is awake and online | Same | Always on |
| Who terminates TLS | **Your Mac** (Funnel relays encrypted TCP) | Cloudflare edge (sees plaintext mail/docs) | Google front end |
| Hostname | Stable `<machine>.<tailnet>.ts.net` | Stable, needs a domain on Cloudflare | Stable `*.run.app` or custom |
| Token location | `~/.google`, unchanged | unchanged | Secret Manager + Firestore |
| Cost / setup | Free, one command | Free, domain + `cloudflared` service | Small monthly cost, deploy pipeline |

**Phase 1: Mac + Tailscale Funnel.** Zero change to where tokens live, and
the tunnel operator never sees plaintext (Funnel ports 443/8443/10000 only;
TLS cert is provisioned for the node). Run the server and `tailscale funnel`
as a launchd agent. Downside, stated plainly: when the laptop sleeps or is
offline, the connectors fail. Cloudflare Tunnel is documented as an
alternative for users who already run it, with the plaintext-at-edge caveat.

**Phase 3 (optional): Cloud Run** (`personal` profile, its own project).
Needed only if "works when the Mac is asleep" matters. Changes:

- Google refresh tokens stored in Secret Manager, mounted read-only; at start
  copy to a tmpfs `~/.google` so `get_credentials` can write refreshed access
  tokens (Google refresh tokens don't rotate, so the secret stays valid).
- Authorization-server state (clients, grants, token hashes) in Firestore
  instead of SQLite.
- Stateless HTTP lets instances scale to zero; `min-instances=1` only if cold
  starts (Python + googleapiclient import, ~2 to 4 s) bother claude.ai.
- Moving the tokens off the laptop is the real security change here: anyone
  with IAM on that project can read them. Dedicated project, no other
  principals, Secret Manager access logged.

## What changes in core

Modest, and nothing about the tool contract changes. Every tool still does
`_api(account)` then `run_tool(...)` then `ok(resolved, data)`.

1. **`core/server.py`**: `build_server` unchanged for stdio. New
   `core/remote.py` (the only new module) builds the parent Starlette app,
   the authorization-server provider, the owner gate, the token store and the
   CLI. Each `server.py` already exposes a module-level `mcp`; `remote.py`
   imports the five, mounts each unauthenticated `mcp.streamable_http_app(...)`
   behind its own bearer-auth middleware stack, and owns all metadata and AS
   routes (see "Mounting mechanics"). No per-server edits beyond what the 2.x
   migration does.
2. **Account allowlist**: `get_api` gains an optional allowlist check
   (`GOOGLE_MCP_ACCOUNTS`, set by `--accounts`). A remote caller can otherwise
   name any account in the store; the allowlist lets the owner expose, say,
   only the personal account to the phone. Unset means today's behaviour.
3. **Thread safety** (finding 3): give each request its own `Http` object,
   googleapiclient's documented pattern. A per-client lock was considered and
   rejected: Docs and Drive share one cached client, `run_tool(fn)` gets no
   service or account (making it lock would touch every call site), and the
   lock would be held through retry sleeps and long downloads while claude.ai
   times out. Keying a cache by thread would not help either, because each
   wrapper keeps one `self.service` for the life of the process. Instead,
   build every client with `build(..., requestBuilder=...)`, where the builder
   makes a fresh `HttpRequest(AuthorizedHttp(creds, http=httplib2.Http()),
   ...)` per request. That has to land in three places: google-auth-core
   `get_service` (Sheets/Docs/Drive), gmail-cli-oauth and
   google-calendar-cli (three releases, then bump the pins here). Calls stay
   fully parallel. Worth landing for stdio as soon as the 2.x migration
   merges, independent of this spec.
4. **Atomic token refresh** (finding 4, a **google-auth-core** change): write
   refreshed tokens to a temp file then `os.replace`, under a per-account
   lock. Ships as a google-auth-core release this repo then requires.
5. **Read-only gate made per-process configurable** (see Security). Today
   `READONLY` is read at import; `remote.py` must set the env before importing
   the server modules, or (Phase 2) the gate moves to call time. `register`
   also gains `GOOGLE_MCP_NO_DESTRUCTIVE` (skip `destructive=True` tools) and
   an allow set for the named exfiltration tools (`--allow-tools`).
6. **Call-time hook** for the audit log (and Phase 2 tier checks): a
   `WorkspaceServer.call_tool` override, which already exists on the 2.x
   branch for error mapping, or the `MCPServer(middleware=...)` parameter in
   2.3.0.

### The "servers never run interactive auth" invariant

It carries over unchanged and gets stronger tests. The invariant is about
**Google data credentials**: no server ever starts a Google consent flow for
Gmail/Drive/... scopes or writes a new refresh token. In remote mode:

- The MCP OAuth flow (claude.ai to us) is not Google auth; it issues our own
  tokens and never touches `~/.google/tokens/`.
- The owner sign-in uses Google for **identity only** (`openid email`),
  through a separate code path that never calls
  `google_auth_core.authenticate` and never writes to the token store.
- Missing or expired Google tokens still surface as the existing
  `Run: google-auth login <account>` error, now telling the owner to run it
  on the host machine.

Tests to add to `tests/test_integration.py` (the spec file):

- the existing `authenticate`-must-not-run monkeypatch, applied to a full
  remote OAuth round trip plus a tool call over HTTP;
- the token directory's file set and mtimes are unchanged after an owner
  sign-in;
- the scope set requested by the owner gate is exactly `{"openid", "email"}`.

## Security

### What's at stake

The suite can send and forward mail, create filters, share Drive files
(including `anyone` links), permanently delete messages and files, and edit
every doc and sheet, across every logged-in account. A remote endpoint turns
"someone at my keyboard" into "anyone on the internet who gets a token".

### Threat model

| Threat | Mitigation |
|---|---|
| Stranger finds the URL | Every MCP path returns 401 without a bearer token; only `/.well-known/*`, `/register`, `/authorize`, `/token`, `/revoke`, `/owner/callback` and the consent POST are public, and none of them grants anything without the owner gate |
| Attacker registers a client via DCR and phishes the owner into consenting | Redirect-URI allowlist (claude.ai/claude.com callbacks and loopback only), so the code can only go to claude.ai or the owner's own machine; consent page shows client name, redirect host and tier |
| Stolen MCP access token | 1 h lifetime, bound to one service by RFC 8707 audience, scoped to a tier; `revoke --all` |
| Stolen refresh token | Rotation with reuse detection revokes the grant |
| Owner gate brute force | Phase 1 uses Google sign-in only (Google's own protections). Behind Funnel every request arrives from 127.0.0.1, so per-IP limits would be global and let an attacker lock out the owner; only key limits on `X-Forwarded-For` if Phase 0 confirms Funnel sets it and nothing else can. Same for limits on `/token` and `/register` |
| CSRF / login fixation on the owner callback | `state` bound to a pending authorize, ID-token `nonce`, PKCE, `sub` pinning (see Owner gate) |
| Clickjacked consent | POST + CSRF token, `frame-ancestors 'none'` |
| Codes and tokens in logs | uvicorn access logs record query strings (the Google `code` on `/owner/callback`, `state` on `/authorize`): access log disabled or query strings redacted; never log `Authorization` headers |
| Optional extra fence | Claude's connector traffic comes from a published Anthropic IP range (`160.79.104.0/21` per Anthropic's docs; recheck before use). An opt-in `--allow-cidrs` on the MCP paths, `/token` and `/register` shrinks exposure, at the cost of breaking if the range changes |
| **Prompt injection** via email/doc content telling Claude to forward mail or share files | The biggest real risk, present in stdio too but amplified by phone use with "always allow". Mitigations: read-only by default, destructive tools a separate opt-in, claude.ai's per-tool approval driven by our annotations, an audit log the owner can read, account allowlist |
| Tunnel operator reads traffic | Tailscale Funnel terminates TLS on the Mac; Cloudflare Tunnel does not, documented |
| Host compromise | Same as today: `~/.google` was already the crown jewel; remote mode adds an auth DB holding only token hashes |
| DNS rebinding against the local port | Bind 127.0.0.1, `TransportSecuritySettings` host allowlist |

### Token storage

- Google tokens: unchanged location and 0600 permissions on the Mac; Secret
  Manager on Cloud Run.
- MCP tokens: hashes only, SQLite 0600 (Firestore on Cloud Run). Owner
  web-client secret read from `mcp-oauth-web.json`, never logged.
- Audit log: `~/.google/mcp-remote/audit.jsonl`, one line per tool call
  (time, client_id, service, tool, resolved account, ok/error code), **no
  arguments or results** (they contain mail content).

### Read-only gate and destructive annotations, remotely

Three tiers, mapped onto the existing `@register` flags so no tool needs
editing:

| Tier | Tools exposed | How enabled |
|---|---|---|
| `read` (default) | `mutating=False` | always |
| `write` | + `mutating=True, destructive=False` | `--allow-writes` |
| `destructive` | + `destructive=True` | `--allow-destructive` (implies writes) |

- **Phase 1** enforces tiers per process at registration time, reusing the
  existing mechanism: `READONLY` covers `read`, and a sibling
  `GOOGLE_MCP_NO_DESTRUCTIVE` skips `destructive=True` tools the same way.
  Hidden tools never appear in `list_tools`, same guarantee as stdio. These
  env vars are process-wide, so in Phase 1 **one tier applies to all five
  services** (you can't have read-only Gmail with writable Sheets in one
  process).
- **Phase 2** moves the check to call time so one server can serve several
  tiers: our OAuth scopes `workspace.read`, `workspace.write`,
  `workspace.destructive`; the owner picks the tier on the consent page;
  `WorkspaceServer.list_tools` filters by the caller's token scopes
  (`get_access_token()`), and `call_tool` rejects out-of-tier tools with
  `insufficient_scope`. The process flags become the ceiling.
- **Annotations** (`readOnlyHint`, `destructiveHint`, `idempotentHint`) are
  sent unchanged over HTTP. claude.ai uses them for its tool-approval UX, but
  they are hints for the client, not a control: the server-side tiers are the
  control. The `[DESTRUCTIVE]` description suffix also stays, so the model
  sees it.
- The `write` tier is wider than it sounds: everything `mutating=True,
  destructive=False`. That includes the paths a prompt injection would use
  to get data out or act as the owner: `send_message`, `forward_message`,
  `send_draft`, `reply_to_message`, `share_file`, `copy_file`,
  `create_filter` (takes an arbitrary `action`, e.g. auto-forward),
  `block_sender`, `create_event`, `update_event` and `add_attendees` (send
  invites to arbitrary addresses), `respond_to_event` (can notify all
  guests), `upload_file`, plus tools that make Google fetch a URL the
  attacker picks (Docs `insert_inline_image`, Sheets `IMAGE`/`IMPORTXML`
  formulas written through any cell-writing tool). Including, not limited
  to: the list is maintained as a named set in code, reviewed when tools
  are added.
  Proposal: these stay out of `write` unless named explicitly
  (`--allow-tools`). Open question below.

## Testing

All in-memory, no network, following existing patterns (`store_env`,
`write_token`, FakeAPI / `MagicMock(spec=...)`):

- Starlette `TestClient` against the parent app: 401 + `WWW-Authenticate`
  on each service path; PRM and AS metadata documents correct per path.
- Full OAuth round trip with a stubbed owner gate: DCR, authorize with PKCE,
  token, refresh rotation, reuse detection, revoke.
- Audience binding: a Gmail token is rejected on `/drive/mcp`.
- Tier gating: `list_tools` per tier matches the `@register` flags for all
  five servers (mirrors the existing read-only gate test).
- Account allowlist: a non-allowlisted account returns the auth error, and
  isolation under concurrency still holds over HTTP.
- Thread safety: concurrent calls on one account from different threads get
  different `Http` objects; a concurrent refresh never leaves a truncated
  token file (google-auth-core test).
- Refresh rotation grace window: previous token accepted within 60 s,
  rejected after, replay after that revokes the grant.
- `/register` rejects a redirect URI not on the allowlist.
- Owner gate rejects an email not on the allowlist and a known email whose
  `sub` doesn't match the pinned one; rejects a reused or unknown `state`.
- `GOOGLE_MCP_NO_DESTRUCTIVE` hides every `destructive=True` tool in all five
  servers; `--allow-tools` exposes only the named exfiltration tools.
- Invariant tests listed under Core changes.
- Manual (owner): add each connector in claude.ai web, then the iOS app, run a
  read tool, confirm a write tool is absent in the default tier.

## Phased plan and effort

| Phase | Scope | Estimate |
|---|---|---|
| 0. Spike | After the 2.x branch merges: mount two servers under one Starlette app with combined lifespans, minimal provider, add as a claude.ai connector through Funnel, confirm DCR + PKCE + audience binding end to end, confirm how claude.ai behaves with stateless mode, check whether Funnel sets a trustworthy `X-Forwarded-For`, check whether claude.ai sends an `Origin` header (an empty `allowed_origins` 403s any request that has one) | 0.5 to 1 day |
| 1a. Prerequisites | Per-request `Http` via `requestBuilder` in google-auth-core, gmail-cli-oauth and google-calendar-cli; atomic token refresh in google-auth-core; three releases, bump pins here | 1.5 to 2 days |
| 1. Single-user remote | `core/remote.py` (mounting, middleware, metadata routes), `serve` command, `GOOGLE_MCP_NO_DESTRUCTIVE` in `register`, `--allow-tools` exfiltration set, call-time audit hook, owner gate (Google identity, state/nonce/PKCE, `sub` pinning), consent page hardening, SQLite token store with rotation grace, DCR eviction, tier flags, account allowlist, log redaction, audit log, tests, README section + launchd example | 5 to 7 days |
| 2. Per-token tiers | OAuth scopes, consent-page tier picker, call-time `list_tools`/`call_tool` filtering, `grants`/`revoke` CLI polish | 1.5 to 2 days |
| 3. Cloud Run (optional) | Secret Manager token mount, Firestore AS state, Dockerfile, deploy notes | 2 to 3 days |
| B. Multi-user (deferred) | Encrypted per-user tokens, tenant-keyed cache, Google verification/CASA | 3 to 6 weeks + verification lead time |

Dependencies: mcp 2.x migration merged first. Phase 1a can land on its own
right after it (it matters for stdio under 2.x too).

## Out of scope

- Multi-user hosting (Option B), billing, a public directory listing.
- SSE transport.
- Any change to `google-auth login` or the BYO desktop client.
- Server-initiated features that need stateful sessions.

## Open questions

1. Default `write` tier: should the send/forward/reply/share/filter/invite
   tools listed under Security need an explicit `--allow-tools` even when
   writes are on?
2. Is "works only while the Mac is awake" acceptable for Phase 1, or should
   Phase 3 (Cloud Run) be pulled forward?
3. Should the owner allowlist default to every account in the store, or to
   the default account only?
4. Ship `remote` as a `[remote]` extra (pulls `uvicorn`) or in the base install?
