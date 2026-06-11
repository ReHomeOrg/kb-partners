"""Доступ к хранилищу заявок (собственная БД kb-partners, арх-константа ADR-0001).

Только свои таблицы (`service_requests`, ...). Данные соседей (Collaborator,
ServiceOrder, User) сюда НЕ джойнятся — резолвятся по HTTP через `api/clients/`.
Коммит — ответственность вызывающего слоя/сервиса (паттерн `get_session`).
"""

from __future__ import annotations

from sqlalchemy import Sequence, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.requests.models import ServiceRequest

__all__ = ["RequestRepository"]

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
