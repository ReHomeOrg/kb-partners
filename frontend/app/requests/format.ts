/**
 * Чистые хелперы отображения статусов и доступных партнёру действий (E10).
 * Действия соответствуют FSM бэкенда (§7): партнёр двигает свою заявку
 * DISPATCHED→ACCEPTED→IN_PROGRESS→DONE, либо отклоняет (rejected → MATCHING).
 */

export const STATUS_LABELS: Record<string, string> = {
  NEW: "Новая",
  CLASSIFYING: "Классификация",
  CLASSIFIED: "Классифицирована",
  NEEDS_REVIEW: "Требует проверки",
  MATCHING: "Подбор партнёра",
  ASSIGNED: "Назначена",
  DISPATCHED: "Передана вам",
  FAILED_DISPATCH: "Не доставлена",
  ACCEPTED: "Принята",
  IN_PROGRESS: "В работе",
  DONE: "Выполнена",
  ACCEPTED_BY_USER: "Принята клиентом",
  DISPUTE: "Спор",
  PAID: "Оплачена",
  CANCELLED: "Отменена",
  REJECTED: "Отклонена",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export type PartnerActionValue = "accepted" | "rejected" | "in_progress" | "done";

export interface PartnerAction {
  value: PartnerActionValue;
  label: string;
}

/** Доступные партнёру действия в текущем статусе (пусто — действий нет). */
export function partnerActions(status: string): PartnerAction[] {
  switch (status) {
    case "DISPATCHED":
      return [
        { value: "accepted", label: "Принять" },
        { value: "rejected", label: "Отклонить" },
      ];
    case "ACCEPTED":
      return [{ value: "in_progress", label: "Начать выполнение" }];
    case "IN_PROGRESS":
      return [{ value: "done", label: "Завершить" }];
    default:
      return [];
  }
}
