# kb-partners

Модуль обработки партнёрских заявок reHome. Принимает заявки пользователей на
партнёрские услуги (группа B: клининг, переезд, мелкий ремонт, доставка ключей),
**распознаёт категорию** (классификатор), **подбирает партнёра**, **диспетчеризует**
заявку по настроенному каналу (API / CRM / Telegram / MAX / e-mail) и ведёт её
жизненный цикл до приёмки и расчёта.

Часть экосистемы reHome рядом с **kb-platform** (реестр партнёров) и **kb-support**
(поддержка/претензии); управляется ИИ-агентом-оркестратором «Консьерж»
(`kb-concierge`, отдельный сервис). См. ТЗ v1.1 в
`docs/handoff/01_postanovka/01_TZ_kb_partners_v1.1.md`.

## Статус

**M0 (каркас).** Backend-скелет: FastAPI + observability + Keycloak-валидатор +
arch-constraint + CI + OpenAPI-скелет + `healthz/readyz/metrics`. Доменные эпики
(M1–M7) — впереди (см. ТЗ §15 и план).

## Структура

```
backend/         FastAPI-сервис (см. backend/README.md)
  src/api/       config, errors, db, observability, auth + (M1+) доменные модули
  alembic/       миграции БД
  tests/         unit / integration / contract
docs/
  openapi.yaml   контракт API (OpenAPI 3.1, источник истины)
  adr/           архитектурные решения (0001 — арх-константа, 0002 — ServiceOrder)
  handoff/       ТЗ и входные артефакты для агентов
scripts/         check-arch-constraint.sh (AT-001)
tests/arch-constraint/  self-test arch-constraint + fixtures
.github/workflows/      CI
CLAUDE.md / CLAUDE-REVIEWER.md   двухагентная схема разработки
```

## Быстрый старт (backend)

```bash
cd backend
make install      # .venv + зависимости
make db-up        # Postgres (docker compose, порт хоста 5434)
make migrate      # alembic upgrade head
make dev          # uvicorn → http://localhost:8000  (/docs, /healthz)
```

## Гейты качества (как в CI)

```bash
cd backend
make lint typecheck test      # ruff + mypy strict + pytest (cov ≥80%)
make arch-check               # AT-001 — архитектурная константа
```

## Архитектурная константа

Отдельный сервис: своя БД, связь с соседями только по HTTP API; запрещены прямые
SQL к чужим таблицам и импорты кода соседних модулей. См. ADR-0001, CLAUDE.md §7.
