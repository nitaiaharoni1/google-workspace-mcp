"""Tests for the Google Drive MCP server."""
from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mcp.types import TextContent

from google_workspace_mcp.drive import server
from google_workspace_mcp.drive.drive_api import (
    DriveAPI,
    EXPORT_FORMATS,
    TEXT_READ_MAX_BYTES,
    _resolve_export_mime,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def envelope(res):
    if isinstance(res, tuple):
        content, structured = res
        if structured:
            return structured
        res = content
    for b in res:
        if isinstance(b, TextContent):
            return json.loads(b.text)
    raise AssertionError("no parsable content")


# --- DriveAPI unit (mocked googleapiclient service) ---

def _api_with_mock(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr("google_auth_core.get_service", lambda *a, **k: svc)
    return DriveAPI("x@x.com"), svc


def test_search_files_builds_query(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().list().execute.return_value = {"files": []}
    api.search_files(name="report", mime_type="application/pdf", parent_id="P1", full_text="budget")
    _, kwargs = svc.files().list.call_args
    q = kwargs["q"]
    assert "trashed = false" in q
    assert "name contains 'report'" in q
    assert "mimeType = 'application/pdf'" in q
    assert "'P1' in parents" in q
    assert "fullText contains 'budget'" in q
    assert kwargs["pageSize"] == 25


def test_list_files_in_folder(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().list().execute.return_value = {"files": []}
    api.list_files(folder_id="F1", page_size=10)
    _, kwargs = svc.files().list.call_args
    assert "'F1' in parents" in kwargs["q"]
    assert kwargs["orderBy"] == "modifiedTime desc"
    assert kwargs["pageSize"] == 10


def test_get_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().get().execute.return_value = {"id": "F1", "name": "doc.txt"}
    out = api.get_file("F1")
    assert out["name"] == "doc.txt"
    svc.files().get.assert_called_with(fileId="F1", fields=svc.files().get.call_args.kwargs.get("fields", object()))


def test_download_file_writes_binary(monkeypatch, tmp_path):
    api, svc = _api_with_mock(monkeypatch)
    files = MagicMock()
    svc.files.return_value = files
    files.get().execute.return_value = {
        "id": "B1", "name": "data.bin", "mimeType": "application/octet-stream",
    }
    files.get_media.return_value = MagicMock()

    def fake_download(service, request):
        return b"hello bytes"

    monkeypatch.setattr("google_workspace_mcp.drive.drive_api._download_to_bytes", fake_download)
    out_path = str(tmp_path / "data.bin")
    out = api.download_file("B1", output_path=out_path)
    assert out["path"] == out_path
    assert out["bytes"] == 11
    assert open(out_path, "rb").read() == b"hello bytes"


def test_download_file_rejects_google_doc(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().get().execute.return_value = {
        "id": "D1", "name": "Doc", "mimeType": "application/vnd.google-apps.document",
    }
    with pytest.raises(ValueError, match="export_file"):
        api.download_file("D1")


def test_export_file_resolves_format(monkeypatch, tmp_path):
    api, svc = _api_with_mock(monkeypatch)
    files = MagicMock()
    svc.files.return_value = files
    files.get().execute.return_value = {
        "id": "D1", "name": "Notes", "mimeType": "application/vnd.google-apps.document",
    }
    files.export_media.return_value = MagicMock()
    monkeypatch.setattr(
        "google_workspace_mcp.drive.drive_api._download_to_bytes",
        lambda *a, **k: b"# md",
    )
    out_path = str(tmp_path / "notes.md")
    out = api.export_file("D1", "markdown", output_path=out_path)
    assert out["exportMimeType"] == "text/markdown"
    assert out["bytes"] == 4
    files.export_media.assert_called_with(fileId="D1", mimeType="text/markdown")


def test_export_unknown_format_raises():
    with pytest.raises(ValueError, match="unknown export format"):
        _resolve_export_mime("application/vnd.google-apps.document", "xlsx")


def test_read_file_text_binary(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    files = MagicMock()
    svc.files.return_value = files
    files.get().execute.return_value = {
        "id": "T1", "name": "hi.txt", "mimeType": "text/plain",
    }
    files.get_media.return_value = MagicMock()
    monkeypatch.setattr(
        "google_workspace_mcp.drive.drive_api._download_to_bytes",
        lambda *a, **k: b"hello",
    )
    out = api.read_file_text("T1")
    assert out["text"] == "hello"
    assert out["bytes"] == 5


def test_read_file_text_size_cap(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    files = MagicMock()
    svc.files.return_value = files
    files.get().execute.return_value = {
        "id": "T1", "name": "big.txt", "mimeType": "text/plain",
    }
    files.get_media.return_value = MagicMock()
    monkeypatch.setattr(
        "google_workspace_mcp.drive.drive_api._download_to_bytes",
        lambda *a, **k: b"x" * (TEXT_READ_MAX_BYTES + 1),
    )
    with pytest.raises(ValueError, match="exceeding read_file_text cap"):
        api.read_file_text("T1")


def test_read_file_text_rejects_slides(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().get().execute.return_value = {
        "id": "S1", "name": "Deck", "mimeType": "application/vnd.google-apps.presentation",
    }
    with pytest.raises(ValueError, match="export_file"):
        api.read_file_text("S1")


def test_update_file_content_rejects_native(monkeypatch, tmp_path):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().get().execute.return_value = {
        "id": "D1", "name": "Doc", "mimeType": "application/vnd.google-apps.document",
    }
    p = tmp_path / "x.txt"
    p.write_text("x")
    with pytest.raises(ValueError, match="Google-native"):
        api.update_file_content("D1", str(p))


def test_upload_file(monkeypatch, tmp_path):
    api, svc = _api_with_mock(monkeypatch)
    f = tmp_path / "up.txt"
    f.write_text("content")
    svc.files().create().execute.return_value = {"id": "N1", "name": "up.txt"}
    out = api.upload_file(str(f), parent_id="P1")
    assert out["id"] == "N1"
    _, kwargs = svc.files().create.call_args
    assert kwargs["body"]["parents"] == ["P1"]


def test_create_folder(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().create().execute.return_value = {"id": "F1", "name": "Archive"}
    out = api.create_folder("Archive", parent_id="ROOT")
    assert out["name"] == "Archive"
    _, kwargs = svc.files().create.call_args
    assert kwargs["body"]["mimeType"] == "application/vnd.google-apps.folder"
    assert kwargs["body"]["parents"] == ["ROOT"]


def test_move_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().get().execute.return_value = {"id": "F1", "parents": ["OLD"]}
    svc.files().update().execute.return_value = {"id": "F1", "parents": ["NEW"]}
    out = api.move_file("F1", "NEW")
    assert out["parents"] == ["NEW"]
    _, kwargs = svc.files().update.call_args
    assert kwargs["addParents"] == "NEW"
    assert kwargs["removeParents"] == "OLD"


def test_rename_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().update().execute.return_value = {"id": "F1", "name": "Renamed"}
    out = api.rename_file("F1", "Renamed")
    assert out["name"] == "Renamed"
    _, kwargs = svc.files().update.call_args
    assert kwargs["body"]["name"] == "Renamed"


def test_copy_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().copy().execute.return_value = {"id": "C1", "name": "Copy"}
    out = api.copy_file("F1", name="Copy", parent_id="P2")
    assert out["id"] == "C1"
    _, kwargs = svc.files().copy.call_args
    assert kwargs["body"]["name"] == "Copy"
    assert kwargs["body"]["parents"] == ["P2"]


def test_share_file_email(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().create().execute.return_value = {"id": "perm1", "role": "reader"}
    out = api.share_file("F1", email="friend@x.com", role="reader")
    assert out["role"] == "reader"
    _, kwargs = svc.permissions().create.call_args
    assert kwargs["body"]["emailAddress"] == "friend@x.com"


def test_share_file_anyone(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().create().execute.return_value = {"id": "perm2"}
    api.share_file("F1", anyone=True, role="reader")
    _, kwargs = svc.permissions().create.call_args
    assert kwargs["body"]["type"] == "anyone"


def test_list_permissions(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().list().execute.return_value = {"permissions": []}
    api.list_permissions("F1")
    svc.permissions().list.assert_called_with(
        fileId="F1",
        fields="permissions(id, type, role, emailAddress, displayName)",
    )


def test_trash_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().update().execute.return_value = {"id": "F1", "trashed": True}
    out = api.trash_file("F1")
    assert out["trashed"] is True
    _, kwargs = svc.files().update.call_args
    assert kwargs["body"]["trashed"] is True


def test_delete_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().delete().execute.return_value = None
    out = api.delete_file("F1")
    assert out["deleted"] is True
    svc.files().delete.assert_called_with(fileId="F1")


def test_batch_move_files(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().get().execute.return_value = {"id": "F1", "parents": ["OLD"], "name": "f"}
    svc.files().update().execute.return_value = {"id": "F1", "parents": ["NEW"], "name": "f"}
    out = api.batch_move_files([
        {"file_id": "F1", "new_parent_id": "NEW"},
        {"file_id": "F2", "new_parent_id": "NEW"},
    ])
    assert out["total"] == 2
    assert out["succeeded"] == 2
    assert out["failed"] == 0
    assert all(r["ok"] for r in out["results"])


def test_batch_move_files_isolates_per_item_errors(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().get().execute.return_value = {"id": "F1", "parents": ["OLD"], "name": "f"}
    svc.files().update().execute.return_value = {"id": "F1", "parents": ["NEW"], "name": "f"}
    out = api.batch_move_files([
        {"file_id": "F1", "new_parent_id": "NEW"},
        {"file_id": "", "new_parent_id": "NEW"},  # invalid -> isolated failure
    ])
    assert out["succeeded"] == 1
    assert out["failed"] == 1
    bad = [r for r in out["results"] if not r["ok"]][0]
    assert "file_id" in bad["error"]


def test_batch_move_files_requires_list(monkeypatch):
    api, _ = _api_with_mock(monkeypatch)
    with pytest.raises(ValueError, match="non-empty list"):
        api.batch_move_files([])


def test_batch_create_folders(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().create().execute.return_value = {"id": "NEW", "name": "X", "parents": ["P"]}
    out = api.batch_create_folders([{"name": "A"}, {"name": "B", "parent_id": "P"}])
    assert out["total"] == 2 and out["succeeded"] == 2
    assert out["results"][0]["id"] == "NEW"


def test_batch_trash_files(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().update().execute.return_value = {"id": "F1", "trashed": True, "name": "f"}
    out = api.batch_trash_files(["F1", "F2", "F3"])
    assert out["total"] == 3 and out["succeeded"] == 3


def test_batch_delete_files(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().delete().execute.return_value = None
    out = api.batch_delete_files(["F1", "F2"])
    assert out["succeeded"] == 2
    assert all(r["deleted"] for r in out["results"])


def test_default_output_path_uses_tempdir(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    files = MagicMock()
    svc.files.return_value = files
    files.get().execute.return_value = {
        "id": "B1", "name": "report.pdf", "mimeType": "application/pdf",
    }
    files.get_media.return_value = MagicMock()
    monkeypatch.setattr(
        "google_workspace_mcp.drive.drive_api._download_to_bytes",
        lambda *a, **k: b"pdf",
    )
    out = api.download_file("B1")
    assert out["path"].startswith(tempfile.gettempdir())
    assert os.path.isfile(out["path"])


def test_export_formats_cover_spec_types():
    assert "application/vnd.google-apps.document" in EXPORT_FORMATS
    assert "markdown" in EXPORT_FORMATS["application/vnd.google-apps.document"]
    assert "xlsx" in EXPORT_FORMATS["application/vnd.google-apps.spreadsheet"]
    assert "pdf" in EXPORT_FORMATS["application/vnd.google-apps.presentation"]


# --- server tools (mocked _api) ---

@pytest.mark.anyio
async def test_search_files_envelope(monkeypatch):
    fake = SimpleNamespace(search_files=lambda **kw: {"files": [{"id": "F1"}]})
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("search_files", {"name": "test"}))
    assert env["ok"] is True and env["account"] == "d@x.com"
    assert env["data"]["files"][0]["id"] == "F1"


@pytest.mark.anyio
async def test_tools_registered_and_account_param():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    drive_tools = [
        "search_files", "list_files", "get_file", "download_file", "export_file",
        "read_file_text", "list_permissions", "upload_file", "update_file_content",
        "create_folder", "move_file", "rename_file", "copy_file", "share_file",
        "trash_file", "delete_file",
        "batch_move_files", "batch_create_folders", "batch_trash_files", "batch_delete_files",
    ]
    for name in drive_tools:
        assert name in tools, f"missing tool {name}"
        assert "account" in (tools[name].inputSchema or {}).get("properties", {})
    assert {"list_accounts", "whoami", "auth_status"}.issubset(tools)


@pytest.mark.anyio
async def test_batch_move_files_envelope(monkeypatch):
    fake = SimpleNamespace(
        batch_move_files=lambda items: {"total": len(items), "succeeded": len(items), "failed": 0, "results": []}
    )
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool(
        "batch_move_files", {"file_ids": ["A", "B"], "new_parent_id": "DEST"}
    ))
    assert env["ok"] is True
    assert env["data"]["total"] == 2


@pytest.mark.anyio
async def test_batch_delete_files_marked_destructive():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    desc = (tools["batch_delete_files"].description or "").lower()
    assert "destructive" in desc


@pytest.mark.anyio
async def test_delete_file_marked_destructive():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    desc = (tools["delete_file"].description or "").lower()
    assert "destructive" in desc
