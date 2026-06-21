# Sheets MCP: complete content-editing surface

Date: 2026-06-21
Status: Approved (pending spec review)

## Problem

The Google Sheets MCP already edits existing content broadly (`update_range`,
`batch_update_values`, `append_rows`, `clear_range`, `delete_rows/columns`,
`insert_rows/columns`, formatting, banding, filters). But several common
"edit existing content" operations are missing entirely, and there is no
end-to-end verification that the full edit surface works against a real sheet.

Concretely missing:

1. **Find & replace** — no way to replace text across a range/sheet/spreadsheet.
2. **Copy/paste and cut/paste** — no way to move or duplicate cell content,
   formats, or formulas within or across sheets.
3. **Hide / unhide columns and rows** — `resize_columns`/`resize_rows` can only
   collapse a column to a few pixels; there is no true `hiddenByUser` hide.
4. **Delete a native table** — `add_table` creates one but nothing removes it.
5. **Edit a native table's settings** — no way to rename, resize, recolor, or
   set per-column name/type/dropdown on an existing native table.

## Goals

- Add the seven missing tools listed below (plus shared API helpers), following
  existing `sheets_api.py` patterns (`_a1_to_grid_range`, `_batch`,
  `_dimension_range`, `_banding_properties`).
- Verify the entire content-editing surface (existing + new) against a live
  scratch spreadsheet via a new integration test, reading back results and
  asserting. Any existing op that fails read-back is treated as a gap and fixed.
- Unit-test every new API method and server tool for exact request shape,
  matching the conventions already in `tests/test_sheets_server.py`.

## Non-goals (YAGNI)

`pasteData` (CSV/TSV import), `autoFill`, `deleteDuplicates`, `trimWhitespace`,
`textToColumns`, single-cell convenience wrappers (`update_range` covers it).
Not building these unless requested later.

## Design

### New API methods (`google_workspace_mcp/sheets/sheets_api.py`)

All new methods reuse existing helpers and go through `_batch`.

#### 1. `find_replace`

```
find_replace(spreadsheet_id, find, replacement, range=None, all_sheets=False,
             match_case=False, match_entire_cell=False, search_by_regex=False,
             include_formulas=False)
```

Builds a single `findReplace` request. Scope is exactly one of:

- `range` with a cell part (e.g. `Sheet1!A1:C9`) → `range` = `GridRange`.
- `range` as a bare sheet name (e.g. `Sheet1`, no `!` and no cell part) →
  resolve to `sheetId` and use the `sheetId` scope.
- `all_sheets=True` → `allSheets: true`.
- Neither `range` nor `all_sheets` → `ValueError`.

Request fields: `find`, `replacement`, `matchCase`, `matchEntireCell`,
`searchByRegex`, `includeFormulas`. Returns the `findReplace` reply
(`occurrencesChanged`, `valuesChanged`, `rowsChanged`, `sheetsChanged`,
`formulasChanged`).

Scope helper: a small branch inside `find_replace`. Bare-sheet detection: split
the A1 on `!`; if there is no `!` and the token has no digits, treat it as a
sheet name and resolve via the existing metadata lookup used by `_resolve_a1`.

#### 2. `copy_paste`

```
copy_paste(spreadsheet_id, source_range, destination_range,
           paste_type="PASTE_NORMAL", transpose=False)
```

Builds a `copyPaste` request: `source` and `destination` both via
`_a1_to_grid_range` (cross-sheet works because the A1 carries the sheet name).
`pasteType` = `paste_type`; `pasteOrientation` = `TRANSPOSE` if `transpose` else
`NORMAL`.

#### 3. `cut_paste`

```
cut_paste(spreadsheet_id, source_range, destination, paste_type="PASTE_NORMAL")
```

Builds a `cutPaste` request: `source` = `_a1_to_grid_range`, `destination` =
single anchor `GridCoordinate` via a new helper `_a1_to_grid_coordinate`
(`{sheetId, rowIndex, columnIndex}` from a single-cell A1). `pasteType` =
`paste_type`. Clears the source.

`paste_type` (used by both paste ops) accepts the Sheets enum: `PASTE_NORMAL`,
`PASTE_VALUES`, `PASTE_FORMAT`, `PASTE_NO_BORDERS`, `PASTE_FORMULA`,
`PASTE_DATA_VALIDATION`, `PASTE_CONDITIONAL_FORMATTING`.

#### 4. `set_dimension_visibility`

```
set_dimension_visibility(spreadsheet_id, range, dimension, hidden)
```

Joins the existing dimensions family (`resize_dimension`, `insert_dimension`,
`delete_dimension`). Uses `_dimension_range` then an `updateDimensionProperties`
request with `properties={"hiddenByUser": hidden}`, `fields="hiddenByUser"`.
`dimension` is `"COLUMNS"` or `"ROWS"`.

#### 5. `delete_table`

```
delete_table(spreadsheet_id, table_id)
```

`{"deleteTable": {"tableId": table_id}}` through `_batch`.

#### 6. `update_table`

```
update_table(spreadsheet_id, table_id, name=None, range=None,
             header_color=None, first_band_color=None, second_band_color=None,
             footer_color=None, column_properties=None)
```

Builds an `updateTable` request with a `fields` mask containing only the
provided args:

- `name` → `table.name`, field `name`.
- `range` (A1) → `table.range` = `_a1_to_grid_range`, field `range`.
- any of the four colors → `table.rowsProperties` via the existing
  `_banding_properties(header, first, second, footer)` (same `*ColorStyle`
  keys), field `rowsProperties`. Only called when at least one color is given.
- `column_properties` → `table.columnProperties` via new helper
  `_build_table_columns`, field `columnProperties`.

`_build_table_columns(specs)` maps each spec dict to a `TableColumnProperties`:

- `column_index` → `columnIndex` (required).
- `column_name` → `columnName` (optional).
- `column_type` → `columnType` (optional; Sheets table column enum, e.g.
  `TEXT`, `DOUBLE`, `PERCENT`, `DATE`, `BOOLEAN`, `DROPDOWN`).
- `values` (optional) → `dataValidationRule.condition` =
  `{type: "ONE_OF_LIST", values: [{userEnteredValue: str(v)}, ...]}`.

Raises `ValueError` if no updatable field is provided.

### New server tools (`google_workspace_mcp/sheets/server.py`)

Thin wrappers in the existing style (`api, resolved = _api(account)`,
`run_tool(...)`, `ok(resolved, data)`):

| Tool | Decorator | Notes |
|------|-----------|-------|
| `find_replace` | `mutating=True` | scope via `range`/bare-sheet/`all_sheets` |
| `copy_paste` | `mutating=True` | overwrites destination |
| `cut_paste` | `mutating=True, destructive=True` | clears source |
| `hide_columns` | `mutating=True` | `hidden=True` default; `hidden=False` unhides; calls `set_dimension_visibility(..., "COLUMNS", hidden)` |
| `hide_rows` | `mutating=True` | same for `"ROWS"` |
| `delete_table` | `mutating=True, destructive=True` | `table_id` from `add_table` reply or `get_spreadsheet` |
| `update_table` | `mutating=True` | rename/resize/recolor/columns |

Docstrings state where IDs come from and that `hidden=False` unhides.

### README

Add the seven new tools to the Sheets tool list in `README.md`.

## Testing

### Unit (`tests/test_sheets_server.py`)

Add cases (mock `google_auth_core.get_service`, assert exact request body):

- `find_replace`: the three scope branches (cell range → `range`; bare sheet →
  `sheetId`; `all_sheets=True` → `allSheets`), and a regex/match-case variant.
- `copy_paste`: normal and `transpose=True`; a non-default `paste_type`.
- `cut_paste`: `cutPaste` body with `GridCoordinate` destination.
- `set_dimension_visibility`: `COLUMNS` and `ROWS`, `hidden` true and false.
- `delete_table`: `deleteTable` body.
- `update_table`: name-only mask; range; recolor; `column_properties` with and
  without `values` (dropdown); `ValueError` when nothing to update.
- A couple of server-tool wrapper tests matching the existing style.

### Live audit (`tests/live_sheets_editing.py`)

New file mirroring `tests/live_sheets_formatting.py` (scratch spreadsheet,
`check()` helper, Drive-delete cleanup, `ACCOUNT = "aviv.joels@gmail.com"`).
Drives the full content-CRUD surface and verifies by read-back:

1. `update_range` → `batch_update_values` → `append_rows` → read back values.
2. `clear_range` → assert cells empty.
3. `insert_rows`/`insert_columns` → `delete_rows`/`delete_columns` → assert
   shifts via read-back.
4. `find_replace`: range scope, whole-sheet scope, and a regex replace → assert
   `occurrencesChanged` and read-back values.
5. `copy_paste` (`PASTE_VALUES` vs `PASTE_NORMAL`) and `cut_paste` → assert
   destination populated and (for cut) source cleared.
6. `hide_columns` → assert `hiddenByUser` true via `get_spreadsheet`; unhide
   (`hidden=False`) → assert cleared. Same spot-check for `hide_rows`.
7. `add_table` → `update_table` (rename, recolor, set a `DROPDOWN` column) →
   read back the sheet's `tables` and assert `name`, `rowsProperties`, and
   `columnProperties` changed → `delete_table` → assert `tables` empty.
8. `merge_cells`/`unmerge_cells`, `set_data_validation`, `duplicate_sheet`,
   `sort_range` exercised and spot-checked (audit coverage for existing ops not
   already covered by `live_sheets_formatting.py`).

A failing read-back assertion on any existing op is a gap to fix as part of this
work.

## Risks / notes

- Native table support (`addTable`/`updateTable`/`deleteTable`, `tables` in
  sheet metadata) is relatively new in the Sheets API; the live audit is what
  confirms it behaves as specified for this account.
- `cut_paste` and `delete_table` are destructive; both are marked
  `destructive=True` so the harness can gate them.
- `find_replace` bare-sheet scope depends on detecting "no cell part"; the unit
  tests pin all three scope branches so the detection logic stays correct.
