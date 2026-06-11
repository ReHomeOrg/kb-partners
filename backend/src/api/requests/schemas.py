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

from api.requests.enums import AuthorType, Category, ChannelIn, RequestStatus

# Предел длины свободного ввода (анти-абьюз публичной формы, NFR-11).
_MAX_RAW_INPUT = 20_000
_MAX_ID = 255
_MAX_MESSAGE = 20_000


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


class RequestDetail(RequestRead):
    """Карточка заявки (§11.1): + `allowed_transitions` (источник истины — бэкенд, §7).

    `raw_input` маскируется по scope (FR-1.6/FR-4.6): оператору/владельцу — исходник,
    партнёру — `raw_input_masked`. Поле строит сервис (не прямой ORM-маппинг).
    """

    partner_id: str | None
    product_code: str | None
    booking_id: str | None
    premises_id: str | None
    delivery_channel: str | None
    service_order_id: str | None
    amount_ref: str | None
    escrow_ref: str | None
    dispute_id: str | None
    claim_ref: str | None
    updated_at: datetime.datetime
    raw_input: str
    classification: dict[str, Any] | None
    sla: dict[str, Any] | None
    # match_trace / fallback_chain — операторская объяснимость подбора; раскрываются
    # только сотрудникам (раскрытие конкурентов-партнёров заявителю/партнёру недопустимо).
    match_trace: dict[str, Any] | None
    fallback_chain: list[str] | None
    allowed_transitions: list[RequestStatus]


class AttachmentRef(BaseModel):
    """Ссылка на вложение в kb-files (FR-1.5). Секреты/байты не инлайнятся."""

    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1, max_length=_MAX_ID)
    filename: str | None = Field(default=None, max_length=_MAX_ID)
    content_type: str | None = Field(default=None, max_length=128)


class MessageCreate(BaseModel):
    """Тело `POST /requests/{id}/messages` (§11.1).

    `is_internal=True` — внутренняя заметка; доступна только операторам (CLAUDE.md
    правило 10), сервис отклоняет её от заявителя/партнёра (403).
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=_MAX_MESSAGE)
    is_internal: bool = False
    attachments: list[AttachmentRef] = Field(default_factory=list)


class MessageRead(BaseModel):
    """Сообщение/заметка заявки. Внутренние заметки в выдаче — только операторам."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_type: AuthorType
    author_id: str | None
    is_internal: bool
    text: str
    attachments: list[dict[str, Any]]
    created_at: datetime.datetime


class TransitionRequest(BaseModel):
    """Тело `POST /requests/{id}/transition` — переход FSM (валидируется по §7)."""

    model_config = ConfigDict(extra="forbid")

    target: RequestStatus


class CancelRequest(BaseModel):
    """Тело `POST /requests/{id}/cancel` — отмена с обязательной причиной (§11.1)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=_MAX_MESSAGE)


class DisputeRequest(BaseModel):
    """Тело `POST /requests/{id}/dispute` — открыть спор с причиной (FR-7.2)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=_MAX_MESSAGE)


class SettlementConfirm(BaseModel):
    """Тело `POST /requests/{id}/settlement` — подтверждение расчёта контуром (FR-7.3)."""

    model_config = ConfigDict(extra="forbid")

    amount_ref: str | None = Field(default=None, max_length=_MAX_ID)
    escrow_ref: str | None = Field(default=None, max_length=_MAX_ID)


class AssignRequest(BaseModel):
    """Тело `POST /requests/{id}/assign` (§11.1, E3).

    `partner_id` задан → ручное назначение/переназначение (FR-3.4). Пусто →
    авто-подбор по реестру (`service_area` — опциональный гео-фильтр, FR-3.1).
    """

    model_config = ConfigDict(extra="forbid")

    partner_id: str | None = Field(default=None, max_length=_MAX_ID)
    service_area: str | None = Field(default=None, max_length=_MAX_ID)


class RequesterContextResponse(BaseModel):
    """Контекст заявителя из rehome.one (§11.1, operator/agent). Все поля опциональны."""

    user_display_name: str | None = None
    user_phone: str | None = None
    user_email: str | None = None
    premises_address: str | None = None
    booking_status: str | None = None


class RequestListResponse(BaseModel):
    """Страница списка заявок: элементы + курсор следующей страницы (или null)."""

    items: list[RequestRead]
    next_cursor: str | None
