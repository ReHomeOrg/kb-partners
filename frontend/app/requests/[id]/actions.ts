"use server";

import { revalidatePath } from "next/cache";

import { addEstimate, partnerRespond, type PartnerResponseInput } from "@/lib/api/client";

/** Server action: ответ партнёра по заявке (FR-10.2), затем обновление страницы. */
export async function respondAction(id: string, status: string, message?: string): Promise<void> {
  const body: PartnerResponseInput = { status };
  if (message && message.trim()) {
    body.message = message.trim();
  }
  await partnerRespond(id, body);
  revalidatePath(`/requests/${id}`);
}

/** Server action: партнёр называет цену и срок по факту осмотра (issue #6). */
export async function estimateAction(
  id: string,
  kind: "PRELIMINARY" | "FINAL",
  amount: string,
  eta: string,
): Promise<void> {
  await addEstimate(id, {
    kind,
    // Пустое поле — это «не назвал», а не ноль: ноль означал бы «бесплатно».
    amount_rub: amount.trim() ? amount.trim() : null,
    eta_text: eta.trim() ? eta.trim() : null,
  });
  revalidatePath(`/requests/${id}`);
}
