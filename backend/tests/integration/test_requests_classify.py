"""Интеграционные тесты классификации (E2, FR-2.1–2.6, acceptance E2).

Использует общие фикстуры `make_client` / `make_principal` / `seed` из conftest.py.
Классификатор работает по `raw_input_masked` (FR-1.6); LLM в тестах инертен
(NullLLMProvider) → проверяется детерминированный rules-путь.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.requests.enums import HistoryAction, RequestStatus
from api.requests.models import RequestHistory, ServiceRequest

_BASE = "/api/v1/partners/requests"

PrincipalFactory = Callable[..., Principal]
SeedFactory = Callable[..., Awaitable[ServiceRequest]]


async def test_unambiguous_input_classified_via_rules(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
) -> None:
    operator = make_principal(PrincipalKind.OPERATOR)
    req = await seed(raw_input_masked="Нужна уборка квартиры", status=RequestStatus.NEW)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/classify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "CLEANING"
    assert body["status"] == "CLASSIFIED"
    # Rules-путь без LLM (FR-2.2) + трассировка (FR-2.6).
    assert body["classification"]["method"] == "rules"
    assert body["classification"]["confidence"] >= 0.7


async def test_low_confidence_goes_to_needs_review(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
) -> None:
    operator = make_principal(PrincipalKind.OPERATOR)
    req = await seed(raw_input_masked="просто текст без смысла", status=RequestStatus.NEW)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/classify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "OTHER"
    assert body["status"] == "NEEDS_REVIEW"  # FR-2.4


async def test_classification_traceability_and_history(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
    session: AsyncSession,
) -> None:
    operator = make_principal(PrincipalKind.OPERATOR)
    req = await seed(raw_input_masked="нужен переезд в субботу", status=RequestStatus.NEW)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/classify")
    classification = resp.json()["classification"]
    assert {"confidence", "model", "version", "method", "classified_at", "params"} <= set(
        classification
    )
    hist = await session.scalar(
        select(RequestHistory).where(
            RequestHistory.request_id == req.id,
            RequestHistory.action == HistoryAction.CLASSIFIED,
        )
    )
    assert hist is not None
    assert hist.to_value == "MOVING"
    assert hist.from_value == "rules"


async def test_agent_can_classify_on_behalf(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
) -> None:
    user = uuid.uuid4()
    agent = make_principal(PrincipalKind.AGENT, on_behalf_of=user)
    req = await seed(requester_id=str(user), raw_input_masked="починить кран, ремонт")
    resp = await make_client(agent).post(f"{_BASE}/{req.id}/classify")
    assert resp.status_code == 200
    assert resp.json()["category"] == "REPAIR"


async def test_requester_cannot_classify_403(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
) -> None:
    owner = make_principal(PrincipalKind.REQUESTER)
    req = await seed(requester_id=str(owner.user_id))
    resp = await make_client(owner).post(f"{_BASE}/{req.id}/classify")
    assert resp.status_code == 403


async def test_classify_foreign_request_404(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
) -> None:
    req = await seed(requester_id="other")
    stranger = make_principal(PrincipalKind.REQUESTER)
    resp = await make_client(stranger).post(f"{_BASE}/{req.id}/classify")
    assert resp.status_code == 404


async def test_classify_terminal_status_409(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
) -> None:
    operator = make_principal(PrincipalKind.OPERATOR)
    req = await seed(status=RequestStatus.PAID)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/classify")
    assert resp.status_code == 409


async def test_reclassify_classified_stays_when_confident(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
) -> None:
    operator = make_principal(PrincipalKind.OPERATOR)
    req = await seed(raw_input_masked="уборка", status=RequestStatus.CLASSIFIED)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/classify")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CLASSIFIED"
    assert resp.json()["category"] == "CLEANING"


async def test_reclassify_classified_drops_to_needs_review(
    make_client: Callable[..., AsyncClient],
    make_principal: PrincipalFactory,
    seed: SeedFactory,
) -> None:
    operator = make_principal(PrincipalKind.OPERATOR)
    req = await seed(raw_input_masked="текст без признаков", status=RequestStatus.CLASSIFIED)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/classify")
    assert resp.status_code == 200
    assert resp.json()["status"] == "NEEDS_REVIEW"
