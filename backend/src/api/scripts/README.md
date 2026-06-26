# Скрипты kb-partners

Запуск из `backend/` с активным venv: `python -m api.scripts.<name>`.

## `seed_test_partners` — тестовые партнёры для сквозного прогона «Консьержа»

Заводит 5 тестовых партнёров (документ `reHome_Консьерж_тестовые_партнёры.md`) для
прогона сценария ИИ-агента «Консьерж»: подбор → диспетчеризация → авто-fallback.

```bash
make seed-test-partners            # = python -m api.scripts.seed_test_partners
```

Идемпотентно (upsert по `(collaborator_id, channel_type)`): повторный прогон не плодит
дублей. После прогона — 5 партнёров, 9 строк `partner_channel_configs`.

### Что где живёт (арх-константа ADR-0001)

Реестр `Collaborator` принадлежит **kb-platform**, не kb-partners. Поэтому:

- **Мастер-записи партнёров** (категория, гео, рейтинг) — отдаются фикстурным реестром
  `FixturePlatformClient` (config-gated), единый источник —
  `src/api/clients/platform/fixtures.py` (`TEST_PARTNERS`).
- **Каналы доставки** (`PartnerChannelConfig`) — своя таблица kb-partners, их и пишет
  seed-скрипт.

Чтобы матчинг/сценарий работал без живого kb-platform, включите фикстурный реестр:

```bash
export KBP_PLATFORM_TEST_FIXTURES=true
```

При `true` `search_candidates`/`get_partner_contact`/`create_service_order` обслуживаются
из `TEST_PARTNERS` (как `MockChannel`/`StubBroker` — только dev/test). В production флаг
всегда `false` → боевой `HttpPlatformClient`.

### Секреты — только ссылками (A7)

В `config` каналов хранятся **не секреты, а `ENV:`-ссылки**: `ENV:TG_BOT_TOKEN_TEST`,
`ENV:PROFI_API_KEY_TEST`. Сами токены — в окружении/kb-vault, не в БД и не в коммитах.
`chat_id`/`base_url` — тестовые плейсхолдеры (не секреты).

### Очистка

Натуральный ключ тест-партнёра — `collaborator_id` с префиксом `test-` (замена
отсутствующего в модели `tags:[test]`):

```sql
DELETE FROM partner_channel_configs WHERE collaborator_id LIKE 'test-%';
```

### Маппинг документа на фактическую модель

Документ описывает самодостаточную модель `Collaborator`; фактически часть полей
принадлежит kb-platform или вычисляется. Подробный маппинг — в шапке
`src/api/clients/platform/fixtures.py`. Ключевое:

| Документ | Реализация |
|---|---|
| `slug` | `collaborator_id` |
| `priority 10/50` | `rating` (профили 5.0 > агрегатор 3.0) — матчер ранжирует по рейтингу |
| `fallback_collaborator_id` | поля нет; `fallback_chain` строится динамически → агрегатор в хвосте |
| `coverage MSK/SPB` | `service_areas` (`msk`/`spb`, нижний регистр) |
| `home_repair` | категория `REPAIR` |

**Известный gap (вне scope сидов):** диспетч берёт ОДИН канал по возрастанию `priority`
(first-success) и копию на email НЕ шлёт. Документный `role: duplicate` реализован как
фолбэк-канал `priority=2`, а не как дубль-копия. Истинная копия — отдельная фича + ADR.
