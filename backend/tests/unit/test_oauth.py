"""Юнит-тесты OAuth2-провайдеров токенов (ADR-0005, FR-9.7) — без сети (MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from api.clients.auth import StaticTokenProvider, build_token_provider
from api.clients.errors import ExternalServiceError
from api.clients.oauth import ClientCredentialsTokenProvider, TokenExchangeProvider
from api.config import Settings

_TOKEN_URL = "https://kc/realms/r/protocol/openid-connect/token"


def _transport(handler: object) -> httpx.MockTransport:
    return httpx.MockTransport(handler)  # type: ignore[arg-type]


async def test_client_credentials_fetches_and_caches() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert b"grant_type=client_credentials" in request.content
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 300})

    clock = {"t": 1000.0}
    provider = ClientCredentialsTokenProvider(
        token_url=_TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        transport=_transport(handler),
        now=lambda: clock["t"],
    )
    assert await provider.get_token() == "AT"
    # В пределах TTL — кеш, без второго запроса.
    assert await provider.get_token() == "AT"
    assert calls["n"] == 1
    # После истечения (300 - 30 запас) — рефреш.
    clock["t"] += 300
    assert await provider.get_token() == "AT"
    assert calls["n"] == 2


async def test_client_credentials_error_raises() -> None:
    provider = ClientCredentialsTokenProvider(
        token_url=_TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        transport=_transport(lambda r: httpx.Response(401)),
    )
    with pytest.raises(ExternalServiceError):
        await provider.get_token()


async def test_token_exchange_includes_requested_subject() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "grant-type%3Atoken-exchange" in body or "token-exchange" in body
        assert "requested_subject=user-1" in body
        return httpx.Response(200, json={"access_token": "DELEGATED"})

    provider = TokenExchangeProvider(
        token_url=_TOKEN_URL, client_id="cid", client_secret="sec", transport=_transport(handler)
    )
    token = await provider.exchange(subject_token="agent-tok", requested_subject="user-1")
    assert token == "DELEGATED"


def test_build_token_provider_dev_fallback() -> None:
    # Без OAuth-настроек → StaticTokenProvider с placeholder соседа.
    provider = build_token_provider(Settings(), fallback_token="dev-tok")
    assert isinstance(provider, StaticTokenProvider)


def test_build_token_provider_real_when_configured() -> None:
    settings = Settings(
        oauth_token_url=_TOKEN_URL, oauth_client_id="cid", oauth_client_secret="sec"
    )
    assert isinstance(build_token_provider(settings), ClientCredentialsTokenProvider)
