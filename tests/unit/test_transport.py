"""
Unit tests for chronos_mcp.transport module.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from chronos_mcp.transport import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TRANSPORT,
    QueryStringTokenMiddleware,
    mask_token,
    create_token_validator,
    get_auth_token,
    get_transport_config,
)


# ---------------------------------------------------------------------------
# get_transport_config
# ---------------------------------------------------------------------------
class TestGetTransportConfig:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = get_transport_config()
        assert cfg["transport"] == DEFAULT_TRANSPORT
        assert cfg["host"] == DEFAULT_HOST
        assert cfg["port"] == DEFAULT_PORT

    def test_custom_values(self):
        env = {
            "CHRONOS_TRANSPORT": "sse",
            "CHRONOS_HOST": "0.0.0.0",
            "CHRONOS_PORT": "9000",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = get_transport_config()
        assert cfg["transport"] == "sse"
        assert cfg["host"] == "0.0.0.0"
        assert cfg["port"] == 9000

    def test_partial_override(self):
        env = {"CHRONOS_PORT": "3000"}
        with patch.dict(os.environ, env, clear=True):
            cfg = get_transport_config()
        assert cfg["transport"] == DEFAULT_TRANSPORT
        assert cfg["host"] == DEFAULT_HOST
        assert cfg["port"] == 3000


# ---------------------------------------------------------------------------
# get_auth_token
# ---------------------------------------------------------------------------
class TestGetAuthToken:
    def test_no_token(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_auth_token() is None

    def test_empty_token(self):
        with patch.dict(os.environ, {"CHRONOS_AUTH_TOKEN": ""}, clear=True):
            assert get_auth_token() is None

    def test_valid_token(self):
        with patch.dict(os.environ, {"CHRONOS_AUTH_TOKEN": "s3cret"}, clear=True):
            assert get_auth_token() == "s3cret"


# ---------------------------------------------------------------------------
# create_token_validator
# ---------------------------------------------------------------------------
class TestCreateTokenValidator:
    def test_matching_token(self):
        validate = create_token_validator("my-token")
        assert validate("my-token") is True

    def test_non_matching_token(self):
        validate = create_token_validator("my-token")
        assert validate("wrong-token") is False

    def test_empty_token(self):
        validate = create_token_validator("my-token")
        assert validate("") is False

    def test_constant_time(self):
        """Validator uses secrets.compare_digest (constant-time)."""
        import secrets

        with patch.object(secrets, "compare_digest", return_value=True) as mock_cmp:
            validate = create_token_validator("tok")
            validate("tok")
            mock_cmp.assert_called_once_with("tok", "tok")


# ---------------------------------------------------------------------------
# mask_token
# ---------------------------------------------------------------------------
class TestMaskToken:
    def test_empty_token(self):
        assert mask_token("") == "<empty>"

    def test_short_token(self):
        assert mask_token("ab") == "a***"

    def test_four_char_token(self):
        assert mask_token("abcd") == "a***"

    def test_long_token(self):
        assert mask_token("my-secret-token") == "my-s***"

    def test_five_char_token(self):
        assert mask_token("abcde") == "abcd***"


# ---------------------------------------------------------------------------
# QueryStringTokenMiddleware
# ---------------------------------------------------------------------------
class TestQueryStringTokenMiddleware:
    @pytest.mark.asyncio
    async def test_injects_bearer_from_query_string(self):
        """Token in query string is converted to Authorization header."""
        captured_scope = {}

        async def inner_app(scope, receive, send):
            captured_scope.update(scope)

        middleware = QueryStringTokenMiddleware(inner_app)
        scope = {
            "type": "http",
            "query_string": b"token=abc123",
            "headers": [],
        }
        await middleware(scope, AsyncMock(), AsyncMock())

        headers = dict(captured_scope["headers"])
        assert headers[b"authorization"] == b"Bearer abc123"

    @pytest.mark.asyncio
    async def test_does_not_override_existing_auth_header(self):
        """Existing Authorization header takes precedence."""
        captured_scope = {}

        async def inner_app(scope, receive, send):
            captured_scope.update(scope)

        middleware = QueryStringTokenMiddleware(inner_app)
        scope = {
            "type": "http",
            "query_string": b"token=qs-token",
            "headers": [(b"authorization", b"Bearer existing-token")],
        }
        await middleware(scope, AsyncMock(), AsyncMock())

        headers = dict(captured_scope["headers"])
        assert headers[b"authorization"] == b"Bearer existing-token"

    @pytest.mark.asyncio
    async def test_no_token_in_query_string(self):
        """Without ?token= the scope is passed through unchanged."""
        captured_scope = {}

        async def inner_app(scope, receive, send):
            captured_scope.update(scope)

        middleware = QueryStringTokenMiddleware(inner_app)
        scope = {
            "type": "http",
            "query_string": b"foo=bar",
            "headers": [],
        }
        await middleware(scope, AsyncMock(), AsyncMock())

        headers = dict(captured_scope.get("headers", []))
        assert b"authorization" not in headers

    @pytest.mark.asyncio
    async def test_empty_query_string(self):
        """Empty query string passes through."""
        captured_scope = {}

        async def inner_app(scope, receive, send):
            captured_scope.update(scope)

        middleware = QueryStringTokenMiddleware(inner_app)
        scope = {
            "type": "http",
            "query_string": b"",
            "headers": [],
        }
        await middleware(scope, AsyncMock(), AsyncMock())

        headers = dict(captured_scope.get("headers", []))
        assert b"authorization" not in headers

    @pytest.mark.asyncio
    async def test_websocket_scope(self):
        """Middleware also handles websocket scopes."""
        captured_scope = {}

        async def inner_app(scope, receive, send):
            captured_scope.update(scope)

        middleware = QueryStringTokenMiddleware(inner_app)
        scope = {
            "type": "websocket",
            "query_string": b"token=ws-token",
            "headers": [],
        }
        await middleware(scope, AsyncMock(), AsyncMock())

        headers = dict(captured_scope["headers"])
        assert headers[b"authorization"] == b"Bearer ws-token"

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self):
        """Non-http/websocket scopes (e.g. lifespan) pass through."""
        captured_scope = {}

        async def inner_app(scope, receive, send):
            captured_scope.update(scope)

        middleware = QueryStringTokenMiddleware(inner_app)
        scope = {"type": "lifespan"}
        await middleware(scope, AsyncMock(), AsyncMock())

        assert captured_scope["type"] == "lifespan"

    @pytest.mark.asyncio
    async def test_multiple_token_params_uses_first(self):
        """When multiple token= params exist, the first is used."""
        captured_scope = {}

        async def inner_app(scope, receive, send):
            captured_scope.update(scope)

        middleware = QueryStringTokenMiddleware(inner_app)
        scope = {
            "type": "http",
            "query_string": b"token=first&token=second",
            "headers": [],
        }
        await middleware(scope, AsyncMock(), AsyncMock())

        headers = dict(captured_scope["headers"])
        assert headers[b"authorization"] == b"Bearer first"
