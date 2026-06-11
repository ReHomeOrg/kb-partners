"""Источник m2m-токена для исходящих вызовов к соседям (NFR-9, ADR-0005).

`TokenProvider` абстрагирует получение Bearer-токена. Боевой механизм — Keycloak
client_credentials (`ClientCredentialsTokenProvider`, `api/clients/oauth.py`); фабрика
`build_token_provider` выбирает его при заполненных OAuth-настройках, иначе fallback —
`StaticTokenProvider` (dev/test-плейсхолдер из env).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from api.config import Settings


@runtime_checkable
class TokenProvider(Protocol):
    async def get_token(self) -> str: ...


class StaticTokenProvider:
    """DEV/TEST-only. Отдаёт фиксированный токен (из env-плейсхолдера)."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_token(self) -> str:
        return self._token


def build_token_provider(settings: Settings, *, fallback_token: str = "") -> TokenProvider:
    """Выбрать боевой провайдер (Keycloak client_credentials) или dev-fallback.

    Заполнены `oauth_token_url`+`oauth_client_id`+`oauth_client_secret` → боевой
    `ClientCredentialsTokenProvider`; иначе — `StaticTokenProvider(fallback_token)`
    (dev/test-плейсхолдер соседа). Реальный механизм подключается env, без правки адаптеров.
    """
    if settings.oauth_token_url and settings.oauth_client_id and settings.oauth_client_secret:
        from api.clients.oauth import ClientCredentialsTokenProvider

        return ClientCredentialsTokenProvider(
            token_url=settings.oauth_token_url,
            client_id=settings.oauth_client_id,
            client_secret=settings.oauth_client_secret,
            timeout=settings.client_timeout_seconds,
        )
    return StaticTokenProvider(fallback_token)
