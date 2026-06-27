"""Tests for the Gmail MCP server."""
from __future__ import annotations

import importlib
import json
import os

import pytest

from google_workspace_mcp.gmail import server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeAPI:
    """Minimal stand-in for GmailAPI that records calls and returns canned values."""

    def __init__(self):
        self.calls: dict = {}

    def _record(self, method, **kwargs):
        self.calls[method] = kwargs

    # READ methods
    def get_profile(self):
        self._record("get_profile")
        return {"emailAddress": "test@x.com", "messagesTotal": 42}

    def list_messages(self, max_results=10, label_ids=None, query=None):
        self._record("list_messages", max_results=max_results, label_ids=label_ids, query=query)
        return [{"id": "msg1"}, {"id": "msg2"}]

    def search_with_details(self, max_results=10, label_ids=None, query=None, format="metadata"):
        self._record("search_with_details", max_results=max_results, query=query, format=format)
        return [{"id": "msg1", "snippet": "Hello"}]

    def get_message(self, message_id, format="full"):
        self._record("get_message", message_id=message_id, format=format)
        return {"id": message_id, "snippet": "Hi"}

    def list_threads(self, max_results=10, query=None):
        self._record("list_threads", max_results=max_results, query=query)
        return [{"id": "thread1"}]

    def list_labels(self):
        self._record("list_labels")
        return [{"id": "INBOX", "name": "INBOX"}]

    def get_label(self, label_id):
        self._record("get_label", label_id=label_id)
        return {"id": label_id, "name": "MyLabel"}

    def list_drafts(self, max_results=10):
        self._record("list_drafts", max_results=max_results)
        return [{"id": "draft1"}]

    def get_draft(self, draft_id):
        self._record("get_draft", draft_id=draft_id)
        return {"id": draft_id}

    def list_filters(self):
        self._record("list_filters")
        return [{"id": "filter1"}]

    def get_filter(self, filter_id):
        self._record("get_filter", filter_id=filter_id)
        return {"id": filter_id}

    # WRITE methods
    def send_message(self, to, subject, body, attachments=None, cc=None, html=False):
        self._record("send_message", to=to, subject=subject, body=body, cc=cc, html=html)
        return {"id": "sent1", "threadId": "t1"}

    def reply_to_message(self, message_id, body, reply_all=False, additional_cc=None):
        self._record("reply_to_message", message_id=message_id, body=body, reply_all=reply_all)
        return {"id": "sent2"}

    def forward_message(self, message_id, to, body=None):
        self._record("forward_message", message_id=message_id, to=to, body=body)
        return {"id": "sent3"}

    def create_draft(self, to, subject, body, attachments=None, cc=None, html=False):
        self._record("create_draft", to=to, subject=subject, body=body, cc=cc, html=html)
        return {"id": "draft_new"}

    def update_draft(self, draft_id, to=None, subject=None, body=None, attachments=None, cc=None, html=False):
        self._record("update_draft", draft_id=draft_id, to=to, subject=subject, body=body, cc=cc, html=html)
        return {"id": draft_id}

    def modify_message(self, message_id, add_label_ids=None, remove_label_ids=None):
        self._record("modify_message", message_id=message_id, add_label_ids=add_label_ids, remove_label_ids=remove_label_ids)
        return {"id": message_id, "labelIds": []}

    def mark_as_read(self, message_id):
        self._record("mark_as_read", message_id=message_id)
        return {"id": message_id}

    def archive_message(self, message_id):
        self._record("archive_message", message_id=message_id)
        return {"id": message_id}

    def star_message(self, message_id):
        self._record("star_message", message_id=message_id)
        return {"id": message_id}

    def unstar_message(self, message_id):
        self._record("unstar_message", message_id=message_id)
        return {"id": message_id}

    def mark_as_spam(self, message_id):
        self._record("mark_as_spam", message_id=message_id)
        return {"id": message_id}

    def unmark_spam(self, message_id):
        self._record("unmark_spam", message_id=message_id)
        return {"id": message_id}

    def create_label(self, name, message_list_visibility="show", label_list_visibility="labelShow", color=None):
        self._record("create_label", name=name)
        return {"id": "label_new", "name": name}

    def update_label(self, label_id, name=None, message_list_visibility=None, label_list_visibility=None, color=None):
        self._record("update_label", label_id=label_id, name=name)
        return {"id": label_id}

    def create_filter(self, criteria, action):
        self._record("create_filter", criteria=criteria, action=action)
        return {"id": "filter_new"}

    def block_sender(self, email):
        self._record("block_sender", email=email)
        return {"id": "filter_block"}

    def batch_modify_messages(self, message_ids, add_label_ids=None, remove_label_ids=None):
        self._record("batch_modify_messages", message_ids=message_ids)
        return {"modified": len(message_ids), "errors": []}

    # DESTRUCTIVE methods
    def trash_message(self, message_id):
        self._record("trash_message", message_id=message_id)
        return None

    def untrash_message(self, message_id):
        self._record("untrash_message", message_id=message_id)
        return None

    def delete_message(self, message_id):
        self._record("delete_message", message_id=message_id)
        return None

    def delete_label(self, label_id):
        self._record("delete_label", label_id=label_id)
        return None

    def delete_filter(self, filter_id):
        self._record("delete_filter", filter_id=filter_id)
        return None

    def batch_trash_messages(self, message_ids):
        self._record("batch_trash_messages", message_ids=message_ids)
        return {"trashed": len(message_ids), "errors": []}

    def batch_untrash_messages(self, message_ids):
        self._record("batch_untrash_messages", message_ids=message_ids)
        return {"untrashed": len(message_ids), "errors": []}

    def batch_delete_messages(self, message_ids):
        self._record("batch_delete_messages", message_ids=message_ids)
        return {"deleted": len(message_ids), "errors": []}


def make_fake_api():
    """Return (fake_api_instance, patched _api callable)."""
    fake = FakeAPI()
    return fake, lambda account=None: (fake, "test@x.com")


def parse_result(result):
    """Extract the dict from call_tool's TextContent list."""
    assert isinstance(result, list) and len(result) > 0
    text = result[0].text
    return json.loads(text)


# ---------------------------------------------------------------------------
# Test 1: import + tool list
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_tool_names():
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}

    expected_read = {
        "get_profile", "list_messages", "search_messages", "get_message",
        "list_threads", "list_labels", "get_label",
        "list_drafts", "get_draft", "list_filters", "get_filter",
    }
    expected_write = {
        "send_message", "reply_to_message", "forward_message",
        "create_draft", "update_draft", "modify_labels", "mark_read",
        "archive_message", "star_message", "unstar_message",
        "mark_as_spam", "unmark_spam",
        "create_label", "update_label", "create_filter", "block_sender",
        "batch_modify_labels",
    }
    expected_destructive = {
        "trash_message", "untrash_message", "delete_message",
        "delete_label", "delete_filter",
        "batch_trash_messages", "batch_untrash_messages", "batch_delete_messages",
    }
    expected_common = {"list_accounts", "auth_status", "whoami"}

    for name in expected_read | expected_write | expected_destructive | expected_common:
        assert name in names, f"Tool '{name}' missing from server"


# ---------------------------------------------------------------------------
# Test 2: read tool returns correct envelope
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_messages_envelope(monkeypatch):
    fake, patched = make_fake_api()
    monkeypatch.setattr(server, "_api", patched)

    result = await server.mcp.call_tool("list_messages", {"query": "is:unread"})
    data = parse_result(result)

    assert data["ok"] is True
    assert data["account"] == "test@x.com"
    assert isinstance(data["data"], list)
    assert data["data"][0]["id"] == "msg1"

    # confirm underlying api was called with the query
    assert fake.calls["list_messages"]["query"] == "is:unread"


# ---------------------------------------------------------------------------
# Test 3: mutating tool calls underlying api with correct args
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_send_message_args(monkeypatch):
    fake, patched = make_fake_api()
    monkeypatch.setattr(server, "_api", patched)

    result = await server.mcp.call_tool(
        "send_message",
        {"to": "alice@example.com", "subject": "Hello", "body": "World", "cc": "bob@example.com"},
    )
    data = parse_result(result)

    assert data["ok"] is True
    assert data["data"]["id"] == "sent1"

    call = fake.calls["send_message"]
    assert call["to"] == "alice@example.com"
    assert call["subject"] == "Hello"
    assert call["body"] == "World"
    assert call["cc"] == "bob@example.com"


# ---------------------------------------------------------------------------
# Test 4: get_profile read tool
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_profile(monkeypatch):
    fake, patched = make_fake_api()
    monkeypatch.setattr(server, "_api", patched)

    result = await server.mcp.call_tool("get_profile", {})
    data = parse_result(result)

    assert data["ok"] is True
    assert data["data"]["emailAddress"] == "test@x.com"
    assert data["data"]["messagesTotal"] == 42


# ---------------------------------------------------------------------------
# Test 5: destructive tool is registered and works correctly
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_delete_message(monkeypatch):
    fake, patched = make_fake_api()
    monkeypatch.setattr(server, "_api", patched)

    result = await server.mcp.call_tool("delete_message", {"message_id": "abc"})
    data = parse_result(result)

    assert data["ok"] is True
    assert fake.calls["delete_message"]["message_id"] == "abc"


# ---------------------------------------------------------------------------
# Test 6: READONLY env hides mutating tools (subprocess approach)
# ---------------------------------------------------------------------------

def test_readonly_hides_mutating_tools():
    """Check that mutating tools are absent when GOOGLE_MCP_READONLY=1."""
    import subprocess
    code = """
import os
os.environ["GOOGLE_MCP_READONLY"] = "1"

# Reload runtime so READONLY is re-evaluated
import importlib
import google_workspace_mcp.core.runtime as rt
importlib.reload(rt)

# Re-import server so register() uses fresh READONLY value
import google_workspace_mcp.gmail.server as srv
importlib.reload(srv)

import asyncio
async def main():
    tools = await srv.mcp.list_tools()
    names = [t.name for t in tools]
    # send_message is mutating — must not appear
    assert "send_message" not in names, f"send_message should be hidden; got {names}"
    # list_messages is read-only — must still appear
    assert "list_messages" in names, f"list_messages should be present; got {names}"
    print("OK")

asyncio.run(main())
"""
    result = subprocess.run(
        ["/Users/nitai/REPOS/google-workspace-mcp/.venv/bin/python", "-c", code],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"subprocess failed:\n{result.stdout}\n{result.stderr}"
    assert "OK" in result.stdout
