"""Build an MCPServer preconfigured with the shared common tools."""

from __future__ import annotations

from typing import Any, Optional

import google_auth_core as core
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .common_tools import register_common_tools


class WorkspaceServer(MCPServer):
    """MCPServer that keeps our anticipated errors readable by the model.

    Since mcp 2.x, an exception that is not a ``ToolError`` reaches the client
    only as "Error executing tool <name>", its text logged server-side. Our
    ``GoogleCoreError`` messages (e.g. "Run: google-auth login <account>") and
    argument ``ValueError``s are meant for the model, so re-raise them as
    ``ToolError`` with their text.
    """

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as e:
            cause = e.__cause__
            if isinstance(cause, (core.GoogleCoreError, ValueError)):
                raise ToolError(f"Error executing tool {name}: {cause}") from cause
            raise


def build_server(
    name: str,
    instructions: Optional[str] = None,
    service_name: Optional[str] = None,
) -> MCPServer:
    """Create an MCPServer with the common account/auth tools registered.

    Service-specific tools are added by each server module after calling this.
    """
    mcp = WorkspaceServer(name, instructions=instructions)
    register_common_tools(mcp, service_name=service_name)
    return mcp
