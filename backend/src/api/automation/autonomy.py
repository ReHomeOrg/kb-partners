"""Политика автономности агента/автоматизации (E9, FR-9.3).

Уровень определяет, как далеко авто-пайплайн ведёт заявку без человека:
- CLASSIFY — только классификация (дальше — оператор/агент вручную);
- ASSIGN   — классификация + подбор/назначение;
- DISPATCH — полный цикл до диспетчеризации.

Низкая уверенность/нет партнёра/нет канала и так уводят в human-handoff (FR-9.4);
уровень — дополнительный конфигурируемый предохранитель (FR-9.3).
"""

from __future__ import annotations

import enum


class AutonomyLevel(enum.IntEnum):
    CLASSIFY = 1
    ASSIGN = 2
    DISPATCH = 3


def parse_autonomy(value: str) -> AutonomyLevel:
    """Разобрать уровень из конфигурации; неизвестное → консервативно CLASSIFY."""
    mapping = {
        "classify": AutonomyLevel.CLASSIFY,
        "assign": AutonomyLevel.ASSIGN,
        "dispatch": AutonomyLevel.DISPATCH,
    }
    return mapping.get(value.strip().lower(), AutonomyLevel.CLASSIFY)
