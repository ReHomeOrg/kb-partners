/**
 * Хелперы рабочего места оператора: какие действия доступны в текущем статусе.
 * Логика следует FSM/эпикам бэкенда (§7, E2/E3/E4): оператор классифицирует,
 * подбирает партнёра и диспетчеризует. Право/валидность — на бэкенде (409 при
 * запрещённом), фронт лишь не показывает заведомо нерелевантные кнопки.
 */

export type OperatorActionValue = "classify" | "assign" | "dispatch";

export interface OperatorAction {
  value: OperatorActionValue;
  label: string;
}

const _CLASSIFIABLE = new Set(["NEW", "CLASSIFIED", "NEEDS_REVIEW"]);
const _ASSIGNABLE = new Set([
  "CLASSIFIED",
  "NEEDS_REVIEW",
  "MATCHING",
  "DISPATCHED",
  "FAILED_DISPATCH",
]);

/** Доступные оператору действия в статусе (пусто — нет применимых). */
export function operatorActions(status: string): OperatorAction[] {
  const actions: OperatorAction[] = [];
  if (_CLASSIFIABLE.has(status)) {
    actions.push({ value: "classify", label: "Классифицировать" });
  }
  if (_ASSIGNABLE.has(status)) {
    actions.push({ value: "assign", label: "Подобрать партнёра" });
  }
  if (status === "ASSIGNED") {
    actions.push({ value: "dispatch", label: "Диспетчеризовать" });
  }
  return actions;
}
