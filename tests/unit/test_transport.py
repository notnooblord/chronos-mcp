"""
Unit tests for chronos_mcp.transport module.
"""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from chronos_mcp.transport import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TRANSPORT,
    TokenAuthMiddleware,
    get_auth_token,
    get_transport_config,
    mask_token,
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
# TokenAuthMiddleware
# ---------------------------------------------------------------------------


class TestTokenAuthMiddleware:
    SECRET = "my-secret-token"

    def _make_middleware(self, inner_app=None):
        if inner_app is None:
            inner_app = AsyncMock()
        return TokenAuthMiddleware(inner_app, expected_token=self.SECRET), inner_app

    # --- Valid token via query string ---
    @pytest.mark.asyncio
    async def test_valid_token_query_string(self):
        mw, inner = self._make_middleware()
        scope = {
            "type": "http",
            "query_string": b"token=my-secret-token",
            "headers": [],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    # --- Valid token via Authorization header ---
    @pytest.mark.asyncio
    async def test_valid_token_bearer_header(self):
        mw, inner = self._make_middleware()
        scope = {
            "type": "http",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer my-secret-token")],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    # --- Header takes precedence over query string ---
    @pytest.mark.asyncio
    async def test_header_takes_precedence(self):
        mw, inner = self._make_middleware()
        scope = {
            "type": "http",
            "query_string": b"token=wrong-token",
            "headers": [(b"authorization", b"Bearer my-secret-token")],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    # --- Invalid token returns 401 ---
    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self):
        mw, inner = self._make_middleware()
        send = AsyncMock()
        scope = {
            "type": "http",
            "query_string": b"token=wrong",
            "headers": [],
        }
        await mw(scope, AsyncMock(), send)
        inner.assert_not_awaited()
        # Check that a 401 was sent
        assert send.await_count == 2
        start_msg = send.await_args_list[0][0][0]
        assert start_msg["status"] == 401

    # --- Missing token returns 401 ---
    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self):
        mw, inner = self._make_middleware()
        send = AsyncMock()
        scope = {
            "type": "http",
            "query_string": b"",
            "headers": [],
        }
        await mw(scope, AsyncMock(), send)
        inner.assert_not_awaited()
        start_msg = send.await_args_list[0][0][0]
        assert start_msg["status"] == 401

    # --- 401 response is valid JSON ---
    @pytest.mark.asyncio
    async def test_401_body_is_json(self):
        mw, _ = self._make_middleware()
        send = AsyncMock()
        scope = {
            "type": "http",
            "query_string": b"token=bad",
            "headers": [],
        }
        await mw(scope, AsyncMock(), send)
        body_msg = send.await_args_list[1][0][0]
        body = json.loads(body_msg["body"])
        assert body["error"] == "invalid_token"

    # --- Non-HTTP scope passes through without auth ---
    @pytest.mark.asyncio
    async def test_lifespan_passthrough(self):
        mw, inner = self._make_middleware()
        scope = {"type": "lifespan"}
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    # --- Websocket scope is also validated ---
    @pytest.mark.asyncio
    async def test_websocket_valid_token(self):
        mw, inner = self._make_middleware()
        scope = {
            "type": "websocket",
            "query_string": b"token=my-secret-token",
            "headers": [],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    # --- Empty query string without token → 401 ---
    @pytest.mark.asyncio
    async def test_empty_query_string_401(self):
        mw, inner = self._make_middleware()
        send = AsyncMock()
        scope = {
            "type": "http",
            "query_string": b"foo=bar",
            "headers": [],
        }
        await mw(scope, AsyncMock(), send)
        inner.assert_not_awaited()
        start_msg = send.await_args_list[0][0][0]
        assert start_msg["status"] == 401

    # --- Multiple token params uses first ---
    @pytest.mark.asyncio
    async def test_multiple_token_params_uses_first(self):
        mw, inner = self._make_middleware()
        scope = {
            "type": "http",
            "query_string": b"token=my-secret-token&token=wrong",
            "headers": [],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    # --- Constant-time comparison used ---
    @pytest.mark.asyncio
    async def test_uses_constant_time_comparison(self):
        """Token comparison uses secrets.compare_digest."""
        import secrets

        mw, inner = self._make_middleware()
        with patch.object(secrets, "compare_digest", return_value=True) as mock_cmp:
            scope = {
                "type": "http",
                "query_string": b"token=test",
                "headers": [],
            }
            await mw(scope, AsyncMock(), AsyncMock())
            mock_cmp.assert_called_once_with("test", self.SECRET)

    # --- Bearer prefix is case-insensitive ---
    @pytest.mark.asyncio
    async def test_bearer_case_insensitive(self):
        mw, inner = self._make_middleware()
        scope = {
            "type": "http",
            "query_string": b"",
            "headers": [(b"authorization", b"bearer my-secret-token")],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    # --- Non-Bearer auth header is rejected ---
    @pytest.mark.asyncio
    async def test_non_bearer_auth_header_rejected(self):
        mw, inner = self._make_middleware()
        send = AsyncMock()
        scope = {
            "type": "http",
            "query_string": b"",
            "headers": [(b"authorization", b"Basic dXNlcjpwYXNz")],
        }
        await mw(scope, AsyncMock(), send)
        inner.assert_not_awaited()
        start_msg = send.await_args_list[0][0][0]
        assert start_msg["status"] == 401
