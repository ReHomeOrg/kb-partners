import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError, getRequest, listMessages } from "@/lib/api/client";

import { statusLabel } from "../format";

import { PartnerActions } from "./PartnerActions";

export const dynamic = "force-dynamic";

export default async function RequestDetailPage({ params }: { params: { id: string } }) {
  let detail;
  try {
    detail = await getRequest(params.id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
  const messages = await listMessages(params.id);

  return (
    <main>
      <Link className="text-sm text-blue-700 hover:underline" href="/requests">
        ← К списку заявок
      </Link>
      <h1 className="mt-2 text-xl font-semibold">Заявка {detail.number}</h1>
      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <dt className="text-gray-500">Статус</dt>
        <dd>{statusLabel(detail.status)}</dd>
        <dt className="text-gray-500">Категория</dt>
        <dd>{detail.category ?? "—"}</dd>
        <dt className="text-gray-500">Канал</dt>
        <dd>{detail.delivery_channel ?? "—"}</dd>
      </dl>

      <section className="mt-4 rounded-md border bg-white p-3">
        <h2 className="text-sm font-medium text-gray-700">Описание</h2>
        <p className="mt-1 whitespace-pre-wrap text-sm">{detail.raw_input}</p>
      </section>

      <PartnerActions id={detail.id} status={detail.status} />

      <section className="mt-6">
        <h2 className="text-sm font-medium text-gray-700">Сообщения</h2>
        {messages.length === 0 ? (
          <p className="mt-1 text-sm text-gray-500">Сообщений нет.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {messages.map((m) => (
              <li key={m.id} className="rounded-md border bg-white p-2 text-sm">
                <span className="text-xs uppercase text-gray-400">{m.author_type}</span>
                <p className="mt-1 whitespace-pre-wrap">{m.text}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
