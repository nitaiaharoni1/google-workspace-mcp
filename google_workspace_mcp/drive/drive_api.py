"""Google Drive API wrapper (search, read, upload, organize, share)."""
from __future__ import annotations

import io
import mimetypes
import os
import re
import tempfile

import google_auth_core as core
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

GOOGLE_APPS_PREFIX = "application/vnd.google-apps."
FOLDER_MIME = "application/vnd.google-apps.folder"

FILE_LIST_FIELDS = "nextPageToken, files(id, name, mimeType, size, modifiedTime, parents)"
FILE_METADATA_FIELDS = "id, name, mimeType, size, modifiedTime, parents, webViewLink, trashed, owners, shared"

# Max bytes returned inline by read_file_text (1 MiB).
TEXT_READ_MAX_BYTES = 1_048_576

# format alias -> export mimeType, keyed by source Google Apps mimeType.
EXPORT_FORMATS: dict[str, dict[str, str]] = {
    "application/vnd.google-apps.document": {
        "markdown": "text/markdown",
        "md": "text/markdown",
        "pdf": "application/pdf",
        "txt": "text/plain",
        "plain": "text/plain",
    },
    "application/vnd.google-apps.spreadsheet": {
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "application/vnd.google-apps.presentation": {
        "pdf": "application/pdf",
    },
}


def _is_google_native(mime_type: str | None) -> bool:
    return bool(mime_type and mime_type.startswith(GOOGLE_APPS_PREFIX))


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name) or "download"
    return re.sub(r'[^\w.\- ]', "_", base)


def _default_output_path(name: str, suffix: str = "") -> str:
    out_dir = tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    stem, ext = os.path.splitext(_sanitize_filename(name))
    if suffix and not ext:
        ext = suffix if suffix.startswith(".") else f".{suffix}"
    return os.path.join(out_dir, f"{stem}{ext}")


def _resolve_export_mime(source_mime: str, fmt: str) -> str:
    mapping = EXPORT_FORMATS.get(source_mime)
    if not mapping:
        raise ValueError(
            f"export_file does not support source mimeType {source_mime!r}; "
            f"supported: {sorted(EXPORT_FORMATS)}"
        )
    export_mime = mapping.get(fmt.lower())
    if not export_mime:
        raise ValueError(
            f"unknown export format {fmt!r} for {source_mime!r}; "
            f"allowed: {sorted(mapping)}"
        )
    return export_mime


def _download_to_bytes(service, request) -> bytes:
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


class DriveAPI:
    def __init__(self, account=None):
        self.account = account
        self.service = core.get_service("drive", "v3", account=account)

    def _files(self):
        return self.service.files()

    def search_files(
        self,
        query: str | None = None,
        name: str | None = None,
        mime_type: str | None = None,
        parent_id: str | None = None,
        full_text: str | None = None,
        page_size: int = 25,
    ):
        parts = ["trashed = false"]
        if query:
            parts.append(f"({query})")
        if name:
            escaped = name.replace("'", "\\'")
            parts.append(f"name contains '{escaped}'")
        if mime_type:
            parts.append(f"mimeType = '{mime_type}'")
        if parent_id:
            parts.append(f"'{parent_id}' in parents")
        if full_text:
            escaped = full_text.replace("'", "\\'")
            parts.append(f"fullText contains '{escaped}'")
        q = " and ".join(parts)
        return self._files().list(
            q=q,
            pageSize=page_size,
            fields=FILE_LIST_FIELDS,
        ).execute()

    def list_files(self, folder_id: str | None = None, page_size: int = 25):
        q = "trashed = false"
        if folder_id:
            q += f" and '{folder_id}' in parents"
        return self._files().list(
            q=q,
            orderBy="modifiedTime desc",
            pageSize=page_size,
            fields=FILE_LIST_FIELDS,
        ).execute()

    def get_file(self, file_id: str):
        return self._files().get(fileId=file_id, fields=FILE_METADATA_FIELDS).execute()

    def download_file(self, file_id: str, output_path: str | None = None):
        meta = self.get_file(file_id)
        mime = meta.get("mimeType", "")
        if _is_google_native(mime):
            raise ValueError(
                f"download_file only supports binary files; {mime!r} is a Google-native "
                "file — use export_file or read_file_text instead"
            )
        if output_path is None:
            output_path = _default_output_path(meta.get("name", file_id))
        else:
            out_dir = os.path.dirname(os.path.abspath(output_path))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
        request = self._files().get_media(fileId=file_id)
        data = _download_to_bytes(self.service, request)
        with open(output_path, "wb") as f:
            f.write(data)
        return {"path": output_path, "bytes": len(data), "name": meta.get("name"), "mimeType": mime}

    def export_file(self, file_id: str, fmt: str, output_path: str | None = None):
        meta = self.get_file(file_id)
        source_mime = meta.get("mimeType", "")
        export_mime = _resolve_export_mime(source_mime, fmt)
        if output_path is None:
            ext = mimetypes.guess_extension(export_mime) or f".{fmt.lower()}"
            output_path = _default_output_path(meta.get("name", file_id), suffix=ext)
        else:
            out_dir = os.path.dirname(os.path.abspath(output_path))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
        request = self._files().export_media(fileId=file_id, mimeType=export_mime)
        data = _download_to_bytes(self.service, request)
        with open(output_path, "wb") as f:
            f.write(data)
        return {
            "path": output_path,
            "bytes": len(data),
            "name": meta.get("name"),
            "sourceMimeType": source_mime,
            "exportMimeType": export_mime,
        }

    def read_file_text(self, file_id: str, max_bytes: int = TEXT_READ_MAX_BYTES):
        meta = self.get_file(file_id)
        mime = meta.get("mimeType", "")
        if _is_google_native(mime):
            if mime == FOLDER_MIME:
                raise ValueError("read_file_text cannot read a folder")
            if mime == "application/vnd.google-apps.document":
                export_mime = "text/plain"
            elif mime == "application/vnd.google-apps.spreadsheet":
                export_mime = "text/csv"
            else:
                raise ValueError(
                    f"read_file_text cannot extract text from {mime!r}; use export_file"
                )
            request = self._files().export_media(fileId=file_id, mimeType=export_mime)
            data = _download_to_bytes(self.service, request)
        else:
            request = self._files().get_media(fileId=file_id)
            data = _download_to_bytes(self.service, request)
        if len(data) > max_bytes:
            raise ValueError(
                f"file content is {len(data)} bytes, exceeding read_file_text cap of {max_bytes}; "
                "use download_file or export_file instead"
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "file is not UTF-8 text; use download_file for binary content"
            ) from exc
        return {
            "fileId": file_id,
            "name": meta.get("name"),
            "mimeType": mime,
            "bytes": len(data),
            "text": text,
        }

    def upload_file(
        self,
        local_path: str,
        name: str | None = None,
        parent_id: str | None = None,
        mime_type: str | None = None,
    ):
        if not os.path.isfile(local_path):
            raise ValueError(f"local path does not exist or is not a file: {local_path!r}")
        file_name = name or os.path.basename(local_path)
        guessed, _ = mimetypes.guess_type(local_path)
        media_mime = mime_type or guessed or "application/octet-stream"
        body: dict = {"name": file_name}
        if parent_id:
            body["parents"] = [parent_id]
        media = MediaFileUpload(local_path, mimetype=media_mime, resumable=True)
        created = self._files().create(body=body, media_body=media, fields=FILE_METADATA_FIELDS).execute()
        return created

    def update_file_content(self, file_id: str, local_path: str, mime_type: str | None = None):
        if not os.path.isfile(local_path):
            raise ValueError(f"local path does not exist or is not a file: {local_path!r}")
        meta = self.get_file(file_id)
        mime = meta.get("mimeType", "")
        if _is_google_native(mime):
            raise ValueError(
                f"update_file_content cannot replace bytes on Google-native files ({mime!r}); "
                "edit via the Docs/Sheets/Slides APIs or export, edit locally, and re-upload"
            )
        guessed, _ = mimetypes.guess_type(local_path)
        media_mime = mime_type or guessed or mime or "application/octet-stream"
        media = MediaFileUpload(local_path, mimetype=media_mime, resumable=True)
        return self._files().update(
            fileId=file_id, media_body=media, fields=FILE_METADATA_FIELDS
        ).execute()

    def create_folder(self, name: str, parent_id: str | None = None):
        body: dict = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            body["parents"] = [parent_id]
        return self._files().create(body=body, fields=FILE_METADATA_FIELDS).execute()

    def move_file(self, file_id: str, new_parent_id: str):
        meta = self.get_file(file_id)
        previous_parents = ",".join(meta.get("parents", []))
        return self._files().update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=previous_parents,
            fields=FILE_METADATA_FIELDS,
        ).execute()

    def rename_file(self, file_id: str, name: str):
        return self._files().update(
            fileId=file_id, body={"name": name}, fields=FILE_METADATA_FIELDS
        ).execute()

    def copy_file(self, file_id: str, name: str | None = None, parent_id: str | None = None):
        body: dict = {}
        if name:
            body["name"] = name
        if parent_id:
            body["parents"] = [parent_id]
        return self._files().copy(
            fileId=file_id, body=body, fields=FILE_METADATA_FIELDS
        ).execute()

    def share_file(
        self,
        file_id: str,
        role: str = "reader",
        email: str | None = None,
        anyone: bool = False,
        send_notification: bool = True,
    ):
        if anyone:
            body = {"type": "anyone", "role": role}
        elif email:
            body = {"type": "user", "role": role, "emailAddress": email}
        else:
            raise ValueError("share_file requires email or anyone=True")
        return self.service.permissions().create(
            fileId=file_id,
            body=body,
            sendNotificationEmail=send_notification,
            fields="id, type, role, emailAddress",
        ).execute()

    def list_permissions(self, file_id: str):
        return self.service.permissions().list(
            fileId=file_id, fields="permissions(id, type, role, emailAddress, displayName)"
        ).execute()

    def trash_file(self, file_id: str):
        return self._files().update(
            fileId=file_id, body={"trashed": True}, fields=FILE_METADATA_FIELDS
        ).execute()

    def delete_file(self, file_id: str):
        self._files().delete(fileId=file_id).execute()
        return {"fileId": file_id, "deleted": True}

    # --- batch helpers ---
    @staticmethod
    def _run_batch(items, fn):
        """Apply ``fn`` to each item, isolating per-item failures.

        Returns a summary with a per-item result list; a single bad item is
        reported as ``{"ok": False, "error": ...}`` instead of aborting the rest.
        """
        results = []
        succeeded = 0
        for item in items:
            try:
                res = fn(item)
                results.append({"ok": True, **res})
                succeeded += 1
            except core.GoogleCoreError as e:
                results.append({"ok": False, "error": str(e), "item": item})
            except Exception as e:  # noqa: BLE001 - normalize to a readable message
                results.append({"ok": False, "error": str(core.map_exception(e)), "item": item})
        return {
            "total": len(items),
            "succeeded": succeeded,
            "failed": len(items) - succeeded,
            "results": results,
        }

    def batch_move_files(self, items):
        """Move many files. ``items``: list of ``{file_id, new_parent_id}``."""
        if not isinstance(items, list) or not items:
            raise ValueError(
                "batch_move_files requires a non-empty list of {file_id, new_parent_id}"
            )

        def _one(item):
            file_id = item.get("file_id")
            new_parent_id = item.get("new_parent_id")
            if not file_id or not new_parent_id:
                raise ValueError(f"each item needs file_id and new_parent_id; got {item!r}")
            data = self.move_file(file_id, new_parent_id)
            return {"file_id": file_id, "name": data.get("name"), "parents": data.get("parents")}

        return self._run_batch(items, _one)

    def batch_create_folders(self, items):
        """Create many folders. ``items``: list of ``{name, parent_id?}``."""
        if not isinstance(items, list) or not items:
            raise ValueError(
                "batch_create_folders requires a non-empty list of {name, parent_id?}"
            )

        def _one(item):
            name = item.get("name")
            if not name:
                raise ValueError(f"each item needs a name; got {item!r}")
            data = self.create_folder(name, parent_id=item.get("parent_id"))
            return {"id": data.get("id"), "name": data.get("name"), "parents": data.get("parents")}

        return self._run_batch(items, _one)

    def batch_trash_files(self, file_ids):
        """Trash many files (reversible). ``file_ids``: list of ids."""
        if not isinstance(file_ids, list) or not file_ids:
            raise ValueError("batch_trash_files requires a non-empty list of file_ids")

        def _one(file_id):
            data = self.trash_file(file_id)
            return {"file_id": file_id, "name": data.get("name"), "trashed": data.get("trashed")}

        return self._run_batch(file_ids, _one)

    def batch_delete_files(self, file_ids):
        """Permanently delete many files. ``file_ids``: list of ids."""
        if not isinstance(file_ids, list) or not file_ids:
            raise ValueError("batch_delete_files requires a non-empty list of file_ids")

        def _one(file_id):
            self.delete_file(file_id)
            return {"file_id": file_id, "deleted": True}

        return self._run_batch(file_ids, _one)
