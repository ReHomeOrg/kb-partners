"""HTTP-реализация platform-клиента реестра партнёров (E3, FR-3.1) поверх фундамента.

Провизорный контракт kb-platform API (ADR-0002) изолирован ЗДЕСЬ: `_map_candidate`
мапит провизорный JSON → доменный DTO. Смена upstream = правка только маппера + ADR.

Деградация (NFR-9): недоступность соседа (`ExternalServiceError`/`CircuitOpenError`),
4xx и битый JSON → пустой список с WARN-логом (не тихое проглатывание). В лог НЕ
попадает тело ответа (ФЗ-152) — только operation/status. Кешируется только 200.
"""

from __future__ import annotations

import json
from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.cache import Cache
from api.clients.errors import ExternalServiceError
from api.clients.platform.models import CollaboratorCandidate, ServiceOrderRef
from api.observability.logging import get_logger

_logger = get_logger("clients.platform")

_CANDIDATES_PATH = "/api/v1/collaborators"
_SERVICE_ORDERS_PATH = "/api/v1/service-orders"


def _map_candidate(
    d: dict[str, Any],
) -> CollaboratorCandidate:  # provisional contract, see ADR-0002
    return CollaboratorCandidate(
        id=str(d["id"]),
        name=d["name"],
        category=d["category"],
        is_active=bool(d.get("is_active", False)),
        available=bool(d.get("available", False)),
        rating=d.get("rating"),
        service_areas=tuple(d.get("service_areas", ())),
        channels=tuple(d.get("channels", ())),
    )


class HttpPlatformClient:
    """`PlatformClient` поверх `ResilientHttpClient` + `Cache`.

    Зависимости инъектируются явно (тесты — без сети/Redis). Реестр партнёров —
    справочные read-only данные, кешируются (cache-aside, без ПДн в ключе).
    """

    def __init__(
        self,
        *,
        http_client: ResilientHttpClient,
        token_provider: TokenProvider,
        cache: Cache,
        cache_ttl_seconds: int,
    ) -> None:
        self._http = http_client
        self._token_provider = token_provider
        self._cache = cache
        self._ttl = cache_ttl_seconds

    async def search_candidates(
        self, *, category: str, service_area: str | None = None
    ) -> list[CollaboratorCandidate]:
        cache_key = f"platform:candidates:{category}:{service_area or '*'}"
        raw = await self._fetch_candidates(category, service_area, cache_key)
        if raw is None:
            return []
        candidates: list[CollaboratorCandidate] = []
        for item in raw:
            try:
                candidates.append(_map_candidate(item))
            except (KeyError, TypeError, ValueError):
                # Провизорный контракт разошёлся по одному элементу — пропускаем его,
                # не роняя весь подбор (деградация поэлементно).
                _logger.warning("platform search_candidates: skipped malformed candidate")
        return candidates

    async def create_service_order(
        self, *, request_id: str, partner_id: str, category: str, idempotency_key: str
    ) -> ServiceOrderRef | None:
        """Создать/привязать ServiceOrder (FR-3.5). Идемпотентность — заголовком на m2m.

        НЕ кешируется (запись). Деградация: недоступность/4xx/битый JSON → None + WARN.
        """
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key}
        body = {"request_id": request_id, "partner_id": partner_id, "category": category}
        try:
            response = await self._http.request(
                "POST",
                _SERVICE_ORDERS_PATH,
                operation="create_service_order",
                headers=headers,
                json=body,
            )
        except ExternalServiceError as exc:
            _logger.warning("platform create_service_order degraded: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            _logger.warning(
                "platform create_service_order degraded: status=%d", response.status_code
            )
            return None
        try:
            payload: dict[str, Any] = response.json()
            return ServiceOrderRef(id=str(payload["id"]), status=str(payload["status"]))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            _logger.warning("platform create_service_order degraded: malformed JSON")
            return None

    async def _fetch_candidates(
        self, category: str, service_area: str | None, cache_key: str
    ) -> list[dict[str, Any]] | None:
        cached = await self._cache.get(cache_key)
        if cached is not None:
            parsed: list[dict[str, Any]] = json.loads(cached)
            return parsed

        params = {"category": category, "group": "B"}
        if service_area is not None:
            params["service_area"] = service_area
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await self._http.request(
                "GET",
                _CANDIDATES_PATH,
                operation="search_candidates",
                headers=headers,
                params=params,
            )
        except ExternalServiceError as exc:
            _logger.warning("platform search_candidates degraded: %s", type(exc).__name__)
            return None

        if response.status_code >= 400:
            _logger.warning("platform search_candidates degraded: status=%d", response.status_code)
            return None

        try:
            payload: list[dict[str, Any]] = response.json()
        except (ValueError, json.JSONDecodeError):
            _logger.warning("platform search_candidates degraded: malformed JSON")
            return None
        if not isinstance(payload, list):
            _logger.warning("platform search_candidates degraded: expected JSON array")
            return None

        await self._cache.set(cache_key, json.dumps(payload), self._ttl)
        return payload
