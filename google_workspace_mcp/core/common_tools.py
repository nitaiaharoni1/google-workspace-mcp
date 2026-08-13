"""Tools present in every server: list_accounts, auth_status, whoami.

These are credential/account utilities that do not depend on a specific Google
service, so they are identical across all five servers.
"""

from __future__ import annotations

from typing import Optional

import google_auth_core as core

from .runtime import register


def register_common_tools(mcp, service_name: Optional[str] = None) -> None:
    @register(mcp)
    def list_accounts() -> dict:
        """List configured Google accounts, the default account, and aliases."""
        return {
            "ok": True,
            "data": {
                "accounts": core.list_accounts(),
                "default": core.get_default_account(service_name),
                "aliases": core.get_account_aliases(),
            },
        }

    @register(mcp)
    def auth_status(account: Optional[str] = None) -> dict:
        """Report token health for one account, or all accounts if omitted."""
        accounts = [core.resolve_account(account)] if account else core.list_accounts()
        statuses = {
            a: core.check_token_health(a, "unified", core.ALL_SCOPES) for a in accounts
        }
        return {"ok": True, "data": statuses}

    @register(mcp)
    def whoami(account: Optional[str] = None) -> dict:
        """Resolve an account or alias and report its credential status.

        Does not call any Google API; use service-specific tools for live data.
        """
        try:
            _creds, resolved = core.get_credentials(account, service_name=service_name)
        except core.AuthError as e:
            resolved = (
                core.resolve_account(account)
                if account
                else core.get_default_account(service_name)
            )
            return {"ok": False, "account": resolved, "data": {"error": str(e)}}
        health = core.check_token_health(resolved, "unified", core.ALL_SCOPES)
        return {
            "ok": True,
            "account": resolved,
            "data": {"account": resolved, "health": health},
        }
