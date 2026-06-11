"""Юнит-тесты политики автономности (E9, FR-9.3)."""

from __future__ import annotations

from api.automation.autonomy import AutonomyLevel, parse_autonomy


def test_parse_known_levels() -> None:
    assert parse_autonomy("classify") is AutonomyLevel.CLASSIFY
    assert parse_autonomy("assign") is AutonomyLevel.ASSIGN
    assert parse_autonomy("DISPATCH") is AutonomyLevel.DISPATCH
    assert parse_autonomy(" Assign ") is AutonomyLevel.ASSIGN


def test_parse_unknown_is_conservative() -> None:
    assert parse_autonomy("") is AutonomyLevel.CLASSIFY
    assert parse_autonomy("nonsense") is AutonomyLevel.CLASSIFY


def test_levels_ordered() -> None:
    assert AutonomyLevel.CLASSIFY < AutonomyLevel.ASSIGN < AutonomyLevel.DISPATCH
