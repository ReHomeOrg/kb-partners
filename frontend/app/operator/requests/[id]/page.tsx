import Link from "next/link";
import { notFound } from "next/navigation";

import {
  ApiError,
  getRequest,
  getRequesterContext,
  listMessages,
  type RequesterContext,
} from "@/lib/api/client";

import { statusLabel } from "../../../requests/format";
import { OperatorActions } from "../OperatorActions";

export const dynamic = "force-dynamic";

export default async function OperatorRequestDetail({ params }: { params: { id: string } }) {
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

  // Контекст заявителя (ПДн) — best-effort: может быть недоступен (контур инертен).
  let context: RequesterContext | null = null;
  try {
    context = await getRequesterContext(params.id);
  } catch {
    context = null;
  }

  return (
    <main>
      <Link className="text-sm text-blue-700 hover:underline" href="/operator/requests">
        ← К списку
      </Link>
      <h1 className="mt-2 text-xl font-semibold">Заявка {detail.number}</h1>

      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <dt className="text-gray-500">Статус</dt>
        <dd>{statusLabel(detail.status)}</dd>
        <dt className="text-gray-500">Категория</dt>
        <dd>{detail.category ?? "—"}</dd>
        <dt className="text-gray-500">Партнёр</dt>
        <dd>{detail.partner_id ?? "—"}</dd>
        <dt className="text-gray-500">Канал доставки</dt>
        <dd>{detail.delivery_channel ?? "—"}</dd>
      </dl>

      <section className="mt-4 rounded-md border bg-white p-3">
        <h2 className="text-sm font-medium text-gray-700">Описание (исходное)</h2>
        <p className="mt-1 whitespace-pre-wrap text-sm">{detail.raw_input}</p>
      </section>

      {context && (
        <section className="mt-4 rounded-md border bg-amber-50 p-3">
          <h2 className="text-sm font-medium text-gray-700">Контекст заявителя (ПДн)</h2>
          <dl className="mt-1 grid grid-cols-2 gap-1 text-sm">
            <dt className="text-gray-500">Имя</dt>
            <dd>{context.user_display_name ?? "—"}</dd>
            <dt className="text-gray-500">Телефон</dt>
            <dd>{context.user_phone ?? "—"}</dd>
            <dt className="text-gray-500">Адрес</dt>
            <dd>{context.premises_address ?? "—"}</dd>
          </dl>
        </section>
      )}

      <OperatorActions id={detail.id} status={detail.status} />

      <section className="mt-6">
        <h2 className="text-sm font-medium text-gray-700">Сообщения и заметки</h2>
        {messages.length === 0 ? (
          <p className="mt-1 text-sm text-gray-500">Сообщений нет.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {messages.map((m) => (
              <li
                key={m.id}
                className={`rounded-md border p-2 text-sm ${
                  m.is_internal ? "bg-yellow-50" : "bg-white"
                }`}
              >
                <span className="text-xs uppercase text-gray-400">
                  {m.author_type}
                  {m.is_internal ? " · внутренняя" : ""}
                </span>
                <p className="mt-1 whitespace-pre-wrap">{m.text}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
