"""Юнит-тесты ранжирования партнёров (E3, §4.5)."""

from __future__ import annotations

from api.clients.platform.models import CollaboratorCandidate
from api.matching.engine import Matcher

_MATCHER = Matcher()


def _candidate(
    cid: str,
    *,
    category: str = "CLEANING",
    is_active: bool = True,
    available: bool = True,
    rating: float | None = 4.0,
    service_areas: tuple[str, ...] = (),
    channels: tuple[str, ...] = ("API",),
) -> CollaboratorCandidate:
    return CollaboratorCandidate(
        id=cid,
        name=cid,
        category=category,
        is_active=is_active,
        available=available,
        rating=rating,
        service_areas=service_areas,
        channels=channels,
    )


def test_rank_picks_highest_rating_and_builds_fallback() -> None:
    result = _MATCHER.rank(
        [_candidate("a", rating=4.0), _candidate("b", rating=4.9), _candidate("c", rating=4.5)],
        category="CLEANING",
    )
    assert result is not None
    assert result.partner_id == "b"
    assert result.fallback_chain == ["c", "a"]  # по убыванию рейтинга, без выбранного
    assert result.delivery_channel == "API"
    assert result.match_trace["method"] == "auto"
    assert len(result.match_trace["candidates"]) == 3


def test_rank_filters_by_category() -> None:
    result = _MATCHER.rank(
        [_candidate("a", category="MOVING"), _candidate("b", category="CLEANING")],
        category="CLEANING",
    )
    assert result is not None
    assert result.partner_id == "b"


def test_rank_excludes_inactive_unavailable_or_no_channel() -> None:
    result = _MATCHER.rank(
        [
            _candidate("a", is_active=False),
            _candidate("b", available=False),
            _candidate("c", channels=()),
        ],
        category="CLEANING",
    )
    assert result is None


def test_rank_geo_filter_excludes_other_areas() -> None:
    result = _MATCHER.rank(
        [_candidate("a", service_areas=("spb",)), _candidate("b", service_areas=("msk",))],
        category="CLEANING",
        service_area="msk",
    )
    assert result is not None
    assert result.partner_id == "b"


def test_rank_candidate_without_areas_serves_anywhere() -> None:
    result = _MATCHER.rank(
        [_candidate("a", service_areas=())], category="CLEANING", service_area="msk"
    )
    assert result is not None
    assert result.partner_id == "a"


def test_rank_returns_none_when_no_candidates() -> None:
    assert _MATCHER.rank([], category="CLEANING") is None


def test_rank_tie_break_by_id() -> None:
    result = _MATCHER.rank(
        [_candidate("b", rating=4.0), _candidate("a", rating=4.0)], category="CLEANING"
    )
    assert result is not None
    assert result.partner_id == "a"  # одинаковый рейтинг → id по возрастанию
