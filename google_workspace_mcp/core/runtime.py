"""Shared runtime: account resolution + warm-client cache, the read-only gate,
error mapping, and the response envelope. Every tool in every server goes
through these helpers, which is what keeps the five servers aligned.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Optional

import google_auth_core as core
from mcp.types import ToolAnnotations


def _readonly() -> bool:
    return os.getenv("GOOGLE_MCP_READONLY", "").strip().lower() in ("1", "true", "yes", "on")


# Evaluated once at import; servers are launched with the env already set.
READONLY = _readonly()

_api_cache: dict = {}
_lock = threading.Lock()

# Seconds to wait before each retry when a connection to Google could not be
# opened at all (network blip, Wi-Fi/VPN change, wake from sleep).
_CONNECT_RETRY_DELAYS = (2, 5)


def ok(account: str, data: Any, **meta: Any) -> dict:
    """Standard success envelope shared by all tools.

    Extra keyword args are added to the envelope only when not None. The only
    meta key defined today is next_page_token.
    """
    out = {"ok": True, "account": account, "data": data}
    out.update({k: v for k, v in meta.items() if v is not None})
    return out


def get_api(
    service_name: str,
    factory: Callable[[Optional[str]], Any],
    account: Optional[str],
):
    """Resolve ``account``, validate credentials, and return a cached API client.

    Raises :class:`google_auth_core.AuthError` with an actionable message when
    credentials are missing or unusable. Instances are cached per
    ``(service_name, resolved_account)`` so a long-lived server reuses warm
    authorized clients across calls, and different accounts use different
    instances and therefore never interfere.

    Returns ``(api_instance, resolved_account)``.
    """
    _creds, resolved = core.get_credentials(account, service_name=service_name)
    key = (service_name, resolved)
    with _lock:
        inst = _api_cache.get(key)
        if inst is None:
            inst = factory(resolved)
            _api_cache[key] = inst
        return inst, resolved


def reset_api_cache() -> None:
    """Drop all cached API clients (used by tests and after re-auth)."""
    with _lock:
        _api_cache.clear()


def cached_keys() -> list:
    """Return the cached (service, account) keys, for tests/inspection."""
    with _lock:
        return sorted(_api_cache.keys())


def run_tool(fn: Callable[[], Any]) -> Any:
    """Execute an API call, mapping any failure to the shared error taxonomy.

    Failures to open a connection at all are retried after a short wait. The
    request never reached Google in that case, so retrying is safe even for
    writes such as sending mail.
    """
    for delay in (*_CONNECT_RETRY_DELAYS, None):
        try:
            return fn()
        except core.GoogleCoreError:
            raise
        except ValueError as e:
            raise core.InvalidArgumentError(str(e)) from e
        except Exception as e:  # noqa: BLE001 - normalize everything to GoogleCoreError
            if delay is not None and core.is_connect_failure(e):
                time.sleep(delay)
                continue
            raise core.map_exception(e)


def register(
    mcp,
    *,
    mutating: bool = False,
    destructive: bool = False,
    idempotent: bool | None = None,
):
    """Decorator that registers a tool, honoring the read-only gate and
    attaching MCP ToolAnnotations derived from the same flags.

    Mutating tools are not registered at all when ``GOOGLE_MCP_READONLY`` is set,
    so they never appear in ``list_tools``. Destructive tools get a clear marker
    appended to their description.
    """

    def deco(fn: Callable) -> Callable:
        if mutating and READONLY:
            return fn  # skip registration entirely
        if destructive and fn.__doc__:
            fn.__doc__ = fn.__doc__.rstrip() + (
                "\n\n[DESTRUCTIVE] Permanently changes or deletes data; cannot be undone."
            )
        annotations = ToolAnnotations(
            readOnlyHint=not mutating,
            # MCP defaults destructiveHint to True when absent; mutating
            # non-destructive tools must set it False explicitly.
            destructiveHint=destructive if mutating else None,
            idempotentHint=idempotent,
        )
        return mcp.tool(annotations=annotations)(fn)

    return deco
