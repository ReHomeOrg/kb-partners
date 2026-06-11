"""Юнит-тесты EmailChannel (E4/E5, §9.2, ADR-0004) — SMTP через инъекцию sender."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from api.channels.adapters.email import EmailChannel
from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.protocol import ChannelConfig, DeliveryPayload
from api.config import Settings

_SMTP = Settings(notify_smtp_host="smtp.local", notify_email_from="no-reply@rehome.one")


def _config(email: str = "partner@example.com") -> ChannelConfig:
    return ChannelConfig(
        collaborator_id="c-1",
        channel_type=ChannelType.EMAIL,
        priority=10,
        config={"email": email} if email else {},
    )


def _payload() -> DeliveryPayload:
    return DeliveryPayload(
        request_id="r1",
        number="RQ-1",
        category="CLEANING",
        summary="уборка",
        params={},
        idempotency_key="dispatch:r1:1",
    )


async def test_deliver_sends_email_via_injected_sender() -> None:
    sent: list[EmailMessage] = []
    channel = EmailChannel(_SMTP, sender=lambda msg, s: sent.append(msg))
    result = await channel.deliver(_payload(), _config())
    assert result.outcome is DeliveryOutcome.SENT
    assert sent and sent[0]["To"] == "partner@example.com"
    assert "RQ-1" in str(sent[0]["Subject"])


async def test_deliver_missing_email_config_fails() -> None:
    channel = EmailChannel(_SMTP, sender=lambda msg, s: None)
    result = await channel.deliver(_payload(), _config(email=""))
    assert result.outcome is DeliveryOutcome.FAILED
    assert result.provider_response["error"] == "missing_email_config"


async def test_deliver_inert_without_smtp() -> None:
    channel = EmailChannel(Settings(), sender=lambda msg, s: None)
    result = await channel.deliver(_payload(), _config())
    assert result.outcome is DeliveryOutcome.FAILED


async def test_deliver_smtp_error_degrades() -> None:
    def boom(msg: EmailMessage, s: Settings) -> None:
        raise smtplib.SMTPException("down")

    result = await EmailChannel(_SMTP, sender=boom).deliver(_payload(), _config())
    assert result.outcome is DeliveryOutcome.FAILED
    assert result.provider_response["error"] == "SMTPException"


async def test_parse_inbound_maps_status() -> None:
    update = await EmailChannel(_SMTP).parse_inbound(
        {"request_ref": "r1", "status": "rejected"}, _config()
    )
    assert update is not None and update.outcome is DeliveryOutcome.FAILED


async def test_healthcheck_reflects_config() -> None:
    assert (await EmailChannel(_SMTP).healthcheck(_config())).status is HealthStatus.HEALTHY
    assert (await EmailChannel(Settings()).healthcheck(_config())).status is HealthStatus.UNHEALTHY
