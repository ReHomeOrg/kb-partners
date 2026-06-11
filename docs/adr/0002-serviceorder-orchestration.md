# ADR-0002 — Оркестрация ServiceOrder и маппинг машин состояний

- Статус: Принято (решение Архитектора, 2026-06-11)
- Дата: 2026-06-11
- Контекст: ТЗ `kb-partners` v1.1 §4.1, §6.1, §7, §16.1; контракт kb-platform

## Контекст

ТЗ требует, чтобы kb-partners владел **жизненным циклом** партнёрской заявки.
Центральная сущность модуля — `ServiceRequest` с богатой FSM (§7). При этом в
kb-platform **уже существует** сущность `ServiceOrder` со своей машиной из 8
статусов:

```
DRAFT → PENDING_COLLABORATOR → ACCEPTED → IN_PROGRESS
      → COMPLETED | CANCELLED | FAILED | DISPUTED
```

Развилка (§16.1): мигрировать `ServiceOrder` в kb-partners или оставить в
kb-platform и управлять им по API.

## Решение

**Оркестрация через API (без миграции данных).** `ServiceOrder` физически
остаётся в kb-platform (мастер-данные заказа, escrow-привязка, портал партнёра
на стороне платформы). kb-partners владеет `ServiceRequest` в своей БД и
**драйвит** переходы `ServiceOrder` по m2m-контракту kb-platform
(`POST /api/v1/service-orders`, `.../accept|complete|fail|cancel`),
идемпотентно (Idempotency-Key, FR-3.5).

`ServiceRequest.service_order_id` — ссылка на заказ в kb-platform.

### Маппинг FSM `ServiceRequest` → `ServiceOrder`

| ServiceRequest (§7)        | ServiceOrder (kb-platform) | Действие kb-partners |
|---|---|---|
| `ASSIGNED`                 | `DRAFT` (create)           | `POST /service-orders` (идемпотентно) |
| `DISPATCHED`               | `PENDING_COLLABORATOR`     | перевод после успешной диспетчеризации |
| `ACCEPTED`                 | `ACCEPTED`                 | по inbound-ответу партнёра |
| `IN_PROGRESS`              | `IN_PROGRESS`              | по inbound |
| `DONE`                     | `COMPLETED`                | по inbound |
| `DISPUTE`                  | `DISPUTED`                 | спор пользователя |
| `CANCELLED`                | `CANCELLED`                | отмена (FR-7.5) |
| `FAILED_DISPATCH`          | `FAILED` / без заказа      | если заказ ещё не создан — заказ не трогаем |

Обратная синхронизация (партнёр на портале kb-platform сменил статус заказа) —
через inbound-событие/опрос; kb-partners продвигает `ServiceRequest` согласно
своей FSM. Источник истины по **заявке** — kb-partners; по **заказу/деньгам** —
kb-platform/контур.

## Последствия

- Нужен контрактный тест маппинга (kb-partners ↔ kb-platform), включая
  идемпотентность создания заказа и расхождения статусов.
- Расхождение FSM — основной риск; покрывается контрактными и интеграционными
  тестами в M2/M5.
- Альтернатива (миграция `service_orders` в kb-partners) отклонена: дороже
  (миграция данных + правка kb-platform) и ломает существующую escrow-привязку.
