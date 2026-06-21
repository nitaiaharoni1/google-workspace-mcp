# Sheets Content-Editing Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the seven missing content-editing tools to the Google Sheets MCP (`find_replace`, `copy_paste`, `cut_paste`, `hide_columns`, `hide_rows`, `delete_table`, `update_table`) and verify the full edit surface against a live sheet.

**Architecture:** Each tool is a thin `@register` wrapper in `sheets/server.py` that delegates to a new method on `SheetsAPI` in `sheets/sheets_api.py`. New API methods reuse existing helpers (`_a1_to_grid_range`, `_dimension_range`, `_banding_properties`, `_batch`) and go through the Sheets `batchUpdate` endpoint. Each API method is unit-tested for exact request shape (mock `google_auth_core.get_service`); each server tool is unit-tested for the response envelope (monkeypatch `server._api`); a new live integration script exercises everything end-to-end.

**Tech Stack:** Python 3.14, `googleapiclient` (Sheets API v4), FastMCP, pytest.

---

## File Structure

- **Modify** `google_workspace_mcp/sheets/sheets_api.py` — add API methods + helpers `_a1_to_grid_coordinate`, `_build_table_columns`.
- **Modify** `google_workspace_mcp/sheets/server.py` — add 7 `@register` tool wrappers.
- **Modify** `tests/test_sheets_server.py` — add API unit tests + server-tool tests + extend the `list_tools` expected set.
- **Create** `tests/live_sheets_editing.py` — live audit script (mirrors `tests/live_sheets_formatting.py`).
- **Modify** `README.md` — bump the Sheets tool count.

## Conventions (read once before starting)

- API unit tests use two fixtures already in `tests/test_sheets_server.py`:
  - `sheets_api` → `(api, svc)` where `svc` is a MagicMock service.
  - `api_with_meta` → same but `svc.spreadsheets().get(...).execute()` returns
    `{"sheets": [{"properties": {"sheetId": 7, "title": "Tab"}}]}` and
    `svc.spreadsheets().batchUpdate(...).execute()` returns `{"replies": [{}]}`.
    Use `api_with_meta` whenever the method resolves an A1 range (needs metadata).
- Server-tool tests use the `patched_server` fixture (monkeypatches `server._api`
  to return `(fake_api, "test@x.com")`) and `_parse_result(raw)` to read the
  envelope. Set `patched_server.<api_method>.return_value` to the fake API return.
- Run tests with the project venv: `.venv/bin/python -m pytest`.

---

## Task 1: `find_replace`

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py`
- Modify: `google_workspace_mcp/sheets/server.py`
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API unit tests**

Add to the `TestSheetsAPIDimensions` class in `tests/test_sheets_server.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k find_replace -v`
Expected: FAIL with `AttributeError: 'SheetsAPI' object has no attribute 'find_replace'`.

- [ ] **Step 3: Implement `find_replace` in `sheets_api.py`**

Add after `clear_basic_filter` (near the other batch helpers), inside the `SheetsAPI` class:

```python
    def find_replace(self, spreadsheet_id, find, replacement, range=None, all_sheets=False,
                     match_case=False, match_entire_cell=False, search_by_regex=False,
                     include_formulas=False):
        fr = {
            "find": find,
            "replacement": replacement,
            "matchCase": match_case,
            "matchEntireCell": match_entire_cell,
            "searchByRegex": search_by_regex,
            "includeFormulas": include_formulas,
        }
        if all_sheets:
            fr["allSheets"] = True
        elif range:
            meta = self.get_spreadsheet(spreadsheet_id)
            titles = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
            if "!" not in range and range in titles:
                fr["sheetId"] = titles[range]
            else:
                fr["range"] = self._a1_to_grid_range(spreadsheet_id, range, meta)
        else:
            raise ValueError("find_replace requires range or all_sheets=True")
        return self._batch(spreadsheet_id, [{"findReplace": fr}])
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k find_replace -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Add the server tool in `server.py`**

Add in the "DESTRUCTIVE / mutating" area near `clear_basic_filter` (it is mutating, not destructive):

```python
@register(mcp, mutating=True)
def find_replace(account: str | None = None, spreadsheet_id: str = "", find: str = "", replacement: str = "", range: str | None = None, all_sheets: bool = False, match_case: bool = False, match_entire_cell: bool = False, search_by_regex: bool = False, include_formulas: bool = False) -> dict:
    """Find and replace text. Scope to a range (A1, e.g. 'Sheet1!A1:C9'), a whole sheet (bare tab name like 'Sheet1'), or set all_sheets=True. search_by_regex treats 'find' as a regex; include_formulas also searches formula text. Returns counts of changes."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.find_replace(spreadsheet_id, find, replacement, range, all_sheets, match_case, match_entire_cell, search_by_regex, include_formulas))
    return ok(resolved, data)
```

- [ ] **Step 6: Write the failing server-tool test**

Add in the server integration section (section (b)) of `tests/test_sheets_server.py`:

```python
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
```

- [ ] **Step 7: Run the server-tool test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k find_replace -v`
Expected: PASS (5 tests total).

- [ ] **Step 8: Commit**

```bash
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add find_replace tool"
```

---

## Task 2: `copy_paste` and `cut_paste`

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py`
- Modify: `google_workspace_mcp/sheets/server.py`
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API unit tests**

Add to `TestSheetsAPIDimensions`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k "copy_paste or cut_paste" -v`
Expected: FAIL with `AttributeError` (no `copy_paste` / `cut_paste`).

- [ ] **Step 3: Implement the helper and methods in `sheets_api.py`**

Add `_a1_to_grid_coordinate` right after the existing `_a1_to_grid_range` method:

```python
    def _a1_to_grid_coordinate(self, spreadsheet_id, a1, meta=None):
        _, sheet_id, grid, _, _, _, _ = self._resolve_a1(spreadsheet_id, a1, meta)
        return {
            "sheetId": sheet_id,
            "rowIndex": grid.get("startRowIndex", 0),
            "columnIndex": grid.get("startColumnIndex", 0),
        }
```

Add `copy_paste` and `cut_paste` near `find_replace`:

```python
    def copy_paste(self, spreadsheet_id, source_range, destination_range,
                   paste_type="PASTE_NORMAL", transpose=False):
        meta = self.get_spreadsheet(spreadsheet_id)
        req = {"copyPaste": {
            "source": self._a1_to_grid_range(spreadsheet_id, source_range, meta),
            "destination": self._a1_to_grid_range(spreadsheet_id, destination_range, meta),
            "pasteType": paste_type,
            "pasteOrientation": "TRANSPOSE" if transpose else "NORMAL",
        }}
        return self._batch(spreadsheet_id, [req])

    def cut_paste(self, spreadsheet_id, source_range, destination, paste_type="PASTE_NORMAL"):
        meta = self.get_spreadsheet(spreadsheet_id)
        req = {"cutPaste": {
            "source": self._a1_to_grid_range(spreadsheet_id, source_range, meta),
            "destination": self._a1_to_grid_coordinate(spreadsheet_id, destination, meta),
            "pasteType": paste_type,
        }}
        return self._batch(spreadsheet_id, [req])
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k "copy_paste or cut_paste" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Add the server tools in `server.py`**

Add near `find_replace`:

```python
@register(mcp, mutating=True)
def copy_paste(account: str | None = None, spreadsheet_id: str = "", source_range: str = "", destination_range: str = "", paste_type: str = "PASTE_NORMAL", transpose: bool = False) -> dict:
    """Copy a range (A1) to a destination range, within or across sheets (use a sheet prefix in either A1). paste_type: PASTE_NORMAL/PASTE_VALUES/PASTE_FORMAT/PASTE_FORMULA/PASTE_NO_BORDERS/PASTE_DATA_VALIDATION/PASTE_CONDITIONAL_FORMATTING. transpose=True flips rows and columns."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.copy_paste(spreadsheet_id, source_range, destination_range, paste_type, transpose))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def cut_paste(account: str | None = None, spreadsheet_id: str = "", source_range: str = "", destination: str = "", paste_type: str = "PASTE_NORMAL") -> dict:
    """Move a range (A1) to a destination anchor cell (single cell A1, e.g. 'Sheet2!A1'), clearing the source. paste_type matches copy_paste."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.cut_paste(spreadsheet_id, source_range, destination, paste_type))
    return ok(resolved, data)
```

- [ ] **Step 6: Write the failing server-tool tests**

Add in section (b):

```python
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
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k "copy_paste or cut_paste" -v`
Expected: PASS (5 tests total).

- [ ] **Step 8: Commit**

```bash
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add copy_paste and cut_paste tools"
```

---

## Task 3: `hide_columns` and `hide_rows`

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py`
- Modify: `google_workspace_mcp/sheets/server.py`
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API unit tests**

Add to `TestSheetsAPIDimensions`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k "hide_columns or unhide_rows" -v`
Expected: FAIL with `AttributeError: ... no attribute 'set_dimension_visibility'`.

- [ ] **Step 3: Implement `set_dimension_visibility` in `sheets_api.py`**

Add in the dimensions section, right after `delete_dimension`:

```python
    def set_dimension_visibility(self, spreadsheet_id, range, dimension, hidden):
        dim = self._dimension_range(spreadsheet_id, range, dimension)
        req = {"updateDimensionProperties": {"range": dim, "properties": {"hiddenByUser": hidden}, "fields": "hiddenByUser"}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k "hide_columns or unhide_rows" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Add the server tools in `server.py`**

Add near `resize_columns`/`resize_rows`:

```python
@register(mcp, mutating=True)
def hide_columns(account: str | None = None, spreadsheet_id: str = "", range: str = "", hidden: bool = True) -> dict:
    """Hide the columns covered by a column range (e.g. 'Sheet1!C:D'). Pass hidden=False to unhide them."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_dimension_visibility(spreadsheet_id, range, "COLUMNS", hidden))
    return ok(resolved, data)


@register(mcp, mutating=True)
def hide_rows(account: str | None = None, spreadsheet_id: str = "", range: str = "", hidden: bool = True) -> dict:
    """Hide the rows covered by a row range (e.g. 'Sheet1!3:5'). Pass hidden=False to unhide them."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_dimension_visibility(spreadsheet_id, range, "ROWS", hidden))
    return ok(resolved, data)
```

- [ ] **Step 6: Write the failing server-tool test**

Add in section (b):

```python
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
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k "hide_columns or unhide_rows" -v`
Expected: PASS (3 tests total).

- [ ] **Step 8: Commit**

```bash
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add hide_columns and hide_rows tools"
```

---

## Task 4: `delete_table`

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py`
- Modify: `google_workspace_mcp/sheets/server.py`
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API unit test**

Add to `TestSheetsAPIDimensions`:

```python
    def test_delete_table(self, api_with_meta):
        api, svc = api_with_meta
        api.delete_table("sid", "table123")
        svc.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="sid",
            body={"requests": [{"deleteTable": {"tableId": "table123"}}]},
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k delete_table -v`
Expected: FAIL with `AttributeError: ... no attribute 'delete_table'`.

- [ ] **Step 3: Implement `delete_table` in `sheets_api.py`**

Add right after the `add_table` method:

```python
    def delete_table(self, spreadsheet_id, table_id):
        return self._batch(spreadsheet_id, [{"deleteTable": {"tableId": table_id}}])
```

- [ ] **Step 4: Run the API test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k delete_table -v`
Expected: PASS (1 test).

- [ ] **Step 5: Add the server tool in `server.py`**

Add right after `add_table`:

```python
@register(mcp, mutating=True, destructive=True)
def delete_table(account: str | None = None, spreadsheet_id: str = "", table_id: str = "") -> dict:
    """Delete a native table by its tableId (from the add_table reply, or get_spreadsheet where each sheet lists its 'tables'). Cell values remain; the table structure is removed."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_table(spreadsheet_id, table_id))
    return ok(resolved, data)
```

- [ ] **Step 6: Write the failing server-tool test**

Add in section (b):

```python
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
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k delete_table -v`
Expected: PASS (2 tests total).

- [ ] **Step 8: Commit**

```bash
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add delete_table tool"
```

---

## Task 5: `update_table`

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py`
- Modify: `google_workspace_mcp/sheets/server.py`
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API unit tests**

Add to `TestSheetsAPIDimensions`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k update_table -v`
Expected: FAIL with `AttributeError: ... no attribute 'update_table'`.

- [ ] **Step 3: Implement `_build_table_columns` and `update_table` in `sheets_api.py`**

Add both right after the `delete_table` method:

```python
    def _build_table_columns(self, specs):
        cols = []
        for s in specs:
            col = {"columnIndex": s["column_index"]}
            if s.get("column_name") is not None:
                col["columnName"] = s["column_name"]
            if s.get("column_type") is not None:
                col["columnType"] = s["column_type"]
            if s.get("values"):
                col["dataValidationRule"] = {"condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": str(v)} for v in s["values"]],
                }}
            cols.append(col)
        return cols

    def update_table(self, spreadsheet_id, table_id, name=None, range=None,
                     header_color=None, first_band_color=None, second_band_color=None,
                     footer_color=None, column_properties=None):
        table = {"tableId": table_id}
        fields = []
        if name is not None:
            table["name"] = name
            fields.append("name")
        if range is not None:
            table["range"] = self._a1_to_grid_range(spreadsheet_id, range)
            fields.append("range")
        if any(c is not None for c in (header_color, first_band_color, second_band_color, footer_color)):
            table["rowsProperties"] = self._banding_properties(
                header_color, first_band_color, second_band_color, footer_color,
            )
            fields.append("rowsProperties")
        if column_properties is not None:
            table["columnProperties"] = self._build_table_columns(column_properties)
            fields.append("columnProperties")
        if not fields:
            raise ValueError("update_table requires at least one field to update")
        return self._batch(spreadsheet_id, [{"updateTable": {"table": table, "fields": ",".join(fields)}}])
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k update_table -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Add the server tool in `server.py`**

Add right after `add_table` (and after `delete_table` from Task 4):

```python
@register(mcp, mutating=True)
def update_table(account: str | None = None, spreadsheet_id: str = "", table_id: str = "", name: str | None = None, range: str | None = None, header_color: str | None = None, first_band_color: str | None = None, second_band_color: str | None = None, footer_color: str | None = None, column_properties: list[dict] | None = None) -> dict:
    """Update an existing native table's settings by tableId. name renames it; range (A1) resizes/moves it; header/first_band/second_band/footer_color recolor it (hex). column_properties sets per-column settings: [{column_index, column_name, column_type, values}] where column_type is TEXT/DOUBLE/PERCENT/DATE/BOOLEAN/DROPDOWN and values builds a dropdown."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.update_table(spreadsheet_id, table_id, name, range, header_color, first_band_color, second_band_color, footer_color, column_properties))
    return ok(resolved, data)
```

- [ ] **Step 6: Write the failing server-tool test**

Add in section (b):

```python
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
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k update_table -v`
Expected: PASS (5 tests total).

- [ ] **Step 8: Commit**

```bash
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add update_table tool"
```

---

## Task 6: Update `list_tools` test and README

**Files:**
- Modify: `tests/test_sheets_server.py:405-419` (the `expected` set)
- Modify: `README.md:12`

- [ ] **Step 1: Extend the `list_tools` expected set**

In `test_list_tools_includes_expected`, add the new tool names to the `expected` set. Replace the `add_table, format_table, ...` line so the set includes:

```python
        "add_table", "update_table", "delete_table", "format_table", "read_formulas", "write_formulas",
        "find_replace", "copy_paste", "cut_paste", "hide_columns", "hide_rows",
```

(Keep the existing `# common tools` line unchanged.)

- [ ] **Step 2: Run the list_tools test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -k list_tools -v`
Expected: PASS.

- [ ] **Step 3: Update the README tool count**

In `README.md` line 12, change `~11 Sheets tools` to `~41 Sheets tools`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_sheets_server.py README.md
git commit -m "sheets: register new edit tools in list_tools test and README"
```

---

## Task 7: Live audit integration script

**Files:**
- Create: `tests/live_sheets_editing.py`

- [ ] **Step 1: Create the live audit script**

Create `tests/live_sheets_editing.py` with this content:

```python
#!/usr/bin/env python3
"""Live audit for the Sheets content-editing surface (CRUD + new edit tools).

Creates a scratch spreadsheet, exercises every edit operation, verifies by
reading back, then deletes it.
Run: .venv/bin/python tests/live_sheets_editing.py
"""
from __future__ import annotations

import sys
import traceback

from google_workspace_mcp.sheets.sheets_api import SheetsAPI

ACCOUNT = "nitaiaharoni1@gmail.com"
PASS = 0
FAIL = 0


def check(label: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def first_sheet(api, sid):
    return api.get_spreadsheet(sid)["sheets"][0]


def main() -> int:
    api = SheetsAPI(account=ACCOUNT)
    sid = None
    print(f"Account: {ACCOUNT}\n")
    try:
        print("1. Create scratch spreadsheet")
        created = api.create_spreadsheet("MCP Edit Audit (auto-delete)")
        sid = created["spreadsheetId"]
        print(f"   ID: {sid}")

        print("\n2. update_range + batch_update_values + append_rows")
        api.update_range(sid, "Sheet1!A1:C3", [
            ["Name", "Score", "Status"],
            ["Alpha", 10, "Active"],
            ["Beta", 5, "Draft"],
        ])
        api.batch_update_values(sid, [
            {"range": "Sheet1!B2", "values": [[11]]},
            {"range": "Sheet1!B3", "values": [[6]]},
        ])
        api.append_rows(sid, "Sheet1!A1", [["Gamma", 8, "Active"]])
        vals = api.read_range(sid, "Sheet1!A1:C4").get("values", [])
        check("update + batch_update applied", vals and str(vals[1][1]) == "11")
        check("append added a row", len(vals) == 4 and vals[3][0] == "Gamma")

        print("\n3. find_replace (range scope)")
        fr = api.find_replace(sid, "Active", "Open", range="Sheet1!A1:C4")
        occ = fr.get("replies", [{}])[0].get("findReplace", {}).get("occurrencesChanged")
        check("find_replace changed occurrences", bool(occ and occ >= 2), f"occ={occ}")
        vals = api.read_range(sid, "Sheet1!C1:C4").get("values", [])
        check("values replaced to Open", any(r and r[0] == "Open" for r in vals))

        print("\n4. find_replace (regex, all sheets)")
        api.find_replace(sid, "^Op.*", "Closed", all_sheets=True, search_by_regex=True, match_entire_cell=True)
        vals = api.read_range(sid, "Sheet1!C1:C4").get("values", [])
        check("regex replace applied", any(r and r[0] == "Closed" for r in vals))

        print("\n5. copy_paste (values) + cut_paste")
        api.copy_paste(sid, "Sheet1!A1:C1", "Sheet1!E1:G1", paste_type="PASTE_VALUES")
        ev = api.read_range(sid, "Sheet1!E1:G1").get("values", [])
        check("copy_paste copied header", ev and ev[0][0] == "Name")
        api.cut_paste(sid, "Sheet1!E1:G1", "Sheet1!E5")
        moved = api.read_range(sid, "Sheet1!E5:G5").get("values", [])
        src = api.read_range(sid, "Sheet1!E1:G1").get("values", [])
        check("cut_paste moved to E5", moved and moved[0][0] == "Name")
        check("cut_paste cleared source", not src)

        print("\n6. insert/delete rows + columns")
        api.insert_rows(sid, "Sheet1!2:2")
        after_insert = api.read_range(sid, "Sheet1!A3:A3").get("values", [])
        check("insert_rows shifted Alpha down", after_insert and after_insert[0][0] == "Alpha")
        api.delete_rows(sid, "Sheet1!2:2")
        api.insert_columns(sid, "Sheet1!B:B")
        api.delete_columns(sid, "Sheet1!B:B")
        check("insert/delete row+column ran", True)

        print("\n7. hide_columns + unhide")
        api.set_dimension_visibility(sid, "Sheet1!C:C", "COLUMNS", True)
        # hiddenByUser shows up in columnMetadata when grid data is requested
        meta = api.get_spreadsheet(sid, include_grid_data=True)["sheets"][0]
        col_meta = meta.get("data", [{}])[0].get("columnMetadata", [])
        hidden_c = len(col_meta) > 2 and col_meta[2].get("hiddenByUser") is True
        check("hide_columns set hiddenByUser on C", hidden_c)
        api.set_dimension_visibility(sid, "Sheet1!C:C", "COLUMNS", False)
        meta = api.get_spreadsheet(sid, include_grid_data=True)["sheets"][0]
        col_meta = meta.get("data", [{}])[0].get("columnMetadata", [])
        unhidden_c = not (len(col_meta) > 2 and col_meta[2].get("hiddenByUser") is True)
        check("unhide cleared hiddenByUser on C", unhidden_c)

        print("\n8. add_table -> update_table -> delete_table")
        api.update_range(sid, "Sheet1!A10:C12", [
            ["City", "Pop", "Tier"],
            ["NYC", 8, "A"],
            ["LA", 4, "B"],
        ])
        add = api.add_table(sid, "Sheet1!A10:C12", "Cities")
        table_id = add.get("replies", [{}])[0].get("addTable", {}).get("table", {}).get("tableId")
        check("add_table returned tableId", bool(table_id), f"reply={add}")
        if table_id:
            api.update_table(
                sid, table_id, name="CitiesRenamed", header_color="#4285F4",
                column_properties=[{"column_index": 2, "column_name": "Tier",
                                    "column_type": "DROPDOWN", "values": ["A", "B"]}],
            )
            tables = first_sheet(api, sid).get("tables", [])
            t = tables[0] if tables else {}
            check("update_table renamed", t.get("name") == "CitiesRenamed", f"name={t.get('name')}")
            check("update_table recolored header", "headerColorStyle" in t.get("rowsProperties", {}))
            api.delete_table(sid, table_id)
            tables_after = first_sheet(api, sid).get("tables", [])
            check("delete_table removed table", not tables_after)

        print("\n9. merge/unmerge + duplicate_sheet + sort_range + clear_range")
        api.merge_cells(sid, "Sheet1!E10:F10")
        api.unmerge_cells(sid, "Sheet1!E10:F10")
        api.sort_range(sid, "Sheet1!A11:C12", column=1, ascending=False)
        dup = api.duplicate_sheet(sid, first_sheet(api, sid)["properties"]["sheetId"], "Copy")
        check("duplicate_sheet ran", "replies" in dup)
        api.clear_range(sid, "Sheet1!E5:G5")
        cleared = api.read_range(sid, "Sheet1!E5:G5").get("values", [])
        check("clear_range emptied E5:G5", not cleared)

    except Exception as exc:
        print(f"\n  ✗ EXCEPTION: {exc}")
        traceback.print_exc()
        global FAIL
        FAIL += 1
    finally:
        if sid:
            print(f"\nCleanup: removing scratch spreadsheet {sid}")
            try:
                import google_auth_core as core
                drive = core.get_service("drive", "v3", account=ACCOUNT)
                drive.files().delete(fileId=sid).execute()
                print("  ✓ deleted via Drive API")
            except Exception as exc2:
                print(f"  ⚠ cleanup failed: {exc2}")
                print(f"    https://docs.google.com/spreadsheets/d/{sid}")

    print(f"\n{'=' * 40}")
    print(f"PASSED: {PASS}  FAILED: {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the full unit suite to confirm nothing regressed**

Run: `.venv/bin/python -m pytest tests/test_sheets_server.py -v`
Expected: PASS (all existing + new tests).

- [ ] **Step 3: Run the live audit (requires the `nitaiaharoni1@gmail.com` credential)**

Run: `.venv/bin/python tests/live_sheets_editing.py`
Expected: `PASSED: N  FAILED: 0`. If any op fails read-back, fix the underlying
API method (this is the audit deliverable), re-run, then continue.

- [ ] **Step 4: Commit**

```bash
git add tests/live_sheets_editing.py
git commit -m "test: add live audit for Sheets content-editing surface"
```

---

## Self-Review Notes

- **Spec coverage:** find_replace (Task 1), copy_paste/cut_paste (Task 2),
  hide_columns/hide_rows via set_dimension_visibility (Task 3), delete_table
  (Task 4), update_table + _build_table_columns (Task 5), README (Task 6), live
  audit of full surface (Task 7). All spec items mapped.
- **Helpers:** `_a1_to_grid_coordinate` (Task 2), `_build_table_columns` (Task 5)
  are each defined before first use.
- **Destructive flags:** `cut_paste` and `delete_table` marked
  `destructive=True`; the rest `mutating=True`, matching the spec table.
- **Scope detection:** find_replace bare-sheet vs cell-range disambiguation is
  pinned by `test_find_replace_range_scope` (cells) and
  `test_find_replace_bare_sheet_scope` (bare tab name), using the sheet-title
  lookup so a tab named "Sheet1" is not mistaken for a cell reference.
```
