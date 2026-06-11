# kb-partners backend

FastAPI-сервис модуля обработки партнёрских заявок reHome (ТЗ v1.1).

## Quick start

```bash
# Зависимости (создаёт .venv в backend/, устанавливает runtime + dev)
make install

# Поднять Postgres (docker compose, порт хоста 5434)
make db-up

# Применить миграции
make migrate

# Запустить dev-сервер (auto-reload, localhost:8000)
make dev

# Проверить /healthz
curl http://localhost:8000/healthz
# → {"status":"ok"}

# OpenAPI docs (FastAPI Swagger UI)
open http://localhost:8000/docs
```

## Конфигурация (env vars)

Префикс — `KBP_*`. Полный список с дефолтами — в `src/api/config.py`; шаблон —
`.env.example`. Ключевые:

| Переменная | По умолчанию | Описание |
|---|---|---|
| `KBP_DATABASE_URL` | `postgresql+asyncpg://kbpartners:devpass@localhost:5434/kbpartners` | Async DSN PostgreSQL |
| `KBP_AUTH_JWKS_URL` | `` (пусто → 401) | URL JWKS Keycloak |
| `KBP_AUTH_AUDIENCE` | `` | Ожидаемый `aud` (= `kb-partners`) |
| `KBP_REDIS_URL` | `redis://localhost:6379/0` | Redis (кеш клиентов + брокер) |
| `KBP_WORKER_BROKER_URL` | `` (пусто → StubBroker) | Брокер Dramatiq |

## Команды разработки

| Цель | Что делает |
|---|---|
| `make install` | Создаёт `.venv/` и ставит runtime + dev зависимости |
| `make lint` | `ruff check` + `ruff format --check` |
| `make format` | `ruff format` (in-place) + `ruff check --fix` |
| `make typecheck` | `mypy --strict src tests` |
| `make test` / `make test-cov` | `pytest` / `pytest --cov` (порог 80%) |
| `make dev` | uvicorn с auto-reload |
| `make db-up` / `db-down` / `db-logs` | docker compose: Postgres lifecycle |
| `make migrate` / `migrate-down` | `alembic upgrade head` / `downgrade -1` |
| `make revision m="..."` | Создать новую миграцию (autogenerate) |
| `make arch-check` | AT-001 — проверка архитектурной константы |

## Архитектурная константа

kb-partners — отдельный сервис. Запрещены прямые SQL к чужим таблицам
(`collaborators`, `service_orders`, `users`, `premises`, ...) и импорты кода
из `rehome-kb-platform` / `kb-support`. Доступ к реестру партнёров, заказам и
платёжному контуру — только через HTTP-клиенты (`src/api/clients/`). Enforce —
`make arch-check` / CI job `arch-constraint`. См. CLAUDE.md правило 7, ADR-0001.
