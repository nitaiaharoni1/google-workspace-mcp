"""search_contacts, registered on every server that needs name-to-email lookup."""
from __future__ import annotations

import google_auth_core as core

from ..core import get_api, ok, register, run_tool
from .people_api import PeopleAPI


def _api(account=None, service_name=None):
    # Resolve with the host server's service name so GMAIL_ACCOUNT /
    # GOOGLE_CALENDAR_ACCOUNT defaults apply, while the client cache stays keyed
    # on "people" and never collides with the host server's own client.
    resolved = core.resolve_account(account) if account else core.get_default_account(service_name)
    return get_api("people", PeopleAPI, resolved)


def register_contacts_tools(mcp, service_name: str | None = None) -> None:
    @register(mcp)
    def search_contacts(
        account: str | None = None,
        *,
        query: str,
        max_results: int = 10,
    ) -> dict:
        """Find people's email addresses by name (or partial email) before sending mail or inviting them.

        Searches saved contacts, people this account has emailed with, and (for
        Workspace accounts) the company directory. Each result has name, emails,
        phone, and source ('contact', 'other', or 'directory'). 'skipped' lists
        sources that could not be searched and why. Google warms its search index
        on the first call, so if the first search after startup finds nothing,
        retry once before concluding the person isn't there.
        """
        if not query.strip():
            raise core.InvalidArgumentError("query is required, e.g. a first name like 'Dana'")
        if max_results < 1:
            raise core.InvalidArgumentError("max_results must be at least 1")
        api, resolved = _api(account, service_name)
        data = run_tool(lambda: api.search(query, max_results=max_results))
        return ok(resolved, data)
