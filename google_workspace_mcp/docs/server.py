"""Google Docs MCP server: create, read, and edit documents for one or more accounts."""
from __future__ import annotations

import json

from ..core import build_server, get_api, ok, register, run_tool
from .docs_api import DocsAPI

mcp = build_server(
    "gdocs-mcp",
    "Google Docs: create, read, and edit documents for one or more Google accounts. "
    "For formatted content (headings, lists, tables, bold), prefer the markdown tools "
    "(create_document_from_markdown, replace_document_with_markdown, append_markdown) "
    "over element-by-element insert/format calls.",
)


def _api(account=None):
    return get_api("docs", DocsAPI, account)


# --- read ---
@register(mcp)
def get_document(account: str | None = None, document_id: str = "") -> dict:
    """Get a document's full structure/metadata (title, body content as JSON)."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.get_document(document_id)))


@register(mcp)
def read_document(account: str | None = None, document_id: str = "") -> dict:
    """Read a document's plain text (paragraphs and table cells)."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.get_document_text(document_id)))


@register(mcp)
def read_document_as_markdown(account: str | None = None, document_id: str = "") -> dict:
    """Read a document as markdown, preserving headings, lists, tables, and links (unlike read_document's plain text)."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.read_document_as_markdown(document_id)))


@register(mcp)
def get_content_map(account: str | None = None, document_id: str = "", include_headers_footers: bool = True) -> dict:
    """Return a structured index map of document elements (paragraphs, tables, indices, text previews)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_content_map(document_id, include_headers_footers))
    return ok(resolved, data)


# --- write ---
@register(mcp, mutating=True)
def create_document(account: str | None = None, title: str = "") -> dict:
    """Create a new (empty) Google Doc with the given title."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.create_document(title)))


@register(mcp, mutating=True)
def create_document_from_markdown(account: str | None = None, title: str = "", markdown: str = "", folder_id: str | None = None) -> dict:
    """Create a Google Doc from markdown text: headings, bold/italic, lists, links, and tables become native Docs formatting. Prefer this over create_document + insert/format calls for formatted content."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.create_document_from_markdown(title, markdown, folder_id)))


@register(mcp, mutating=True, destructive=True)
def replace_document_with_markdown(account: str | None = None, document_id: str = "", markdown: str = "") -> dict:
    """Replace a document's ENTIRE content by re-importing markdown. Comments/suggestions are lost."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.replace_document_with_markdown(document_id, markdown)))


@register(mcp, mutating=True, destructive=True)
def append_markdown(account: str | None = None, document_id: str = "", markdown: str = "") -> dict:
    """Append markdown to the end of a document. Round-trips the whole doc through markdown export/import, so elements markdown cannot express (comments, positioned images) are lost."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.append_markdown(document_id, markdown)))


@register(mcp, mutating=True)
def append_text(account: str | None = None, document_id: str = "", text: str = "") -> dict:
    """Append text to the end of a document."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.append_text(document_id, text)))


@register(mcp, mutating=True)
def insert_text(account: str | None = None, document_id: str = "", text: str = "", index: int = 1) -> dict:
    """Insert text at a specific character index (1 = start of body)."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.insert_text(document_id, text, index)))


@register(mcp, mutating=True)
def replace_all_text(account: str | None = None, document_id: str = "", find: str = "", replace: str = "", match_case: bool = False) -> dict:
    """Replace every occurrence of a string throughout the document."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.replace_all_text(document_id, find, replace, match_case)))


# --- format / structure ---
@register(mcp, mutating=True)
def format_text(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, bold: bool | None = None, italic: bool | None = None, underline: bool | None = None, strikethrough: bool | None = None, font_size: float | None = None, font_family: str | None = None, link_url: str | None = None, foreground_color: str | None = None, background_color: str | None = None, segment_id: str | None = None) -> dict:
    """Style a character range (bold/italic/underline/strikethrough, font size/family in PT, link URL, hex foreground/background colors). Use segment_id for header/footer text."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.format_text(document_id, start_index, end_index, bold, italic, underline, strikethrough, font_size, font_family, link_url, foreground_color, background_color, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def set_paragraph_style(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, named_style: str = "NORMAL_TEXT") -> dict:
    """Apply a paragraph named style (NORMAL_TEXT, TITLE, SUBTITLE, HEADING_1..HEADING_6) to a range."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_paragraph_style(document_id, start_index, end_index, named_style))
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_paragraph_style(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, named_style_type: str | None = None, alignment: str | None = None, indent_start_pt: float | None = None, indent_end_pt: float | None = None, space_above_pt: float | None = None, space_below_pt: float | None = None, line_spacing: float | None = None, line_spacing_mode: str | None = None, segment_id: str | None = None) -> dict:
    """Apply paragraph formatting: alignment, indents/spacing in PT, line_spacing (100=normal), line_spacing_mode (AT_LEAST/EXACTLY/MULTIPLE), named style type."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.update_paragraph_style(document_id, start_index, end_index, named_style_type, alignment, indent_start_pt, indent_end_pt, space_above_pt, space_below_pt, line_spacing, line_spacing_mode, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def set_page_layout(account: str | None = None, document_id: str = "", page_preset: str | None = None, width_pt: float | None = None, height_pt: float | None = None, margin_top_pt: float | None = None, margin_bottom_pt: float | None = None, margin_left_pt: float | None = None, margin_right_pt: float | None = None, margin_header_pt: float | None = None, margin_footer_pt: float | None = None, flip_page_orientation: bool | None = None) -> dict:
    """Set page size and margins. Use page_preset (LETTER, A4, LEGAL, TABLOID) or explicit width_pt/height_pt. Margins are in points (72 PT = 1 inch)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_page_layout(document_id, page_preset, width_pt, height_pt, margin_top_pt, margin_bottom_pt, margin_left_pt, margin_right_pt, margin_header_pt, margin_footer_pt, flip_page_orientation))
    return ok(resolved, data)


@register(mcp, mutating=True)
def flip_page_orientation(account: str | None = None, document_id: str = "", flip: bool = True) -> dict:
    """Toggle page orientation (portrait ↔ landscape) by swapping width and height."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.flip_page_orientation(document_id, flip))
    return ok(resolved, data)


@register(mcp, mutating=True)
def setup_header(account: str | None = None, document_id: str = "", text: str = "", header_type: str = "DEFAULT", index: int = 0) -> dict:
    """Create a default header and insert text. Returns headerId for further edits."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.setup_header(document_id, text, header_type, index))
    return ok(resolved, data)


@register(mcp, mutating=True)
def setup_footer(account: str | None = None, document_id: str = "", text: str = "", footer_type: str = "DEFAULT", index: int = 0) -> dict:
    """Create a default footer and insert text. Returns footerId for further edits."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.setup_footer(document_id, text, footer_type, index))
    return ok(resolved, data)


@register(mcp, mutating=True)
def create_header(account: str | None = None, document_id: str = "", header_type: str = "DEFAULT") -> dict:
    """Create an empty header (DEFAULT type). Fails if one already exists."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.create_header(document_id, header_type))
    return ok(resolved, data)


@register(mcp, mutating=True)
def create_footer(account: str | None = None, document_id: str = "", footer_type: str = "DEFAULT") -> dict:
    """Create an empty footer (DEFAULT type). Fails if one already exists."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.create_footer(document_id, footer_type))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_inline_image(account: str | None = None, document_id: str = "", uri: str = "", index: int = 1, width_pt: float | None = None, height_pt: float | None = None, segment_id: str | None = None) -> dict:
    """Insert an inline image from a public URI (PNG/JPEG/GIF, max 2KB URL). Optional width/height in PT. Use segment_id for header/footer images."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_inline_image(document_id, uri, index, width_pt, height_pt, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_chart_image(account: str | None = None, document_id: str = "", uri: str = "", index: int = 1, width_pt: float = 468, height_pt: float = 280, segment_id: str | None = None) -> dict:
    """Insert a chart rendered as an image (export from Sheets or another tool, then pass a public image URL). Default size fits a letter-width page."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_chart_image(document_id, uri, index, width_pt, height_pt, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_table(account: str | None = None, document_id: str = "", rows: int = 2, columns: int = 2, index: int = 1, segment_id: str | None = None) -> dict:
    """Insert an empty table at the given body index (or in a header/footer via segment_id)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_table(document_id, rows, columns, index, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_page_break(account: str | None = None, document_id: str = "", index: int = 1, segment_id: str | None = None) -> dict:
    """Insert a page break at the given index (body or header/footer via segment_id)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_page_break(document_id, index, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_bullets(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, bullet_preset: str = "BULLET_DISC_CIRCLE_SQUARE", segment_id: str | None = None) -> dict:
    """Turn the paragraphs in a range into a bulleted/numbered list (e.g. BULLET_DISC_CIRCLE_SQUARE, NUMBERED_DECIMAL_ALPHA_ROMAN)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_bullets(document_id, start_index, end_index, bullet_preset, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_numbered_list(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, preset: str = "NUMBERED_DECIMAL_ALPHA_ROMAN", segment_id: str | None = None) -> dict:
    """Apply numbered list formatting. Presets: NUMBERED_DECIMAL_ALPHA_ROMAN, NUMBERED_DECIMAL_ALPHA_ROMAN_PARENS, NUMBERED_DECIMAL_NESTED, NUMBERED_UPPERALPHA_ALPHA_ROMAN, NUMBERED_UPPERROMAN_UPPERALPHA_DECIMAL, NUMBERED_ZERODECIMAL_ALPHA_ROMAN."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_numbered_list(document_id, start_index, end_index, preset, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def populate_table(account: str | None = None, document_id: str = "", table_start_index: int = 1, rows: list[list[str]] | None = None, segment_id: str | None = None) -> dict:
    """Fill table cells with text. Use get_content_map to find table_start_index and dimensions."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.populate_table(document_id, table_start_index, rows or [], segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def merge_table_cells(account: str | None = None, document_id: str = "", table_start_index: int = 1, row: int = 0, column: int = 0, row_span: int = 1, column_span: int = 1, segment_id: str | None = None) -> dict:
    """Merge a rectangular range of table cells."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.merge_table_cells(document_id, table_start_index, row, column, row_span, column_span, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def format_table_cells(account: str | None = None, document_id: str = "", table_start_index: int = 1, row: int = 0, column: int = 0, row_span: int = 1, column_span: int = 1, background_color: str | None = None, border_color: str | None = None, border_width_pt: float | None = None, segment_id: str | None = None) -> dict:
    """Style table cells: hex background_color, border_color, border_width_pt."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.format_table_cells(document_id, table_start_index, row, column, row_span, column_span, background_color, border_color, border_width_pt, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_page_number(account: str | None = None, document_id: str = "", footer_id: str = "", index: int = 0) -> dict:
    """Insert a dynamic page number into an existing footer (footer_id from setup_footer/create_footer)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_page_number(document_id, footer_id, index))
    return ok(resolved, data)


@register(mcp, mutating=True)
def batch_update(account: str | None = None, document_id: str = "", requests: list[dict] | str | None = None) -> dict:
    """Execute raw Docs batchUpdate requests. Pass a list of request dicts or a JSON string."""
    api, resolved = _api(account)

    def _call():
        raw = requests
        if isinstance(raw, str):
            raw = json.loads(raw)
        return api.batch_update(document_id, raw)

    data = run_tool(_call)
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_sheets_chart(account: str | None = None, document_id: str = "", spreadsheet_id: str = "", chart_id: int = 0, index: int = 1, width_pt: float = 468, height_pt: float = 280) -> dict:
    """Export a Google Sheets chart as PNG and insert it into the document."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_sheets_chart(document_id, spreadsheet_id, chart_id, index, width_pt, height_pt, account=resolved))
    return ok(resolved, data)


@register(mcp, mutating=True)
def remove_bullets(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, segment_id: str | None = None) -> dict:
    """Remove bullets/numbering from paragraphs in a range."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.remove_bullets(document_id, start_index, end_index, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_range(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, segment_id: str | None = None) -> dict:
    """Delete content in the given character index range (body or header/footer via segment_id)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_range(document_id, start_index, end_index, segment_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_header(account: str | None = None, document_id: str = "", header_id: str = "") -> dict:
    """Delete a header by its headerId."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_header(document_id, header_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_footer(account: str | None = None, document_id: str = "", footer_id: str = "") -> dict:
    """Delete a footer by its footerId."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_footer(document_id, footer_id))
    return ok(resolved, data)


def main():
    mcp.run()
