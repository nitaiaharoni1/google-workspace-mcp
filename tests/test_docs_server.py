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


def test_set_page_layout_a4_with_margins(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.set_page_layout("D1", page_preset="A4", margin_top_pt=72, margin_bottom_pt=72, margin_left_pt=72, margin_right_pt=72)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["updateDocumentStyle"]
    assert req["documentStyle"]["pageSize"]["width"]["magnitude"] == 595.28
    assert req["documentStyle"]["marginTop"]["magnitude"] == 72
    assert "pageSize" in req["fields"]


def test_flip_page_orientation(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.flip_page_orientation("D1", flip=True)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["updateDocumentStyle"]
    assert req["documentStyle"]["flipPageOrientation"] is True
    assert "flipPageOrientation" in req["fields"]


def test_format_text_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.format_text(
        "D1", 1, 10, bold=True, italic=True, underline=True, strikethrough=True,
        font_size=14, font_family="Arial", link_url="https://example.com",
        foreground_color="#FF0000", background_color="#00FF00",
    )
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["updateTextStyle"]
    style = req["textStyle"]
    assert style["bold"] is True
    assert style["italic"] is True
    assert style["underline"] is True
    assert style["strikethrough"] is True
    assert style["fontSize"]["magnitude"] == 14
    assert style["weightedFontFamily"]["fontFamily"] == "Arial"
    assert style["link"]["url"] == "https://example.com"
    assert style["foregroundColor"]["color"]["rgbColor"]["red"] == 1.0
    assert style["backgroundColor"]["color"]["rgbColor"]["green"] == 1.0


def test_setup_header_creates_and_inserts(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    docs = MagicMock()
    batch = MagicMock()
    svc.documents.return_value = docs
    docs.batchUpdate.return_value = batch
    batch.execute.side_effect = [
        {"replies": [{"createHeader": {"headerId": "H1"}}]},
        {"ok": True},
    ]
    out = api.setup_header("D1", "Page 1")
    assert out["headerId"] == "H1"
    insert_call = docs.batchUpdate.call_args_list[1]
    req = insert_call.kwargs["body"]["requests"][0]["insertText"]
    assert req["location"]["segmentId"] == "H1"
    assert req["text"] == "Page 1"


def test_setup_footer_creates_and_inserts(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    docs = MagicMock()
    batch = MagicMock()
    svc.documents.return_value = docs
    docs.batchUpdate.return_value = batch
    batch.execute.side_effect = [
        {"replies": [{"createFooter": {"footerId": "F1"}}]},
        {"ok": True},
    ]
    out = api.setup_footer("D1", "Page 1")
    assert out["footerId"] == "F1"
    insert_call = docs.batchUpdate.call_args_list[1]
    req = insert_call.kwargs["body"]["requests"][0]["insertText"]
    assert req["location"]["segmentId"] == "F1"
    assert req["text"] == "Page 1"


def test_insert_inline_image_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"replies": [{"insertInlineImage": {"objectId": "IMG1"}}]}
    api.insert_inline_image("D1", "https://example.com/chart.png", index=5, width_pt=400, height_pt=250)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["insertInlineImage"]
    assert req["uri"] == "https://example.com/chart.png"
    assert req["location"]["index"] == 5
    assert req["objectSize"]["width"]["magnitude"] == 400


def test_insert_chart_image_uses_defaults(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.insert_chart_image("D1", "https://example.com/chart.png", index=3)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["insertInlineImage"]
    assert req["uri"] == "https://example.com/chart.png"
    assert req["objectSize"]["width"]["magnitude"] == 468
    assert req["objectSize"]["height"]["magnitude"] == 280


def test_update_paragraph_style_alignment(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.update_paragraph_style("D1", 1, 10, alignment="CENTER", space_below_pt=12)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["updateParagraphStyle"]
    assert req["paragraphStyle"]["alignment"] == "CENTER"
    assert req["paragraphStyle"]["spaceBelow"]["magnitude"] == 12


def test_insert_table_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.insert_table("D1", rows=3, columns=4, index=2)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["insertTable"]
    assert req["rows"] == 3 and req["columns"] == 4
    assert req["location"]["index"] == 2


def test_insert_page_break_with_segment(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.insert_page_break("D1", index=1, segment_id="H1")
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["insertPageBreak"]
    assert req["location"]["index"] == 1
    assert req["location"]["segmentId"] == "H1"


def test_insert_bullets_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.insert_bullets("D1", 1, 20, bullet_preset="NUMBERED_DECIMAL_ALPHA_ROMAN", segment_id="H1")
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["createParagraphBullets"]
    assert req["range"]["startIndex"] == 1
    assert req["range"]["endIndex"] == 20
    assert req["range"]["segmentId"] == "H1"
    assert req["bulletPreset"] == "NUMBERED_DECIMAL_ALPHA_ROMAN"


def test_remove_bullets_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.remove_bullets("D1", 1, 20)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["deleteParagraphBullets"]
    assert req["range"]["startIndex"] == 1
    assert req["range"]["endIndex"] == 20


def test_delete_header_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.delete_header("D1", "H1")
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["deleteHeader"]
    assert req["headerId"] == "H1"


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
    docs_tools = [
        "get_document", "read_document", "create_document", "append_text", "insert_text",
        "replace_all_text", "format_text", "set_paragraph_style", "update_paragraph_style",
        "set_page_layout", "flip_page_orientation", "setup_header", "setup_footer",
        "create_header", "create_footer", "delete_header", "delete_footer",
        "insert_inline_image", "insert_chart_image", "insert_table", "insert_page_break",
        "insert_bullets", "remove_bullets", "delete_range",
    ]
    for name in docs_tools:
        assert name in tools, f"missing tool {name}"
        assert "account" in (tools[name].inputSchema or {}).get("properties", {})
    # common tools present
    assert {"list_accounts", "whoami", "auth_status"}.issubset(tools)
