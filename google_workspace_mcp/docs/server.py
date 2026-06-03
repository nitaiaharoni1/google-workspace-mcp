"""Google Docs MCP server: create, read, and edit documents for one or more accounts."""
from __future__ import annotations

from ..core import build_server, register, get_api, run_tool, ok
from .docs_api import DocsAPI

mcp = build_server(
    "gdocs-mcp",
    "Google Docs: create, read, and edit documents for one or more Google accounts.",
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


# --- write ---
@register(mcp, mutating=True)
def create_document(account: str | None = None, title: str = "") -> dict:
    """Create a new (empty) Google Doc with the given title."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.create_document(title)))


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
def format_text(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, bold: bool | None = None, italic: bool | None = None, underline: bool | None = None, font_size: float | None = None, link_url: str | None = None, foreground_color: str | None = None) -> dict:
    """Style a character range (bold/italic/underline, font size in PT, link URL, hex foreground color)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.format_text(document_id, start_index, end_index, bold, italic, underline, font_size, link_url, foreground_color))
    return ok(resolved, data)


@register(mcp, mutating=True)
def set_paragraph_style(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, named_style: str = "NORMAL_TEXT") -> dict:
    """Apply a paragraph named style (NORMAL_TEXT, TITLE, SUBTITLE, HEADING_1..HEADING_6) to a range."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.set_paragraph_style(document_id, start_index, end_index, named_style))
    return ok(resolved, data)


@register(mcp, mutating=True)
def insert_bullets(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1, bullet_preset: str = "BULLET_DISC_CIRCLE_SQUARE") -> dict:
    """Turn the paragraphs in a range into a bulleted/numbered list (e.g. BULLET_DISC_CIRCLE_SQUARE, NUMBERED_DECIMAL_ALPHA_ROMAN)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.insert_bullets(document_id, start_index, end_index, bullet_preset))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_range(account: str | None = None, document_id: str = "", start_index: int = 1, end_index: int = 1) -> dict:
    """Delete content in the given character index range."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_range(document_id, start_index, end_index))
    return ok(resolved, data)


def main():
    mcp.run()
