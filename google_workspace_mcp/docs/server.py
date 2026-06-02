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


def main():
    mcp.run()
