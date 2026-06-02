"""Tests for the Google Docs MCP server."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mcp.types import TextContent

from google_workspace_mcp.docs import server
from google_workspace_mcp.docs.docs_api import DocsAPI


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


# --- DocsAPI unit (mocked googleapiclient service) ---

def _api_with_mock(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr("google_auth_core.get_service", lambda *a, **k: svc)
    return DocsAPI("x@x.com"), svc


def test_create_document(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().create().execute.return_value = {"documentId": "D1", "title": "Hi"}
    out = api.create_document("Hi")
    assert out["documentId"] == "D1"
    svc.documents().create.assert_called_with(body={"title": "Hi"})


def test_get_document_text_extracts_paragraphs(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().get().execute.return_value = {
        "title": "Doc",
        "body": {"content": [
            {"paragraph": {"elements": [{"textRun": {"content": "Hello "}}]}},
            {"paragraph": {"elements": [{"textRun": {"content": "world\n"}}]}},
        ]},
    }
    out = api.get_document_text("D1")
    assert out["text"] == "Hello world\n"
    assert out["title"] == "Doc"


def test_replace_all_text_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.replace_all_text("D1", "foo", "bar", match_case=True)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["replaceAllText"]
    assert req["containsText"] == {"text": "foo", "matchCase": True}
    assert req["replaceText"] == "bar"


# --- server tools (mocked _api) ---

@pytest.mark.anyio
async def test_read_document_envelope(monkeypatch):
    fake = SimpleNamespace(get_document_text=lambda doc_id: {"documentId": doc_id, "text": "hi"})
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("read_document", {"document_id": "D1"}))
    assert env["ok"] is True and env["account"] == "d@x.com"
    assert env["data"]["text"] == "hi"


@pytest.mark.anyio
async def test_tools_registered_and_account_param():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    for name in ["get_document", "read_document", "create_document", "append_text", "insert_text", "replace_all_text"]:
        assert name in tools, f"missing tool {name}"
        assert "account" in (tools[name].inputSchema or {}).get("properties", {})
    # common tools present
    assert {"list_accounts", "whoami", "auth_status"}.issubset(tools)
