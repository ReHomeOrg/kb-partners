"""Подбор партнёра (эпик E3, §4.5).

Критичный модуль (CLAUDE-REVIEWER.md): объяснимость выбора (`match_trace`) и
формирование `fallback_chain`. Ранжирование — чистая функция над кандидатами
реестра (`CollaboratorCandidate`), без сети и БД; источник кандидатов —
`api/clients/platform` (арх-константа: только по HTTP).
"""

from __future__ import annotations
