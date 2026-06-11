import Link from "next/link";

import { listRequests } from "@/lib/api/client";

import { statusLabel } from "./format";

// Список зависит от сессии партнёра — рендерим на запросе, не на сборке.
export const dynamic = "force-dynamic";

export default async function RequestsPage() {
  const data = await listRequests({});
  const items = data.items ?? [];

  return (
    <main>
      <h1 className="text-xl font-semibold">Мои заявки</h1>
      {items.length === 0 ? (
        <p className="mt-6 text-sm text-gray-600">Назначенных заявок пока нет.</p>
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
                  <Link className="text-blue-700 hover:underline" href={`/requests/${item.id}`}>
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
