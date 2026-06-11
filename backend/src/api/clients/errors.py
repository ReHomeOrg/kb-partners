"""Типизированные ошибки слоя HTTP-клиентов к соседям (NFR-9, арх-константа).

Конкретные клиенты ловят эти типы и решают, как деградировать (вернуть кеш/None/
пусто). `ResilientHttpClient` не «глотает» ошибки — типизирует и пробрасывает.
"""

from __future__ import annotations


class ExternalServiceError(Exception):
    """Сбой вызова соседа (после исчерпания retry / неретраибельный).

    Несёт техконтекст для логов/метрик, но НЕ тело ответа соседа (ФЗ-152: не тащим
    потенциальные ПДн в текст исключения дальше необходимого).
    """

    def __init__(self, client: str, operation: str, message: str) -> None:
        self.client = client
        self.operation = operation
        super().__init__(f"{client}.{operation}: {message}")


class CircuitOpenError(ExternalServiceError):
    """Circuit breaker открыт — вызов соседа отклонён без сетевой попытки."""

    def __init__(self, client: str, operation: str) -> None:
        super().__init__(client, operation, "circuit breaker is open")
