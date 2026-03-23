"""
HTTP transport configuration for Chronos MCP.

Provides token authentication middleware and transport configuration
helpers for running the MCP server over HTTP with SSE and Streamable
HTTP support.
"""

from __future__ import annotations

import json
import os
import secrets
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


class TokenAuthMiddleware:
    """ASGI middleware that validates a shared-secret token on every HTTP
    request.

    The token may be supplied as a ``?token=<value>`` query-string parameter
    **or** as a ``Bearer`` token in the ``Authorization`` header.  If both
    are present the explicit header takes precedence.

    Requests without a valid token receive a ``401 Unauthorized`` JSON
    response.  Non-HTTP scopes (e.g. ``lifespan``) are passed through
    without authentication.
    """

    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        self.app = app
        self.expected_token = expected_token

    # ------------------------------------------------------------------
    # Token extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _token_from_header(headers: list[tuple[bytes, bytes]]) -> str | None:
        """Extract a Bearer token from the Authorization header."""
        for name, value in headers:
            if name.lower() == b"authorization":
                decoded = value.decode("latin-1")
                if decoded.lower().startswith("bearer "):
                    return decoded[len("bearer "):]
                return None
        return None

    @staticmethod
    def _token_from_query(query_string: bytes) -> str | None:
        """Extract the first ``token`` query-string parameter."""
        if not query_string:
            return None
        params = parse_qs(query_string.decode("latin-1"))
        values = params.get("token")
        return values[0] if values else None

    # ------------------------------------------------------------------

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = list(scope.get("headers", []))

        # 1. Try Authorization header first, then fall back to query string
        header_token = self._token_from_header(headers)
        qs_token = self._token_from_query(scope.get("query_string", b""))
        token = header_token or qs_token

        if token:
            source = "header" if header_token else "query_string"
            logger.debug(
                "Token received (source=%s, token=%s)",
                source,
                mask_token(token),
            )

        # 2. Validate
        if not token or not secrets.compare_digest(token, self.expected_token):
            if token:
                logger.warning(
                    "Token validation failed (received=%s, expected=%s)",
                    mask_token(token),
                    mask_token(self.expected_token),
                )
            else:
                logger.warning("No auth token provided — rejecting request")
            await self._send_401(send)
            return

        logger.debug("Token validation succeeded (token=%s)", mask_token(token))
        await self.app(scope, receive, send)

    # ------------------------------------------------------------------
    # Error response
    # ------------------------------------------------------------------

    @staticmethod
    async def _send_401(send: Send) -> None:
        """Send a 401 Unauthorized JSON response."""
        body = json.dumps(
            {
                "error": "invalid_token",
                "error_description": "Missing or invalid authentication token.",
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer error="invalid_token"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


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
