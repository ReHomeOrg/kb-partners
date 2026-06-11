"""HTTP-роутер входящих от партнёров (§11.3). Публичный (без JWT): аутентификация —
токен в пути + HMAC-подпись + таймстемп (replay-защита). Монтируется под /api/v1/partners.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from api.channels.dependencies import get_inbound_service
from api.channels.inbound import InboundService

router = APIRouter(prefix="/inbound", tags=["Inbound"])


@router.post("/api/{token}", summary="Входящее от партнёра (подписанный webhook)")
async def inbound_api(
    token: str,
    request: Request,
    service: InboundService = Depends(get_inbound_service),
    x_signature: str = Header(alias="X-Signature"),
    x_timestamp: str = Header(alias="X-Timestamp"),
) -> dict[str, str]:
    """E5: HMAC-подписанный webhook партнёра. Дубль по nonce → no-op; статус → FSM."""
    raw_body = await request.body()
    return await service.handle_api(
        token=token, raw_body=raw_body, signature=x_signature, timestamp=x_timestamp
    )
