"""Gmail MCP server: read, search, send, label, and manage messages."""
from __future__ import annotations

from ..core import build_server, register, get_api, run_tool, ok
from gmail_cli.api import GmailAPI

mcp = build_server(
    "gmail-mcp",
    "Gmail: read, search, send, draft, label, and manage messages for one or more Google accounts.",
)


def _api(account=None):
    return get_api("gmail", GmailAPI, account)


# ---------------------------------------------------------------------------
# READ tools (no mutating flag)
# ---------------------------------------------------------------------------

@register(mcp)
def get_profile(account: str | None = None) -> dict:
    """Get Gmail profile info (email address, message count, thread count, history ID)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_profile())
    return ok(resolved, data)


@register(mcp)
def list_messages(
    account: str | None = None,
    query: str | None = None,
    label_ids: list[str] | None = None,
    max_results: int = 10,
) -> dict:
    """List messages, optionally filtered by a Gmail search query (e.g. 'from:bob is:unread')."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.list_messages(max_results=max_results, label_ids=label_ids, query=query))
    return ok(resolved, data)


@register(mcp)
def search_messages(
    account: str | None = None,
    query: str | None = None,
    label_ids: list[str] | None = None,
    max_results: int = 10,
    format: str = "metadata",
) -> dict:
    """Search messages and return full details (headers, snippet, labels) in one call."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.search_with_details(max_results=max_results, label_ids=label_ids, query=query, format=format))
    return ok(resolved, data)


@register(mcp)
def get_message(
    account: str | None = None,
    message_id: str = "",
    format: str = "full",
) -> dict:
    """Get a specific message by ID (format: full, metadata, minimal, or raw)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_message(message_id, format=format))
    return ok(resolved, data)


@register(mcp)
def list_threads(
    account: str | None = None,
    query: str | None = None,
    max_results: int = 10,
) -> dict:
    """List email threads, optionally filtered by a Gmail search query."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.list_threads(max_results=max_results, query=query))
    return ok(resolved, data)


@register(mcp)
def list_labels(account: str | None = None) -> dict:
    """List all labels (system and user-created) in the mailbox."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.list_labels())
    return ok(resolved, data)


@register(mcp)
def get_label(account: str | None = None, label_id: str = "") -> dict:
    """Get a specific label by ID."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_label(label_id))
    return ok(resolved, data)


@register(mcp)
def list_drafts(account: str | None = None, max_results: int = 10) -> dict:
    """List draft messages."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.list_drafts(max_results=max_results))
    return ok(resolved, data)


@register(mcp)
def get_draft(account: str | None = None, draft_id: str = "") -> dict:
    """Get a specific draft by ID."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_draft(draft_id))
    return ok(resolved, data)


@register(mcp)
def list_filters(account: str | None = None) -> dict:
    """List all Gmail filters configured for this account."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.list_filters())
    return ok(resolved, data)


@register(mcp)
def get_filter(account: str | None = None, filter_id: str = "") -> dict:
    """Get a specific Gmail filter by ID."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_filter(filter_id))
    return ok(resolved, data)


# ---------------------------------------------------------------------------
# WRITE tools (mutating=True)
# ---------------------------------------------------------------------------

@register(mcp, mutating=True)
def send_message(
    account: str | None = None,
    to: str = "",
    subject: str = "",
    body: str = "",
    cc: str | None = None,
) -> dict:
    """Send an email message."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.send_message(to=to, subject=subject, body=body, cc=cc))
    return ok(resolved, data)


@register(mcp, mutating=True)
def reply_to_message(
    account: str | None = None,
    message_id: str = "",
    body: str = "",
    reply_all: bool = False,
    additional_cc: str | None = None,
) -> dict:
    """Reply to a message; set reply_all=True to reply to all recipients."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.reply_to_message(message_id, body=body, reply_all=reply_all, additional_cc=additional_cc))
    return ok(resolved, data)


@register(mcp, mutating=True)
def forward_message(
    account: str | None = None,
    message_id: str = "",
    to: str = "",
    body: str | None = None,
) -> dict:
    """Forward a message to another recipient."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.forward_message(message_id, to=to, body=body))
    return ok(resolved, data)


@register(mcp, mutating=True)
def create_draft(
    account: str | None = None,
    to: str = "",
    subject: str = "",
    body: str = "",
) -> dict:
    """Create a draft message."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.create_draft(to=to, subject=subject, body=body))
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_draft(
    account: str | None = None,
    draft_id: str = "",
    to: str = "",
    subject: str = "",
    body: str = "",
) -> dict:
    """Update an existing draft message."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.update_draft(draft_id, to=to, subject=subject, body=body))
    return ok(resolved, data)


@register(mcp, mutating=True)
def modify_labels(
    account: str | None = None,
    message_id: str = "",
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> dict:
    """Add or remove labels on a message."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.modify_message(message_id, add_label_ids=add_label_ids, remove_label_ids=remove_label_ids))
    return ok(resolved, data)


@register(mcp, mutating=True)
def mark_read(account: str | None = None, message_id: str = "") -> dict:
    """Mark a message as read (removes the UNREAD label)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.mark_as_read(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def archive_message(account: str | None = None, message_id: str = "") -> dict:
    """Archive a message by removing it from the INBOX."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.archive_message(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def star_message(account: str | None = None, message_id: str = "") -> dict:
    """Star a message."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.star_message(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def unstar_message(account: str | None = None, message_id: str = "") -> dict:
    """Remove the star from a message."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.unstar_message(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def mark_as_spam(account: str | None = None, message_id: str = "") -> dict:
    """Mark a message as spam (adds SPAM label, removes INBOX)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.mark_as_spam(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def unmark_spam(account: str | None = None, message_id: str = "") -> dict:
    """Remove spam marking from a message (removes SPAM label, restores INBOX)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.unmark_spam(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def create_label(
    account: str | None = None,
    name: str = "",
    message_list_visibility: str = "show",
    label_list_visibility: str = "labelShow",
) -> dict:
    """Create a new label in the mailbox."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.create_label(name, message_list_visibility=message_list_visibility, label_list_visibility=label_list_visibility))
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_label(
    account: str | None = None,
    label_id: str = "",
    name: str | None = None,
    message_list_visibility: str | None = None,
    label_list_visibility: str | None = None,
) -> dict:
    """Update an existing label's name or visibility settings."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.update_label(label_id, name=name, message_list_visibility=message_list_visibility, label_list_visibility=label_list_visibility))
    return ok(resolved, data)


@register(mcp, mutating=True)
def create_filter(
    account: str | None = None,
    criteria: dict | None = None,
    action: dict | None = None,
) -> dict:
    """Create a Gmail filter with given criteria (from, to, subject) and action (addLabelIds, etc.)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.create_filter(criteria or {}, action or {}))
    return ok(resolved, data)


@register(mcp, mutating=True)
def block_sender(account: str | None = None, email: str = "") -> dict:
    """Block a sender by creating a filter that marks their emails as spam."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.block_sender(email))
    return ok(resolved, data)


@register(mcp, mutating=True)
def batch_modify_labels(
    account: str | None = None,
    message_ids: list[str] | None = None,
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> dict:
    """Add or remove labels on multiple messages in a single batch operation."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.batch_modify_messages(message_ids or [], add_label_ids=add_label_ids, remove_label_ids=remove_label_ids))
    return ok(resolved, data)


# ---------------------------------------------------------------------------
# DESTRUCTIVE tools (mutating=True, destructive=True)
# ---------------------------------------------------------------------------

@register(mcp, mutating=True, destructive=True)
def trash_message(account: str | None = None, message_id: str = "") -> dict:
    """Move a message to trash (can be recovered with untrash_message)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.trash_message(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def untrash_message(account: str | None = None, message_id: str = "") -> dict:
    """Restore a message from trash back to the inbox."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.untrash_message(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_message(account: str | None = None, message_id: str = "") -> dict:
    """Permanently delete a message (cannot be undone; use trash_message to recover later)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_message(message_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_label(account: str | None = None, label_id: str = "") -> dict:
    """Permanently delete a label from the mailbox."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_label(label_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_filter(account: str | None = None, filter_id: str = "") -> dict:
    """Permanently delete a Gmail filter."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_filter(filter_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def batch_trash_messages(
    account: str | None = None,
    message_ids: list[str] | None = None,
) -> dict:
    """Move multiple messages to trash in a single batch operation."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.batch_trash_messages(message_ids or []))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def batch_untrash_messages(
    account: str | None = None,
    message_ids: list[str] | None = None,
) -> dict:
    """Restore multiple messages from trash in a single batch operation."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.batch_untrash_messages(message_ids or []))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def batch_delete_messages(
    account: str | None = None,
    message_ids: list[str] | None = None,
) -> dict:
    """Permanently delete multiple messages in a single batch operation (cannot be undone)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.batch_delete_messages(message_ids or []))
    return ok(resolved, data)


def main():
    mcp.run()
