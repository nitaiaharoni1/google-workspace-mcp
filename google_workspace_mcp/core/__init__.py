"""Shared MCP core: server builder, runtime helpers, and the response envelope."""

from .runtime import (
    DEFAULT_MAX_CHARS,
    READONLY,
    cached_keys,
    cap_items,
    cap_text,
    get_api,
    ok,
    register,
    reset_api_cache,
    run_tool,
)
from .server import build_server

__all__ = [
    "build_server",
    "get_api",
    "register",
    "run_tool",
    "ok",
    "reset_api_cache",
    "cached_keys",
    "READONLY",
    "DEFAULT_MAX_CHARS",
    "cap_text",
    "cap_items",
]
