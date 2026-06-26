"""Юнит-тесты фикстурного реестра тест-партнёров + матчинга (acceptance A2–A6).

Документ `reHome_Консьерж_тестовые_партнёры.md`. Чистая логика без БД: проверяем,
что реестр отдаёт ровно 5 тест-партнёров и что matcher разводит их по категории/гео
и строит fallback к агрегатору.
"""

from __future__ import annotations

import pytest

from api.clients.platform.fixture_client import FixturePlatformClient
from api.clients.platform.fixtures import (
    PROFI_AGGREGATOR_CATEGORIES,
    PROFI_AGGREGATOR_ID,
    TEST_COLLABORATOR_PREFIX,
    TEST_PARTNERS,
)
from api.matching.engine import Matcher

_CLIENT = FixturePlatformClient()
_MATCHER = Matcher()


def test_exactly_five_test_partners_all_tagged() -> None:
    # A2: ровно 5 тест-партнёров, у всех натуральный ключ с префиксом `test-`.
    assert len(TEST_PARTNERS) == 5
    assert all(p.collaborator_id.startswith(TEST_COLLABORATOR_PREFIX) for p in TEST_PARTNERS)
    assert len({p.collaborator_id for p in TEST_PARTNERS}) == 5  # slug уникален


async def test_search_returns_only_test_candidates() -> None:
    # A2: реестр возвращает только тест-кандидатов (префикс `test-`).
    for category in ("CLEANING", "MOVING", "REPAIR"):
        candidates = await _CLIENT.search_candidates(category=category)
        assert candidates
        assert all(c.id.startswith(TEST_COLLABORATOR_PREFIX) for c in candidates)
        assert all(c.is_active and c.available for c in candidates)


async def test_category_distribution() -> None:
    # A3: в каждой категории — профиль(и) + агрегатор; moving содержит оба города.
    cleaning = {c.id for c in await _CLIENT.search_candidates(category="CLEANING")}
    moving = {c.id for c in await _CLIENT.search_candidates(category="MOVING")}
    repair = {c.id for c in await _CLIENT.search_candidates(category="REPAIR")}
    assert cleaning == {"test-chistyakoff", PROFI_AGGREGATOR_ID}
    assert moving == {
        "test-delikatny-pereezd-spb",
        "test-delikatny-pereezd-msk",
        PROFI_AGGREGATOR_ID,
    }
    assert repair == {"test-lenremont", PROFI_AGGREGATOR_ID}


async def test_aggregator_offered_in_all_categories() -> None:
    # Профи.ру предлагается во всех своих категориях (override категории в реестре).
    for category in PROFI_AGGREGATOR_CATEGORIES:
        ids = {c.id for c in await _CLIENT.search_candidates(category=category)}
        assert PROFI_AGGREGATOR_ID in ids


async def test_channel_types_primary_first() -> None:
    # A4 (сторона кандидата): профили — TELEGRAM(primary)+EMAIL; агрегатор — API.
    by_id = {p.collaborator_id: p for p in TEST_PARTNERS}
    assert by_id["test-chistyakoff"].channel_types == ("TELEGRAM", "EMAIL")
    assert by_id[PROFI_AGGREGATOR_ID].channel_types == ("API",)
    # matcher берёт channels[0] как канал доставки — должен быть приёмный канал.
    cleaning = await _CLIENT.search_candidates(category="CLEANING")
    result = _MATCHER.rank(cleaning, category="CLEANING")
    assert result is not None
    assert result.partner_id == "test-chistyakoff"  # профиль выше агрегатора по rating
    assert result.delivery_channel == "TELEGRAM"


@pytest.mark.parametrize(
    ("category", "expected_partner"),
    [
        ("CLEANING", "test-chistyakoff"),
        ("REPAIR", "test-lenremont"),
    ],
)
async def test_fallback_chain_ends_with_aggregator(category: str, expected_partner: str) -> None:
    # A5: профиль выбран, агрегатор — последним в fallback_chain (авто-fallback).
    candidates = await _CLIENT.search_candidates(category=category)
    result = _MATCHER.rank(candidates, category=category)
    assert result is not None
    assert result.partner_id == expected_partner
    assert result.fallback_chain[-1] == PROFI_AGGREGATOR_ID


@pytest.mark.parametrize(
    ("service_area", "expected_partner"),
    [
        ("spb", "test-delikatny-pereezd-spb"),
        ("msk", "test-delikatny-pereezd-msk"),
    ],
)
async def test_moving_routed_by_coverage(service_area: str, expected_partner: str) -> None:
    # A6: moving разводится по гео; агрегатор (оба города) — в хвосте fallback.
    candidates = await _CLIENT.search_candidates(category="MOVING", service_area=service_area)
    result = _MATCHER.rank(candidates, category="MOVING", service_area=service_area)
    assert result is not None
    assert result.partner_id == expected_partner
    # Партнёр другого города не попадает даже в fallback (гео-фильтр matcher'а).
    other_city_partner = (
        "test-delikatny-pereezd-msk"
        if expected_partner == "test-delikatny-pereezd-spb"
        else "test-delikatny-pereezd-spb"
    )
    assert other_city_partner not in result.fallback_chain
    assert result.fallback_chain == [PROFI_AGGREGATOR_ID]


async def test_partner_contact_lookup() -> None:
    contact = await _CLIENT.get_partner_contact(partner_id="test-chistyakoff")
    assert contact is not None
    assert contact.email == "test+chistyakoff@rehome.one"
    assert await _CLIENT.get_partner_contact(partner_id="nope") is None
