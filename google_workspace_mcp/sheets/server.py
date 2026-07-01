"""Google Sheets MCP server: read/write values and manage sheet structure."""
from __future__ import annotations

from ..core import build_server, get_api, ok, register, run_tool
from .sheets_api import SheetsAPI

mcp = build_server(
    "gsheets-mcp",
    "Google Sheets: read/write values, formulas, filters, and table formatting (banding, wrap, column sizing) for one or more accounts. Ranges use A1 notation.",
)


def _api(account=None):
    return get_api("sheets", SheetsAPI, account)


# --- READ tools ---

@register(mcp)
def get_spreadsheet(account: str | None = None, spreadsheet_id: str = "", include_grid_data: bool = False) -> dict:
    """Return spreadsheet metadata (title, sheets list, properties). Set include_grid_data=True to also return cell data."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_spreadsheet(spreadsheet_id, include_grid_data))
    return ok(resolved, data)


@register(mcp)
def read_range(account: str | None = None, spreadsheet_id: str = "", range: str = "", value_render_option: str = "FORMATTED_VALUE") -> dict:
    """Read cell values from a range (A1 notation, e.g. 'Sheet1!A1:C10')."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.read_range(spreadsheet_id, range, value_render_option))
    return ok(resolved, data)


@register(mcp)
def batch_read(account: str | None = None, spreadsheet_id: str = "", ranges: list[str] | None = None, value_render_option: str = "FORMATTED_VALUE") -> dict:
    """Read cell values from multiple ranges in one request (A1 notation)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.batch_read(spreadsheet_id, ranges or [], value_render_option))
    return ok(resolved, data)


# --- WRITE (mutating) tools ---

@register(mcp, mutating=True)
def create_spreadsheet(account: str | None = None, title: str = "") -> dict:
    """Create a new Google Spreadsheet with the given title and return its metadata."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.create_spreadsheet(title))
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_range(account: str | None = None, spreadsheet_id: str = "", range: str = "", values: list[list] | None = None, value_input_option: str = "USER_ENTERED") -> dict:
    """Write a 2D array of values to a range (A1 notation). Overwrites existing cells."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.update_range(spreadsheet_id, range, values or [], value_input_option))
    return ok(resolved, data)


@register(mcp, mutating=True)
def batch_update_values(account: str | None = None, spreadsheet_id: str = "", data: list[dict] | None = None, value_input_option: str = "USER_ENTERED") -> dict:
    """Write values to multiple ranges in one request. Each item in data must have 'range' and 'values' keys."""
    api, resolved = _api(account)
    result = run_tool(lambda: api.batch_update_values(spreadsheet_id, data or [], value_input_option))
    return ok(resolved, result)


@register(mcp, mutating=True)
def append_rows(account: str | None = None, spreadsheet_id: str = "", range: str = "", values: list[list] | None = None, value_input_option: str = "USER_ENTERED") -> dict:
    """Append rows after the last row with data in the given range (A1 notation)."""
    api, resolved = _api(account)
    result = run_tool(lambda: api.append_rows(spreadsheet_id, range, values or [], value_input_option))
    return ok(resolved, result)


@register(mcp, mutating=True)
def add_sheet(account: str | None = None, spreadsheet_id: str = "", title: str = "") -> dict:
    """Add a new sheet (tab) to an existing spreadsheet."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.add_sheet(spreadsheet_id, title))
    return ok(resolved, data)


@register(mcp, mutating=True)
def rename_sheet(account: str | None = None, spreadsheet_id: str = "", sheet_id: int = 0, new_title: str = "") -> dict:
    """Rename a sheet (tab) by its numeric sheet ID."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.rename_sheet(spreadsheet_id, sheet_id, new_title))
    return ok(resolved, data)


# --- DESTRUCTIVE tools ---

@register(mcp, mutating=True, destructive=True)
def clear_range(account: str | None = None, spreadsheet_id: str = "", range: str = "") -> dict:
    """Clear values from a range (formatting is kept)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.clear_range(spreadsheet_id, range))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_sheet(account: str | None = None, spreadsheet_id: str = "", sheet_id: int = 0) -> dict:
    """Delete a sheet (tab) by its numeric sheet ID."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_sheet(spreadsheet_id, sheet_id))
    return ok(resolved, data)


# --- FORMATTING / STRUCTURE (mutating) tools ---

@register(mcp, mutating=True)
def format_cells(account: str | None = None, spreadsheet_id: str = "", range: str = "", bold: bool | None = None, italic: bool | None = None, strikethrough: bool | None = None, underline: bool | None = None, font_size: int | None = None, text_color: str | None = None, background_color: str | None = None, number_format: str | None = None, horizontal_alignment: str | None = None, vertical_alignment: str | None = None, wrap: bool | None = None) -> dict:
    """Apply formatting to a range (A1 notation). Colors are hex (e.g. '#FF0000'); horizontal_alignment is LEFT/CENTER/RIGHT; vertical_alignment is TOP/MIDDLE/BOTTOM; wrap=True enables text wrap."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.format_cells(spreadsheet_id, range, bold, italic, strikethrough, underline, font_size, text_color, background_color, number_format, horizontal_alignment, vertical_alignment, wrap))
    return ok(resolved, data)


@register(mcp, mutating=True)
def sort_range(account: str | None = None, spreadsheet_id: str = "", range: str = "", column: int = 0, ascending: bool = True) -> dict:
    """Sort a range (A1 notation) by an absolute 0-based sheet column index, ascending or descending."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.sort_range(spreadsheet_id, range, column, ascending))
    return ok(resolved, data)


@register(mcp, mutating=True)
def set_basic_filter(account: str | None = None, spreadsheet_id: str = "", range: str = "", filter_specs: list[dict] | None = None, sort_specs: list[dict] | None = None) -> dict:
    """Set a basic filter over a range (A1 notation). filter_specs: [{column: 0, hidden_values: ['x']}] or [{column: 1, condition_type: 'TEXT_CONTAINS', values: ['foo']}]. sort_specs: [{column: 0, ascending: true}]."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_basic_filter(spreadsheet_id, range, filter_specs, sort_specs))
    return ok(resolved, data)


@register(mcp, mutating=True)
def clear_basic_filter(account: str | None = None, spreadsheet_id: str = "", range: str = "") -> dict:
    """Clear the basic filter from the sheet that contains the given range (A1 notation)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.clear_basic_filter(spreadsheet_id, range))
    return ok(resolved, data)


@register(mcp, mutating=True)
def find_replace(account: str | None = None, spreadsheet_id: str = "", find: str = "", replacement: str = "", range: str | None = None, all_sheets: bool = False, match_case: bool = False, match_entire_cell: bool = False, search_by_regex: bool = False, include_formulas: bool = False) -> dict:
    """Find and replace text. Scope to a range (A1, e.g. 'Sheet1!A1:C9'), a whole sheet (bare tab name like 'Sheet1'), or set all_sheets=True. search_by_regex treats 'find' as a regex; include_formulas also searches formula text. Returns counts of changes."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.find_replace(spreadsheet_id, find, replacement, range, all_sheets, match_case, match_entire_cell, search_by_regex, include_formulas))
    return ok(resolved, data)


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


@register(mcp, mutating=True)
def merge_cells(account: str | None = None, spreadsheet_id: str = "", range: str = "", merge_type: str = "MERGE_ALL") -> dict:
    """Merge cells in a range (A1 notation). merge_type is MERGE_ALL/MERGE_COLUMNS/MERGE_ROWS."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.merge_cells(spreadsheet_id, range, merge_type))
    return ok(resolved, data)


@register(mcp, mutating=True)
def unmerge_cells(account: str | None = None, spreadsheet_id: str = "", range: str = "") -> dict:
    """Unmerge any merged cells within a range (A1 notation)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.unmerge_cells(spreadsheet_id, range))
    return ok(resolved, data)


@register(mcp, mutating=True)
def resize_columns(account: str | None = None, spreadsheet_id: str = "", range: str = "", width: int | None = None) -> dict:
    """Resize the columns covered by a range (e.g. 'Sheet1!A:C' or 'Sheet1!B2:D9') to a pixel width. Omit width to auto-fit each column to its content."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.resize_dimension(spreadsheet_id, range, "COLUMNS", width))
    return ok(resolved, data)


@register(mcp, mutating=True)
def resize_rows(account: str | None = None, spreadsheet_id: str = "", range: str = "", height: int | None = None) -> dict:
    """Resize the rows covered by a range (e.g. 'Sheet1!2:10') to a pixel height. Omit height to auto-fit each row to its content."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.resize_dimension(spreadsheet_id, range, "ROWS", height))
    return ok(resolved, data)


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


@register(mcp, mutating=True)
def freeze_panes(account: str | None = None, spreadsheet_id: str = "", range: str = "", rows: int | None = None, cols: int | None = None) -> dict:
    """Freeze the first N rows and/or columns of the sheet containing the given range (A1 notation). Pass 0 to unfreeze."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.freeze_panes(spreadsheet_id, range, rows, cols))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_rows(account: str | None = None, spreadsheet_id: str = "", range: str = "", inherit_from_before: bool = False) -> dict:
    """Insert blank rows at the position covered by a row range (e.g. 'Sheet1!3:5' inserts 3 rows starting at row 3). Existing rows shift down."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_dimension(spreadsheet_id, range, "ROWS", inherit_from_before))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_columns(account: str | None = None, spreadsheet_id: str = "", range: str = "", inherit_from_before: bool = False) -> dict:
    """Insert blank columns at the position covered by a column range (e.g. 'Sheet1!C:D' inserts 2 columns at C). Existing columns shift right."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_dimension(spreadsheet_id, range, "COLUMNS", inherit_from_before))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_rows(account: str | None = None, spreadsheet_id: str = "", range: str = "") -> dict:
    """Delete the rows covered by a row range (e.g. 'Sheet1!3:5'). Rows below shift up."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_dimension(spreadsheet_id, range, "ROWS"))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_columns(account: str | None = None, spreadsheet_id: str = "", range: str = "") -> dict:
    """Delete the columns covered by a column range (e.g. 'Sheet1!C:D'). Columns to the right shift left."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_dimension(spreadsheet_id, range, "COLUMNS"))
    return ok(resolved, data)


@register(mcp, mutating=True)
def set_borders(account: str | None = None, spreadsheet_id: str = "", range: str = "", style: str = "SOLID", color: str = "#000000", top: bool = True, bottom: bool = True, left: bool = True, right: bool = True, inner: bool = False) -> dict:
    """Draw borders around a range (A1 notation). style is SOLID/SOLID_MEDIUM/SOLID_THICK/DASHED/DOTTED/DOUBLE; color is hex. Set inner=True to also draw gridlines between cells."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_borders(spreadsheet_id, range, style, color, top, bottom, left, right, inner))
    return ok(resolved, data)


@register(mcp, mutating=True)
def set_data_validation(account: str | None = None, spreadsheet_id: str = "", range: str = "", allowed_values: list[str] | None = None, show_dropdown: bool = True) -> dict:
    """Restrict cells in a range to a list of allowed values, shown as an in-cell dropdown. Pass an empty list to clear validation."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_data_validation(spreadsheet_id, range, allowed_values, show_dropdown))
    return ok(resolved, data)


@register(mcp, mutating=True)
def duplicate_sheet(account: str | None = None, spreadsheet_id: str = "", sheet_id: int = 0, new_title: str | None = None) -> dict:
    """Duplicate a sheet (tab) by its numeric sheet ID, optionally giving the copy a new title."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.duplicate_sheet(spreadsheet_id, sheet_id, new_title))
    return ok(resolved, data)


@register(mcp, mutating=True)
def add_banding(account: str | None = None, spreadsheet_id: str = "", range: str = "", header_color: str | None = None, first_band_color: str = "#FFFFFF", second_band_color: str = "#F3F3F3", footer_color: str | None = None, band_rows: bool = True) -> dict:
    """Add alternating row (or column) colors to a range. header_color styles the first row; first/second_band_color alternate thereafter."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.add_banding(spreadsheet_id, range, header_color, first_band_color, second_band_color, footer_color, band_rows))
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_banding(account: str | None = None, spreadsheet_id: str = "", banded_range_id: int = 0, header_color: str | None = None, first_band_color: str | None = None, second_band_color: str | None = None, footer_color: str | None = None) -> dict:
    """Update colors on an existing banded range by bandedRangeId."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.update_banding(spreadsheet_id, banded_range_id, header_color, first_band_color, second_band_color, footer_color))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_banding(account: str | None = None, spreadsheet_id: str = "", banded_range_id: int = 0) -> dict:
    """Remove a banded (alternating color) range by its bandedRangeId (from get_spreadsheet or add_banding response)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_banding(spreadsheet_id, banded_range_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def add_table(account: str | None = None, spreadsheet_id: str = "", range: str = "", name: str = "", header_color: str = "#355468", first_band_color: str = "#FFFFFF", second_band_color: str = "#F3F3F3", column_names: list[str] | None = None) -> dict:
    """Create a native Google Sheets table with header and alternating row colors. column_names sets header labels by column index."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.add_table(spreadsheet_id, range, name, header_color, first_band_color, second_band_color, column_names))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_table(account: str | None = None, spreadsheet_id: str = "", table_id: str = "") -> dict:
    """Delete a native table by its tableId (from the add_table reply, or get_spreadsheet where each sheet lists its 'tables'). Cell values remain; the table structure is removed."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_table(spreadsheet_id, table_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_table(account: str | None = None, spreadsheet_id: str = "", table_id: str = "", name: str | None = None, range: str | None = None, header_color: str | None = None, first_band_color: str | None = None, second_band_color: str | None = None, footer_color: str | None = None, column_properties: list[dict] | None = None) -> dict:
    """Update an existing native table's settings by tableId. name renames it; range (A1) resizes/moves it; header/first_band/second_band/footer_color recolor it (hex). column_properties sets per-column settings: [{column_index, column_name, column_type, values}] where column_type is TEXT/DOUBLE/PERCENT/DATE/BOOLEAN/DROPDOWN and values builds a dropdown."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.update_table(spreadsheet_id, table_id, name, range, header_color, first_band_color, second_band_color, footer_color, column_properties))
    return ok(resolved, data)


@register(mcp, mutating=True)
def format_table(account: str | None = None, spreadsheet_id: str = "", range: str = "", header_color: str = "#355468", header_text_color: str = "#FFFFFF", first_band_color: str = "#FFFFFF", second_band_color: str = "#F3F3F3", wrap: bool = True, auto_resize_columns: bool = True, add_filter: bool = True, add_borders: bool = True, freeze_header: bool = False, max_column_width: int = 320) -> dict:
    """One-shot table styling: formatted header, alternating row colors, filter dropdowns, borders, and content-aware column widths (capped at max_column_width px; over-cap columns wrap). Set freeze_header=True only if the user asks for frozen headers."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.format_table(spreadsheet_id, range, header_color, header_text_color, first_band_color, second_band_color, wrap, auto_resize_columns, add_filter, add_borders, freeze_header, max_column_width))
    return ok(resolved, data)


@register(mcp, mutating=True)
def optimize_layout(account: str | None = None, spreadsheet_id: str = "", range: str = "", max_column_width: int = 320, min_column_width: int = 48, resize_rows: bool = True) -> dict:
    """Make a sheet readable in one call: size each column to its content (capped at max_column_width px), wrap only over-cap columns (top-aligned), and auto-fit row heights. Pass an A1 range or a bare tab name for the whole sheet. Use after writing data."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.optimize_layout(spreadsheet_id, range, max_column_width, min_column_width, resize_rows))
    return ok(resolved, data)


@register(mcp, mutating=True)
def write_table(account: str | None = None, spreadsheet_id: str = "", anchor: str = "", values: list[list] | None = None, style: str = "native", name: str | None = None, header_color: str = "#355468", first_band_color: str = "#FFFFFF", second_band_color: str = "#F3F3F3", max_column_width: int = 320) -> dict:
    """Write a 2D array (first row = headers) at an anchor cell (e.g. 'Sheet1!A1') and make it readable in one shot: native Sheets table (style='native'), alternating-color banding (style='banded'), or values only (style='plain'), plus content-aware column widths and wrapping. Prefer this over update_range for tabular data. Overwrites cells in the target range. If a native table already overlaps the range, use style='banded' or update_table instead."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.write_table(spreadsheet_id, anchor, values or [], style, name, header_color, first_band_color, second_band_color, max_column_width))
    return ok(resolved, data)


@register(mcp)
def read_formulas(account: str | None = None, spreadsheet_id: str = "", range: str = "") -> dict:
    """Read formula strings from a range (A1 notation), e.g. '=SUM(A2:A10)'."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.read_formulas(spreadsheet_id, range))
    return ok(resolved, data)


@register(mcp, mutating=True)
def write_formulas(account: str | None = None, spreadsheet_id: str = "", range: str = "", formulas: list[list] | None = None) -> dict:
    """Write formula strings to a range (A1 notation). Pass 2D array with '=' prefixes, e.g. [['=SUM(A2:A10)', '=A2*B2']]."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.write_formulas(spreadsheet_id, range, formulas or []))
    return ok(resolved, data)


# --- TEXT EDITING (mutating) tools ---

@register(mcp, mutating=True)
def edit_cell(account: str | None = None, spreadsheet_id: str = "", cell: str = "", operation: str = "", find: str | None = None, replacement: str | None = None, position: int | None = None, length: int | None = None, text: str | None = None, count: int | None = None) -> dict:
    """Edit the text of a single cell in place. operation is one of replace/insert/delete/append/prepend/newline. Reads the cell's literal text (the formula string for formula cells), applies the edit, writes it back. 'newline' adds an in-cell line break (pair with format_cells wrap=True). Returns {cell, old, new, changed}."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.edit_cell(spreadsheet_id, cell, operation, find, replacement, position, length, text, count))
    return ok(resolved, data)


@register(mcp, mutating=True)
def transform_text(account: str | None = None, spreadsheet_id: str = "", range: str = "", transform: str = "") -> dict:
    """Bulk text transform across a range: upper/lower/title/capitalize/trim/collapse_spaces. Transforms literal text only; cells holding a formula ('=...') and numbers are left unchanged."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.transform_text(spreadsheet_id, range, transform))
    return ok(resolved, data)


@register(mcp, mutating=True)
def regex_replace(account: str | None = None, spreadsheet_id: str = "", range: str = "", pattern: str = "", replacement: str = "", count: int = 0, ignore_case: bool = False) -> dict:
    r"""Regex find/replace across a range using Python re. Supports \1 / \g<name> backreferences (unlike native find_replace). count=0 replaces all matches in each cell. Cells holding a formula ('=...') are skipped."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.regex_replace(spreadsheet_id, range, pattern, replacement, count, ignore_case))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def split_column(account: str | None = None, spreadsheet_id: str = "", range: str = "", delimiter: str = "", max_splits: int = -1) -> dict:
    """Split a single column's cells by a delimiter into adjacent columns (like Sheets 'Split text to columns'). OVERWRITES columns to the right of the source column. max_splits=-1 means no limit."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.split_column(spreadsheet_id, range, delimiter, max_splits))
    return ok(resolved, data)


@register(mcp, mutating=True)
def join_columns(account: str | None = None, spreadsheet_id: str = "", range: str = "", separator: str = " ", target_range: str | None = None) -> dict:
    """Join each row of a multi-column range into one string (separator placed between non-empty cells) and write it to target_range. target_range defaults to the range's first column (overwriting it)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.join_columns(spreadsheet_id, range, separator, target_range))
    return ok(resolved, data)


@register(mcp, mutating=True)
def regex_extract(account: str | None = None, spreadsheet_id: str = "", range: str = "", pattern: str = "", group: int = 0, target_range: str | None = None) -> dict:
    """Extract the first regex match (or a capture group) from each cell in a single column into target_range. group=0 is the whole match. target_range defaults in-place (overwriting the source column). Non-matching cells become ''."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.regex_extract(spreadsheet_id, range, pattern, group, target_range))
    return ok(resolved, data)


def main():
    mcp.run()
