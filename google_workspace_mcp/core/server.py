"""Build a FastMCP server preconfigured with the shared common tools."""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from .common_tools import register_common_tools


def build_server(name: str, instructions: Optional[str] = None) -> FastMCP:
    """Create a FastMCP server with the common account/auth tools registered.

    Service-specific tools are added by each server module after calling this.
    """
    mcp = FastMCP(name, instructions=instructions)
    register_common_tools(mcp)
    return mcp
