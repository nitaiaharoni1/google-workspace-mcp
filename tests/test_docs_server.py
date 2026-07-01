"""Tests for the Google Docs MCP server."""
from __future__ import annotations

import json
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


def test_get_content_map_body_and_table(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().get().execute.return_value = {
        "title": "Map",
        "body": {"content": [
            {"startIndex": 1, "endIndex": 8, "paragraph": {
                "elements": [{"textRun": {"content": "Hello\n"}}],
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            }},
            {"startIndex": 8, "endIndex": 40, "table": {
                "rows": 1,
                "columns": 2,
                "tableRows": [{"tableCells": [
                    {"content": [{"startIndex": 10, "endIndex": 12, "paragraph": {
                        "elements": [{"textRun": {"content": "\n"}}],
                    }}]},
                    {"content": [{"startIndex": 15, "endIndex": 17, "paragraph": {
                        "elements": [{"textRun": {"content": "\n"}}],
                    }}]},
                ]}],
            }},
        ]},
        "footers": {"F1": {"content": [
            {"startIndex": 1, "endIndex": 3, "paragraph": {"elements": [{"textRun": {"content": "\n"}}]}},
        ]}},
    }
    out = api.get_content_map("D1")
    assert out["title"] == "Map"
    assert out["elements"][0]["type"] == "paragraph"
    assert out["elements"][0]["textPreview"] == "Hello"
    table_el = out["elements"][1]
    assert table_el["type"] == "table"
    assert table_el["rows"] == 1 and table_el["columns"] == 2
    assert len(table_el["cells"]) == 2
    assert out["elements"][-1]["segmentType"] == "footer"


def test_populate_table_inserts_reverse_order(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().get().execute.return_value = {
        "body": {"content": [{
            "startIndex": 2,
            "table": {
                "tableRows": [{"tableCells": [
                    {"content": [{"startIndex": 5, "paragraph": {"elements": []}}]},
                    {"content": [{"startIndex": 8, "paragraph": {"elements": []}}]},
                ]}],
            },
        }]},
    }
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.populate_table("D1", 2, [["A", "B"]])
    _, kwargs = svc.documents().batchUpdate.call_args
    reqs = kwargs["body"]["requests"]
    assert len(reqs) == 2
    assert reqs[0]["insertText"]["location"]["index"] == 8
    assert reqs[0]["insertText"]["text"] == "B"
    assert reqs[1]["insertText"]["text"] == "A"


def test_merge_table_cells_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.merge_table_cells("D1", 2, row=0, column=0, row_span=2, column_span=1)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["mergeTableCells"]
    tr = req["tableRange"]
    assert tr["tableCellLocation"]["tableStartLocation"]["index"] == 2
    assert tr["rowSpan"] == 2 and tr["columnSpan"] == 1


def test_format_table_cells_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.format_table_cells("D1", 2, 0, 0, background_color="#FF0000", border_color="#000000", border_width_pt=1)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["updateTableCellStyle"]
    assert "backgroundColor" in req["fields"]
    assert "borderTop" in req["fields"]
    assert req["tableCellStyle"]["borderTop"]["width"]["magnitude"] == 1


def test_insert_page_number_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.insert_page_number("D1", "F1", index=0)
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["insertPageNumber"]
    assert req["location"]["segmentId"] == "F1"
    assert req["location"]["index"] == 0


def test_update_paragraph_style_line_spacing(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.update_paragraph_style("D1", 1, 10, line_spacing=150, line_spacing_mode="MULTIPLE")
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["updateParagraphStyle"]
    assert req["paragraphStyle"]["lineSpacing"] == 150
    assert req["paragraphStyle"]["spacingMode"] == "MULTIPLE"


def test_insert_numbered_list_builds_request(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    api.insert_numbered_list("D1", 1, 20, preset="NUMBERED_DECIMAL_NESTED")
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["createParagraphBullets"]
    assert req["bulletPreset"] == "NUMBERED_DECIMAL_NESTED"


def test_batch_update_passthrough(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    payload = [{"insertText": {"location": {"index": 1}, "text": "x"}}]
    api.batch_update("D1", payload)
    _, kwargs = svc.documents().batchUpdate.call_args
    assert kwargs["body"]["requests"] == payload


def test_batch_update_rejects_empty(monkeypatch):
    api, _svc = _api_with_mock(monkeypatch)
    with pytest.raises(ValueError, match="non-empty"):
        api.batch_update("D1", [])


def test_insert_sheets_chart_pipeline(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    monkeypatch.setattr(
        "google_workspace_mcp.sheets.sheets_api.SheetsAPI.fetch_chart_image_bytes",
        lambda self, sid, cid: b"PNG",
    )
    drive = MagicMock()
    monkeypatch.setattr("google_auth_core.get_service", lambda name, ver, account=None: drive if name == "drive" else svc)
    drive.files().create().execute.return_value = {"id": "FILE1"}
    drive.permissions().create().execute.return_value = {"id": "perm"}
    svc.documents().batchUpdate().execute.return_value = {"ok": True}
    out = api.insert_sheets_chart("D1", "SHEET1", 123, index=5)
    assert "drive.google.com" in out["imageUri"]
    _, kwargs = svc.documents().batchUpdate.call_args
    req = kwargs["body"]["requests"][0]["insertInlineImage"]
    assert req["location"]["index"] == 5
    assert "FILE1" in req["uri"]


def test_get_chart_image_url():
    from google_workspace_mcp.sheets.sheets_api import SheetsAPI
    url = SheetsAPI.get_chart_image_url("abc", 999)
    assert url == "https://docs.google.com/spreadsheets/d/abc/chart?oid=999&format=image"


def test_create_document_from_markdown(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().create().execute.return_value = {
        "id": "D9", "name": "Spec",
        "mimeType": "application/vnd.google-apps.document",
        "webViewLink": "https://docs.google.com/document/d/D9",
    }
    out = api.create_document_from_markdown("Spec", "# Title\n\nBody", folder_id="F1")
    assert out["documentId"] == "D9"
    assert out["title"] == "Spec"
    _, kwargs = svc.files().create.call_args
    assert kwargs["body"] == {
        "name": "Spec",
        "mimeType": "application/vnd.google-apps.document",
        "parents": ["F1"],
    }
    assert kwargs["media_body"].mimetype() == "text/markdown"


def test_create_document_from_markdown_no_folder(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().create().execute.return_value = {"id": "D9", "name": "Spec"}
    api.create_document_from_markdown("Spec", "# T")
    _, kwargs = svc.files().create.call_args
    assert "parents" not in kwargs["body"]


def test_replace_document_with_markdown(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().update().execute.return_value = {"id": "D1", "name": "Doc"}
    out = api.replace_document_with_markdown("D1", "# New")
    assert out == {"documentId": "D1", "title": "Doc", "replaced": True}
    _, kwargs = svc.files().update.call_args
    assert kwargs["fileId"] == "D1"
    assert kwargs["media_body"].mimetype() == "text/markdown"


def test_read_document_as_markdown(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().export().execute.return_value = b"# Hi\n"
    out = api.read_document_as_markdown("D1")
    assert out == {"documentId": "D1", "markdown": "# Hi\n"}
    svc.files().export.assert_called_with(fileId="D1", mimeType="text/markdown")


def test_append_markdown_round_trips(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().export().execute.return_value = b"# Existing\n\nBody\n"
    svc.files().update().execute.return_value = {"id": "D1", "name": "Doc"}
    out = api.append_markdown("D1", "## Added")
    assert out == {"documentId": "D1", "title": "Doc", "appended": True}
    _, kwargs = svc.files().update.call_args
    media = kwargs["media_body"]
    assert media.getbytes(0, media.size()) == b"# Existing\n\nBody\n\n## Added"


def test_append_markdown_to_empty_doc(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().export().execute.return_value = b"\n"
    svc.files().update().execute.return_value = {"id": "D1", "name": "Doc"}
    api.append_markdown("D1", "# First")
    _, kwargs = svc.files().update.call_args
    media = kwargs["media_body"]
    assert media.getbytes(0, media.size()) == b"# First"


# --- server tools (mocked _api) ---

@pytest.mark.anyio
async def test_read_document_envelope(monkeypatch):
    fake = MagicMock(spec=DocsAPI)
    fake.get_document_text.return_value = {"documentId": "D1", "text": "hi"}
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("read_document", {"document_id": "D1"}))
    assert env["ok"] is True and env["account"] == "d@x.com"
    assert env["data"]["text"] == "hi"


@pytest.mark.anyio
async def test_get_content_map_envelope(monkeypatch):
    fake = MagicMock(spec=DocsAPI)
    fake.get_content_map.return_value = {"documentId": "D1", "elements": []}
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool("get_content_map", {"document_id": "D1"}))
    assert env["ok"] is True
    assert env["data"]["documentId"] == "D1"


@pytest.mark.anyio
async def test_populate_table_envelope(monkeypatch):
    fake = MagicMock(spec=DocsAPI)
    fake.populate_table.return_value = {"filled": 1}
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "d@x.com"))
    env = envelope(await server.mcp.call_tool(
        "populate_table",
        {"document_id": "D1", "table_start_index": 2, "rows": [["A", "B"]]},
    ))
    assert env["ok"] is True
    assert env["data"]["filled"] == 1


@pytest.mark.anyio
async def test_tools_registered_and_account_param():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    docs_tools = [
        "get_document", "read_document", "get_content_map", "create_document", "append_text", "insert_text",
        "replace_all_text", "format_text", "set_paragraph_style", "update_paragraph_style",
        "set_page_layout", "flip_page_orientation", "setup_header", "setup_footer",
        "create_header", "create_footer", "delete_header", "delete_footer",
        "insert_inline_image", "insert_chart_image", "insert_sheets_chart", "insert_table", "insert_page_break",
        "insert_bullets", "insert_numbered_list", "populate_table", "merge_table_cells", "format_table_cells",
        "insert_page_number", "batch_update", "remove_bullets", "delete_range",
    ]
    for name in docs_tools:
        assert name in tools, f"missing tool {name}"
        assert "account" in (tools[name].inputSchema or {}).get("properties", {})
    # common tools present
    assert {"list_accounts", "whoami", "auth_status"}.issubset(tools)


# --- markdown tools (server level) ---

@pytest.fixture
def patched_docs_server(monkeypatch):
    fake = MagicMock(spec=DocsAPI)
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "test@x.com"))
    return fake


@pytest.mark.anyio
async def test_markdown_tools_registered():
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    assert {
        "create_document_from_markdown", "replace_document_with_markdown",
        "append_markdown", "read_document_as_markdown",
    } <= names


@pytest.mark.anyio
async def test_create_document_from_markdown_tool(patched_docs_server):
    patched_docs_server.create_document_from_markdown.return_value = {"documentId": "D9"}
    raw = await server.mcp.call_tool("create_document_from_markdown", {
        "title": "Spec", "markdown": "# T",
    })
    payload = envelope(raw)
    assert payload["ok"] is True
    assert payload["account"] == "test@x.com"
    assert payload["data"]["documentId"] == "D9"
    patched_docs_server.create_document_from_markdown.assert_called_once_with("Spec", "# T", None)


@pytest.mark.anyio
async def test_replace_document_with_markdown_tool(patched_docs_server):
    patched_docs_server.replace_document_with_markdown.return_value = {"replaced": True}
    raw = await server.mcp.call_tool("replace_document_with_markdown", {
        "document_id": "D1", "markdown": "# New",
    })
    assert envelope(raw)["ok"] is True
    patched_docs_server.replace_document_with_markdown.assert_called_once_with("D1", "# New")


@pytest.mark.anyio
async def test_append_markdown_tool(patched_docs_server):
    patched_docs_server.append_markdown.return_value = {"appended": True}
    raw = await server.mcp.call_tool("append_markdown", {
        "document_id": "D1", "markdown": "## More",
    })
    assert envelope(raw)["ok"] is True
    patched_docs_server.append_markdown.assert_called_once_with("D1", "## More")


@pytest.mark.anyio
async def test_read_document_as_markdown_tool(patched_docs_server):
    patched_docs_server.read_document_as_markdown.return_value = {"markdown": "# Hi"}
    raw = await server.mcp.call_tool("read_document_as_markdown", {"document_id": "D1"})
    assert envelope(raw)["data"]["markdown"] == "# Hi"
    patched_docs_server.read_document_as_markdown.assert_called_once_with("D1")
