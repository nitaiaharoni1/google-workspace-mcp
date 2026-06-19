# Google Drive MCP server — design

**Date:** 2026-06-19
**Status:** Approved, pending implementation
**Author:** nitai (+ Claude)

## Goal

Add a fifth service to the `google-workspace-mcp` monorepo: a Google Drive MCP
server, consistent with the existing Gmail / Calendar / Sheets / Docs servers.
Multi-account, persistent auth, per-call `account` param. Tools surface as
`mcp__google-drive__*`.

There is already a hosted Google Drive MCP connected via claude.ai
(`drivemcp.googleapis.com`); we are deliberately building a local server instead
for consistency with the existing suite, multi-account support, full control of
the operation set, and availability in the Claude Code CLI.

## Architecture

Mirror the existing service pattern exactly. No changes to `core/`.

- `google_workspace_mcp/drive/__init__.py`
- `google_workspace_mcp/drive/drive_api.py` — thin wrapper class `DriveAPI`
  over `core.get_service("drive", "v3", account=account)`.
- `google_workspace_mcp/drive/server.py` — `build_server("gdrive-mcp", ...)`,
  one `@register`-decorated tool per operation, `_api()` helper via
  `get_api("drive", DriveAPI, account)`, `main()` calling `mcp.run()`.

Each tool body is the standard envelope:
`api, resolved = _api(account); return ok(resolved, run_tool(lambda: api.<method>(...)))`.

## Scope & auth

- Add to `~/REPOS/google-auth-core/google_auth_core/scopes.py`:
  - `DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]` (full read/write).
  - Append `DRIVE_SCOPES` to `ALL_SCOPES` and add `"DRIVE_SCOPES"` to `__all__`.
- `google-auth-core` and `google_workspace_mcp` are editable installs, so no
  reinstall is needed for code changes — but the new scope requires re-consent.
- **GCP:** enable the **Google Drive API** in project `google-mcp`
  (`noted-sandbox-498211-j7`).
- **Re-auth** each of the 3 accounts (browser consent) so the new Drive scope is
  granted into the unified token:
  `~/REPOS/google-workspace-mcp/.venv/bin/google-auth login`
  (accounts: nitaiaharoni1@gmail.com, nitai@handi.co.il, nitai@tesse.co).

## Registration

- `pyproject.toml` `[project.scripts]`:
  `gdrive-mcp = "google_workspace_mcp.drive.server:main"`.
- Register in Claude Code at **user scope**:
  `claude mcp add -s user google-drive ~/REPOS/google-workspace-mcp/.venv/bin/gdrive-mcp`
  (entry point appears after an editable re-sync of the venv; verify the binary
  exists before registering).
- Restart the Claude Code session to load `mcp__google-drive__*` tools.

## Tools

Drive API v3. Flags use the existing `register(mcp, *, mutating=, destructive=)`
convention.

| Tool | Flags | Behavior |
|---|---|---|
| `search_files` | read | Query by name / mimeType / parent / full-text. Returns id, name, mimeType, size, modifiedTime, parents. Optional `page_size`. |
| `list_files` | read | Recent files; optional `folder_id` to list a folder's children. |
| `get_file` | read | Full metadata for one file id. |
| `download_file` | read | Binary file → **local path**. Returns `{path, bytes}`. Uses `MediaIoBaseDownload` + `files().get_media`. |
| `export_file` | read | Google-native file → md/pdf/txt/csv/xlsx → local path. Uses `files().export_media`. |
| `read_file_text` | read | Text content inline (small text or native files exported to text). |
| `upload_file` | mutating | Local path → Drive. Optional `parent_id`, explicit `mime_type`. Uses `MediaFileUpload`. |
| `update_file_content` | mutating | Replace an existing file's bytes from a local path. |
| `create_folder` | mutating | Create folder; optional `parent_id`. |
| `move_file` | mutating | Reparent: add new parent, remove old parents. |
| `rename_file` | mutating | Update `name`. |
| `copy_file` | mutating | `files().copy`; optional new name / parent. |
| `share_file` | mutating | Add a permission (email + role, or `anyone` link). |
| `list_permissions` | read | List permissions on a file. |
| `trash_file` | mutating | Set `trashed=true` (reversible). |
| `delete_file` | mutating, **destructive** | Permanent `files().delete`. |

### Export mime mapping (`export_file`)

- Google Docs (`application/vnd.google-apps.document`) →
  `text/markdown`, `application/pdf`, `text/plain`.
- Google Sheets (`application/vnd.google-apps.spreadsheet`) →
  `text/csv`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (xlsx).
- Google Slides (`application/vnd.google-apps.presentation`) → `application/pdf`.

A small `format → mime` lookup in `drive_api.py` resolves the target; unknown
combinations raise `ValueError` (surfaced via `run_tool`).

## Key design choices

- **Binary I/O via local file paths, never base64 inline.** `download_file` and
  `export_file` write to a path and return `{path, bytes}`; `upload_file` /
  `update_file_content` read a local path. Returning megabytes of base64 through
  MCP is the wrong call.
- **Full `drive` scope** (not `drive.readonly` / `drive.file`) so the server can
  organize, share, and trash arbitrary existing files — matching the write
  capability the Sheets/Docs servers already hold.
- **No `core/` changes.** Everything reuses `build_server`, `register`,
  `get_api`, `run_tool`, `ok`.

## Error handling

Unchanged from the other servers: every API call is wrapped in `run_tool(...)`;
responses use the `ok(resolved, data)` envelope. Argument validation errors
(bad export format, missing path) raise `ValueError` inside the lambda and are
caught by `run_tool`.

## Testing

- `tests/test_drive_server.py` — mirror `tests/test_docs_server.py`: mock the
  Drive service and assert each tool calls the right `files()` method with the
  right arguments. No network.
- **Live verification** (after re-auth): one `search_files` per account, one
  `download_file`/`export_file` round-trip, and a create-folder → upload →
  trash cycle on a throwaway file.

## Out of scope (YAGNI)

- Revisions / version history.
- Shared-drive (Team Drive) specific params (`supportsAllDrives`,
  `driveId`) — add later if needed.
- Comments / replies.
- Real-time change watching / push notifications.

## Rollout checklist

1. Add `DRIVE_SCOPES` to `scopes.py`.
2. Create `drive/` package (`__init__.py`, `drive_api.py`, `server.py`).
3. Add `gdrive-mcp` entry point to `pyproject.toml`; re-sync editable venv.
4. Add `tests/test_drive_server.py`; run the suite.
5. Enable the Drive API in GCP project `google-mcp`.
6. Re-auth the 3 accounts (`google-auth login`).
7. `claude mcp add -s user google-drive .../gdrive-mcp`.
8. Restart session; live-verify per account.
9. Update `README.md` and the `google-workspace-mcp-setup` memory.
