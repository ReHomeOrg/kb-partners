"""Фикстурный `PlatformClient` для dev/test — реестр из встроенных тест-партнёров.

Config-gated stand-in (`KBP_PLATFORM_TEST_FIXTURES=true`) на месте `HttpPlatformClient`:
matcher и сквозной сценарий «Консьержа» работают без живого kb-platform. Это легальный
mock dev/test-контура (как `MockChannel`/`StubBroker`/`NullLLMProvider`), не прямой
доступ к чужой БД — арх-константа ADR-0001 соблюдена. В production флаг всегда false.

Деградации/кеша нет (данные локальные): контракт `PlatformClient` сохранён один-в-один.
"""

from __future__ import annotations

from api.clients.platform.fixtures import (
    PROFI_AGGREGATOR_CATEGORIES,
    PROFI_AGGREGATOR_ID,
    TEST_PARTNERS,
)
from api.clients.platform.models import CollaboratorCandidate, PartnerContact, ServiceOrderRef


class FixturePlatformClient:
    """`PlatformClient` поверх `TEST_PARTNERS`. Гео-фильтрацию делает matcher."""

    async def search_candidates(
        self, *, category: str, service_area: str | None = None
    ) -> list[CollaboratorCandidate]:
        # Фильтр по категории (как реестр); гео отсекает matcher по `service_areas`.
        # Агрегатор предлагается в каждой своей категории с override категории.
        candidates: list[CollaboratorCandidate] = []
        for partner in TEST_PARTNERS:
            if partner.collaborator_id == PROFI_AGGREGATOR_ID:
                if category in PROFI_AGGREGATOR_CATEGORIES:
                    candidates.append(partner.candidate(category))
            elif partner.category == category:
                candidates.append(partner.candidate())
        return candidates

    async def get_partner_contact(self, *, partner_id: str) -> PartnerContact | None:
        for partner in TEST_PARTNERS:
            if partner.collaborator_id == partner_id:
                return partner.contact
        return None

    async def create_service_order(
        self, *, request_id: str, partner_id: str, category: str, idempotency_key: str
    ) -> ServiceOrderRef | None:
        # Заглушка заказа: реальный ServiceOrder живёт в kb-platform (ADR-0002).
        return ServiceOrderRef(id=f"test-order:{request_id}:{partner_id}", status="CREATED")
