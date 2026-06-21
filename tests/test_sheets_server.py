"""Tests for the Google Sheets MCP server and SheetsAPI wrapper."""
from __future__ import annotations
import json
from unittest.mock import MagicMock, patch

import pytest

from google_workspace_mcp.sheets.sheets_api import SheetsAPI
from google_workspace_mcp.sheets import server


# ──────────────────────────────────────────────────────────────────────────────
# Fixture
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def anyio_backend():
    return "asyncio"


# ──────────────────────────────────────────────────────────────────────────────
# (a) SheetsAPI unit tests — monkeypatch google_auth_core.get_service
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_service():
    """A MagicMock that mimics the googleapiclient service chain."""
    return MagicMock()


@pytest.fixture
def sheets_api(mock_service):
    with patch("google_auth_core.get_service", return_value=mock_service):
        api = SheetsAPI("x@x.com")
    return api, mock_service


class TestSheetsAPIUnit:
    def test_read_range(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["A1"]]}

        result = api.read_range("sid", "Sheet1!A1:C3")

        svc.spreadsheets().values().get.assert_called_with(
            spreadsheetId="sid", range="Sheet1!A1:C3", valueRenderOption="FORMATTED_VALUE"
        )
        assert result == {"values": [["A1"]]}

    def test_update_range(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 2}

        result = api.update_range("sid", "A1:B1", [["hello", "world"]])

        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid",
            range="A1:B1",
            valueInputOption="USER_ENTERED",
            body={"values": [["hello", "world"]]},
        )
        assert result == {"updatedCells": 2}

    def test_append_rows(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().append.return_value.execute.return_value = {"updates": {}}

        result = api.append_rows("sid", "Sheet1!A1", [["row1", "row2"]])

        svc.spreadsheets().values().append.assert_called_with(
            spreadsheetId="sid",
            range="Sheet1!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [["row1", "row2"]]},
        )
        assert result == {"updates": {}}

    def test_create_spreadsheet(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().create.return_value.execute.return_value = {"spreadsheetId": "new_id", "properties": {"title": "My Sheet"}}

        result = api.create_spreadsheet("My Sheet")

        svc.spreadsheets().create.assert_called_with(
            body={"properties": {"title": "My Sheet"}}
        )
        assert result["spreadsheetId"] == "new_id"

    def test_add_sheet(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().batchUpdate.return_value.execute.return_value = {"replies": [{}]}

        result = api.add_sheet("sid", "NewTab")

        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"addSheet": {"properties": {"title": "NewTab"}}}]},
        )
        assert result == {"replies": [{}]}

    def test_batch_read(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().batchGet.return_value.execute.return_value = {"valueRanges": []}

        result = api.batch_read("sid", ["A1:B2", "C1:D2"])

        svc.spreadsheets().values().batchGet.assert_called_with(
            spreadsheetId="sid",
            ranges=["A1:B2", "C1:D2"],
            valueRenderOption="FORMATTED_VALUE",
        )
        assert result == {"valueRanges": []}

    def test_clear_range(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().clear.return_value.execute.return_value = {"clearedRange": "A1:B2"}

        result = api.clear_range("sid", "A1:B2")

        svc.spreadsheets().values().clear.assert_called_with(
            spreadsheetId="sid", range="A1:B2", body={}
        )
        assert result == {"clearedRange": "A1:B2"}

    def test_delete_sheet(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().batchUpdate.return_value.execute.return_value = {"replies": [{}]}

        result = api.delete_sheet("sid", 42)

        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"deleteSheet": {"sheetId": 42}}]},
        )

    def test_rename_sheet(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().batchUpdate.return_value.execute.return_value = {"replies": [{}]}

        result = api.rename_sheet("sid", 0, "Renamed")

        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"updateSheetProperties": {"properties": {"sheetId": 0, "title": "Renamed"}, "fields": "title"}}]},
        )

    def test_batch_update_values(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().batchUpdate.return_value.execute.return_value = {"totalUpdatedCells": 4}

        payload = [{"range": "A1:B2", "values": [[1, 2], [3, 4]]}]
        result = api.batch_update_values("sid", payload)

        svc.spreadsheets().values().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"valueInputOption": "USER_ENTERED", "data": payload},
        )
        assert result == {"totalUpdatedCells": 4}

    def test_get_spreadsheet(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().get.return_value.execute.return_value = {"spreadsheetId": "sid", "sheets": []}

        result = api.get_spreadsheet("sid")

        svc.spreadsheets().get.assert_called_with(
            spreadsheetId="sid", includeGridData=False
        )
        assert result["spreadsheetId"] == "sid"


class TestSheetsAPIDimensions:
    """Unit tests for dimension / structure helpers (resize, freeze, borders, validation)."""

    @pytest.fixture
    def api_with_meta(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().get.return_value.execute.return_value = {
            "sheets": [{"properties": {"sheetId": 7, "title": "Tab"}}]
        }
        svc.spreadsheets().batchUpdate.return_value.execute.return_value = {"replies": [{}]}
        return api, svc

    def test_resize_columns_pixels(self, api_with_meta):
        api, svc = api_with_meta
        api.resize_dimension("sid", "Tab!A:C", "COLUMNS", 120)
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"updateDimensionProperties": {
                "range": {"sheetId": 7, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 3},
                "properties": {"pixelSize": 120},
                "fields": "pixelSize",
            }}]},
        )

    def test_resize_columns_autofit(self, api_with_meta):
        api, svc = api_with_meta
        api.resize_dimension("sid", "Tab!B:B", "COLUMNS", None)
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"autoResizeDimensions": {
                "dimensions": {"sheetId": 7, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            }}]},
        )

    def test_resize_rows_requires_row_numbers(self, api_with_meta):
        api, _ = api_with_meta
        with pytest.raises(ValueError):
            api.resize_dimension("sid", "Tab!A:C", "ROWS", 30)

    def test_insert_rows(self, api_with_meta):
        api, svc = api_with_meta
        api.insert_dimension("sid", "Tab!3:5", "ROWS")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"insertDimension": {
                "range": {"sheetId": 7, "dimension": "ROWS", "startIndex": 2, "endIndex": 5},
                "inheritFromBefore": False,
            }}]},
        )

    def test_delete_columns(self, api_with_meta):
        api, svc = api_with_meta
        api.delete_dimension("sid", "Tab!C:D", "COLUMNS")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"deleteDimension": {
                "range": {"sheetId": 7, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 4},
            }}]},
        )

    def test_hide_columns(self, api_with_meta):
        api, svc = api_with_meta
        api.set_dimension_visibility("sid", "Tab!C:D", "COLUMNS", True)
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"updateDimensionProperties": {
                "range": {"sheetId": 7, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 4},
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }}]},
        )

    def test_unhide_rows(self, api_with_meta):
        api, svc = api_with_meta
        api.set_dimension_visibility("sid", "Tab!2:5", "ROWS", False)
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"updateDimensionProperties": {
                "range": {"sheetId": 7, "dimension": "ROWS", "startIndex": 1, "endIndex": 5},
                "properties": {"hiddenByUser": False},
                "fields": "hiddenByUser",
            }}]},
        )

    def test_freeze_panes(self, api_with_meta):
        api, svc = api_with_meta
        api.freeze_panes("sid", "Tab!A1", rows=1, cols=2)
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": 7, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
            }}]},
        )

    def test_freeze_panes_requires_rows_or_cols(self, api_with_meta):
        api, _ = api_with_meta
        with pytest.raises(ValueError):
            api.freeze_panes("sid", "Tab!A1")

    def test_set_borders_inner(self, api_with_meta):
        api, svc = api_with_meta
        api.set_borders("sid", "Tab!A1:B2", style="SOLID", color="#FF0000", inner=True)
        border = {"style": "SOLID", "color": {"red": 1.0, "green": 0.0, "blue": 0.0}}
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"updateBorders": {
                "range": {"sheetId": 7, "startColumnIndex": 0, "endColumnIndex": 2, "startRowIndex": 0, "endRowIndex": 2},
                "top": border, "bottom": border, "left": border, "right": border,
                "innerHorizontal": border, "innerVertical": border,
            }}]},
        )

    def test_set_data_validation_dropdown(self, api_with_meta):
        api, svc = api_with_meta
        api.set_data_validation("sid", "Tab!B2", allowed_values=["Yes", "No"])
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"setDataValidation": {
                "range": {"sheetId": 7, "startColumnIndex": 1, "endColumnIndex": 2, "startRowIndex": 1, "endRowIndex": 2},
                "rule": {
                    "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Yes"}, {"userEnteredValue": "No"}]},
                    "showCustomUi": True,
                    "strict": True,
                },
            }}]},
        )

    def test_set_data_validation_clear(self, api_with_meta):
        api, svc = api_with_meta
        api.set_data_validation("sid", "Tab!B2", allowed_values=None)
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"setDataValidation": {
                "range": {"sheetId": 7, "startColumnIndex": 1, "endColumnIndex": 2, "startRowIndex": 1, "endRowIndex": 2},
            }}]},
        )

    def test_duplicate_sheet(self, api_with_meta):
        api, svc = api_with_meta
        api.duplicate_sheet("sid", 7, "Copy")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"duplicateSheet": {"sourceSheetId": 7, "newSheetName": "Copy"}}]},
        )

    def test_add_banding(self, api_with_meta):
        api, svc = api_with_meta
        api.add_banding("sid", "Tab!A1:C10", header_color="#355468", first_band_color="#FFFFFF", second_band_color="#F3F3F3")
        call = svc.spreadsheets().batchUpdate.call_args
        req = call.kwargs["body"]["requests"][0]["addBanding"]["bandedRange"]
        assert req["range"]["sheetId"] == 7
        assert req["rowProperties"]["firstBandColorStyle"]["rgbColor"]["red"] == 1.0
        assert req["rowProperties"]["headerColorStyle"]["rgbColor"]["blue"] == pytest.approx(0.408, abs=0.01)

    def test_set_basic_filter_with_specs(self, api_with_meta):
        api, svc = api_with_meta
        api.set_basic_filter("sid", "Tab!A1:C10", filter_specs=[{"column": 0, "hidden_values": ["Draft"]}])
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"setBasicFilter": {"filter": {
                "range": {"sheetId": 7, "startColumnIndex": 0, "endColumnIndex": 3, "startRowIndex": 0, "endRowIndex": 10},
                "filterSpecs": [{"columnIndex": 0, "filterCriteria": {"hiddenValues": ["Draft"]}}],
            }}}]},
        )

    def test_find_replace_range_scope(self, api_with_meta):
        api, svc = api_with_meta
        api.find_replace("sid", "old", "new", range="Tab!A1:C9")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"findReplace": {
                "find": "old", "replacement": "new",
                "matchCase": False, "matchEntireCell": False,
                "searchByRegex": False, "includeFormulas": False,
                "range": {"sheetId": 7, "startColumnIndex": 0, "endColumnIndex": 3,
                          "startRowIndex": 0, "endRowIndex": 9},
            }}]},
        )

    def test_find_replace_bare_sheet_scope(self, api_with_meta):
        api, svc = api_with_meta
        api.find_replace("sid", "old", "new", range="Tab", match_case=True)
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"findReplace": {
                "find": "old", "replacement": "new",
                "matchCase": True, "matchEntireCell": False,
                "searchByRegex": False, "includeFormulas": False,
                "sheetId": 7,
            }}]},
        )

    def test_find_replace_all_sheets_regex(self, api_with_meta):
        api, svc = api_with_meta
        api.find_replace("sid", "a.*", "x", all_sheets=True, search_by_regex=True)
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"findReplace": {
                "find": "a.*", "replacement": "x",
                "matchCase": False, "matchEntireCell": False,
                "searchByRegex": True, "includeFormulas": False,
                "allSheets": True,
            }}]},
        )

    def test_find_replace_requires_scope(self, api_with_meta):
        api, _ = api_with_meta
        with pytest.raises(ValueError):
            api.find_replace("sid", "old", "new")

    def test_copy_paste_values(self, api_with_meta):
        api, svc = api_with_meta
        api.copy_paste("sid", "Tab!A1:B2", "Tab!D1:E2", paste_type="PASTE_VALUES")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"copyPaste": {
                "source": {"sheetId": 7, "startColumnIndex": 0, "endColumnIndex": 2,
                           "startRowIndex": 0, "endRowIndex": 2},
                "destination": {"sheetId": 7, "startColumnIndex": 3, "endColumnIndex": 5,
                                "startRowIndex": 0, "endRowIndex": 2},
                "pasteType": "PASTE_VALUES",
                "pasteOrientation": "NORMAL",
            }}]},
        )

    def test_copy_paste_transpose(self, api_with_meta):
        api, svc = api_with_meta
        api.copy_paste("sid", "Tab!A1:B2", "Tab!D1:E2", transpose=True)
        body = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]
        cp = body["requests"][0]["copyPaste"]
        assert cp["pasteType"] == "PASTE_NORMAL"
        assert cp["pasteOrientation"] == "TRANSPOSE"

    def test_cut_paste(self, api_with_meta):
        api, svc = api_with_meta
        api.cut_paste("sid", "Tab!A1:B2", "Tab!D1")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"cutPaste": {
                "source": {"sheetId": 7, "startColumnIndex": 0, "endColumnIndex": 2,
                           "startRowIndex": 0, "endRowIndex": 2},
                "destination": {"sheetId": 7, "rowIndex": 0, "columnIndex": 3},
                "pasteType": "PASTE_NORMAL",
            }}]},
        )

    def test_format_cells_wrap_and_vertical(self, api_with_meta):
        api, svc = api_with_meta
        api.format_cells("sid", "Tab!A1", wrap=True, vertical_alignment="TOP", strikethrough=True)
        call = svc.spreadsheets().batchUpdate.call_args
        req = call.kwargs["body"]["requests"][0]["repeatCell"]
        fmt = req["cell"]["userEnteredFormat"]
        assert fmt["wrapStrategy"] == "WRAP"
        assert fmt["verticalAlignment"] == "TOP"
        assert fmt["textFormat"]["strikethrough"] is True

    def test_write_formulas(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        result = api.write_formulas("sid", "A1", [["=SUM(B2:B10)"]])
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="A1", valueInputOption="USER_ENTERED",
            body={"values": [["=SUM(B2:B10)"]]},
        )
        assert result == {"updatedCells": 1}

    def test_read_formulas(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["=SUM(B2:B10)"]]}
        result = api.read_formulas("sid", "A1")
        svc.spreadsheets().values().get.assert_called_with(
            spreadsheetId="sid", range="A1", valueRenderOption="FORMULA",
        )
        assert result["values"] == [["=SUM(B2:B10)"]]

    def test_format_table_batches_single_request(self, api_with_meta):
        api, svc = api_with_meta
        result = api.format_table("sid", "Tab!A1:C5")
        call = svc.spreadsheets().batchUpdate.call_args
        requests = call.kwargs["body"]["requests"]
        assert len(requests) >= 5
        assert requests[0]["repeatCell"]["range"]["startRowIndex"] == 0
        assert requests[0]["repeatCell"]["range"]["endRowIndex"] == 1
        assert any("addBanding" in r for r in requests)
        assert any("setBasicFilter" in r for r in requests)
        assert any("autoResizeDimensions" in r for r in requests)
        assert result["requests_sent"] == len(requests)
        svc.spreadsheets().get.assert_called_once()

    def test_add_table(self, api_with_meta):
        api, svc = api_with_meta
        api.add_table("sid", "Tab!A1:C10", "MyTable", column_names=["A", "B", "C"])
        call = svc.spreadsheets().batchUpdate.call_args
        req = call.kwargs["body"]["requests"][0]["addTable"]["table"]
        assert req["name"] == "MyTable"
        assert len(req["columnProperties"]) == 3

    def test_delete_table(self, api_with_meta):
        api, svc = api_with_meta
        api.delete_table("sid", "table123")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"deleteTable": {"tableId": "table123"}}]},
        )

    def test_update_table_name_only(self, api_with_meta):
        api, svc = api_with_meta
        api.update_table("sid", "t1", name="Sales")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"updateTable": {
                "table": {"tableId": "t1", "name": "Sales"},
                "fields": "name",
            }}]},
        )

    def test_update_table_recolor_and_columns(self, api_with_meta):
        api, svc = api_with_meta
        api.update_table(
            "sid", "t1",
            header_color="#FF0000",
            column_properties=[
                {"column_index": 2, "column_name": "Status", "column_type": "DROPDOWN", "values": ["Active", "Draft"]},
                {"column_index": 1, "column_name": "Score", "column_type": "PERCENT"},
            ],
        )
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"updateTable": {
                "table": {
                    "tableId": "t1",
                    "rowsProperties": {
                        "headerColorStyle": {"rgbColor": {"red": 1.0, "green": 0.0, "blue": 0.0}},
                    },
                    "columnProperties": [
                        {"columnIndex": 2, "columnName": "Status", "columnType": "DROPDOWN",
                         "dataValidationRule": {"condition": {"type": "ONE_OF_LIST", "values": [
                             {"userEnteredValue": "Active"}, {"userEnteredValue": "Draft"}]}}},
                        {"columnIndex": 1, "columnName": "Score", "columnType": "PERCENT"},
                    ],
                },
                "fields": "rowsProperties,columnProperties",
            }}]},
        )

    def test_update_table_range(self, api_with_meta):
        api, svc = api_with_meta
        api.update_table("sid", "t1", range="Tab!A1:D5")
        body = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]
        ut = body["requests"][0]["updateTable"]
        assert ut["fields"] == "range"
        assert ut["table"]["range"] == {
            "sheetId": 7, "startColumnIndex": 0, "endColumnIndex": 4,
            "startRowIndex": 0, "endRowIndex": 5,
        }

    def test_update_table_requires_a_field(self, api_with_meta):
        api, _ = api_with_meta
        with pytest.raises(ValueError):
            api.update_table("sid", "t1")

    def test_filter_spec_requires_criteria(self, api_with_meta):
        api, _ = api_with_meta
        with pytest.raises(ValueError, match="filter_spec"):
            api.set_basic_filter("sid", "Tab!A1:C10", filter_specs=[{"column": 0}])

    def test_invalid_hex_color(self, api_with_meta):
        api, _ = api_with_meta
        with pytest.raises(ValueError, match="invalid hex"):
            api.format_cells("sid", "Tab!A1", background_color="not-a-color")


# ──────────────────────────────────────────────────────────────────────────────
# (b) Server integration tests — monkeypatch _api
# ──────────────────────────────────────────────────────────────────────────────

def _parse_result(raw):
    """Extract the dict payload from a FastMCP call_tool response (list of TextContent)."""
    assert len(raw) == 1, f"Expected 1 content item, got {len(raw)}: {raw}"
    return json.loads(raw[0].text)


@pytest.fixture
def fake_api():
    return MagicMock()


@pytest.fixture
def patched_server(fake_api, monkeypatch):
    monkeypatch.setattr(server, "_api", lambda account=None: (fake_api, "test@x.com"))
    return fake_api


mcp = server.mcp


@pytest.mark.anyio
async def test_list_tools_includes_expected(patched_server):
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "read_range", "batch_read", "get_spreadsheet",
        "update_range", "batch_update_values", "append_rows",
        "create_spreadsheet", "add_sheet", "rename_sheet",
        "clear_range", "delete_sheet",
        # dimensions / structure
        "resize_columns", "resize_rows", "freeze_panes",
        "insert_rows", "insert_columns", "delete_rows", "delete_columns",
        "set_borders", "set_data_validation", "duplicate_sheet",
        "format_cells", "sort_range", "set_basic_filter", "clear_basic_filter",
        "merge_cells", "unmerge_cells", "add_banding", "update_banding", "delete_banding",
        "add_table", "update_table", "delete_table", "format_table", "read_formulas", "write_formulas",
        "find_replace", "copy_paste", "cut_paste", "hide_columns", "hide_rows",
        # common tools
        "list_accounts", "auth_status", "whoami",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"


@pytest.mark.anyio
async def test_read_range_tool(patched_server):
    patched_server.read_range.return_value = {"values": [["hello"]]}

    raw = await mcp.call_tool("read_range", {
        "spreadsheet_id": "sid",
        "range": "A1:A1",
        "account": "test@x.com",
    })

    # Print once to document the shape (as required by spec)
    print("call_tool raw result:", raw)

    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["account"] == "test@x.com"
    assert result["data"] == {"values": [["hello"]]}


@pytest.mark.anyio
async def test_update_range_tool(patched_server):
    patched_server.update_range.return_value = {"updatedCells": 3}

    raw = await mcp.call_tool("update_range", {
        "spreadsheet_id": "sid",
        "range": "A1:C1",
        "values": [["x", "y", "z"]],
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["updatedCells"] == 3


@pytest.mark.anyio
async def test_clear_range_tool(patched_server):
    patched_server.clear_range.return_value = {"clearedRange": "A1:B2"}

    raw = await mcp.call_tool("clear_range", {
        "spreadsheet_id": "sid",
        "range": "A1:B2",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["clearedRange"] == "A1:B2"


@pytest.mark.anyio
async def test_batch_read_tool(patched_server):
    patched_server.batch_read.return_value = {"valueRanges": []}

    raw = await mcp.call_tool("batch_read", {
        "spreadsheet_id": "sid",
        "ranges": ["A1:B2"],
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"] == {"valueRanges": []}


@pytest.mark.anyio
async def test_create_spreadsheet_tool(patched_server):
    patched_server.create_spreadsheet.return_value = {"spreadsheetId": "new_id"}

    raw = await mcp.call_tool("create_spreadsheet", {"title": "Test Sheet"})
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["spreadsheetId"] == "new_id"


@pytest.mark.anyio
async def test_add_sheet_tool(patched_server):
    patched_server.add_sheet.return_value = {"replies": [{}]}

    raw = await mcp.call_tool("add_sheet", {
        "spreadsheet_id": "sid",
        "title": "NewTab",
    })
    result = _parse_result(raw)
    assert result["ok"] is True


@pytest.mark.anyio
async def test_delete_sheet_tool(patched_server):
    patched_server.delete_sheet.return_value = {"replies": [{}]}

    raw = await mcp.call_tool("delete_sheet", {
        "spreadsheet_id": "sid",
        "sheet_id": 42,
    })
    result = _parse_result(raw)
    assert result["ok"] is True


@pytest.mark.anyio
async def test_rename_sheet_tool(patched_server):
    patched_server.rename_sheet.return_value = {"replies": [{}]}

    raw = await mcp.call_tool("rename_sheet", {
        "spreadsheet_id": "sid",
        "sheet_id": 0,
        "new_title": "Renamed",
    })
    result = _parse_result(raw)
    assert result["ok"] is True


@pytest.mark.anyio
async def test_append_rows_tool(patched_server):
    patched_server.append_rows.return_value = {"updates": {"updatedRows": 1}}

    raw = await mcp.call_tool("append_rows", {
        "spreadsheet_id": "sid",
        "range": "Sheet1!A:A",
        "values": [["newrow"]],
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["updates"]["updatedRows"] == 1


@pytest.mark.anyio
async def test_batch_update_values_tool(patched_server):
    patched_server.batch_update_values.return_value = {"totalUpdatedCells": 4}

    raw = await mcp.call_tool("batch_update_values", {
        "spreadsheet_id": "sid",
        "data": [{"range": "A1:B2", "values": [[1, 2], [3, 4]]}],
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["totalUpdatedCells"] == 4


@pytest.mark.anyio
async def test_get_spreadsheet_tool(patched_server):
    patched_server.get_spreadsheet.return_value = {"spreadsheetId": "sid", "sheets": []}

    raw = await mcp.call_tool("get_spreadsheet", {
        "spreadsheet_id": "sid",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["spreadsheetId"] == "sid"


@pytest.mark.anyio
async def test_find_replace_tool(patched_server):
    patched_server.find_replace.return_value = {"occurrencesChanged": 3}

    raw = await mcp.call_tool("find_replace", {
        "spreadsheet_id": "sid",
        "find": "old",
        "replacement": "new",
        "range": "Sheet1!A1:C9",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["occurrencesChanged"] == 3


@pytest.mark.anyio
async def test_copy_paste_tool(patched_server):
    patched_server.copy_paste.return_value = {"replies": [{}]}

    raw = await mcp.call_tool("copy_paste", {
        "spreadsheet_id": "sid",
        "source_range": "Sheet1!A1:B2",
        "destination_range": "Sheet1!D1:E2",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"] == {"replies": [{}]}


@pytest.mark.anyio
async def test_cut_paste_tool(patched_server):
    patched_server.cut_paste.return_value = {"replies": [{}]}

    raw = await mcp.call_tool("cut_paste", {
        "spreadsheet_id": "sid",
        "source_range": "Sheet1!A1:B2",
        "destination": "Sheet1!D1",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"] == {"replies": [{}]}


@pytest.mark.anyio
async def test_hide_columns_tool(patched_server):
    patched_server.set_dimension_visibility.return_value = {"replies": [{}]}

    raw = await mcp.call_tool("hide_columns", {
        "spreadsheet_id": "sid",
        "range": "Sheet1!C:D",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    patched_server.set_dimension_visibility.assert_called_with("sid", "Sheet1!C:D", "COLUMNS", True)


@pytest.mark.anyio
async def test_delete_table_tool(patched_server):
    patched_server.delete_table.return_value = {"replies": [{}]}

    raw = await mcp.call_tool("delete_table", {
        "spreadsheet_id": "sid",
        "table_id": "table123",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    patched_server.delete_table.assert_called_with("sid", "table123")


@pytest.mark.anyio
async def test_update_table_tool(patched_server):
    patched_server.update_table.return_value = {"replies": [{}]}

    raw = await mcp.call_tool("update_table", {
        "spreadsheet_id": "sid",
        "table_id": "t1",
        "name": "Sales",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"] == {"replies": [{}]}


class TestSheetsChartExport:
    def test_get_chart_image_url(self):
        url = SheetsAPI.get_chart_image_url("abc123", 999)
        assert url == "https://docs.google.com/spreadsheets/d/abc123/chart?oid=999&format=image"

    def test_fetch_chart_image_bytes(self, sheets_api):
        api, _svc = sheets_api
        creds = MagicMock()
        creds.expired = False
        creds.token = "tok"

        class FakeResp:
            def read(self):
                return b"PNGDATA"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch("google_auth_core.get_credentials", return_value=(creds, None)), \
             patch("urllib.request.urlopen", return_value=FakeResp()) as urlopen:
            data = api.fetch_chart_image_bytes("sid", 42)

        assert data == b"PNGDATA"
        req = urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer tok"
        assert "sid" in req.full_url and "oid=42" in req.full_url
