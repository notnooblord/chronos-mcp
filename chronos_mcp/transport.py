"""
HTTP transport configuration for Chronos MCP.

Provides query-string token authentication middleware and transport
configuration helpers for running the MCP server over HTTP with
SSE and Streamable HTTP support.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

from .logging_config import setup_logging

logger = setup_logging()

# Environment variable names
ENV_AUTH_TOKEN = "CHRONOS_AUTH_TOKEN"
ENV_TRANSPORT = "CHRONOS_TRANSPORT"
ENV_HOST = "CHRONOS_HOST"
ENV_PORT = "CHRONOS_PORT"

# Defaults
DEFAULT_HOST = "::"
DEFAULT_PORT = 8000
DEFAULT_TRANSPORT = "http"


class QueryStringTokenMiddleware:
    """ASGI middleware that extracts a ``token`` query-string parameter and
    injects it as a ``Bearer`` token in the ``Authorization`` header.

    This allows clients to authenticate via ``?token=<value>`` in the URL
    instead of (or in addition to) sending a standard ``Authorization``
    header.  If both are present the explicit header takes precedence.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            query_string = scope.get("query_string", b"")
            if query_string:
                params = parse_qs(query_string.decode("latin-1"))
                token_values = params.get("token")
                if token_values:
                    # Only inject if no Authorization header is already present
                    headers = list(scope.get("headers", []))
                    has_auth = any(
                        name.lower() == b"authorization" for name, _ in headers
                    )
                    if not has_auth:
                        logger.debug(
                            "Injecting query-string token as Bearer header (token=%s)",
                            mask_token(token_values[0]),
                        )
                        headers.append(
                            (
                                b"authorization",
                                f"Bearer {token_values[0]}".encode("latin-1"),
                            )
                        )
                        scope = dict(scope, headers=headers)
                    else:
                        logger.debug(
                            "Authorization header already present, skipping "
                            "query-string token injection"
                        )

        await self.app(scope, receive, send)


def get_transport_config() -> dict:
    """Read transport configuration from environment variables.

    Returns a dict with keys ``transport``, ``host``, and ``port``.
    """
    return {
        "transport": os.environ.get(ENV_TRANSPORT, DEFAULT_TRANSPORT),
        "host": os.environ.get(ENV_HOST, DEFAULT_HOST),
        "port": int(
            os.environ.get(ENV_PORT) or os.environ.get("PORT") or str(DEFAULT_PORT)
        ),
    }


def get_auth_token() -> str | None:
    """Return the expected auth token from the environment, or ``None``."""
    return os.environ.get(ENV_AUTH_TOKEN) or None


def mask_token(token: str) -> str:
    """Return a masked version of *token* safe for logging.

    Shows the first 4 characters followed by ``***``.  For very short
    tokens (≤4 chars) only the first character is shown.
    """
    if not token:
        return "<empty>"
    if len(token) <= 4:
        return token[0] + "***"
    return token[:4] + "***"


def create_token_validator(expected_token: str) -> Callable[[str], bool]:
    """Return a callable suitable for ``DebugTokenVerifier(validate=...)``.

    Uses constant-time comparison to avoid timing attacks.
    """

    def _validate(token: str) -> bool:
        result = secrets.compare_digest(token, expected_token)
        if result:
            logger.debug("Token validation succeeded (token=%s)", mask_token(token))
        else:
            logger.warning(
                "Token validation failed (received=%s, expected=%s)",
                mask_token(token),
                mask_token(expected_token),
            )
        return result

    return _validate
