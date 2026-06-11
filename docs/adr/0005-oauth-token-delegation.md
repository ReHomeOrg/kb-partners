# ADR-0005 — OAuth2 для исходящих вызовов и делегирование прав (on-behalf-of)

- Статус: Принято (решение Архитектора, 2026-06-11)
- Дата: 2026-06-11
- Контекст: ТЗ `kb-partners` v1.1 §12, E9 (FR-9.5/9.7), §16.12; CLAUDE.md правило 6

## Контекст

Исходящие m2m-вызовы соседям до этого использовали `StaticTokenProvider` (плейсхолдер
из env, dev/test). §16.12 оставлял открытым **механизм делегирования прав пользователя**
для действий ИИ-агента (FR-9.7): проверки `scope`/`access_level` должны применяться к
ПОЛЬЗОВАТЕЛЮ, а не к широкому сервис-принципалу агента.

## Решение

**Свои OAuth2-провайдеры поверх Keycloak token-endpoint (без вендорского SDK):**

1. **`ClientCredentialsTokenProvider`** (`api/clients/oauth.py`) — боевой m2m-токен
   сервис-принципала kb-partners (`grant_type=client_credentials`), с кешированием до
   истечения (минус запас). Фабрика `build_token_provider(settings, fallback_token=...)`
   выбирает его при заполненных `oauth_*`-настройках, иначе — dev `StaticTokenProvider`.
   Внедрён во все места сборки клиентов (actors + dependencies).

2. **`TokenExchangeProvider`** (RFC 8693, `grant_type=…token-exchange`) — обмен входящего
   токена агента на токен ОТ ИМЕНИ пользователя (`requested_subject`) для downstream-
   вызовов, где права должны проверяться у пользователя (on-behalf-of).

### Делегирование прав агента (FR-9.7) — два уровня

- **Внутри kb-partners** (приём вызова агента): токен агента несёт клейм `kbp_act_sub`
  (sub пользователя) → `Principal.on_behalf_of`. Видимость/действия уже ограничиваются
  пользователем (`api/requests/access.py`: `requester_id == on_behalf_of`, raw_input —
  только владельцу). Это ПЕРВИЧНЫЙ механизм, реализован.
- **Downstream-вызовы** kb-partners от имени пользователя: `TokenExchangeProvider` даёт
  делегированный токен. Инфраструктурные вызовы агента — под сервис-принципалом
  (FR-9.5: «4 глаза»/расчёт — не от имени пользователя).

Секреты (`oauth_client_secret`) — ссылкой на kb-vault. Токены в логи не пишутся; ошибки
token-endpoint → `ExternalServiceError` (без тела/токенов в сообщении).

## Последствия

- Боевая m2m-аутентификация включается env (`oauth_token_url`/`oauth_client_id`/
  `oauth_client_secret`); по умолчанию — dev StaticTokenProvider (поведение не меняется).
- Закрыт давний TODO «реальный ClientCredentials провайдер после провижининга realm».
- on-behalf-of: внутренняя авторизация — по `kbp_act_sub` (готово); downstream-делегация —
  через `TokenExchangeProvider` по мере появления user-scoped downstream-вызовов.
