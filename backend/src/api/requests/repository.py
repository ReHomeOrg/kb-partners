"""Доступ к хранилищу заявок (собственная БД kb-partners, арх-константа ADR-0001).

Только свои таблицы (`service_requests`, ...). Данные соседей (Collaborator,
ServiceOrder, User) сюда НЕ джойнятся — резолвятся по HTTP через `api/clients/`.
Коммит — ответственность вызывающего слоя/сервиса (паттерн `get_session`).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from sqlalchemy import DateTime, Sequence, and_, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.requests.access import ownership_condition, visible_access_levels
from api.requests.enums import Category, RequestStatus
from api.requests.models import RequestMessage, ServiceRequest
from api.requests.pagination import Cursor

__all__ = ["RequestRepository", "RequestListFilters"]


@dataclass(frozen=True)
class RequestListFilters:
    """Фильтры списка заявок (§11.1): status / category / partner_id / период."""

    status: RequestStatus | None = None
    category: Category | None = None
    partner_id: str | None = None
    created_from: datetime.datetime | None = None
    created_to: datetime.datetime | None = None


# Последовательность человекочитаемых номеров (создана миграцией M1.1).
_NUMBER_SEQUENCE = Sequence("service_request_number_seq")


class RequestRepository:
    """Репозиторий заявок-на-услугу."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_number(self) -> str:
        """Выдать следующий человекочитаемый номер заявки (RQ-NNNNNNNN)."""
        seq_val = await self._session.scalar(select(_NUMBER_SEQUENCE.next_value()))
        return f"RQ-{int(seq_val or 0):08d}"

    async def get_by_idempotency_key(self, key: str) -> ServiceRequest | None:
        """Найти заявку по ключу идемпотентности приёма (дедуп, §6.1)."""
        stmt = select(ServiceRequest).where(ServiceRequest.idempotency_key == key)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def add(self, request: ServiceRequest) -> None:
        """Поставить заявку в сессию (flush/commit — у сервиса)."""
        self._session.add(request)

    async def get_visible(
        self, principal: Principal, request_id: uuid.UUID, *, for_update: bool = False
    ) -> ServiceRequest | None:
        """Заявка, видимая субъекту (контур + владение). Иначе None → 404 у сервиса."""
        stmt = select(ServiceRequest).where(
            ServiceRequest.id == request_id,
            ServiceRequest.access_level.in_(visible_access_levels(principal)),
        )
        cond = ownership_condition(principal)
        if cond is not None:
            stmt = stmt.where(cond)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_visible(
        self,
        principal: Principal,
        filters: RequestListFilters,
        *,
        cursor: Cursor | None,
        limit: int,
    ) -> list[ServiceRequest]:
        """Видимые субъекту заявки с фильтрами и keyset-пагинацией.

        Возвращает до `limit + 1` строк (хвостовая — маркер наличия следующей
        страницы; сервис её отрезает и кодирует курсор).
        """
        stmt = select(ServiceRequest).where(
            ServiceRequest.access_level.in_(visible_access_levels(principal))
        )
        cond = ownership_condition(principal)
        if cond is not None:
            stmt = stmt.where(cond)
        if filters.status is not None:
            stmt = stmt.where(ServiceRequest.status == filters.status)
        if filters.category is not None:
            stmt = stmt.where(ServiceRequest.category == filters.category)
        if filters.partner_id is not None:
            stmt = stmt.where(ServiceRequest.partner_id == filters.partner_id)
        if filters.created_from is not None:
            stmt = stmt.where(ServiceRequest.created_at >= filters.created_from)
        if filters.created_to is not None:
            stmt = stmt.where(ServiceRequest.created_at <= filters.created_to)
        if cursor is not None:
            cur_ts, cur_id = cursor
            stmt = stmt.where(
                or_(
                    ServiceRequest.created_at < cur_ts,
                    and_(
                        ServiceRequest.created_at == cur_ts,
                        ServiceRequest.id < cur_id,
                    ),
                )
            )
        stmt = stmt.order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
        stmt = stmt.limit(limit + 1)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_accept_overdue(
        self, now: datetime.datetime, *, limit: int
    ) -> list[ServiceRequest]:
        """DISPATCHED-заявки с просроченным сырым `accept_deadline` (грубый пред-фильтр).

        Берёт строки FOR UPDATE SKIP LOCKED (конкурентные сканеры не пересекаются).
        Сырой дедлайн `< now` — НЕОБХОДИМОЕ условие breach (паузы только отодвигают
        эффективный дедлайн позже); точный breach подтверждает `SlaPolicy.evaluate`
        у вызывающего (time_based-движок, E6).
        """
        accept_deadline = cast(
            ServiceRequest.sla["accept_deadline"].astext, DateTime(timezone=True)
        )
        stmt = (
            select(ServiceRequest)
            .where(
                ServiceRequest.status == RequestStatus.DISPATCHED,
                accept_deadline.isnot(None),
                accept_deadline < now,
            )
            .order_by(accept_deadline.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def add_message(self, message: RequestMessage) -> None:
        """Поставить сообщение/заметку в сессию (commit — у сервиса)."""
        self._session.add(message)

    async def list_messages(
        self, request_id: uuid.UUID, *, include_internal: bool
    ) -> list[RequestMessage]:
        """Сообщения заявки в хронологии. `include_internal=False` скрывает заметки (правило 10)."""
        stmt = select(RequestMessage).where(RequestMessage.request_id == request_id)
        if not include_internal:
            stmt = stmt.where(RequestMessage.is_internal.is_(False))
        stmt = stmt.order_by(RequestMessage.created_at.asc(), RequestMessage.id.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
