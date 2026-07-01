"""Unit and server tests for Gmail/Drive/Calendar change-feed tools."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from google_workspace_mcp.calendar import server as calendar_server
from google_workspace_mcp.calendar.changes_api import CalendarChangesAPI, trim_event
from google_workspace_mcp.drive import server as drive_server
from google_workspace_mcp.drive.drive_api import DriveAPI, normalize_drive_change
from google_workspace_mcp.gmail import server as gmail_server
from google_workspace_mcp.gmail.changes_api import GmailChangesAPI, normalize_history_records


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _http_error(status: int) -> HttpError:
    resp = httplib2.Response({"status": str(status), "reason": "Error"})
    return HttpError(resp, b'{"error": {"message": "fail"}}')


def _parse(result) -> dict:
    assert isinstance(result, list) and len(result) == 1
    return json.loads(result[0].text)


# --- Gmail normalization ---

def test_normalize_history_all_change_types():
    history = [
        {
            "id": "100",
            "messagesAdded": [
                {"message": {"id": "m1", "threadId": "t1", "labelIds": ["INBOX"]}}
            ],
            "messagesDeleted": [{"message": {"id": "m2", "threadId": "t2"}}],
            "labelsAdded": [
                {"message": {"id": "m3"}, "labelIds": ["STARRED"]}
            ],
            "labelsRemoved": [
                {"message": {"id": "m4"}, "labelIds": ["UNREAD"]}
            ],
        }
    ]
    out = normalize_history_records(history)
    assert len(out) == 4
    assert out[0] == {
        "type": "message_added",
        "message_id": "m1",
        "thread_id": "t1",
        "label_ids": ["INBOX"],
    }
    assert out[1]["type"] == "message_deleted"
    assert out[2]["type"] == "labels_added"
    assert out[3]["type"] == "labels_removed"


def test_normalize_history_empty():
    assert normalize_history_records([]) == []
    assert normalize_history_records(None) == []


# --- Drive normalization ---

def test_normalize_drive_change_modified_file():
    change = {
        "fileId": "F1",
        "removed": False,
        "time": "2026-01-01T00:00:00.000Z",
        "file": {
            "id": "F1",
            "name": "doc.txt",
            "mimeType": "text/plain",
            "modifiedTime": "2026-01-01T00:00:00.000Z",
            "trashed": False,
            "parents": ["P1"],
        },
    }
    out = normalize_drive_change(change)
    assert out["removed"] is False
    assert out["file"]["name"] == "doc.txt"


def test_normalize_drive_change_hard_removed():
    change = {"fileId": "F2", "removed": True, "time": "2026-01-02T00:00:00.000Z"}
    out = normalize_drive_change(change)
    assert out["removed"] is True
    assert out["file"] is None


def test_normalize_drive_change_trashed():
    change = {
        "fileId": "F3",
        "removed": False,
        "time": "2026-01-03T00:00:00.000Z",
        "file": {"id": "F3", "name": "old", "trashed": True},
    }
    out = normalize_drive_change(change)
    assert out["removed"] is True
    assert out["file"]["trashed"] is True


# --- Calendar trim ---

def test_trim_event_cancelled():
    event = {
        "id": "ev1",
        "status": "cancelled",
        "summary": "Gone",
        "start": {"dateTime": "2026-01-01T10:00:00Z"},
        "end": {"dateTime": "2026-01-01T11:00:00Z"},
        "updated": "2026-01-02T00:00:00Z",
        "organizer": {"email": "a@x.com"},
        "recurringEventId": "master1",
        "extra": "dropped",
    }
    out = trim_event(event)
    assert out["status"] == "cancelled"
    assert "extra" not in out
    assert out["recurringEventId"] == "master1"


# --- GmailChangesAPI (mocked service) ---

def _gmail_api_with_mock(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr("gmail_cli.api.build", lambda *a, **k: svc)
    monkeypatch.setattr("gmail_cli.api.check_auth", lambda account=None: object())
    api = GmailChangesAPI("x@x.com")
    return api, svc


def test_gmail_get_changes_start_token(monkeypatch):
    api, svc = _gmail_api_with_mock(monkeypatch)
    svc.users().getProfile().execute.return_value = {
        "historyId": "12345",
        "emailAddress": "x@x.com",
    }
    out = api.get_changes_start_token()
    assert out == {"start_history_token": "12345", "email": "x@x.com"}


def test_gmail_list_changes_normalizes(monkeypatch):
    api, svc = _gmail_api_with_mock(monkeypatch)
    svc.users().history().list().execute.return_value = {
        "history": [
            {"messagesAdded": [{"message": {"id": "m1", "threadId": "t1", "labelIds": []}}]}
        ],
        "historyId": "999",
    }
    out = api.list_changes("100")
    assert out["changes"][0]["type"] == "message_added"
    assert out["new_history_token"] == "999"
    _, kwargs = svc.users().history().list.call_args
    assert kwargs["startHistoryId"] == "100"


def test_gmail_list_changes_empty_history(monkeypatch):
    api, svc = _gmail_api_with_mock(monkeypatch)
    svc.users().history().list().execute.return_value = {"historyId": "200"}
    out = api.list_changes("100")
    assert out["changes"] == []


def test_gmail_list_changes_requires_token(monkeypatch):
    api, _ = _gmail_api_with_mock(monkeypatch)
    with pytest.raises(ValueError, match="start_history_token is required"):
        api.list_changes("")


def test_gmail_list_changes_expired_token(monkeypatch):
    api, svc = _gmail_api_with_mock(monkeypatch)
    svc.users().history().list().execute.side_effect = _http_error(404)
    with pytest.raises(ValueError, match="get_changes_start_token"):
        api.list_changes("stale")


# --- DriveAPI change methods ---

def _drive_api_with_mock(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr("google_auth_core.get_service", lambda *a, **k: svc)
    return DriveAPI("x@x.com"), svc


def test_drive_get_changes_start_token(monkeypatch):
    api, svc = _drive_api_with_mock(monkeypatch)
    svc.changes().getStartPageToken().execute.return_value = {"startPageToken": "tok0"}
    assert api.get_changes_start_token() == {"start_page_token": "tok0"}


def test_drive_list_changes(monkeypatch):
    api, svc = _drive_api_with_mock(monkeypatch)
    svc.changes().list().execute.return_value = {
        "changes": [{"fileId": "F1", "removed": False, "file": {"id": "F1", "name": "a"}}],
        "newStartPageToken": "tok1",
    }
    out = api.list_changes("tok0")
    assert out["new_start_token"] == "tok1"
    assert out["changes"][0]["file_id"] == "F1"


def test_drive_list_changes_requires_token(monkeypatch):
    api, _ = _drive_api_with_mock(monkeypatch)
    with pytest.raises(ValueError, match="page_token is required"):
        api.list_changes("")


# --- CalendarChangesAPI ---

def _calendar_api_with_mock(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr("google_calendar_cli.api.build", lambda *a, **k: svc)
    monkeypatch.setattr("google_calendar_cli.api.check_auth", lambda account=None: object())
    api = CalendarChangesAPI("x@x.com")
    return api, svc


def test_calendar_list_event_changes_baseline(monkeypatch):
    api, svc = _calendar_api_with_mock(monkeypatch)
    svc.events().list().execute.return_value = {
        "items": [{"id": "ev1", "status": "confirmed", "summary": "Meet"}],
        "nextSyncToken": "sync1",
    }
    out = api.list_event_changes(calendar_id="primary")
    assert out["new_sync_token"] == "sync1"
    assert out["events"][0]["summary"] == "Meet"
    _, kwargs = svc.events().list.call_args
    assert kwargs["showDeleted"] is True
    assert "orderBy" not in kwargs
    assert "syncToken" not in kwargs


def test_calendar_list_event_changes_expired_sync_token(monkeypatch):
    api, svc = _calendar_api_with_mock(monkeypatch)
    svc.events().list().execute.side_effect = _http_error(410)
    with pytest.raises(ValueError, match="re-baseline"):
        api.list_event_changes(sync_token="old")


# --- Server-level tool wiring ---

@pytest.mark.anyio
async def test_gmail_change_feed_tools(monkeypatch):
    fake = SimpleNamespace(
        get_changes_start_token=lambda: {"start_history_token": "1", "email": "x@x.com"},
        list_changes=lambda start_history_token, **kw: {"changes": [], "new_history_token": "2"},
    )
    monkeypatch.setattr(gmail_server, "_api", lambda account=None: (fake, "x@x.com"))

    start = _parse(await gmail_server.mcp.call_tool("get_changes_start_token", {}))
    assert start["data"]["start_history_token"] == "1"

    changes = _parse(
        await gmail_server.mcp.call_tool(
            "list_changes", {"start_history_token": "1", "label_id": "INBOX"}
        )
    )
    assert changes["ok"] is True
    assert changes["data"]["new_history_token"] == "2"


@pytest.mark.anyio
async def test_drive_change_feed_tools(monkeypatch):
    fake = SimpleNamespace(
        get_changes_start_token=lambda: {"start_page_token": "p0"},
        list_changes=lambda page_token, **kw: {
            "changes": [],
            "new_start_token": "p1",
        },
    )
    monkeypatch.setattr(drive_server, "_api", lambda account=None: (fake, "d@x.com"))

    start = _parse(await drive_server.mcp.call_tool("get_changes_start_token", {}))
    assert start["data"]["start_page_token"] == "p0"

    changes = _parse(
        await drive_server.mcp.call_tool("list_changes", {"page_token": "p0"})
    )
    assert changes["data"]["new_start_token"] == "p1"


@pytest.mark.anyio
async def test_calendar_list_event_changes_tool(monkeypatch):
    fake = SimpleNamespace(
        list_event_changes=lambda **kw: {
            "events": [{"id": "ev1", "status": "cancelled"}],
            "new_sync_token": "sync2",
        }
    )
    monkeypatch.setattr(calendar_server, "_api", lambda account=None: (fake, "c@x.com"))

    out = _parse(
        await calendar_server.mcp.call_tool(
            "list_event_changes", {"sync_token": "sync1", "calendar_id": "primary"}
        )
    )
    assert out["data"]["events"][0]["status"] == "cancelled"
    assert out["data"]["new_sync_token"] == "sync2"


CHANGE_FEED_TOOLS = [
    ("gmail", "get_changes_start_token"),
    ("gmail", "list_changes"),
    ("drive", "get_changes_start_token"),
    ("drive", "list_changes"),
    ("calendar", "list_event_changes"),
]


@pytest.mark.parametrize("pkg,tool", CHANGE_FEED_TOOLS)
def test_change_feed_tools_available_in_readonly_mode(pkg, tool):
    code = (
        f"import asyncio\n"
        f"from google_workspace_mcp.{pkg} import server\n"
        f"names = {{t.name for t in asyncio.run(server.mcp.list_tools())}}\n"
        f"print({tool!r} in names)\n"
    )
    env = {**os.environ, "GOOGLE_MCP_READONLY": "1"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "True"
