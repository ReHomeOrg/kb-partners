# ADR-0001 — Архитектура модуля kb-partners

- Статус: Принято
- Дата: 2026-06-11
- Контекст: ТЗ `kb-partners` v1.1 (§4.1, §5, §12), эталон kb-support (ADR-0005)

## Контекст

reHome строит модуль обработки партнёрских заявок. Доменная модель партнёров
(`Collaborator`, `ServiceOrder`, `CollaboratorReview`) уже существует в
kb-platform. Нужно решить периметр сервиса, владение данными и принцип связи.

## Решение

1. **Отдельный, независимо развёртываемый сервис** `kb-partners`: свой
   репозиторий (`~/projects/kb-partners`), своя БД (PostgreSQL 16), свой деплой.
   Стек повторяет эталон kb-support: Python 3.12, FastAPI, async SQLAlchemy 2 +
   asyncpg, Alembic, Dramatiq + Redis, Keycloak (OIDC, RS256/JWKS, verify_aud),
   Next.js 14 (портал партнёра LIGHT + рабочее место оператора), MinIO/kb-files
   по API.

2. **Архитектурная константа (инвариант).** Связь с kb-platform, kb-support,
   kb-search, rehome.one — **только по сети, по HTTP API**. Запрещены:
   - импорты кода из `rehome_kb_platform` / `kb_support` / прочих kb-модулей;
   - прямые SQL к чужим таблицам (`collaborators`, `service_orders`, `users`,
     `premises`, `bookings`, `kb_*`).
   Enforce — `scripts/check-arch-constraint.sh` (CI job `arch-constraint` +
   `make arch-check`). Легитимные исключения — inline `# arch-allow: <reason ≥10>`.

3. **Владение данными.** Реестр партнёров (`Collaborator`) остаётся мастер-данными
   kb-platform; kb-partners читает его по m2m. Жизненным циклом `ServiceOrder`
   kb-partners **оркестрирует** (см. ADR-0002), физически заказ остаётся в
   kb-platform. Деньги (комиссия/escrow/выплата) считает платёжный контур
   rehome.one — модуль хранит только ссылки (`amount_ref`/`escrow_ref`).

4. **Двухконтурность.** Каждый ресурс несёт `access_level`; фильтр на уровне
   хранилища; недоступный ресурс → **404** (anti-enumeration), не 403.

## Последствия

- Сбой kb-partners не роняет KB/поддержку и наоборот (слабая связанность).
- Интеграции реализуются как resilient HTTP-клиенты (timeout → circuit-breaker →
  retry → метрики, cache-aside) в `backend/src/api/clients/`.
- Новые внешние зависимости (SDK мессенджеров/CRM/банка) — только через ADR.
