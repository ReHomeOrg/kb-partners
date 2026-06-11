"use client";

import { useState, useTransition } from "react";

import { partnerActions, type PartnerAction } from "../format";

import { respondAction } from "./actions";

/** Кнопки действий партнёра по статусу заявки (портал LIGHT, FR-10.2). */
export function PartnerActions({ id, status }: { id: string; status: string }) {
  const actions = partnerActions(status);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  if (actions.length === 0) {
    return <p className="mt-4 text-sm text-gray-500">Сейчас действий по заявке нет.</p>;
  }

  function run(action: PartnerAction) {
    setError(null);
    startTransition(async () => {
      try {
        await respondAction(id, action.value);
      } catch {
        setError("Не удалось выполнить действие. Попробуйте позже.");
      }
    });
  }

  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2">
        {actions.map((action) => (
          <button
            key={action.value}
            type="button"
            disabled={pending}
            onClick={() => run(action)}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {action.label}
          </button>
        ))}
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
