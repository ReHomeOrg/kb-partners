"use server";

import { revalidatePath } from "next/cache";

import { addMessage, assignRequest, classifyRequest, dispatchRequest } from "@/lib/api/client";

/** Server action: операторское действие над заявкой (E2/E3/E4), затем обновление страницы. */
export async function operatorAction(id: string, action: string): Promise<void> {
  if (action === "classify") {
    await classifyRequest(id);
  } else if (action === "assign") {
    await assignRequest(id, {});
  } else if (action === "dispatch") {
    await dispatchRequest(id);
  } else {
    throw new Error(`Unknown operator action: ${action}`);
  }
  revalidatePath(`/operator/requests/${id}`);
}

/** Server action: добавить сообщение/внутреннюю заметку (is_internal — только оператор). */
export async function addNoteAction(id: string, text: string, isInternal: boolean): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) {
    return;
  }
  await addMessage(id, { text: trimmed, is_internal: isInternal });
  revalidatePath(`/operator/requests/${id}`);
}
