"""Application settings via pydantic-settings.

Все настройки загружаются из env (или `.env` файла для local dev).
Префикс env-переменных: `KBP_*` (`KBP_DATABASE_URL`, `KBP_DATABASE_POOL_SIZE`, ...).

На bootstrap'е (M0) — DB, observability, Keycloak-валидатор и resilience-параметры
HTTP-клиентов к соседям. Доменные настройки (классификатор, каналы доставки,
SLA-воркер, провайдеры уведомлений) добавляются по мере эпиков M1–M7.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Глобальные настройки сервиса."""

    model_config = SettingsConfigDict(
        env_prefix="KBP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- База данных (своя, не shared — арх-константа) ---
    database_url: str = Field(
        default="postgresql+asyncpg://kbpartners:devpass@localhost:5434/kbpartners",
        description=(
            "PostgreSQL async DSN (asyncpg driver). TLS на этом этапе не enforce'ится; "
            "для prod добавить sslmode=require + sslrootcert через query string."
        ),
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_pool_max_overflow: int = Field(default=20, ge=0, le=200)
    database_echo: bool = Field(
        default=False,
        description="SQLAlchemy echo для debug. В production — всегда False.",
    )
    log_level: str = Field(
        default="INFO",
        description="Уровень JSON-логирования (DEBUG/INFO/WARNING/ERROR).",
    )
    history_retention_days: int = Field(
        default=1825,
        ge=1,
        description=(
            "Срок хранения RequestHistory (аудит). Фактический cleanup-воркер — "
            "отдельный Issue; здесь только конфигурируемая политика."
        ),
    )
    raw_input_retention_days: int = Field(
        default=180,
        ge=1,
        description=(
            "Ретенция ПДн-содержащего raw_input (NFR-12, 152-ФЗ right-to-forget). "
            "По истечении — обезличивание/удаление; в LLM и логи идут только *_masked."
        ),
    )

    # --- Keycloak Bearer JWT (#29-аналог). Пустой auth_jwks_url → auth не
    # сконфигурирован (fail-closed 401). Issuer/audience задаются в окружении деплоя.
    # aud токена фронта/агента ДОЛЖЕН содержать `kb-partners` (verify_aud). ---
    auth_jwks_url: str = Field(
        default="",
        description="URL JWKS Keycloak (.../protocol/openid-connect/certs).",
    )
    auth_issuer: str = Field(default="", description="Ожидаемый iss токена (пусто → не проверять).")
    auth_audience: str = Field(
        default="", description="Ожидаемый aud токена (пусто → не проверять)."
    )
    auth_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    auth_leeway: int = Field(default=0, ge=0, description="Допуск по времени (сек) для exp/nbf.")
    auth_jwks_cache_ttl: int = Field(
        default=300, ge=1, description="TTL кеша JWKS (сек) до принудительного рефреша."
    )

    # --- HTTP-клиенты к соседям (resilience и кеш). Конкретные base-URL —
    # ниже; параметры устойчивости общие (timeout → breaker → retry → метрики). ---
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="URL Redis для кеша HTTP-клиентов и брокера. Пусто/недоступен → кеш off.",
    )
    client_timeout_seconds: float = Field(
        default=5.0, gt=0, description="Таймаут одного HTTP-вызова к соседу (сек)."
    )
    client_retry_attempts: int = Field(
        default=3, ge=1, le=10, description="Всего попыток вызова (включая первую)."
    )
    client_retry_base_delay: float = Field(
        default=0.1, gt=0, description="Базовая задержка backoff (сек): base * 2**(n-1)."
    )
    client_retry_max_delay: float = Field(
        default=2.0, gt=0, description="Потолок задержки backoff (сек)."
    )
    client_breaker_failure_threshold: int = Field(
        default=5, ge=1, description="Подряд ошибок до открытия circuit breaker."
    )
    client_breaker_reset_timeout: float = Field(
        default=30.0, gt=0, description="Сек до перехода OPEN → HALF_OPEN (пробный вызов)."
    )
    client_cache_ttl_seconds: int = Field(
        default=60, ge=1, description="TTL по умолчанию для кеша ответов соседей (сек)."
    )

    # --- kb-platform: реестр Collaborator + ServiceOrder + CollaboratorReview
    # (m2m, ADR-0001/ADR-0002). ПУСТОЙ токен = интеграция инертна (заглушка). ---
    platform_api_base_url: str = Field(
        default="http://localhost:8081",
        description="Базовый URL kb-platform API (реестр партнёров, заказы, отзывы).",
    )
    platform_api_token: str = Field(
        default="",
        description=(
            "Плейсхолдер m2m-токена для StaticTokenProvider (dev/test). Реальный "
            "ClientCredentials провайдер — после провижининга realm."
        ),
    )
    platform_cache_ttl_seconds: int = Field(
        default=300, ge=1, description="TTL кеша справочных данных kb-platform (сек). Read-only."
    )

    # --- rehome.one: контекст User/Premises/Booking + платёжный контур
    # (escrow/комиссия/выплата). Деньги не считаем — только ссылки/триггеры. ---
    rehome_one_api_base_url: str = Field(
        default="http://localhost:8080",
        description="Базовый URL rehome.one API (контекст заявителя + платёжный контур).",
    )
    rehome_one_api_token: str = Field(
        default="", description="m2m-токен rehome.one (dev/test). ПУСТО → интеграция инертна."
    )

    # --- kb-files (вложения фото/актов в MinIO по API, НЕ shared bucket) ---
    kb_files_api_base_url: str = Field(
        default="http://localhost:8084", description="Базовый URL kb-files API (вложения заявок)."
    )
    kb_files_api_token: str = Field(
        default="", description="m2m-токен kb-files. ПУСТО → вложения не загружаются."
    )

    # --- kb-search: инициация заявки из AI-чата (from-chat) ---
    kb_search_api_base_url: str = Field(
        default="http://localhost:8082", description="Базовый URL kb-search API (from-chat)."
    )
    kb_search_api_token: str = Field(
        default="", description="m2m-токен kb-search. ПУСТО → возврат в чат выключен."
    )

    # --- kb-support: эскалация из тикета (from-ticket) + спор → претензия COMPENSATION ---
    kb_support_api_base_url: str = Field(
        default="http://localhost:8000",
        description="Базовый URL kb-support API (claims/from-ticket).",
    )
    kb_support_api_token: str = Field(
        default="", description="m2m-токен kb-support. ПУСТО → интеграция претензий инертна."
    )

    # --- Классификатор категории (E2, §4.11). Детерминированные правила (быстрый
    # путь) + LLMProvider (env-switch, как в kb-search). Реальные LLM-SDK — только
    # через ADR (правило 6); пустой провайдер → NullLLMProvider (rules-only). ---
    classifier_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "Порог уверенности классификатора (FR-2.4). Ниже порога или при "
            "неоднозначности заявка уходит в NEEDS_REVIEW (human-handoff)."
        ),
    )
    classifier_llm_provider: str = Field(
        default="",
        description=(
            "Выбор LLM-провайдера (yandexgpt/gigachat/vllm/mock). ПУСТО → NullLLMProvider "
            "(только rules-путь). Реальные провайдеры подключаются отдельным ADR."
        ),
    )

    # --- SLA (E6, §16 п.3). Бизнес-часы недельного графика + IANA-TZ (DST-корректно,
    # FR-6.1). Дедлайны/breach считаются на чтении и переходах БЕЗ воркера (FR-6.2).
    # Параметры — дефолты, подтверждение Архитектора по вехе (§16). ---
    sla_timezone: str = Field(
        default="Europe/Moscow", description="IANA-таймзона расчёта бизнес-часов SLA."
    )
    sla_business_open_hour: int = Field(
        default=9, ge=0, le=23, description="Час начала рабочего окна (локальное время)."
    )
    sla_business_close_hour: int = Field(
        default=18, ge=1, le=24, description="Час конца рабочего окна (локальное время)."
    )
    sla_business_days: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4],
        description="Рабочие дни недели (0=Пн … 6=Вс).",
    )
    sla_accept_hours: float = Field(
        default=4.0, gt=0, description="SLA принятия партнёром (бизнес-часы от диспетчеризации)."
    )
    sla_perform_hours: float = Field(
        default=24.0, gt=0, description="SLA выполнения (бизнес-часы от принятия партнёром)."
    )
    sla_at_risk_fraction: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description="Доля дедлайна, после которой состояние SLA → AT_RISK.",
    )

    # --- Dramatiq-воркер (SLA-таймеры, time_based, IMAP-poll, outbox-drainer).
    # ПУСТОЙ broker_url → StubBroker, акторы инертны (broker/worker поднимает ops). ---
    worker_broker_url: str = Field(
        default="",
        description=(
            "URL Redis-broker для Dramatiq. ПУСТО → StubBroker, акторы инертны. "
            "Read-side вычисления (breach на чтении) от него не зависят."
        ),
    )
    outbox_batch_size: int = Field(
        default=50, ge=1, le=500, description="Сколько outbox-сообщений берёт дрейнер за раз."
    )
    outbox_max_attempts: int = Field(
        default=5, ge=1, le=20, description="Попыток обработки outbox-сообщения до FAILED."
    )
    outbox_retry_base_seconds: float = Field(
        default=30.0, gt=0, description="База backoff повтора outbox (сек): base * 2**(attempt-1)."
    )
    outbox_visibility_timeout_seconds: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Видимость захваченного outbox-сообщения (сек): по истечении PROCESSING "
            "снова доступно (reclaim осиротевших после сбоя воркера)."
        ),
    )

    # --- Исходящие webhooks (E8, §11.4). Доставка ПОСЛЕ commit через transactional
    # outbox; HMAC-подпись. ПУСТОЙ webhook_url → эмиссия событий выключена. ---
    webhook_url: str = Field(
        default="", description="URL подписчика доменных событий. ПУСТО → webhooks off."
    )
    webhook_secret: str = Field(
        default="", description="Секрет HMAC-подписи исходящих webhooks (X-Signature)."
    )

    # --- Автоматизация (E6, §6.6, FR-6.3). On_create-пайплайн (классификация→подбор→
    # диспетчеризация) асинхронно через outbox. ПУСТО/False → инертно (ручной режим). ---
    automation_on_create_enabled: bool = Field(
        default=False,
        description=(
            "Включает авто-пайплайн при приёме заявки (on_create): intake ставит "
            "outbox-задачу, воркер прогоняет classify→assign→dispatch системным субъектом."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached Settings instance (один объект на процесс)."""
    return Settings()
