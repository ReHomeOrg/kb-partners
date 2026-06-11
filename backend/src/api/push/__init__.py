"""Web-push (VAPID) для портала LIGHT (E8, FR-8.1/10.1, ADR-0004).

Хранилище подписок браузера (`PushSubscription`) + регистрация через API портала +
доставка web-push (pywebpush, RFC 8291/8188, self-hosted). Подписка привязана к
владельцу (`owner_id` = requester_id заявителя / partner_id партнёра) и аудитории.
"""
