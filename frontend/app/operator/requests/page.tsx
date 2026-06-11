import Link from "next/link";

import { listRequests, type ListRequestsQuery } from "@/lib/api/client";

import { statusLabel } from "../../requests/format";

// Список зависит от сессии оператора — рендерим на запросе.
export const dynamic = "force-dynamic";

const STATUSES = [
  "NEW",
  "CLASSIFIED",
  "NEEDS_REVIEW",
  "MATCHING",
  "ASSIGNED",
  "DISPATCHED",
  "FAILED_DISPATCH",
  "ACCEPTED",
  "IN_PROGRESS",
  "DONE",
  "DISPUTE",
];

export default async function OperatorRequestsPage({
  searchParams,
}: {
  searchParams: { status?: string; category?: string };
}) {
  const query: ListRequestsQuery = {};
  if (searchParams.status) {
    query.status = searchParams.status as ListRequestsQuery["status"];
  }
  if (searchParams.category) {
    query.category = searchParams.category as ListRequestsQuery["category"];
  }
  const data = await listRequests(query);
  const items = data.items ?? [];

  return (
    <main>
      <h1 className="text-xl font-semibold">Рабочее место оператора</h1>

      <form className="mt-4 flex flex-wrap items-end gap-3 text-sm" action="/operator/requests">
        <label className="flex flex-col">
          <span className="text-gray-500">Статус</span>
          <select
            name="status"
            defaultValue={searchParams.status ?? ""}
            className="rounded-md border p-1"
          >
            <option value="">Все</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="rounded-md bg-gray-900 px-3 py-1.5 text-white">
          Фильтр
        </button>
      </form>

      {items.length === 0 ? (
        <p className="mt-6 text-sm text-gray-600">Заявок по фильтру нет.</p>
      ) : (
        <table className="mt-6 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2">Номер</th>
              <th className="py-2">Категория</th>
              <th className="py-2">Статус</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b hover:bg-gray-100">
                <td className="py-2">
                  <Link
                    className="text-blue-700 hover:underline"
                    href={`/operator/requests/${item.id}`}
                  >
                    {item.number}
                  </Link>
                </td>
                <td className="py-2">{item.category ?? "—"}</td>
                <td className="py-2">{statusLabel(item.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
