#!/usr/bin/env bash
# AT-001 — проверка архитектурной константы kb-support.
#
# kb-support — отдельный сервис со своей БД. Запрещены:
#   1. Импорты из соседних модулей платформы (rehome_kb_platform / kb_search / ...).
#   2. Прямые SQL-запросы к чужим таблицам (users, premises, bookings,
#      collaborators, service_orders и т.п.).
#
# Allowlist: строки с inline-комментарием `arch-allow: <обоснование длиной >= 10 chars>`
# пропускаются. Reviewer проверяет легитимность каждого использования.
#
# Запуск:
#   bash scripts/check-arch-constraint.sh         # из корня репо
#   make arch-check                               # из backend/
#
# Exit code: 0 — нарушений нет, 1 — найдены нарушения (с file:line:content).

set -euo pipefail

# -------- регулярки -------------------------------------------------------

# Python: from X | import X где X — соседний модуль платформы (включая kb_support).
FORBIDDEN_IMPORTS_PY='^[[:space:]]*(from|import)[[:space:]]+(rehome_kb_platform|kb_platform|kb_search|kb_wiki|kb_vault|kb_files|kb_auth|kb_staff|kb_hr|kb_eval|kb_infra|kb_support)([.[:space:]]|$)'

# TypeScript/JavaScript: import ... from "rehome-kb-platform" | kb-* (dash, не underscore).
FORBIDDEN_IMPORTS_TS='from[[:space:]]+["'\''](.*/)?(rehome-kb-platform|kb-platform|kb-search|kb-wiki|kb-vault|kb-files|kb-auth|kb-staff|kb-hr|kb-eval|kb-infra|kb-support)["'\''/]'

# SQL: FROM / JOIN / UPDATE / INSERT INTO / DROP TABLE чужой таблицы.
# Матчится case-insensitive (#28) — ловит и `select * from users`. Управление
# false positives: имена чужих таблиц специфичны (premises/collaborators/
# service_orders/kb_*); редкие легитимные совпадения — через allowlist.
# Свои таблицы kb-partners (service_requests/request_messages/request_history/
# partner_channel_configs/dispatch_attempts/automation_rules/outbox) НЕ входят.
FORBIDDEN_SQL='\b(FROM|JOIN|UPDATE|INTO|TABLE)[[:space:]]+(users|premises|bookings|collaborators|service_orders|kb_articles|kb_chat_sessions|kb_documents)\b'

# -------- директории сканирования ----------------------------------------

SCAN_DIRS_PY=(backend/src backend/tests backend/alembic)
SCAN_DIRS_TS=(frontend/app frontend/lib frontend/tests)

MIN_ALLOW_REASON=10

# -------- helpers ---------------------------------------------------------

violations=0

# Печать с GitHub Actions error-аннотацией.
emit_violation() {
    local file=$1 line=$2 content=$3 rule=$4
    if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
        # ::error file=path,line=N::message
        printf '::error file=%s,line=%s::AT-001 (%s) → %s\n' "$file" "$line" "$rule" "$content"
    fi
    printf '%s:%s: [%s] %s\n' "$file" "$line" "$rule" "$content" >&2
    violations=$((violations + 1))
}

# Returns 0 если строка имеет валидный allowlist marker (`arch-allow: <reason>` с reason >= MIN_ALLOW_REASON chars).
has_valid_allow() {
    local content=$1
    # Извлечь reason после `arch-allow:`.
    if [[ "$content" =~ arch-allow:[[:space:]]*([^$'\n']*) ]]; then
        local reason=${BASH_REMATCH[1]}
        # trim whitespace
        reason=${reason%"${reason##*[![:space:]]}"}
        reason=${reason#"${reason%%[![:space:]]*}"}
        if (( ${#reason} >= MIN_ALLOW_REASON )); then
            return 0
        fi
    fi
    return 1
}

scan() {
    local rule_name=$1 regex=$2
    shift 2
    local dirs=("$@")

    # SQL-ключевые слова ловим без учёта регистра (#28); импорты — точно по регистру.
    local grep_opts='-nHE'
    [[ "$rule_name" == sql ]] && grep_opts='-inHE'

    for dir in "${dirs[@]}"; do
        [[ -d "$dir" ]] || continue
        local files
        if [[ "$rule_name" == python-import ]] || [[ "$rule_name" == sql ]]; then
            files=$(find "$dir" -type f -name '*.py' 2>/dev/null || true)
        elif [[ "$rule_name" == ts-import ]]; then
            files=$(find "$dir" -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' \) 2>/dev/null || true)
        else
            files=""
        fi
        [[ -z "$files" ]] && continue

        # grep -nE: line numbers + extended regex; -H: всегда печатать file.
        while IFS= read -r match; do
            [[ -z "$match" ]] && continue
            local file line content
            file=${match%%:*}
            local rest=${match#*:}
            line=${rest%%:*}
            content=${rest#*:}

            if has_valid_allow "$content"; then
                continue
            fi
            emit_violation "$file" "$line" "$content" "$rule_name"
        done < <(printf '%s\n' "$files" | xargs -r -d '\n' grep "$grep_opts" "$regex" 2>/dev/null || true)
    done
}

# -------- main ------------------------------------------------------------

echo "AT-001: checking architectural constraint..."

scan python-import "$FORBIDDEN_IMPORTS_PY" "${SCAN_DIRS_PY[@]}"
scan sql "$FORBIDDEN_SQL" "${SCAN_DIRS_PY[@]}"
scan ts-import "$FORBIDDEN_IMPORTS_TS" "${SCAN_DIRS_TS[@]}"

if (( violations > 0 )); then
    echo ""
    echo "AT-001 FAILED — $violations нарушений архитектурной константы."
    echo "См. CLAUDE.md правило 7 + ADR-0005 Решение 1."
    echo "Если нарушение легитимно — добавь inline-комментарий:"
    echo "    # arch-allow: <обоснование >= ${MIN_ALLOW_REASON} chars>"
    exit 1
fi

echo "AT-001 clean: 0 нарушений в $(printf '%s ' "${SCAN_DIRS_PY[@]}" "${SCAN_DIRS_TS[@]}")"
