# Sheets Text-Editing Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 7 within-cell / text-granular editing tools to the Google Sheets MCP server (`find_replace`, `edit_cell`, `transform_text`, `regex_replace`, `split_column`, `join_columns`, `regex_extract`).

**Architecture:** Each tool is a method on `SheetsAPI` (`google_workspace_mcp/sheets/sheets_api.py`) plus a thin `@register`-decorated wrapper in `google_workspace_mcp/sheets/server.py`, following the existing pattern exactly: `api, resolved = _api(account); return ok(resolved, run_tool(lambda: api.<method>(...)))`. `find_replace` uses the native `FindReplaceRequest` (server-side). The other six are read-modify-write over the existing `read_range` / `update_range` value methods. Read-modify-write tools parse A1 locally (no extra metadata fetch) so each costs exactly one read + one write.

**Tech Stack:** Python 3, `googleapiclient` (mocked in tests via `MagicMock`), `pytest`, the project's `core` MCP helpers (`build_server`, `register`, `get_api`, `run_tool`, `ok`).

**Spec:** `docs/superpowers/specs/2026-06-21-sheets-text-editing-design.md`

---

## File Structure

- **Modify** `google_workspace_mcp/sheets/sheets_api.py`
  - Add `import re` (top of file).
  - Add A1 helpers `_parse_a1_local`, `_anchor` near the existing A1 helpers (after `_a1_to_grid_range`, ~line 148).
  - Add 7 public methods: `find_replace`, `edit_cell`, `transform_text`, `regex_replace`, `split_column`, `join_columns`, `regex_extract`, plus the private `_read_text_grid` and `_assert_single_cell` / `_assert_single_column` helpers. Place them after `read_formulas` (~line 456), before the chart-export section.
- **Modify** `google_workspace_mcp/sheets/server.py`
  - Add a new section `# --- TEXT EDITING (mutating) tools ---` before `def main()` (~line 296) with 7 `@register`-decorated wrappers.
- **Modify** `tests/test_sheets_server.py`
  - Add a `TestSheetsAPITextEditing` class (API unit tests).
  - Add server-level tool tests near the existing ones.
  - Extend `test_list_tools_includes_expected` with the 7 new names.
- **Modify** `tests/live_sheets_formatting.py`
  - Add a live section exercising `find_replace` + `edit_cell` + `transform_text`.

Reference signatures (defined across the tasks below; later tasks depend on these exact names):

```python
# sheets_api.py
def _parse_a1_local(self, a1): ...        # -> (sheet_name, start_col, start_row, end_col, end_row)  all strings
def _anchor(self, sheet_name, col, row): ...  # -> A1 anchor string, quoted if sheet_name present
def _read_text_grid(self, spreadsheet_id, range): ...  # -> 2D list (FORMULA render, ragged)
def find_replace(self, spreadsheet_id, range="", find="", replacement="", match_case=False, match_entire_cell=False, search_by_regex=False, include_formulas=False, all_sheets=False): ...
def edit_cell(self, spreadsheet_id, cell, operation, find=None, replacement=None, position=None, length=None, text=None, count=None): ...
def transform_text(self, spreadsheet_id, range, transform): ...
def regex_replace(self, spreadsheet_id, range, pattern, replacement, count=0, ignore_case=False): ...
def split_column(self, spreadsheet_id, range, delimiter, max_splits=-1): ...
def join_columns(self, spreadsheet_id, range, separator=" ", target_range=None): ...
def regex_extract(self, spreadsheet_id, range, pattern, group=0, target_range=None): ...
```

**Run all tests with:** `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py -v`

---

## Task 1: `find_replace` (native FindReplaceRequest)

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py` (add `find_replace` after `read_formulas`, ~line 456)
- Modify: `google_workspace_mcp/sheets/server.py` (add tool in new TEXT EDITING section)
- Test: `tests/test_sheets_server.py` (new `TestSheetsAPITextEditing` class + server tool test)

- [ ] **Step 1: Write the failing API tests**

Add to `tests/test_sheets_server.py` (after the `TestSheetsAPIDimensions` class, before the server-integration section comment):

```python
class TestSheetsAPITextEditing:
    """Unit tests for within-cell / text-granular editing methods."""

    def test_find_replace_range_scope(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().get.return_value.execute.return_value = {
            "sheets": [{"properties": {"sheetId": 7, "title": "Tab"}}]
        }
        svc.spreadsheets().batchUpdate.return_value.execute.return_value = {
            "replies": [{"findReplace": {"valuesChanged": 2}}]
        }
        api.find_replace("sid", "Tab!A1:C10", find="foo", replacement="bar")
        fr = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"][0]["findReplace"]
        assert fr["find"] == "foo" and fr["replacement"] == "bar"
        assert fr["range"] == {
            "sheetId": 7, "startColumnIndex": 0, "endColumnIndex": 3,
            "startRowIndex": 0, "endRowIndex": 10,
        }
        assert "sheetId" not in fr and "allSheets" not in fr

    def test_find_replace_sheet_scope_bare_title(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().get.return_value.execute.return_value = {
            "sheets": [{"properties": {"sheetId": 7, "title": "Tab"}}]
        }
        svc.spreadsheets().batchUpdate.return_value.execute.return_value = {"replies": [{}]}
        api.find_replace("sid", "Tab", find="x", replacement="y")
        fr = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"][0]["findReplace"]
        assert fr["sheetId"] == 7
        assert "range" not in fr and "allSheets" not in fr

    def test_find_replace_all_sheets(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().batchUpdate.return_value.execute.return_value = {"replies": [{}]}
        api.find_replace("sid", "", find="x", replacement="y", all_sheets=True, search_by_regex=True)
        fr = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"][0]["findReplace"]
        assert fr["allSheets"] is True
        assert fr["searchByRegex"] is True
        assert "range" not in fr and "sheetId" not in fr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v`
Expected: FAIL with `AttributeError: 'SheetsAPI' object has no attribute 'find_replace'`

- [ ] **Step 3: Implement `find_replace`**

In `google_workspace_mcp/sheets/sheets_api.py`, add after `read_formulas` (~line 456):

```python
    # --- text editing ---
    def find_replace(self, spreadsheet_id, range="", find="", replacement="",
                     match_case=False, match_entire_cell=False, search_by_regex=False,
                     include_formulas=False, all_sheets=False):
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
        else:
            meta = self.get_spreadsheet(spreadsheet_id)
            titles = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
            if range and "!" not in range and range in titles:
                fr["sheetId"] = titles[range]
            else:
                _, sheet_id, grid, *_ = self._resolve_a1(spreadsheet_id, range, meta)
                has_cell = any(
                    k in grid for k in ("startRowIndex", "endRowIndex", "startColumnIndex", "endColumnIndex")
                )
                if has_cell:
                    fr["range"] = grid
                else:
                    fr["sheetId"] = sheet_id
        return self._batch(spreadsheet_id, [{"findReplace": fr}])
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the MCP tool wrapper**

In `google_workspace_mcp/sheets/server.py`, add before `def main()` (~line 296):

```python
# --- TEXT EDITING (mutating) tools ---

@register(mcp, mutating=True)
def find_replace(account: str | None = None, spreadsheet_id: str = "", range: str = "", find: str = "", replacement: str = "", match_case: bool = False, match_entire_cell: bool = False, search_by_regex: bool = False, include_formulas: bool = False, all_sheets: bool = False) -> dict:
    """Find & replace text. Scope: all_sheets=True covers the whole spreadsheet; a cell range ('Sheet1!A1:C10') limits to that range; a bare sheet name ('Sheet1') covers that whole sheet. Set replacement='' to delete matches. search_by_regex uses RE2 with a literal replacement (no capture-group substitution; use regex_replace for backreferences)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.find_replace(spreadsheet_id, range, find, replacement, match_case, match_entire_cell, search_by_regex, include_formulas, all_sheets))
    return ok(resolved, data)
```

- [ ] **Step 6: Write the failing server tool test**

Add to `tests/test_sheets_server.py` in the server-integration section (after `test_get_spreadsheet_tool`, ~line 565):

```python
@pytest.mark.anyio
async def test_find_replace_tool(patched_server):
    patched_server.find_replace.return_value = {"replies": [{"findReplace": {"valuesChanged": 2}}]}
    raw = await mcp.call_tool("find_replace", {
        "spreadsheet_id": "sid", "range": "Sheet1!A1:C10",
        "find": "foo", "replacement": "bar",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["replies"][0]["findReplace"]["valuesChanged"] == 2
```

- [ ] **Step 7: Run the server tool test**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::test_find_replace_tool -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/nitai/REPOS/google-workspace-mcp
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add native find_replace tool

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: A1 helpers + `edit_cell` (single-cell, position-precise)

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py` (add `_parse_a1_local`, `_anchor` near A1 helpers; `_assert_single_cell` + `edit_cell` in text-editing section)
- Modify: `google_workspace_mcp/sheets/server.py` (add `edit_cell` tool)
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API tests**

Add to `TestSheetsAPITextEditing`:

```python
    def test_edit_cell_insert(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["hello"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        result = api.edit_cell("sid", "Sheet1!B2", "insert", position=2, text="XX")
        svc.spreadsheets().values().get.assert_called_with(
            spreadsheetId="sid", range="Sheet1!B2", valueRenderOption="FORMULA")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!B2", valueInputOption="USER_ENTERED",
            body={"values": [["heXXllo"]]})
        assert result == {"cell": "Sheet1!B2", "old": "hello", "new": "heXXllo", "changed": True}

    def test_edit_cell_newline(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["line1"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        api.edit_cell("sid", "Sheet1!A1", "newline", text="line2")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!A1", valueInputOption="USER_ENTERED",
            body={"values": [["line1\nline2"]]})

    def test_edit_cell_replace_count(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["a-a-a"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        api.edit_cell("sid", "Sheet1!A1", "replace", find="-", replacement="+", count=1)
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!A1", valueInputOption="USER_ENTERED",
            body={"values": [["a+a-a"]]})

    def test_edit_cell_delete_on_empty_is_noop(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {}
        result = api.edit_cell("sid", "Sheet1!A1", "delete", position=0, length=3)
        svc.spreadsheets().values().update.assert_not_called()
        assert result == {"cell": "Sheet1!A1", "old": "", "new": "", "changed": False}

    def test_edit_cell_edits_formula_text(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["=SUM(A1:A5)"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        api.edit_cell("sid", "Sheet1!B1", "replace", find="A5", replacement="A6")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!B1", valueInputOption="USER_ENTERED",
            body={"values": [["=SUM(A1:A6)"]]})

    def test_edit_cell_rejects_range(self, sheets_api):
        api, _ = sheets_api
        with pytest.raises(ValueError, match="single cell"):
            api.edit_cell("sid", "Sheet1!A1:B2", "append", text="x")

    def test_edit_cell_unknown_operation(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["x"]]}
        with pytest.raises(ValueError, match="operation"):
            api.edit_cell("sid", "Sheet1!A1", "frobnicate", text="x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k edit_cell`
Expected: FAIL with `AttributeError: ... has no attribute 'edit_cell'`

- [ ] **Step 3: Add the A1 helpers**

In `google_workspace_mcp/sheets/sheets_api.py`, add right after `_a1_to_grid_range` (~line 148):

```python
    def _parse_a1_local(self, a1):
        """Parse an A1 string without any API call.
        Returns (sheet_name, start_col, start_row, end_col, end_row) as strings."""
        sheet_name, sep, cell_part = a1.rpartition("!")
        sheet_name = sheet_name.strip("'\"") if sep else ""
        start, _, end = cell_part.partition(":")
        end = end or start

        def split(cell):
            return ("".join(c for c in cell if c.isalpha()),
                    "".join(c for c in cell if c.isdigit()))

        start_col, start_row = split(start)
        end_col, end_row = split(end)
        return sheet_name, start_col, start_row, end_col, end_row

    def _anchor(self, sheet_name, col, row):
        cell = f"{col}{row}"
        return self._quoted_sheet_range(sheet_name, cell) if sheet_name else cell
```

- [ ] **Step 4: Implement `_assert_single_cell` and `edit_cell`**

In the text-editing section of `sheets_api.py` (after `find_replace`):

```python
    def _assert_single_cell(self, cell):
        name, sc, sr, ec, er = self._parse_a1_local(cell)
        if not (sc and sr and sc == ec and sr == er):
            raise ValueError(f"edit_cell expects a single cell like 'Sheet1!B2', got {cell!r}")

    def edit_cell(self, spreadsheet_id, cell, operation, find=None, replacement=None,
                  position=None, length=None, text=None, count=None):
        self._assert_single_cell(cell)
        resp = self.read_range(spreadsheet_id, cell, value_render_option="FORMULA")
        values = resp.get("values") or []
        raw = values[0][0] if (values and values[0]) else ""
        old = "" if raw is None else str(raw)

        if operation == "replace":
            if find is None:
                raise ValueError("edit_cell 'replace' requires 'find'")
            new = old.replace(find, replacement or "", -1 if count is None else count)
        elif operation == "insert":
            if position is None or text is None:
                raise ValueError("edit_cell 'insert' requires 'position' and 'text'")
            pos = max(0, min(position, len(old)))
            new = old[:pos] + text + old[pos:]
        elif operation == "delete":
            if position is None or length is None:
                raise ValueError("edit_cell 'delete' requires 'position' and 'length'")
            pos = max(0, min(position, len(old)))
            new = old[:pos] + old[pos + max(0, length):]
        elif operation == "append":
            if text is None:
                raise ValueError("edit_cell 'append' requires 'text'")
            new = old + text
        elif operation == "prepend":
            if text is None:
                raise ValueError("edit_cell 'prepend' requires 'text'")
            new = text + old
        elif operation == "newline":
            new = old + "\n" + (text or "")
        else:
            raise ValueError(
                "edit_cell operation must be one of "
                "replace/insert/delete/append/prepend/newline"
            )

        changed = new != old
        if changed:
            self.update_range(spreadsheet_id, cell, [[new]], "USER_ENTERED")
        return {"cell": cell, "old": old, "new": new, "changed": changed}
```

- [ ] **Step 5: Run the API tests to verify they pass**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k edit_cell`
Expected: PASS (7 tests)

- [ ] **Step 6: Add the MCP tool wrapper**

In `server.py`, in the TEXT EDITING section (after `find_replace`):

```python
@register(mcp, mutating=True)
def edit_cell(account: str | None = None, spreadsheet_id: str = "", cell: str = "", operation: str = "", find: str | None = None, replacement: str | None = None, position: int | None = None, length: int | None = None, text: str | None = None, count: int | None = None) -> dict:
    """Edit the text of a single cell in place. operation is one of replace/insert/delete/append/prepend/newline. Reads the cell's literal text (the formula string for formula cells), applies the edit, writes it back. 'newline' adds an in-cell line break (pair with format_cells wrap=True). Returns {cell, old, new, changed}."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.edit_cell(spreadsheet_id, cell, operation, find, replacement, position, length, text, count))
    return ok(resolved, data)
```

- [ ] **Step 7: Write and run the server tool test**

Add to the server-integration section:

```python
@pytest.mark.anyio
async def test_edit_cell_tool(patched_server):
    patched_server.edit_cell.return_value = {"cell": "Sheet1!A1", "old": "hi", "new": "hi!", "changed": True}
    raw = await mcp.call_tool("edit_cell", {
        "spreadsheet_id": "sid", "cell": "Sheet1!A1", "operation": "append", "text": "!",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["new"] == "hi!"
```

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::test_edit_cell_tool -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/nitai/REPOS/google-workspace-mcp
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add edit_cell for single-cell position-precise text edits

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `transform_text` (bulk case/trim across a range)

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py` (add `import re`, `_read_text_grid`, `transform_text`)
- Modify: `google_workspace_mcp/sheets/server.py` (add `transform_text` tool)
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API tests**

Add to `TestSheetsAPITextEditing`:

```python
    def test_transform_text_upper_skips_formula_and_numbers(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {
            "values": [["abc", "=SUM(A1:A2)"], [5, "def"]]
        }
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 4}
        api.transform_text("sid", "Sheet1!A1:B2", "upper")
        svc.spreadsheets().values().get.assert_called_with(
            spreadsheetId="sid", range="Sheet1!A1:B2", valueRenderOption="FORMULA")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!A1:B2", valueInputOption="USER_ENTERED",
            body={"values": [["ABC", "=SUM(A1:A2)"], [5, "DEF"]]})

    def test_transform_text_collapse_spaces(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["  a   b  "]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        api.transform_text("sid", "Sheet1!A1", "collapse_spaces")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!A1", valueInputOption="USER_ENTERED",
            body={"values": [["a b"]]})

    def test_transform_text_unknown(self, sheets_api):
        api, _ = sheets_api
        with pytest.raises(ValueError, match="transform"):
            api.transform_text("sid", "Sheet1!A1", "sideways")

    def test_transform_text_empty_range_noop(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {}
        result = api.transform_text("sid", "Sheet1!A1:B2", "upper")
        svc.spreadsheets().values().update.assert_not_called()
        assert result == {"updatedCells": 0}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k transform`
Expected: FAIL with `AttributeError: ... has no attribute 'transform_text'`

- [ ] **Step 3: Add `import re` and implement `_read_text_grid` + `transform_text`**

At the top of `sheets_api.py`, add `import re` (after `from __future__ import annotations`):

```python
from __future__ import annotations

import re

import google_auth_core as core
from google.auth.transport.requests import Request as GoogleAuthRequest
```

In the text-editing section, add:

```python
    def _read_text_grid(self, spreadsheet_id, range):
        resp = self.read_range(spreadsheet_id, range, value_render_option="FORMULA")
        return resp.get("values") or []

    def transform_text(self, spreadsheet_id, range, transform):
        funcs = {
            "upper": str.upper,
            "lower": str.lower,
            "title": str.title,
            "capitalize": str.capitalize,
            "trim": str.strip,
            "collapse_spaces": lambda s: re.sub(r"\s+", " ", s).strip(),
        }
        if transform not in funcs:
            raise ValueError(f"transform must be one of {sorted(funcs)}")
        fn = funcs[transform]
        grid = self._read_text_grid(spreadsheet_id, range)
        out = [
            [fn(cell) if (isinstance(cell, str) and not cell.startswith("=")) else cell for cell in row]
            for row in grid
        ]
        if not out:
            return {"updatedCells": 0}
        return self.update_range(spreadsheet_id, range, out, "USER_ENTERED")
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k transform`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the MCP tool wrapper**

In `server.py` TEXT EDITING section (after `edit_cell`):

```python
@register(mcp, mutating=True)
def transform_text(account: str | None = None, spreadsheet_id: str = "", range: str = "", transform: str = "") -> dict:
    """Bulk text transform across a range: upper/lower/title/capitalize/trim/collapse_spaces. Transforms literal text only; cells holding a formula ('=...') and numbers are left unchanged."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.transform_text(spreadsheet_id, range, transform))
    return ok(resolved, data)
```

- [ ] **Step 6: Write and run the server tool test**

Add to the server-integration section:

```python
@pytest.mark.anyio
async def test_transform_text_tool(patched_server):
    patched_server.transform_text.return_value = {"updatedCells": 2}
    raw = await mcp.call_tool("transform_text", {
        "spreadsheet_id": "sid", "range": "Sheet1!A1:A2", "transform": "upper",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["updatedCells"] == 2
```

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::test_transform_text_tool -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/nitai/REPOS/google-workspace-mcp
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add transform_text for bulk case/trim across a range

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `regex_replace` (Python re with backreferences)

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py` (add `regex_replace`)
- Modify: `google_workspace_mcp/sheets/server.py` (add `regex_replace` tool)
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API tests**

Add to `TestSheetsAPITextEditing`:

```python
    def test_regex_replace_backref(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["John Smith"], ["=A1"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 2}
        api.regex_replace("sid", "Sheet1!A1:A2", r"(\w+) (\w+)", r"\2 \1")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!A1:A2", valueInputOption="USER_ENTERED",
            body={"values": [["Smith John"], ["=A1"]]})

    def test_regex_replace_ignore_case(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["FooFOO"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        api.regex_replace("sid", "Sheet1!A1", "foo", "x", ignore_case=True)
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!A1", valueInputOption="USER_ENTERED",
            body={"values": [["xx"]]})

    def test_regex_replace_invalid_pattern(self, sheets_api):
        api, _ = sheets_api
        with pytest.raises(ValueError, match="invalid regex"):
            api.regex_replace("sid", "Sheet1!A1", "(", "x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k regex_replace`
Expected: FAIL with `AttributeError: ... has no attribute 'regex_replace'`

- [ ] **Step 3: Implement `regex_replace`**

In the text-editing section of `sheets_api.py`:

```python
    def regex_replace(self, spreadsheet_id, range, pattern, replacement, count=0, ignore_case=False):
        try:
            rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}")
        grid = self._read_text_grid(spreadsheet_id, range)
        out = [
            [rx.sub(replacement, cell, count=count) if (isinstance(cell, str) and not cell.startswith("=")) else cell
             for cell in row]
            for row in grid
        ]
        if not out:
            return {"updatedCells": 0}
        return self.update_range(spreadsheet_id, range, out, "USER_ENTERED")
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k regex_replace`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the MCP tool wrapper**

In `server.py` TEXT EDITING section (after `transform_text`):

```python
@register(mcp, mutating=True)
def regex_replace(account: str | None = None, spreadsheet_id: str = "", range: str = "", pattern: str = "", replacement: str = "", count: int = 0, ignore_case: bool = False) -> dict:
    r"""Regex find/replace across a range using Python re. Supports \1 / \g<name> backreferences (unlike native find_replace). count=0 replaces all matches in each cell. Cells holding a formula ('=...') are skipped."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.regex_replace(spreadsheet_id, range, pattern, replacement, count, ignore_case))
    return ok(resolved, data)
```

- [ ] **Step 6: Write and run the server tool test**

Add to the server-integration section:

```python
@pytest.mark.anyio
async def test_regex_replace_tool(patched_server):
    patched_server.regex_replace.return_value = {"updatedCells": 1}
    raw = await mcp.call_tool("regex_replace", {
        "spreadsheet_id": "sid", "range": "Sheet1!A1", "pattern": r"(\w+)", "replacement": r"\1!",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["updatedCells"] == 1
```

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::test_regex_replace_tool -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/nitai/REPOS/google-workspace-mcp
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add regex_replace with backreference support

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `split_column` (split text to columns)

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py` (add `_assert_single_column`, `split_column`)
- Modify: `google_workspace_mcp/sheets/server.py` (add `split_column` tool)
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API tests**

Add to `TestSheetsAPITextEditing`:

```python
    def test_split_column(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["a,b,c"], ["d,e"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 5}
        api.split_column("sid", "Sheet1!A1:A2", ",")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="'Sheet1'!A1", valueInputOption="USER_ENTERED",
            body={"values": [["a", "b", "c"], ["d", "e", ""]]})

    def test_split_column_no_sheet_prefix(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["x|y"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 2}
        api.split_column("sid", "A1:A1", "|")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="A1", valueInputOption="USER_ENTERED",
            body={"values": [["x", "y"]]})

    def test_split_column_rejects_multi_column(self, sheets_api):
        api, _ = sheets_api
        with pytest.raises(ValueError, match="single column"):
            api.split_column("sid", "Sheet1!A1:B2", ",")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k split_column`
Expected: FAIL with `AttributeError: ... has no attribute 'split_column'`

- [ ] **Step 3: Implement `_assert_single_column` + `split_column`**

In the text-editing section of `sheets_api.py`:

```python
    def _assert_single_column(self, range, op):
        name, sc, sr, ec, er = self._parse_a1_local(range)
        if not (sc and sc == ec):
            raise ValueError(f"{op} expects a single column like 'Sheet1!A1:A20', got {range!r}")
        return name, sc, sr

    def split_column(self, spreadsheet_id, range, delimiter, max_splits=-1):
        sheet_name, start_col, start_row = self._assert_single_column(range, "split_column")
        grid = self._read_text_grid(spreadsheet_id, range)
        rows = []
        width = 1
        for row in grid:
            cell = row[0] if row else ""
            s = cell if isinstance(cell, str) else str(cell)
            parts = s.split(delimiter, max_splits) if s != "" else [""]
            width = max(width, len(parts))
            rows.append(parts)
        out = [r + [""] * (width - len(r)) for r in rows]
        if not out:
            return {"updatedCells": 0}
        anchor = self._anchor(sheet_name, start_col, start_row)
        return self.update_range(spreadsheet_id, anchor, out, "USER_ENTERED")
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k split_column`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the MCP tool wrapper**

In `server.py` TEXT EDITING section (after `regex_replace`):

```python
@register(mcp, mutating=True, destructive=True)
def split_column(account: str | None = None, spreadsheet_id: str = "", range: str = "", delimiter: str = "", max_splits: int = -1) -> dict:
    """Split a single column's cells by a delimiter into adjacent columns (like Sheets 'Split text to columns'). OVERWRITES columns to the right of the source column. max_splits=-1 means no limit."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.split_column(spreadsheet_id, range, delimiter, max_splits))
    return ok(resolved, data)
```

- [ ] **Step 6: Write and run the server tool test**

Add to the server-integration section:

```python
@pytest.mark.anyio
async def test_split_column_tool(patched_server):
    patched_server.split_column.return_value = {"updatedCells": 4}
    raw = await mcp.call_tool("split_column", {
        "spreadsheet_id": "sid", "range": "Sheet1!A1:A2", "delimiter": ",",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["updatedCells"] == 4
```

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::test_split_column_tool -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/nitai/REPOS/google-workspace-mcp
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add split_column for splitting text to columns

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `join_columns` (concatenate columns into one)

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py` (add `join_columns`)
- Modify: `google_workspace_mcp/sheets/server.py` (add `join_columns` tool)
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API tests**

Add to `TestSheetsAPITextEditing`:

```python
    def test_join_columns_default_target(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["John", "Smith"], ["Jane", ""]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 2}
        api.join_columns("sid", "Sheet1!A1:B2", separator=" ")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="'Sheet1'!A1", valueInputOption="USER_ENTERED",
            body={"values": [["John Smith"], ["Jane"]]})

    def test_join_columns_explicit_target(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["a", "b", "c"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        api.join_columns("sid", "Sheet1!A1:C1", separator="-", target_range="Sheet1!E1")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!E1", valueInputOption="USER_ENTERED",
            body={"values": [["a-b-c"]]})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k join_columns`
Expected: FAIL with `AttributeError: ... has no attribute 'join_columns'`

- [ ] **Step 3: Implement `join_columns`**

In the text-editing section of `sheets_api.py`:

```python
    def join_columns(self, spreadsheet_id, range, separator=" ", target_range=None):
        sheet_name, start_col, start_row, _, _ = self._parse_a1_local(range)
        grid = self._read_text_grid(spreadsheet_id, range)
        out = []
        for row in grid:
            parts = [(c if isinstance(c, str) else str(c)) for c in row]
            parts = [p for p in parts if p != ""]
            out.append([separator.join(parts)])
        if not out:
            return {"updatedCells": 0}
        target = target_range or self._anchor(sheet_name, start_col, start_row)
        return self.update_range(spreadsheet_id, target, out, "USER_ENTERED")
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k join_columns`
Expected: PASS (2 tests)

- [ ] **Step 5: Add the MCP tool wrapper**

In `server.py` TEXT EDITING section (after `split_column`):

```python
@register(mcp, mutating=True)
def join_columns(account: str | None = None, spreadsheet_id: str = "", range: str = "", separator: str = " ", target_range: str | None = None) -> dict:
    """Join each row of a multi-column range into one string (separator placed between non-empty cells) and write it to target_range. target_range defaults to the range's first column (overwriting it)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.join_columns(spreadsheet_id, range, separator, target_range))
    return ok(resolved, data)
```

- [ ] **Step 6: Write and run the server tool test**

Add to the server-integration section:

```python
@pytest.mark.anyio
async def test_join_columns_tool(patched_server):
    patched_server.join_columns.return_value = {"updatedCells": 2}
    raw = await mcp.call_tool("join_columns", {
        "spreadsheet_id": "sid", "range": "Sheet1!A1:B2", "separator": " ",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["updatedCells"] == 2
```

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::test_join_columns_tool -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/nitai/REPOS/google-workspace-mcp
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add join_columns to concatenate columns into one

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `regex_extract` (pull match/group into a target column)

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py` (add `regex_extract`)
- Modify: `google_workspace_mcp/sheets/server.py` (add `regex_extract` tool)
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API tests**

Add to `TestSheetsAPITextEditing`:

```python
    def test_regex_extract_group_to_target(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["Order #123"], ["nope"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 2}
        api.regex_extract("sid", "Sheet1!A1:A2", r"#(\d+)", group=1, target_range="Sheet1!B1")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="Sheet1!B1", valueInputOption="USER_ENTERED",
            body={"values": [["123"], [""]]})

    def test_regex_extract_default_target_in_place(self, sheets_api):
        api, svc = sheets_api
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["abc123"]]}
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 1}
        api.regex_extract("sid", "Sheet1!A1", r"\d+")
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="'Sheet1'!A1", valueInputOption="USER_ENTERED",
            body={"values": [["123"]]})

    def test_regex_extract_rejects_multi_column(self, sheets_api):
        api, _ = sheets_api
        with pytest.raises(ValueError, match="single column"):
            api.regex_extract("sid", "Sheet1!A1:B2", r"\d+")

    def test_regex_extract_invalid_pattern(self, sheets_api):
        api, _ = sheets_api
        with pytest.raises(ValueError, match="invalid regex"):
            api.regex_extract("sid", "Sheet1!A1", "(")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k regex_extract`
Expected: FAIL with `AttributeError: ... has no attribute 'regex_extract'`

- [ ] **Step 3: Implement `regex_extract`**

In the text-editing section of `sheets_api.py`:

```python
    def regex_extract(self, spreadsheet_id, range, pattern, group=0, target_range=None):
        sheet_name, start_col, start_row = self._assert_single_column(range, "regex_extract")
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}")
        grid = self._read_text_grid(spreadsheet_id, range)
        out = []
        for row in grid:
            cell = row[0] if row else ""
            s = cell if isinstance(cell, str) else str(cell)
            m = rx.search(s)
            out.append([m.group(group) if m else ""])
        if not out:
            return {"updatedCells": 0}
        target = target_range or self._anchor(sheet_name, start_col, start_row)
        return self.update_range(spreadsheet_id, target, out, "USER_ENTERED")
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::TestSheetsAPITextEditing -v -k regex_extract`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the MCP tool wrapper**

In `server.py` TEXT EDITING section (after `join_columns`):

```python
@register(mcp, mutating=True)
def regex_extract(account: str | None = None, spreadsheet_id: str = "", range: str = "", pattern: str = "", group: int = 0, target_range: str | None = None) -> dict:
    """Extract the first regex match (or a capture group) from each cell in a single column into target_range. group=0 is the whole match. target_range defaults in-place (overwriting the source column). Non-matching cells become ''."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.regex_extract(spreadsheet_id, range, pattern, group, target_range))
    return ok(resolved, data)
```

- [ ] **Step 6: Write and run the server tool test**

Add to the server-integration section:

```python
@pytest.mark.anyio
async def test_regex_extract_tool(patched_server):
    patched_server.regex_extract.return_value = {"updatedCells": 2}
    raw = await mcp.call_tool("regex_extract", {
        "spreadsheet_id": "sid", "range": "Sheet1!A1:A2", "pattern": r"\d+", "target_range": "Sheet1!B1",
    })
    result = _parse_result(raw)
    assert result["ok"] is True
    assert result["data"]["updatedCells"] == 2
```

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::test_regex_extract_tool -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/nitai/REPOS/google-workspace-mcp
git add google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py tests/test_sheets_server.py
git commit -m "sheets: add regex_extract to pull matches into a target column

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Register tools in the list-tools test + live smoke test

**Files:**
- Modify: `tests/test_sheets_server.py` (`test_list_tools_includes_expected`)
- Modify: `tests/live_sheets_formatting.py`

- [ ] **Step 1: Extend the list-tools expectation (failing first)**

In `tests/test_sheets_server.py`, in `test_list_tools_includes_expected`, add the new names to the `expected` set. Change the block that ends with `"add_table", "format_table", "read_formulas", "write_formulas",` to also include:

```python
        "add_table", "format_table", "read_formulas", "write_formulas",
        # text editing
        "find_replace", "edit_cell", "transform_text", "regex_replace",
        "split_column", "join_columns", "regex_extract",
```

- [ ] **Step 2: Run the list-tools test**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py::test_list_tools_includes_expected -v`
Expected: PASS (all 7 new tools are registered from Tasks 1-7; if any are missing, the assertion message names them)

- [ ] **Step 3: Add a live smoke section**

In `tests/live_sheets_formatting.py`, add a new block inside the `try:` body, after step 12 (the wrap-text block at ~line 123) and before the `except Exception` (~line 125):

```python
        print("\n13. find_replace (replace 'Active' -> 'Open' in column C)")
        api.find_replace(sheet_id, "Sheet1!A1:D5", find="Active", replacement="Open")
        after = api.read_range(sheet_id, "Sheet1!C2")
        check("find_replace changed C2 to Open", after.get("values", [[""]])[0][0] == "Open")

        print("\n14. edit_cell (append + newline on A1)")
        api.edit_cell(sheet_id, "Sheet1!A1", "append", text=" (edited)")
        api.edit_cell(sheet_id, "Sheet1!A1", "newline", text="line2")
        a1 = api.read_range(sheet_id, "Sheet1!A1")
        check("edit_cell produced multi-line A1", "line2" in a1.get("values", [[""]])[0][0])

        print("\n15. transform_text (upper-case the Status column)")
        api.transform_text(sheet_id, "Sheet1!C2:C5", "upper")
        c = api.read_range(sheet_id, "Sheet1!C2:C5")
        vals = [r[0] for r in c.get("values", []) if r]
        check("transform_text upper-cased Status", all(v == v.upper() for v in vals))
```

- [ ] **Step 4: Run the full unit suite**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/pytest tests/test_sheets_server.py -v`
Expected: PASS (all existing tests + ~26 new API tests + 7 new tool tests + updated list-tools test)

- [ ] **Step 5: (Optional, requires real credentials) Run the live smoke test**

Run: `cd /Users/nitai/REPOS/google-workspace-mcp && .venv/bin/python tests/live_sheets_formatting.py`
Expected: `PASSED: <n>  FAILED: 0`, scratch spreadsheet auto-deleted. Skip if no live Google account is configured for the test `ACCOUNT`.

- [ ] **Step 6: Commit**

```bash
cd /Users/nitai/REPOS/google-workspace-mcp
git add tests/test_sheets_server.py tests/live_sheets_formatting.py
git commit -m "test: register text-editing tools in list-tools test + live smoke

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **A1 quoting:** `_anchor` returns a quoted reference (`'Sheet1'!A1`) only when the range carried a sheet name; a bare range (`A1:A1`) yields a bare anchor (`A1`). Tests assert the exact strings — `'Sheet1'!A1` for `split_column`/`join_columns`/`regex_extract` default targets, `A1` when no sheet prefix.
- **FORMULA render:** reading with `value_render_option="FORMULA"` returns numbers as `int`/`float` (left untouched by the bulk tools) and formula cells as their `=...` string. `edit_cell` deliberately treats that formula string as editable text; the bulk tools (`transform_text`, `regex_replace`, `regex_extract` on the source value) skip cells whose value starts with `=`.
- **`str.replace` count:** Python replaces all occurrences when count is negative, so `edit_cell` maps `count=None` to `-1` (replace all).
- **No metadata fetch on RMW tools:** `edit_cell` and the Tier-3 tools parse A1 locally via `_parse_a1_local`; only `find_replace` calls `get_spreadsheet` (it needs the `sheetId` for scope).
- The repo uses an editable install (`.venv`), so no reinstall is needed between tasks — code changes are picked up directly by `pytest`.
