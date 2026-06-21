# Google Sheets text-editing tools — design

**Date:** 2026-06-21
**Status:** Approved, pending implementation
**Author:** nitai (+ Claude)

## Goal

The Sheets MCP can write and overwrite whole cells, but it cannot do
*within-cell* / *text-granular* editing. Add tools so an agent can:

- find & replace words/characters across a range, sheet, or whole spreadsheet
- edit a single cell surgically: insert at a character position, delete a
  character span, replace a substring, append, prepend, add a line break
- bulk-transform text in a range (case, trim) and run regex replace/extract
- split one column into many, or join many columns into one

Everything follows the existing service pattern exactly: a method on
`SheetsAPI` (`google_workspace_mcp/sheets/sheets_api.py`) plus a thin
`@register`-decorated wrapper in `google_workspace_mcp/sheets/server.py`. A1
ranges throughout. No changes to `core/`, scopes, or auth — these are pure
additions on the existing Sheets surface.

## Scope of this spec (all three tiers)

| Tier | Tool | Mechanism |
|---|---|---|
| 1 | `find_replace` | native `FindReplaceRequest` (server-side, atomic) |
| 2 | `edit_cell` | single-cell read-modify-write |
| 3 | `transform_text` | range read-modify-write (case/trim) |
| 3 | `regex_replace` | range read-modify-write, Python `re` (backref support) |
| 3 | `split_column` | range read → write multiple columns |
| 3 | `join_columns` | range read → write one column |
| 3 | `regex_extract` | range read → write extracted values to a target |

## Tier 1 — `find_replace` (native)

The Sheets API v4 has a native `FindReplaceRequest` inside `batchUpdate`. One
round-trip, server-side, no read-modify-write race.

### API method

```python
def find_replace(self, spreadsheet_id, range="", find="", replacement="",
                 match_case=False, match_entire_cell=False,
                 search_by_regex=False, include_formulas=False,
                 all_sheets=False):
```

Builds one request:

```python
{"findReplace": {
    "find": find,
    "replacement": replacement,
    "matchCase": match_case,
    "matchEntireCell": match_entire_cell,
    "searchByRegex": search_by_regex,
    "includeFormulas": include_formulas,
    # exactly one scope key, resolved below
}}
```

**Scope resolution** (the request requires exactly one of `range` / `sheetId` /
`allSheets`):

1. `all_sheets=True` → `"allSheets": True` (the `range` arg is ignored).
2. else if `range` has a cell part (e.g. `Sheet1!A1:C10`) → `"range": grid`
   via `_a1_to_grid_range`.
3. else (bare sheet name `Sheet1`, or `Sheet1!`, or empty) → `"sheetId":
   <id>` for that sheet via `_resolve_a1`. Empty `range` with `all_sheets=False`
   defaults to the first sheet's id.

Returns the native reply `findReplace` object: `valuesChanged`,
`occurrencesChanged`, `rowsChanged`, `sheetsChanged`, `formulasChanged`.

### MCP tool

```python
@register(mcp, mutating=True)
def find_replace(account=None, spreadsheet_id="", range="", find="",
                 replacement="", match_case=False, match_entire_cell=False,
                 search_by_regex=False, include_formulas=False,
                 all_sheets=False) -> dict:
    """Find & replace text across a range, a whole sheet, or all sheets.
    Scope: all_sheets=True covers everything; a cell range (Sheet1!A1:C10)
    limits to that range; a bare sheet name covers the whole sheet. Set
    replacement='' to delete matches. search_by_regex uses RE2 with a literal
    replacement (no capture-group substitution — use regex_replace for that)."""
```

**Note on regex:** native `search_by_regex` matches with RE2 but the
replacement is **literal** — `$1`/`\1` capture references are not substituted.
The Tier-3 `regex_replace` tool fills that gap.

## Tier 2 — `edit_cell` (single cell, position-precise)

For edits the native API can't express: insert at a character index, delete a
character span, splice. Operates on **one cell**.

### Read/write semantics

- Read the cell's literal entered text with `read_range(..., value_render_option="FORMULA")`.
  - This returns the formula string for formula cells (e.g. `=SUM(A1:A5)`), the
    typed text for text cells, and the number for numeric cells.
- An **empty cell** reads as `""` (the API returns no `values`; treat missing as
  empty). `insert`/`append`/`prepend`/`newline` therefore work on empty cells;
  `delete` and `replace` on an empty cell are no-ops returning `{old: "",
  new: ""}`.
- **Formula cells are editable text** (per design decision): the formula string
  itself is the editable buffer. Editing `=SUM(A1:A5)` → `=SUM(A1:A6)` is
  intentional and allowed. The agent is responsible for keeping it valid.
- Write back with `update_range(..., value_input_option="USER_ENTERED")` so a
  resulting `=...` re-parses as a formula and `\n` is stored as a literal
  in-cell newline.
- The `cell` arg must resolve to a single cell; a multi-cell range raises
  `ValueError("edit_cell expects a single cell, got <range>")`.

### Operations

| `operation` | params | effect |
|---|---|---|
| `replace` | `find`, `replacement`, `count` (default all) | `str.replace(find, replacement, count)`; `count=-1`/omitted = all |
| `insert` | `position`, `text` | insert `text` at 0-based char index (clamped to `[0, len]`) |
| `delete` | `position`, `length` | remove `length` chars starting at `position` |
| `append` | `text` | `old + text` |
| `prepend` | `text` | `text + old` |
| `newline` | `text` (default `""`) | `old + "\n" + text` — the in-cell line break |

- `position` out of range is clamped, not an error (insert at end if past EOL).
- `replace` with `count` uses Python's `str.replace` count semantics.
- **Line breaks:** `newline` (or `insert`/`append` with `"\n"` in `text`) stores
  a real newline. It only *displays* as a wrapped line when the cell has wrap on
  — note in the docstring to pair with `format_cells(range, wrap=True)`.

### API method + tool

```python
def edit_cell(self, spreadsheet_id, cell, operation, find=None,
              replacement=None, position=None, length=None, text=None,
              count=None):
    # 1. resolve single cell, read FORMULA-rendered value -> old (str, "" if empty)
    # 2. apply operation -> new
    # 3. if new != old: update_range(cell, [[new]], "USER_ENTERED")
    # 4. return {"cell": <a1>, "old": old, "new": new, "changed": new != old}
```

```python
@register(mcp, mutating=True)
def edit_cell(account=None, spreadsheet_id="", cell="", operation="",
              find=None, replacement=None, position=None, length=None,
              text=None, count=None) -> dict:
    """Edit the text of a single cell in place. operation is one of
    replace/insert/delete/append/prepend/newline. Reads the cell's literal
    text (formula string for formula cells), applies the edit, writes it back.
    'newline' adds an in-cell line break (pair with format_cells wrap=True)."""
```

Unknown `operation`, or missing required params for the chosen operation, raise
`ValueError` with a message naming what's required.

## Tier 3 — granular transforms

All Tier-3 tools are range-level read-modify-write: read the range with a
literal render, transform each cell in Python, write the result back with a
single `update_range`/`batch_update_values`. They skip empty cells (leave `""`
as `""`) and leave non-string values (numbers) untouched unless the transform is
defined on their string form.

### `transform_text`

```python
def transform_text(self, spreadsheet_id, range, transform):
```
`transform` ∈ `{upper, lower, title, capitalize, trim, collapse_spaces}`.

- `upper/lower/title/capitalize` → corresponding `str` method.
- `trim` → `str.strip()`.
- `collapse_spaces` → `re.sub(r"\s+", " ", s).strip()`.

Reads the range with `FORMULA` render (so formula cells are detectable),
**skips any cell whose value starts with `=`** (leaves the formula intact) and
any non-string value, transforms only literal text, then writes the whole 2D
block back with `update_range` (`USER_ENTERED`).

```python
@register(mcp, mutating=True)
def transform_text(account=None, spreadsheet_id="", range="", transform="") -> dict:
    """Bulk text transform across a range: upper/lower/title/capitalize/trim/
    collapse_spaces. Literal text only; cells holding a formula (=...) are left
    unchanged. Numbers are left unchanged."""
```

### `regex_replace`

```python
def regex_replace(self, spreadsheet_id, range, pattern, replacement,
                  count=0, ignore_case=False):
```
Python `re.sub(pattern, replacement, cell, count=count, flags=...)` per cell —
**supports `\1` / `\g<name>` backreferences**, which native `find_replace`
cannot. Same formula-skip rule as `transform_text`. Invalid regex raises
`ValueError` (surfaced via `run_tool`).

```python
@register(mcp, mutating=True)
def regex_replace(account=None, spreadsheet_id="", range="", pattern="",
                  replacement="", count=0, ignore_case=False) -> dict:
    """Regex find/replace across a range using Python re (supports \\1 / \\g<name>
    backreferences, unlike native find_replace). count=0 replaces all in each
    cell. Cells holding a formula (=...) are skipped."""
```

### `split_column`

```python
def split_column(self, spreadsheet_id, range, delimiter, max_splits=-1):
```
- `range` must be a single column (e.g. `Sheet1!A1:A20`); raise `ValueError`
  otherwise.
- For each cell, `cell.split(delimiter, max_splits)`.
- Write results starting at the source column, spreading parts across columns to
  the right (`update_range` over `A1:<last>` where width = max parts in any
  row). **Overwrites** columns to the right — docstring warns of this and the
  tool is `destructive=True`.

```python
@register(mcp, mutating=True, destructive=True)
def split_column(account=None, spreadsheet_id="", range="", delimiter="",
                 max_splits=-1) -> dict:
    """Split a single column's cells by a delimiter into adjacent columns
    (like Sheets 'Split text to columns'). OVERWRITES columns to the right of
    the source column."""
```

### `join_columns`

```python
def join_columns(self, spreadsheet_id, range, separator=" ", target_range=None):
```
- `range` spans the columns to join (e.g. `Sheet1!A1:C20`).
- For each row, join the non-empty cell strings with `separator`.
- Write the joined column to `target_range` (single column, same row count). If
  `target_range` is omitted, write to the first column of `range`.

```python
@register(mcp, mutating=True)
def join_columns(account=None, spreadsheet_id="", range="", separator=" ",
                 target_range=None) -> dict:
    """Join each row of a multi-column range into one string (separator between
    non-empty cells) and write it to target_range (defaults to the range's
    first column)."""
```

### `regex_extract`

```python
def regex_extract(self, spreadsheet_id, range, pattern, group=0,
                  target_range=None):
```
- For each cell in `range` (single column), `re.search(pattern, cell)`; on match
  take `m.group(group)`, else `""`.
- Write results to `target_range` (single column, same row count); default =
  source column (in-place).

```python
@register(mcp, mutating=True)
def regex_extract(account=None, spreadsheet_id="", range="", pattern="",
                  group=0, target_range=None) -> dict:
    """Extract the first regex match (or a capture group) from each cell in a
    column into target_range (defaults in-place). Non-matching cells become ''."""
```

**Trade-off acknowledged:** `split_column` / `join_columns` / `regex_extract`
overlap with the existing `write_formulas` (`SPLIT`, `TEXTJOIN`/`JOIN`,
`REGEXEXTRACT`). They are included as one-shot **value** operations (no lingering
formula), which is genuinely different behavior, and the user opted into the full
toolkit.

## Shared helpers

- Add a private `_read_single_cell(spreadsheet_id, a1)` → `(grid-validated a1,
  old_text)` used by `edit_cell` (validates single cell, returns `""` for empty).
- Add `_read_text_grid(spreadsheet_id, range, render="FORMULA")` → 2D list of
  strings (padded to a rectangle) used by the Tier-3 tools, plus a
  `_require_single_column(range)` guard for `split_column` / `regex_extract`.
- Reuse existing `_resolve_a1`, `_a1_to_grid_range`, `_batch`, `update_range`,
  `read_range`.

## Error handling

- Single-cell / single-column guards raise `ValueError` with the offending range
  in the message; `run_tool` (existing) surfaces it to the agent.
- Unknown `operation`/`transform` raises `ValueError` listing valid values.
- Invalid regex raises `ValueError` (caught by `run_tool`).
- `find_replace` lets the API surface its own errors (e.g. empty `find`) through
  `run_tool`.

## Testing

Match the existing `tests/test_sheets_server.py` mock style (mock the Google
service / `SheetsAPI`, assert the request bodies and returned envelopes).

- **Unit (`SheetsAPI`):**
  - `find_replace`: each scope path (range / sheetId / allSheets) builds the
    right request; flags pass through.
  - `edit_cell`: every operation transforms `old`→`new` correctly; empty-cell and
    formula-cell cases; clamping for `insert`/`delete`; no write when unchanged.
  - `transform_text` / `regex_replace`: each transform; formula cells skipped;
    backref substitution in `regex_replace`.
  - `split_column` / `join_columns` / `regex_extract`: shape of the written
    block; single-column guards; empty-cell handling.
- **Server-level:** one mocked test per new tool asserting the wrapper calls the
  API method with the right args and wraps the result in `ok(...)`.
- **Live smoke (`tests/live_sheets_formatting.py`):** extend to create a scratch
  sheet, exercise `find_replace`, `edit_cell` (insert + newline), and one
  Tier-3 transform end-to-end, then clean up.

## Out of scope

- Rich-text runs (per-character bold/color *within* a cell via
  `textFormatRuns`) — separate concern from text content editing.
- Undo/history.
- Cross-spreadsheet operations.

## Tool count

Adds **7 tools** (`find_replace`, `edit_cell`, `transform_text`,
`regex_replace`, `split_column`, `join_columns`, `regex_extract`), taking the
Sheets server from 34 → 41 Sheets-specific tools.
