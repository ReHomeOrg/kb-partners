"""Config-gated seam-каналы уведомлений push/SMS/email (E8, FR-8.1/8.2, §4.9).

Каналы — **seam'ы, инертные до ops**: включаются непустым токеном/хостом
(`notify_push_token` / `notify_sms_token` / `notify_smtp_host`). Выключен → DEBUG-
намерение БЕЗ ПДн, доставка не выполняется. Включён → пока лишь фиксирует намерение
(боевая доставка через провайдера push/SMS-шлюз/SMTP + резолв контакта адресата
через rehome.one — отдельным ADR, принцип «разрабатываем сами», правило 6).

ФЗ-152: контакт адресата (телефон/email/push-токен — ПДн) здесь НЕ запрашивается и
НЕ логируется. В лог идут только номер заявки + адресат-роль + нейтральная сводка.
Каждый канал best-effort: возвращает «попытался?», исключения не выбрасывает.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from api.config import Settings
from api.notifications.events import NotifyAudience
from api.observability.logging import get_logger

_logger = get_logger("notifications.channels")


@dataclass(frozen=True)
class NotificationNotice:
    """Плоский DTO для seam-доставки — только не-ПДн значения."""

    request_id: uuid.UUID
    number: str
    audience: NotifyAudience
    summary: str  # нейтральная RU-сводка статуса, без ПДн


def maybe_push(notice: NotificationNotice, settings: Settings) -> bool:
    """Доставка push (seam). Выключен (`notify_push_token` пуст) → DEBUG-намерение."""
    if not settings.notify_push_token:
        _logger.debug("push notification skipped: channel off number=%s", notice.number)
        return False
    # Боевой путь (push-провайдер + резолв push-токена адресата) — follow-up после ops/ADR.
    _logger.info(
        "push notification pending ops delivery: number=%s audience=%s",
        notice.number,
        notice.audience.value,
    )
    return True


def maybe_sms(notice: NotificationNotice, settings: Settings) -> bool:
    """Доставка SMS (seam). Выключен (`notify_sms_token` пуст) → DEBUG-намерение."""
    if not settings.notify_sms_token:
        _logger.debug("sms notification skipped: channel off number=%s", notice.number)
        return False
    # Боевой путь (SMS-шлюз РФ + резолв телефона адресата) — follow-up после ops/ADR.
    _logger.info(
        "sms notification pending ops delivery: number=%s audience=%s",
        notice.number,
        notice.audience.value,
    )
    return True


def maybe_email(notice: NotificationNotice, settings: Settings) -> bool:
    """Доставка email (seam). Выключен (`notify_smtp_host` пуст) → DEBUG-намерение."""
    if not settings.notify_smtp_host:
        _logger.debug("email notification skipped: channel off number=%s", notice.number)
        return False
    # Боевой путь (SMTP в РФ + резолв email адресата) — follow-up после ops/ADR.
    _logger.info(
        "email notification pending ops delivery: number=%s audience=%s",
        notice.number,
        notice.audience.value,
    )
    return True
