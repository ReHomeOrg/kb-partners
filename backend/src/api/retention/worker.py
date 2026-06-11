"""Воркер ретенции ПДн (NFR-12, 152-ФЗ): обезличивание просроченного raw_input.

`raw_input` (сырой ввод заявителя — ПДн) по истечении `raw_input_retention_days`
перезаписывается уже посчитанной при приёме маской `raw_input_masked` (PII-free).
Маскированная сводка сохраняется → заявка/история остаются операционно-пригодными,
но сырые ПДн больше не хранятся. Действие фиксируется в `RequestHistory(ANONYMIZED)`
под системным `RETENTION_ACTOR_ID`. Идемпотентно (после обезличивания строка
выпадает из выборки). Инертно при выключенном `retention_worker_enabled`.
"""

from __future__ import annotations

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.system_actors import RETENTION_ACTOR_ID
from api.config import Settings
from api.observability.logging import get_logger
from api.requests.enums import HistoryAction
from api.requests.models import RequestHistory
from api.requests.repository import RequestRepository

_logger = get_logger("retention")


async def anonymize_expired_raw_input(
    session: AsyncSession, *, settings: Settings, now: datetime.datetime | None = None
) -> int:
    """Обезличить заявки с raw_input старше ретенции. Возвращает число обработанных."""
    if not settings.retention_worker_enabled:
        return 0
    moment = now or datetime.datetime.now(datetime.UTC)
    cutoff = moment - datetime.timedelta(days=settings.raw_input_retention_days)
    repo = RequestRepository(session)
    rows = await repo.list_raw_input_expired(cutoff, limit=settings.outbox_batch_size)
    for request in rows:
        # Обезличивание: сырой ПДн → уже посчитанная PII-безопасная маска.
        request.raw_input = request.raw_input_masked
        session.add(
            RequestHistory(
                request_id=request.id,
                actor_id=RETENTION_ACTOR_ID,
                action=HistoryAction.ANONYMIZED,
                to_value="raw_input",
            )
        )
    await session.commit()
    _logger.info("retention anonymize: processed=%d cutoff=%s", len(rows), cutoff.isoformat())
    return len(rows)
