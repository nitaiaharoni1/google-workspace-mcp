"""Google Sheets MCP server: read/write values and manage sheet structure."""
from __future__ import annotations
from ..core import build_server, register, get_api, run_tool, ok
from .sheets_api import SheetsAPI

mcp = build_server(
    "gsheets-mcp",
    "Google Sheets: read and write cell values and manage spreadsheet structure for one or more accounts. Ranges use A1 notation.",
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
def format_cells(account: str | None = None, spreadsheet_id: str = "", range: str = "", bold: bool | None = None, italic: bool | None = None, font_size: int | None = None, text_color: str | None = None, background_color: str | None = None, number_format: str | None = None, horizontal_alignment: str | None = None, wrap: bool | None = None) -> dict:
    """Apply formatting to a range (A1 notation). Colors are hex (e.g. '#FF0000'); horizontal_alignment is LEFT/CENTER/RIGHT."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.format_cells(spreadsheet_id, range, bold, italic, font_size, text_color, background_color, number_format, horizontal_alignment, wrap))
    return ok(resolved, data)


@register(mcp, mutating=True)
def sort_range(account: str | None = None, spreadsheet_id: str = "", range: str = "", column: int = 0, ascending: bool = True) -> dict:
    """Sort a range (A1 notation) by an absolute 0-based sheet column index, ascending or descending."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.sort_range(spreadsheet_id, range, column, ascending))
    return ok(resolved, data)


@register(mcp, mutating=True)
def set_basic_filter(account: str | None = None, spreadsheet_id: str = "", range: str = "") -> dict:
    """Set a basic filter over a range (A1 notation)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_basic_filter(spreadsheet_id, range))
    return ok(resolved, data)


@register(mcp, mutating=True)
def clear_basic_filter(account: str | None = None, spreadsheet_id: str = "", range: str = "") -> dict:
    """Clear the basic filter from the sheet that contains the given range (A1 notation)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.clear_basic_filter(spreadsheet_id, range))
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


def main():
    mcp.run()
