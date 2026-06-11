"use server";

import { revalidatePath } from "next/cache";

import { partnerRespond, type PartnerResponseInput } from "@/lib/api/client";

/** Server action: ответ партнёра по заявке (FR-10.2), затем обновление страницы. */
export async function respondAction(id: string, status: string, message?: string): Promise<void> {
  const body: PartnerResponseInput = { status };
  if (message && message.trim()) {
    body.message = message.trim();
  }
  await partnerRespond(id, body);
  revalidatePath(`/requests/${id}`);
}
