"""Канонический набор тестовых партнёров для сквозного прогона «Консьержа» (dev/test).

Единый источник истины для двух потребителей:
  1. `FixturePlatformClient` (см. `fixture_client.py`) — отдаёт этих партнёров как
     `CollaboratorCandidate`, чтобы matcher работал без живого kb-platform.
  2. seed-скрипт `scripts/seed_test_partners.py` — заводит `PartnerChannelConfig`
     (каналы доставки) в своей БД kb-partners.

Маппинг документа `reHome_Консьерж_тестовые_партнёры.md` на фактическую модель:
  - `slug` → `collaborator_id` (строковая ссылка на реестр, арх-константа ADR-0001).
  - `tags:[test]` → префикс `test-` в `collaborator_id` (фильтр/очистка одним LIKE).
  - `priority 10/50` → matcher ранжирует по `rating`: профили 5.0, агрегатор 3.0
    (поля priority в матчинге нет — агрегатор сам встаёт в хвост `fallback_chain`).
  - `fallback_collaborator_id` → поля нет; `fallback_chain` строится динамически из
    всех eligible-кандидатов по убыванию rating → агрегатор = авто-fallback.
  - `coverage MSK/SPB` → `service_areas` в нижнем регистре (`msk`/`spb`) — конвенция
    группы B реестра kb-platform; matcher сверяет `service_area in service_areas`.
  - `home_repair` → категория `REPAIR` (enum `Category`).
  - `is_aggregator` → поля нет; моделируется данными (3 категории + оба города +
    низкий rating + канал API).

Секреты не хранятся: в `config` каналов только `ENV:`-ссылки (раздел §6 документа).
Это dev/test-данные (config-gated через `KBP_PLATFORM_TEST_FIXTURES`), не production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.channels.enums import ChannelType
from api.clients.platform.models import CollaboratorCandidate, PartnerContact

# Натуральный ключ тест-партнёра = `collaborator_id` с этим префиксом (заменяет
# отсутствующий в модели `tags:[test]`): выборка/очистка одним `LIKE 'test-%'`.
TEST_COLLABORATOR_PREFIX = "test-"

# Категории — значения enum `api.requests.Category` (без импорта, чтобы не тянуть
# доменный слой requests в clients; ср. `CollaboratorCandidate.category: str`).
_CLEANING = "CLEANING"
_MOVING = "MOVING"
_REPAIR = "REPAIR"

# Гео — конвенция нижнего регистра реестра группы B (matcher сверяет дословно).
_MSK = "msk"
_SPB = "spb"

# Рейтинги задают порядок матчинга вместо отсутствующего поля `priority`.
_RATING_PROFILE = 5.0  # профильные партнёры (документ: priority 10 — выше)
_RATING_AGGREGATOR = 3.0  # агрегатор-fallback (документ: priority 50 — ниже)


@dataclass(frozen=True)
class SeedChannel:
    """Канал доставки тест-партнёра для сидов `PartnerChannelConfig` (§6.4).

    `priority` — порядок выбора каналов (ASC, first-success). Документный
    `role: primary` → меньший priority; `role: duplicate` → больший (диспетч берёт
    ОДИН канал по возрастанию priority, копию на email он не шлёт — это фолбэк-канал).
    """

    channel_type: ChannelType
    priority: int
    config: dict[str, Any]


@dataclass(frozen=True)
class TestPartner:
    """Тест-партнёр: и кандидат реестра (matcher), и набор каналов (seed)."""

    collaborator_id: str
    name: str
    category: str
    service_areas: tuple[str, ...]
    rating: float
    contact: PartnerContact
    seed_channels: tuple[SeedChannel, ...]

    @property
    def channel_types(self) -> tuple[str, ...]:
        """Типы каналов в порядке priority — `channels[0]` matcher берёт как основной."""
        return tuple(ch.channel_type.value for ch in self.seed_channels)

    def candidate(self, category: str | None = None) -> CollaboratorCandidate:
        """Кандидат реестра (FR-3.1). Всегда active+available.

        `category` override нужен агрегатору: реестр фильтрует по одной категории за
        запрос, а Профи.ру предлагается во всех (см. `PROFI_AGGREGATOR_CATEGORIES`).
        """
        return CollaboratorCandidate(
            id=self.collaborator_id,
            name=self.name,
            category=category if category is not None else self.category,
            is_active=True,
            available=True,
            rating=self.rating,
            service_areas=self.service_areas,
            channels=self.channel_types,
        )


def _telegram(*, chat_id: str, handle: str) -> SeedChannel:
    """Telegram-канal приёма/обработки (primary, priority=1). Секрет — `ENV:`-ссылкой."""
    return SeedChannel(
        channel_type=ChannelType.TELEGRAM,
        priority=1,
        config={
            "chat_id": chat_id,
            "partner_handle": handle,
            "bot_token_ref": "ENV:TG_BOT_TOKEN_TEST",
        },
    )


def _email(*, to: str) -> SeedChannel:
    """Email-канал-дубль (priority=2 → фолбэк, не копия; см. README)."""
    return SeedChannel(
        channel_type=ChannelType.EMAIL,
        priority=2,
        config={"to": [to]},
    )


# Ровно 5 тест-партнёров (документ §4). Порядок `seed_channels` = порядок priority.
TEST_PARTNERS: tuple[TestPartner, ...] = (
    # §4.1 Клининг — «Чистякофф»
    TestPartner(
        collaborator_id="test-chistyakoff",
        name="Чистякофф (тест)",
        category=_CLEANING,
        service_areas=(_MSK, _SPB),
        rating=_RATING_PROFILE,
        contact=PartnerContact(email="test+chistyakoff@rehome.one", phone="+7 000 000-00-01"),
        seed_channels=(
            _telegram(chat_id="<TG_CHAT_ID_CLEANING>", handle="@test_chistyakoff"),
            _email(to="test+chistyakoff@rehome.one"),
        ),
    ),
    # §4.2 Переезд — «Деликатный переезд СПб» (только SPB)
    TestPartner(
        collaborator_id="test-delikatny-pereezd-spb",
        name="Деликатный переезд СПб (тест)",
        category=_MOVING,
        service_areas=(_SPB,),
        rating=_RATING_PROFILE,
        contact=PartnerContact(email="test+pereezd-spb@rehome.one", phone="+7 000 000-00-02"),
        seed_channels=(
            _telegram(chat_id="<TG_CHAT_ID_MOVING_SPB>", handle="@test_pereezd_spb"),
            _email(to="test+pereezd-spb@rehome.one"),
        ),
    ),
    # §4.3 Переезд — «Деликатный переезд МСК» (только MSK)
    TestPartner(
        collaborator_id="test-delikatny-pereezd-msk",
        name="Деликатный переезд МСК (тест)",
        category=_MOVING,
        service_areas=(_MSK,),
        rating=_RATING_PROFILE,
        contact=PartnerContact(email="test+pereezd-msk@rehome.one", phone="+7 000 000-00-03"),
        seed_channels=(
            _telegram(chat_id="<TG_CHAT_ID_MOVING_MSK>", handle="@test_pereezd_msk"),
            _email(to="test+pereezd-msk@rehome.one"),
        ),
    ),
    # §4.4 Бытовой ремонт — «Ленремонт» (SPB+MSK)
    TestPartner(
        collaborator_id="test-lenremont",
        name="Ленремонт (тест)",
        category=_REPAIR,
        service_areas=(_SPB, _MSK),
        rating=_RATING_PROFILE,
        contact=PartnerContact(email="test+lenremont@rehome.one", phone="+7 000 000-00-04"),
        seed_channels=(
            _telegram(chat_id="<TG_CHAT_ID_REPAIR>", handle="@test_lenremont"),
            _email(to="test+lenremont@rehome.one"),
        ),
    ),
    # §4.5 Агрегатор во всех категориях — «Профи.ру» (API, fallback)
    TestPartner(
        collaborator_id="test-profi-ru",
        name="Профи.ру (тест, агрегатор)",
        category=_CLEANING,  # см. PROFI_AGGREGATOR_CATEGORIES — заводится во всех 3
        service_areas=(_MSK, _SPB),
        rating=_RATING_AGGREGATOR,
        contact=PartnerContact(email="test+profi@rehome.one", phone="+7 000 000-00-05"),
        seed_channels=(
            SeedChannel(
                channel_type=ChannelType.API,
                priority=1,
                config={
                    "base_url": "<PROFI_API_BASE_URL>",
                    "auth_ref": "ENV:PROFI_API_KEY_TEST",
                    "create_order_endpoint": "/orders",
                    "status_callback": "/webhooks/profi",
                },
            ),
        ),
    ),
)

# Агрегатор работает во всех категориях группы B (документ §4.5). Реестр (matcher)
# фильтрует кандидатов по одной категории за запрос, поэтому для подбора Профи.ру
# должен возвращаться в каждой из этих категорий (см. FixturePlatformClient).
PROFI_AGGREGATOR_ID = "test-profi-ru"
PROFI_AGGREGATOR_CATEGORIES: tuple[str, ...] = (_CLEANING, _MOVING, _REPAIR)
