"""Pydantic-схемы API заявок (контракт §11.1). Источник истины — docs/openapi.yaml.

Тела приёма (E1): `RequestCreate` (браузер/m2m), `FromChatCreate` (kb-search),
`FromTicketCreate` (kb-support). Ответ `RequestRead` НЕ содержит `raw_input` (ПДн):
наружу — только ссылки-идентификаторы и состояние (NFR-5, FR-1.6).

`channel_in` для `POST /requests` НЕ принимается от клиента (выводится бэкендом из
типа субъекта) — защита от подмены канала; `MESSENGER_INBOUND` ставит только
контур inbound (E5). `from-chat`/`from-ticket` фиксируют канал жёстко.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from api.requests.enums import Category, ChannelIn, RequestStatus

# Предел длины свободного ввода (анти-абьюз публичной формы, NFR-11).
_MAX_RAW_INPUT = 20_000
_MAX_ID = 255


class RequestCreate(BaseModel):
    """Тело `POST /requests` — приём из ЛК-формы или m2m-инициатора (FR-1.1/FR-1.4)."""

    model_config = ConfigDict(extra="forbid")

    raw_input: str = Field(min_length=1, max_length=_MAX_RAW_INPUT)
    requester_id: str | None = Field(
        default=None,
        max_length=_MAX_ID,
        description=(
            "Пользователь rehome.one. Для заявителя игнорируется (берётся из токена); "
            "для оператора/агента/сервиса задаёт, от чьего имени создаётся заявка."
        ),
    )
    booking_id: str | None = Field(default=None, max_length=_MAX_ID)
    premises_id: str | None = Field(default=None, max_length=_MAX_ID)
    source_ref: dict[str, Any] | None = Field(
        default=None, description="Провенанс источника (необязателен для ЛК-формы)."
    )


class FromChatCreate(BaseModel):
    """Тело `POST /requests/from-chat` — инициация из AI-чата kb-search (FR-1.2)."""

    model_config = ConfigDict(extra="forbid")

    chat_session_id: str = Field(min_length=1, max_length=_MAX_ID)
    requester_id: str = Field(min_length=1, max_length=_MAX_ID)
    raw_input: str = Field(min_length=1, max_length=_MAX_RAW_INPUT)
    transcript: list[dict[str, Any]] | None = Field(
        default=None, description="Реплики диалога — переносятся в source_ref."
    )
    booking_id: str | None = Field(default=None, max_length=_MAX_ID)
    premises_id: str | None = Field(default=None, max_length=_MAX_ID)


class FromTicketCreate(BaseModel):
    """Тело `POST /requests/from-ticket` — эскалация из тикета kb-support (FR-1.3)."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(min_length=1, max_length=_MAX_ID)
    requester_id: str = Field(min_length=1, max_length=_MAX_ID)
    raw_input: str = Field(min_length=1, max_length=_MAX_RAW_INPUT)
    booking_id: str | None = Field(default=None, max_length=_MAX_ID)
    premises_id: str | None = Field(default=None, max_length=_MAX_ID)


class RequestRead(BaseModel):
    """Представление заявки наружу. Без `raw_input` (ПДн, FR-1.6/NFR-5).

    `allowed_transitions` (для карточки) добавляется в read-эндпоинте M1.3.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    requester_id: str
    channel_in: ChannelIn
    category: Category | None
    status: RequestStatus
    created_at: datetime.datetime
