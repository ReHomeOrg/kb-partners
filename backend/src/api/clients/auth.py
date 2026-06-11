"""Источник m2m-токена для исходящих вызовов к соседям (NFR-9).

`TokenProvider` абстрагирует получение Bearer-токена, чтобы реальный механизм
(Keycloak Client Credentials) подставился позже без правки адаптеров.

`StaticTokenProvider` — **только dev/test**: токен из конфига-плейсхолдера. Реальный
`ClientCredentialsTokenProvider` — после провижининга m2m-realm (отдельный Issue).
В prod-сборке фабрика обязана fail-closed выбирать реальный провайдер.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TokenProvider(Protocol):
    async def get_token(self) -> str: ...


class StaticTokenProvider:
    """DEV/TEST-only. Отдаёт фиксированный токен (из env-плейсхолдера)."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_token(self) -> str:
        return self._token
