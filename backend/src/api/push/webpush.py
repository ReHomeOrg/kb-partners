"""Доставка web-push (VAPID, RFC 8291/8188) через pywebpush (E8, ADR-0004).

«Разрабатываем сами» = self-hosted без внешнего сервиса; крипто (ECDH/aes128gcm/HKDF)
не хэндроллим — берём проверенную pywebpush. Config-gated: пустой VAPID-ключ → инертно.
Блокирующий вызов оборачиваем в asyncio.to_thread. ПДн не передаём — только номер
заявки + нейтральная сводка. Истёкшая подписка (404/410) → удаляется владельцем.
"""

from __future__ import annotations

import asyncio
import json

from pywebpush import WebPushException, webpush

from api.config import Settings
from api.observability.logging import get_logger
from api.push.models import PushSubscription

_logger = get_logger("push.webpush")


class SubscriptionExpired(Exception):
    """Подписка отозвана push-сервисом (404/410) — её следует удалить."""


def _send_blocking(subscription: PushSubscription, body: str, settings: Settings) -> None:
    webpush(
        subscription_info={
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
        },
        data=body,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
    )


async def send_webpush(
    subscription: PushSubscription, *, number: str, summary: str, settings: Settings
) -> bool:
    """Отправить web-push. Инертно без VAPID-ключа. 404/410 → SubscriptionExpired.

    Возвращает True при доставке; иные сбои → False+WARN (best-effort, без ПДн в логе).
    """
    if not settings.vapid_private_key or not settings.vapid_subject:
        return False
    body = json.dumps({"title": f"Заявка {number}", "body": summary})
    try:
        await asyncio.to_thread(_send_blocking, subscription, body, settings)
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            raise SubscriptionExpired(str(status)) from exc
        _logger.warning("webpush degraded: status=%s number=%s", status, number)
        return False
    return True
