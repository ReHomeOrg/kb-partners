"""Ядро заявки-на-услугу `ServiceRequest` (ТЗ §6–§7, веха M1).

Критичный модуль (CLAUDE-REVIEWER.md): FSM + двухконтурность (`access_level`) +
инвариант `is_internal`. Доменная логика приёма (E1), классификации (E2),
подбора (E3) и диспетчеризации (E4) подключается по эпикам.
"""

from __future__ import annotations
