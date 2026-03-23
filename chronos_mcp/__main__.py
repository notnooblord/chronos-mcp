#!/usr/bin/env python3
"""
Main entry point for Chronos MCP.

Supports both stdio (default when no CHRONOS_TRANSPORT is set) and HTTP
transports.  When running over HTTP the server listens on ``::`` port
``8000`` by default and can be configured via environment variables:

    CHRONOS_TRANSPORT  – "http" (default for HTTP, supports both SSE and
                         Streamable HTTP), "sse", or "streamable-http"
    CHRONOS_HOST       – bind address (default "::")
    CHRONOS_PORT       – bind port   (default 8000)
    CHRONOS_AUTH_TOKEN – if set, every HTTP request must include this
                         token either as a ``?token=`` query-string
                         parameter or as a ``Bearer`` token in the
                         ``Authorization`` header.
"""

from starlette.middleware import Middleware

from .server import mcp
from .transport import (QueryStringTokenMiddleware, get_auth_token,
                        get_transport_config)

if __name__ == "__main__":
    transport_cfg = get_transport_config()
    transport = transport_cfg["transport"]

    if transport in ("http", "sse", "streamable-http"):
        middleware = []
        if get_auth_token():
            middleware.append(Middleware(QueryStringTokenMiddleware))

        mcp.run(
            transport=transport,
            host=transport_cfg["host"],
            port=transport_cfg["port"],
            middleware=middleware,
        )
    else:
        # Default: stdio transport (standard MCP behavior)
        mcp.run(transport=transport)
