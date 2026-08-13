"""Tests for the Google Drive MCP server."""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from mcp.types import TextContent

from google_workspace_mcp.drive import server
from google_workspace_mcp.drive.drive_api import (
    COMMENT_FIELDS,
    COMMENT_LIST_FIELDS,
    DOCUMENT_MIME,
    EXPORT_FORMATS,
    REPLY_FIELDS,
    TEXT_READ_MAX_BYTES,
    DriveAPI,
    _resolve_export_mime,
    _resolve_upload_mimes,
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
    assert "pageToken" not in kwargs
    assert kwargs["supportsAllDrives"] is True
    assert kwargs["includeItemsFromAllDrives"] is True
    assert "driveId" not in kwargs
    assert "corpora" not in kwargs


def test_search_files_drive_id_sets_corpora(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().list().execute.return_value = {"files": []}
    api.search_files(name="report", drive_id="SD1")
    _, kwargs = svc.files().list.call_args
    assert kwargs["driveId"] == "SD1"
    assert kwargs["corpora"] == "drive"
    assert kwargs["supportsAllDrives"] is True
    assert kwargs["includeItemsFromAllDrives"] is True


def test_search_files_passes_page_token(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().list().execute.return_value = {"files": [], "nextPageToken": "drv2"}
    out = api.search_files(page_token="drv1")
    _, kwargs = svc.files().list.call_args
    assert kwargs["pageToken"] == "drv1"
    assert out["nextPageToken"] == "drv2"


def test_list_files_drive_id_sets_corpora(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().list().execute.return_value = {"files": []}
    api.list_files(drive_id="SD1")
    _, kwargs = svc.files().list.call_args
    assert kwargs["driveId"] == "SD1"
    assert kwargs["corpora"] == "drive"
    assert kwargs["supportsAllDrives"] is True
    assert kwargs["includeItemsFromAllDrives"] is True


def test_list_files_in_folder(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().list().execute.return_value = {"files": []}
    api.list_files(folder_id="F1", page_size=10)
    _, kwargs = svc.files().list.call_args
    assert "'F1' in parents" in kwargs["q"]
    assert kwargs["orderBy"] == "modifiedTime desc"
    assert kwargs["pageSize"] == 10
    assert kwargs["supportsAllDrives"] is True
    assert kwargs["includeItemsFromAllDrives"] is True
    assert "corpora" not in kwargs


def test_list_files_passes_page_token(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().list().execute.return_value = {"files": [], "nextPageToken": "nxt"}
    out = api.list_files(page_token="cur")
    _, kwargs = svc.files().list.call_args
    assert kwargs["pageToken"] == "cur"
    assert out["nextPageToken"] == "nxt"


def test_list_drives(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.drives().list().execute.return_value = {
        "drives": [{"id": "SD1", "name": "Team"}],
        "nextPageToken": "d2",
    }
    out = api.list_drives(page_size=10, page_token="d1")
    _, kwargs = svc.drives().list.call_args
    assert kwargs["pageSize"] == 10
    assert kwargs["pageToken"] == "d1"
    assert kwargs["fields"] == "nextPageToken, drives(id, name)"
    assert out["nextPageToken"] == "d2"


def test_get_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().get().execute.return_value = {"id": "F1", "name": "doc.txt"}
    out = api.get_file("F1")
    assert out["name"] == "doc.txt"
    _, kwargs = svc.files().get.call_args
    assert kwargs["fileId"] == "F1"
    assert kwargs["supportsAllDrives"] is True


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
    assert "mimeType" not in kwargs["body"]


def test_upload_file_converts_to_google_doc(monkeypatch, tmp_path):
    api, svc = _api_with_mock(monkeypatch)
    f = tmp_path / "plan.md"
    f.write_text("# Title\n\nBody")
    svc.files().create().execute.return_value = {
        "id": "D1",
        "name": "plan.md",
        "mimeType": "application/vnd.google-apps.document",
    }
    out = api.upload_file(
        str(f),
        mime_type="application/vnd.google-apps.document",
        name="Acquisition Meetings Plan",
        parent_id="P1",
    )
    assert out["mimeType"] == "application/vnd.google-apps.document"
    _, kwargs = svc.files().create.call_args
    assert kwargs["body"]["mimeType"] == "application/vnd.google-apps.document"
    assert kwargs["body"]["name"] == "Acquisition Meetings Plan"
    assert kwargs["body"]["parents"] == ["P1"]
    assert kwargs["media_body"].mimetype() == "text/markdown"


def test_resolve_upload_mimes_markdown():
    target, media = _resolve_upload_mimes("plan.md", DOCUMENT_MIME)
    assert (target, media) == (DOCUMENT_MIME, "text/markdown")


def test_upload_file_rejects_folder_target(monkeypatch, tmp_path):
    api, _svc = _api_with_mock(monkeypatch)
    f = tmp_path / "x.txt"
    f.write_text("x")
    with pytest.raises(ValueError, match="create_folder"):
        api.upload_file(str(f), mime_type="application/vnd.google-apps.folder")


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
    assert kwargs["supportsAllDrives"] is True


def test_share_file_anyone(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().create().execute.return_value = {"id": "perm2"}
    api.share_file("F1", anyone=True, role="reader")
    _, kwargs = svc.permissions().create.call_args
    assert kwargs["body"]["type"] == "anyone"
    assert "sendNotificationEmail" not in kwargs


def test_list_permissions(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().list().execute.return_value = {"permissions": []}
    api.list_permissions("F1")
    svc.permissions().list.assert_called_with(
        fileId="F1",
        fields="nextPageToken, permissions(id, type, role, emailAddress, displayName)",
        supportsAllDrives=True,
    )


def test_list_permissions_pages_all(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().list().execute.side_effect = [
        {"permissions": [{"id": "p1"}], "nextPageToken": "n2"},
        {"permissions": [{"id": "p2"}]},
    ]
    out = api.list_permissions("F1")
    assert [p["id"] for p in out["permissions"]] == ["p1", "p2"]
    list_calls = [
        kwargs for args, kwargs in svc.permissions().list.call_args_list if kwargs
    ]
    assert len(list_calls) == 2
    assert list_calls[1]["pageToken"] == "n2"


def test_unshare_file_by_permission_id(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().delete().execute.return_value = None
    out = api.unshare_file("F1", permission_id="perm1")
    assert out == {"fileId": "F1", "permissionId": "perm1", "removed": True}
    _, kwargs = svc.permissions().delete.call_args
    assert kwargs["fileId"] == "F1"
    assert kwargs["permissionId"] == "perm1"
    assert kwargs["supportsAllDrives"] is True
    svc.permissions().list.assert_not_called()


def test_unshare_file_by_email_case_insensitive(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().list().execute.return_value = {
        "permissions": [
            {"id": "p1", "type": "user", "emailAddress": "Friend@X.com"},
        ],
    }
    svc.permissions().delete().execute.return_value = None
    out = api.unshare_file("F1", email="friend@x.com")
    assert out["permissionId"] == "p1"
    _, kwargs = svc.permissions().delete.call_args
    assert kwargs["permissionId"] == "p1"
    assert kwargs["supportsAllDrives"] is True


def test_unshare_file_anyone(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().list().execute.return_value = {
        "permissions": [
            {"id": "anyone1", "type": "anyone", "role": "reader"},
        ],
    }
    svc.permissions().delete().execute.return_value = None
    out = api.unshare_file("F1", anyone=True)
    assert out["permissionId"] == "anyone1"


def test_unshare_file_requires_identifier(monkeypatch):
    api, _ = _api_with_mock(monkeypatch)
    with pytest.raises(ValueError, match="permission_id, email, or anyone"):
        api.unshare_file("F1")


def test_unshare_file_no_matching_permission(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().list().execute.return_value = {"permissions": []}
    with pytest.raises(ValueError, match="no matching permission"):
        api.unshare_file("F1", email="missing@x.com")


def test_unshare_file_pages_until_match(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.permissions().list().execute.side_effect = [
        {
            "permissions": [{"id": "p1", "type": "user", "emailAddress": "other@x.com"}],
            "nextPageToken": "p2",
        },
        {
            "permissions": [{"id": "p2", "type": "user", "emailAddress": "friend@x.com"}],
        },
    ]
    svc.permissions().delete().execute.return_value = None
    out = api.unshare_file("F1", email="friend@x.com")
    assert out["permissionId"] == "p2"
    list_calls = [
        kwargs for args, kwargs in svc.permissions().list.call_args_list if kwargs
    ]
    assert len(list_calls) == 2
    assert "pageToken" not in list_calls[0]
    assert list_calls[1]["pageToken"] == "p2"
    assert "nextPageToken" in list_calls[0]["fields"]


def test_trash_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().update().execute.return_value = {"id": "F1", "trashed": True}
    out = api.trash_file("F1")
    assert out["trashed"] is True
    _, kwargs = svc.files().update.call_args
    assert kwargs["body"]["trashed"] is True
    assert kwargs["supportsAllDrives"] is True


def test_untrash_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().update().execute.return_value = {"id": "F1", "trashed": False}
    out = api.untrash_file("F1")
    assert out["trashed"] is False
    _, kwargs = svc.files().update.call_args
    assert kwargs["body"]["trashed"] is False
    assert kwargs["supportsAllDrives"] is True


def test_delete_file(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().delete().execute.return_value = None
    out = api.delete_file("F1")
    assert out["deleted"] is True
    svc.files().delete.assert_called_with(fileId="F1", supportsAllDrives=True)


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


def test_list_comments_normalizes_and_requires_fields(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.comments().list().execute.return_value = {
        "comments": [{
            "id": "c1",
            "content": "look",
            "author": {"displayName": "Nitai"},
            "createdTime": "2026-01-01T00:00:00Z",
            "modifiedTime": "2026-01-01T00:00:00Z",
            "resolved": False,
            "anchor": json.dumps({"docsRange": {"startIndex": 1, "endIndex": 4}}),
            "quotedFileContent": {"value": "look"},
            "replies": [{
                "id": "r1",
                "content": "ok",
                "author": {"displayName": "Ada"},
                "action": "resolve",
            }],
        }],
        "nextPageToken": "tok2",
    }
    out = api.list_comments("F1", page_size=10)
    svc.comments().list.assert_called_with(
        fileId="F1", includeDeleted=False, pageSize=10, fields=COMMENT_LIST_FIELDS,
    )
    comment = out["comments"][0]
    assert comment["author"] == "Nitai"
    assert comment["place"] == {"docsRange": {"startIndex": 1, "endIndex": 4}}
    assert comment["quotedText"] == "look"
    assert comment["replies"][0]["author"] == "Ada"
    assert comment["replies"][0]["action"] == "resolve"
    assert comment["replies"][0]["deleted"] is False
    assert out["nextPageToken"] == "tok2"


def test_list_comments_passes_page_token(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.comments().list().execute.return_value = {"comments": [], "nextPageToken": "c2"}
    out = api.list_comments("F1", page_token="c1")
    svc.comments().list.assert_called_with(
        fileId="F1", includeDeleted=False, pageSize=20, fields=COMMENT_LIST_FIELDS,
        pageToken="c1",
    )
    assert out["nextPageToken"] == "c2"


def test_create_comment_json_anchor_and_fields(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.comments().create().execute.return_value = {"id": "c1", "content": "hi"}
    place = {"sheetsCell": "Sheet1!B2"}
    out = api.create_comment("F1", "hi", place)
    svc.comments().create.assert_called_with(
        fileId="F1",
        body={"content": "hi", "anchor": json.dumps(place)},
        fields=COMMENT_FIELDS,
    )
    assert out["id"] == "c1"


def test_create_comment_sends_quoted_file_content(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.comments().create().execute.return_value = {"id": "c1", "content": "hi"}
    api.create_comment("F1", "hi", quoted_text="brown")
    svc.comments().create.assert_called_with(
        fileId="F1",
        body={
            "content": "hi",
            "quotedFileContent": {"mimeType": "text/plain", "value": "brown"},
        },
        fields=COMMENT_FIELDS,
    )


def test_create_comment_omits_quoted_file_content(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.comments().create().execute.return_value = {"id": "c1", "content": "hi"}
    api.create_comment("F1", "hi")
    _, kwargs = svc.comments().create.call_args
    assert "quotedFileContent" not in kwargs["body"]


def test_create_comment_requires_content(monkeypatch):
    api, _ = _api_with_mock(monkeypatch)
    with pytest.raises(ValueError, match="content is required"):
        api.create_comment("F1", "")
    with pytest.raises(ValueError, match="content is required"):
        api.create_comment("F1", None)


def test_list_comments_region_anchor_place_is_none(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    raw_anchor = '{"region":{"kind":"drive#commentRegion","line":10,"rev":"head"}}'
    svc.comments().list().execute.return_value = {
        "comments": [{"id": "c1", "content": "look", "anchor": raw_anchor}],
    }
    comment = api.list_comments("F1")["comments"][0]
    assert comment["place"] is None
    assert comment["anchor"] == raw_anchor


def test_reply_to_comment_resolve_action(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.replies().create().execute.return_value = {"id": "r1", "action": "resolve"}
    out = api.reply_to_comment("F1", "c1", action="resolve")
    svc.replies().create.assert_called_with(
        fileId="F1", commentId="c1", body={"action": "resolve"}, fields=REPLY_FIELDS,
    )
    assert out["action"] == "resolve"


def test_reply_to_comment_requires_content_or_action(monkeypatch):
    api, _ = _api_with_mock(monkeypatch)
    with pytest.raises(ValueError, match="content or action"):
        api.reply_to_comment("F1", "c1")


def test_reply_to_comment_rejects_unknown_action(monkeypatch):
    api, _ = _api_with_mock(monkeypatch)
    with pytest.raises(ValueError, match="resolve"):
        api.reply_to_comment("F1", "c1", action="close")


def test_delete_comment(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.comments().delete().execute.return_value = None
    out = api.delete_comment("F1", "c1")
    svc.comments().delete.assert_called_with(fileId="F1", commentId="c1")
    assert out == {"id": "c1", "deleted": True}


# --- server tools (mocked _api) ---

@pytest.mark.anyio
async def test_search_files_envelope(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.search_files.return_value = {"files": [{"id": "F1"}]}
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("search_files", {"name": "test"}))
    assert env["ok"] is True and env["account"] == "d@x.com"
    assert env["data"]["files"][0]["id"] == "F1"
    assert "next_page_token" not in env


@pytest.mark.anyio
async def test_search_files_lifts_next_page_token(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.search_files.return_value = {"files": [{"id": "F1"}], "nextPageToken": "drv_tok_2"}
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("search_files", {"name": "test"}))
    assert env["next_page_token"] == "drv_tok_2"
    assert "nextPageToken" not in env["data"]


@pytest.mark.anyio
async def test_list_drives_envelope(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.list_drives.return_value = {
        "drives": [{"id": "SD1", "name": "Team"}], "nextPageToken": "d2",
    }
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("list_drives", {}))
    assert env["ok"] is True and env["account"] == "d@x.com"
    assert env["data"]["drives"][0]["id"] == "SD1"
    assert env["next_page_token"] == "d2"
    assert "nextPageToken" not in env["data"]


@pytest.mark.anyio
async def test_list_comments_envelope(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.list_comments.return_value = {
        "comments": [{"id": "c1"}], "nextPageToken": "n2",
    }
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("list_comments", {"file_id": "F1"}))
    assert env["ok"] is True
    assert env["data"]["comments"][0]["id"] == "c1"
    assert env["next_page_token"] == "n2"
    assert "nextPageToken" not in env["data"]
    fake.list_comments.assert_called_once_with("F1", False, 20, None)


@pytest.mark.anyio
async def test_untrash_file_envelope(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.untrash_file.return_value = {"id": "F1", "trashed": False}
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("untrash_file", {"file_id": "F1"}))
    assert env["ok"] is True
    assert env["data"]["trashed"] is False
    fake.untrash_file.assert_called_once_with("F1")


@pytest.mark.anyio
async def test_unshare_file_envelope(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.unshare_file.return_value = {
        "fileId": "F1", "permissionId": "p1", "removed": True,
    }
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool(
        "unshare_file", {"file_id": "F1", "email": "a@x.com"}
    ))
    assert env["ok"] is True
    assert env["data"]["removed"] is True
    fake.unshare_file.assert_called_once_with(
        "F1", email="a@x.com", permission_id=None, anyone=False,
    )


@pytest.mark.anyio
async def test_tools_registered_and_account_param():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    drive_tools = [
        "search_files", "list_files", "list_drives", "get_file", "download_file", "export_file",
        "read_file_text", "list_permissions", "list_comments",
        "get_changes_start_token", "list_changes",
        "upload_file", "update_file_content",
        "create_folder", "move_file", "rename_file", "copy_file", "share_file", "unshare_file",
        "trash_file", "untrash_file", "delete_file",
        "add_comment", "reply_to_comment", "delete_comment",
        "batch_move_files", "batch_create_folders", "batch_trash_files", "batch_delete_files",
    ]
    for name in drive_tools:
        assert name in tools, f"missing tool {name}"
        assert "account" in (tools[name].inputSchema or {}).get("properties", {})
    assert {"list_accounts", "whoami", "auth_status"}.issubset(tools)


@pytest.mark.anyio
async def test_batch_move_files_envelope(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.batch_move_files.return_value = {
        "total": 2, "succeeded": 2, "failed": 0, "results": [],
    }
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool(
        "batch_move_files", {"file_ids": ["A", "B"], "new_parent_id": "DEST"}
    ))
    assert env["ok"] is True
    assert env["data"]["total"] == 2


@pytest.mark.anyio
async def test_batch_move_files_envelope_all_failed(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.batch_move_files.return_value = {
        "total": 2,
        "succeeded": 0,
        "failed": 2,
        "results": [
            {"ok": False, "file_id": "A", "error": "not found"},
            {"ok": False, "file_id": "B", "error": "not found"},
        ],
    }
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool(
        "batch_move_files", {"file_ids": ["A", "B"], "new_parent_id": "DEST"}
    ))
    assert env["ok"] is False
    assert env["data"]["failed"] == 2
    assert env["data"]["results"]


@pytest.mark.anyio
async def test_batch_move_files_envelope_partial_success(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.batch_move_files.return_value = {
        "total": 2,
        "succeeded": 1,
        "failed": 1,
        "results": [
            {"ok": True, "file_id": "A"},
            {"ok": False, "file_id": "B", "error": "not found"},
        ],
    }
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool(
        "batch_move_files", {"file_ids": ["A", "B"], "new_parent_id": "DEST"}
    ))
    assert env["ok"] is True
    assert env["data"]["failed"] == 1


@pytest.mark.anyio
async def test_batch_delete_files_envelope_all_failed(monkeypatch):
    fake = MagicMock(spec=DriveAPI)
    fake.batch_delete_files.return_value = {
        "total": 2,
        "succeeded": 0,
        "failed": 2,
        "results": [
            {"ok": False, "file_id": "A", "error": "not found"},
            {"ok": False, "file_id": "B", "error": "not found"},
        ],
    }
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool(
        "batch_delete_files", {"file_ids": ["A", "B"]}
    ))
    assert env["ok"] is False
    assert env["data"]["failed"] == 2
    assert env["data"]["results"]


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
