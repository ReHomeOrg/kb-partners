"""CRM-каналы доставки (§9.2, ADR-0004): Bitrix24 + amoCRM.

«Разрабатываем сами»: свои HTTP-адаптеры поверх `ResilientHttpClient` (без вендорских
SDK). Создают лид/сделку в CRM партнёра по REST. Дискриминатор `crm_type` в config канала
выбирает реализацию; endpoint/секреты — в config (ссылка на kb-vault), в URL/заголовке.

- **Bitrix24:** входящий webhook `{base}/crm.lead.add.json` (токен в URL-path конфига).
- **amoCRM:** `POST /api/v4/leads`, Bearer OAuth2-токен из config.

В лид — только минимальный состав по категории (FR-4.6): номер/категория/описание-маска.
"""

from __future__ import annotations

from typing import Any

from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.protocol import (
    ChannelConfig,
    DeliveryPayload,
    DeliveryResult,
    Health,
    StatusUpdate,
)
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError

_INBOUND_STATUS: dict[str, DeliveryOutcome] = {
    "accepted": DeliveryOutcome.ACK,
    "delivered": DeliveryOutcome.DELIVERED,
    "rejected": DeliveryOutcome.FAILED,
    "failed": DeliveryOutcome.FAILED,
}


def _lead_title(payload: DeliveryPayload) -> str:
    return f"Заявка {payload.number} [{payload.category}]"


def _lead_comment(payload: DeliveryPayload) -> str:
    return payload.summary  # маскированное описание, без ПДн (FR-4.6)


def _parse_inbound(payload: dict[str, Any]) -> StatusUpdate | None:
    ref = payload.get("request_ref") or payload.get("external_ref")
    status = payload.get("status")
    if ref is None or not isinstance(status, str):
        return None
    outcome = _INBOUND_STATUS.get(status.lower())
    if outcome is None:
        return None
    return StatusUpdate(request_ref=str(ref), outcome=outcome, raw=payload)


class Bitrix24Channel:
    """Bitrix24 через входящий webhook (`crm.lead.add.json`). Токен — в `webhook_path` конфига."""

    channel_type = ChannelType.CRM

    def __init__(self, http: ResilientHttpClient) -> None:
        self._http = http

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        # webhook_path: "/rest/<user_id>/<token>/" — секрет из config (ссылка на kb-vault).
        webhook = str(config.config.get("webhook_path", "")).rstrip("/")
        if not webhook:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": "missing_webhook"}
            )
        body = {
            "fields": {"TITLE": _lead_title(payload), "COMMENTS": _lead_comment(payload)},
            "params": {"REGISTER_SONET_EVENT": "N"},
        }
        try:
            response = await self._http.request(
                "POST", f"{webhook}/crm.lead.add.json", operation="deliver", json=body
            )
        except ExternalServiceError as exc:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": type(exc).__name__}
            )
        if response.status_code >= 400:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"status": response.status_code}
            )
        return DeliveryResult(
            outcome=DeliveryOutcome.SENT,
            provider_response={"status": response.status_code},
            external_ref=_bitrix_ref(response),
        )

    async def parse_inbound(
        self, payload: dict[str, Any], config: ChannelConfig
    ) -> StatusUpdate | None:
        return _parse_inbound(payload)

    async def healthcheck(self, config: ChannelConfig) -> Health:
        webhook = str(config.config.get("webhook_path", "")).rstrip("/")
        if not webhook:
            return Health(status=HealthStatus.UNHEALTHY, detail="missing webhook_path")
        try:
            response = await self._http.request(
                "GET", f"{webhook}/profile.json", operation="healthcheck"
            )
        except ExternalServiceError:
            return Health(status=HealthStatus.UNHEALTHY, detail="unreachable")
        if response.status_code >= 400:
            return Health(status=HealthStatus.DEGRADED, detail=f"status={response.status_code}")
        return Health(status=HealthStatus.HEALTHY)


class AmoCrmChannel:
    """amoCRM через REST `POST /api/v4/leads` (Bearer OAuth2-токен из config)."""

    channel_type = ChannelType.CRM

    def __init__(self, http: ResilientHttpClient) -> None:
        self._http = http

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        token = str(config.config.get("access_token", ""))
        if not token:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": "missing_token"}
            )
        body = [{"name": _lead_title(payload), "_embedded": {"tags": [{"name": payload.category}]}}]
        try:
            response = await self._http.request(
                "POST",
                "/api/v4/leads",
                operation="deliver",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
        except ExternalServiceError as exc:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": type(exc).__name__}
            )
        if response.status_code >= 400:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"status": response.status_code}
            )
        return DeliveryResult(
            outcome=DeliveryOutcome.SENT, provider_response={"status": response.status_code}
        )

    async def parse_inbound(
        self, payload: dict[str, Any], config: ChannelConfig
    ) -> StatusUpdate | None:
        return _parse_inbound(payload)

    async def healthcheck(self, config: ChannelConfig) -> Health:
        token = str(config.config.get("access_token", ""))
        if not token:
            return Health(status=HealthStatus.UNHEALTHY, detail="missing access_token")
        try:
            response = await self._http.request(
                "GET",
                "/api/v4/account",
                operation="healthcheck",
                headers={"Authorization": f"Bearer {token}"},
            )
        except ExternalServiceError:
            return Health(status=HealthStatus.UNHEALTHY, detail="unreachable")
        if response.status_code >= 400:
            return Health(status=HealthStatus.DEGRADED, detail=f"status={response.status_code}")
        return Health(status=HealthStatus.HEALTHY)


def _bitrix_ref(response: Any) -> str | None:
    """ID созданного лида (Bitrix: {"result": <id>})."""
    try:
        data = response.json()
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("result") is not None:
        return str(data["result"])
    return None


class RehomeCrmChannel:
    """Доставка в НАШУ CRM (rehome.one): подрядчик ведёт заявку внутри нашей системы.

    Отличается от Bitrix24/amoCRM тем, что получатель — не сторонняя система, а наш
    же контур. Отсюда два следствия.

    Первое: гейт не OAuth партнёра, а сервис-ключ (`X-Internal-Service-Key`) — тот
    же механизм, которым ходят прочие соседи платформы.

    Второе: контакт и адрес НЕ передаются. kb-partners их не хранит, и тащить
    персональные данные с платформы сюда, чтобы вернуть обратно, — лишний круг.
    Передаём идентификаторы объекта и брони, а контакт разрешает приёмная сторона,
    у которой эти данные и так есть.

    Идемпотентность — на стороне приёма, по `external_ref`: повтор доставки
    возвращает ту же карточку и не откатывает её стадию.
    """

    channel_type = ChannelType.CRM

    def __init__(self, http: ResilientHttpClient) -> None:
        self._http = http

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        service_key = str(config.config.get("service_key", ""))
        if not service_key:
            # Config-gated: без ключа канал инертен, а не «доставил как-нибудь».
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": "missing_service_key"}
            )
        body: dict[str, Any] = {
            "external_ref": payload.request_id,
            "number": payload.number,
            "category": payload.category,
            "subject": _lead_title(payload),
            "description": payload.summary,
        }
        if payload.premises_id:
            body["premises_id"] = payload.premises_id
        if payload.booking_id:
            body["booking_id"] = payload.booking_id
        try:
            response = await self._http.request(
                "POST",
                "/api/v1/internal/crm/services/tickets",
                operation="deliver",
                headers={"X-Internal-Service-Key": service_key},
                json=body,
            )
        except ExternalServiceError as exc:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": type(exc).__name__}
            )
        if response.status_code >= 400:
            # 422 означает, что контакт или адрес не разрешились: карточка без них
            # бесполезна, и доставка честно считается неуспешной.
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"status": response.status_code}
            )
        return DeliveryResult(
            outcome=DeliveryOutcome.SENT,
            provider_response={"status": response.status_code},
            external_ref=_rehome_ref(response),
        )

    async def parse_inbound(
        self, payload: dict[str, Any], config: ChannelConfig
    ) -> StatusUpdate | None:
        """Обратный поток: стадия (и оценка) из нашей CRM приходят сюда.

        Наша CRM ходит тем же подписанным webhook'ом, что и внешние партнёры: HMAC
        по секрету канала, проверка свежести и дедуп по nonce уже есть в приёме.
        Отдельный доверенный путь для «своих» пришлось бы охранять заново.
        """
        return _parse_inbound(payload)

    async def healthcheck(self, config: ChannelConfig) -> Health:
        """Доступность нашего же контура. Ключ отсутствует — канал неисправен."""
        if not str(config.config.get("service_key", "")):
            return Health(status=HealthStatus.UNHEALTHY, detail="missing_service_key")
        return Health(status=HealthStatus.HEALTHY)


def _rehome_ref(response: Any) -> str | None:
    """Идентификатор карточки на нашей доске — для сверки при разборе."""
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 — тело не обязано быть JSON
        return None
    value = data.get("id") if isinstance(data, dict) else None
    return str(value) if value else None
