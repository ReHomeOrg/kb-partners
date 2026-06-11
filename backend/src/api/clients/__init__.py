"""Слой HTTP-клиентов kb-partners к соседям (rehome-kb-platform, rehome.one, …).

Generic resilience-фундамент (NFR-9): timeout → circuit breaker → retry+backoff →
метрики, cache-aside. Конкретные клиенты строятся поверх и изолируют провизорный
контракт соседа за adapter'ом (ADR-0002).

Связь с соседями — ТОЛЬКО по HTTP (арх-константа ADR-0001): без shared-кода/SQL.
Свой код (правило «разрабатываем сами»), без внешних resilience-либ.
"""

from __future__ import annotations

from api.clients.base import ResilientHttpClient
from api.clients.cache import Cache, InMemoryCache, RedisCache
from api.clients.circuit_breaker import CircuitBreaker, CircuitState
from api.clients.errors import CircuitOpenError, ExternalServiceError
from api.clients.retry import RetryPolicy, retry_async

__all__ = [
    "ResilientHttpClient",
    "Cache",
    "InMemoryCache",
    "RedisCache",
    "CircuitBreaker",
    "CircuitState",
    "CircuitOpenError",
    "ExternalServiceError",
    "RetryPolicy",
    "retry_async",
]
