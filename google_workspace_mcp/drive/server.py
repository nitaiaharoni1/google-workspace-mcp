"""Google Drive MCP server: search, read, upload, organize, and share files."""
from __future__ import annotations

from ..core import build_server, register, get_api, run_tool, ok
from .drive_api import DriveAPI

mcp = build_server(
    "gdrive-mcp",
    "Google Drive: search, read, upload, organize, and share files for one or more Google accounts.",
)


def _api(account=None):
    return get_api("drive", DriveAPI, account)


# --- read ---
@register(mcp)
def search_files(
    account: str | None = None,
    query: str | None = None,
    name: str | None = None,
    mime_type: str | None = None,
    parent_id: str | None = None,
    full_text: str | None = None,
    page_size: int = 25,
) -> dict:
    """Search Drive by name, mimeType, parent folder, full-text, and/or a raw q= query."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.search_files(
            query=query, name=name, mime_type=mime_type,
            parent_id=parent_id, full_text=full_text, page_size=page_size,
        )
    )
    return ok(resolved, data)


@register(mcp)
def list_files(account: str | None = None, folder_id: str | None = None, page_size: int = 25) -> dict:
    """List recent files, optionally restricted to a folder's children."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.list_files(folder_id=folder_id, page_size=page_size))
    return ok(resolved, data)


@register(mcp)
def get_file(account: str | None = None, file_id: str = "") -> dict:
    """Get full metadata for one file id."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_file(file_id))
    return ok(resolved, data)


@register(mcp)
def download_file(
    account: str | None = None,
    file_id: str = "",
    output_path: str | None = None,
) -> dict:
    """Download a binary (non-Google-native) file to a local path.

    Writes to output_path, or to the system temp dir using the file's name when
    omitted. Returns {path, bytes, name, mimeType}. Google Docs/Sheets/Slides
    must use export_file instead.
    """
    api, resolved = _api(account)
    data = run_tool(lambda: api.download_file(file_id, output_path=output_path))
    return ok(resolved, data)


@register(mcp)
def export_file(
    account: str | None = None,
    file_id: str = "",
    fmt: str = "pdf",
    output_path: str | None = None,
) -> dict:
    """Export a Google-native file (Doc/Sheet/Slide) to md/pdf/txt/csv/xlsx on disk.

    fmt: markdown/md, pdf, txt/plain (Docs); csv/xlsx (Sheets); pdf (Slides).
    Writes to output_path, or to the system temp dir when omitted.
    Returns {path, bytes, name, sourceMimeType, exportMimeType}.
    """
    api, resolved = _api(account)
    data = run_tool(lambda: api.export_file(file_id, fmt, output_path=output_path))
    return ok(resolved, data)


@register(mcp)
def read_file_text(account: str | None = None, file_id: str = "") -> dict:
    """Read small text inline (UTF-8 binary files, or Docs/Sheets exported as text).

    Content is capped at 1 MiB; larger files raise an error — use download_file or
    export_file instead. Slides and other non-text native types are not supported.
    """
    api, resolved = _api(account)
    data = run_tool(lambda: api.read_file_text(file_id))
    return ok(resolved, data)


@register(mcp)
def list_permissions(account: str | None = None, file_id: str = "") -> dict:
    """List permissions on a file."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.list_permissions(file_id))
    return ok(resolved, data)


# --- write ---
@register(mcp, mutating=True)
def upload_file(
    account: str | None = None,
    local_path: str = "",
    name: str | None = None,
    parent_id: str | None = None,
    mime_type: str | None = None,
) -> dict:
    """Upload a local file to Drive. Optional parent_id and explicit mime_type."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.upload_file(local_path, name=name, parent_id=parent_id, mime_type=mime_type)
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_file_content(
    account: str | None = None,
    file_id: str = "",
    local_path: str = "",
    mime_type: str | None = None,
) -> dict:
    """Replace an existing binary file's content from a local path.

    Cannot update Google-native files (Docs/Sheets/Slides/folders) — those must
    be edited via their respective APIs or re-uploaded as new files.
    """
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.update_file_content(file_id, local_path, mime_type=mime_type)
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def create_folder(
    account: str | None = None,
    name: str = "",
    parent_id: str | None = None,
) -> dict:
    """Create a folder; optional parent_id to nest inside an existing folder."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.create_folder(name, parent_id=parent_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def move_file(
    account: str | None = None,
    file_id: str = "",
    new_parent_id: str = "",
) -> dict:
    """Move a file to a new parent folder (reparents; removes old parents)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.move_file(file_id, new_parent_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def rename_file(account: str | None = None, file_id: str = "", name: str = "") -> dict:
    """Rename a file."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.rename_file(file_id, name))
    return ok(resolved, data)


@register(mcp, mutating=True)
def copy_file(
    account: str | None = None,
    file_id: str = "",
    name: str | None = None,
    parent_id: str | None = None,
) -> dict:
    """Copy a file; optional new name and/or destination parent folder."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.copy_file(file_id, name=name, parent_id=parent_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def share_file(
    account: str | None = None,
    file_id: str = "",
    role: str = "reader",
    email: str | None = None,
    anyone: bool = False,
    send_notification: bool = True,
) -> dict:
    """Share a file with an email address (role: reader/writer/commenter) or anyone link."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.share_file(
            file_id, role=role, email=email, anyone=anyone,
            send_notification=send_notification,
        )
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def trash_file(account: str | None = None, file_id: str = "") -> dict:
    """Move a file to trash (reversible from the Drive UI)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.trash_file(file_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_file(account: str | None = None, file_id: str = "") -> dict:
    """Permanently delete a file (cannot be undone)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_file(file_id))
    return ok(resolved, data)


# --- batch ---
def _coalesce_move_items(items, file_ids, new_parent_id):
    if items:
        return items
    if file_ids and new_parent_id:
        return [{"file_id": fid, "new_parent_id": new_parent_id} for fid in file_ids]
    raise ValueError(
        "provide items=[{file_id, new_parent_id}, ...] or file_ids=[...] with new_parent_id"
    )


@register(mcp, mutating=True)
def batch_move_files(
    account: str | None = None,
    items: list | None = None,
    file_ids: list | None = None,
    new_parent_id: str | None = None,
) -> dict:
    """Move many files in one call.

    Pass items=[{file_id, new_parent_id}, ...] for per-file destinations, or
    file_ids=[...] with a shared new_parent_id. Per-file errors are reported
    individually without aborting the rest; returns {total, succeeded, failed, results}.
    """
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.batch_move_files(_coalesce_move_items(items, file_ids, new_parent_id))
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def batch_create_folders(account: str | None = None, items: list | None = None) -> dict:
    """Create many folders in one call.

    items=[{name, parent_id?}, ...]. Returns each created folder's id so you can
    follow up with batch_move_files. Per-folder errors are reported individually.
    """
    api, resolved = _api(account)
    data = run_tool(lambda: api.batch_create_folders(items or []))
    return ok(resolved, data)


@register(mcp, mutating=True)
def batch_trash_files(account: str | None = None, file_ids: list | None = None) -> dict:
    """Trash many files in one call (reversible). file_ids=[...].

    Per-file errors are reported individually; returns {total, succeeded, failed, results}.
    """
    api, resolved = _api(account)
    data = run_tool(lambda: api.batch_trash_files(file_ids or []))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def batch_delete_files(account: str | None = None, file_ids: list | None = None) -> dict:
    """Permanently delete many files in one call. file_ids=[...].

    Per-file errors are reported individually; returns {total, succeeded, failed, results}.
    """
    api, resolved = _api(account)
    data = run_tool(lambda: api.batch_delete_files(file_ids or []))
    return ok(resolved, data)


def main():
    mcp.run()
