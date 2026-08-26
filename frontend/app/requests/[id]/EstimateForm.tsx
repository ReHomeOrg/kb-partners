"use client";

import { useState, useTransition } from "react";

import { estimateAction } from "./actions";

type Estimate = {
  kind: string;
  amount_rub?: string | null;
  eta_text?: string | null;
  created_at: string;
};

const KIND_LABEL: Record<string, string> = {
  PRELIMINARY: "предварительная",
  FINAL: "по факту осмотра",
};

function money(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n).toLocaleString("ru-RU")} ₽` : `${value} ₽`;
}

/**
 * Оценка стоимости работ партнёром (issue #6).
 *
 * Цену называет исполнитель по факту осмотра — как правило уже после выезда мастера.
 * История показывается целиком: расхождение предварительной и финальной оценки —
 * первое, что выясняют при разборе с заявителем, и прятать его нельзя.
 */
export function EstimateForm({ id, estimates }: { id: string; estimates: Estimate[] }) {
  const [kind, setKind] = useState<"PRELIMINARY" | "FINAL">("FINAL");
  const [amount, setAmount] = useState("");
  const [eta, setEta] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    if (!amount.trim() && !eta.trim()) {
      setError("Укажите сумму или срок — пустая оценка ничего не сообщает.");
      return;
    }
    setError(null);
    startTransition(async () => {
      try {
        await estimateAction(id, kind, amount, eta);
        setAmount("");
        setEta("");
      } catch {
        setError("Не удалось сохранить оценку. Попробуйте позже.");
      }
    });
  }

  return (
    <section className="mt-8">
      <h2 className="text-base font-semibold">Оценка работ</h2>

      {estimates.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {estimates.map((e) => (
            <li key={e.created_at} className="text-gray-700">
              <span className="font-medium">
                {e.amount_rub ? money(e.amount_rub) : "без суммы"}
              </span>
              {e.eta_text ? `, ${e.eta_text}` : ""}{" "}
              <span className="text-gray-500">
                — {KIND_LABEL[e.kind] ?? e.kind},{" "}
                {new Date(e.created_at).toLocaleDateString("ru-RU")}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="block text-gray-600">Когда оценивали</span>
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value as "PRELIMINARY" | "FINAL")}
            className="mt-1 rounded-md border px-2 py-1.5"
          >
            <option value="FINAL">По факту осмотра</option>
            <option value="PRELIMINARY">Предварительно, по описанию</option>
          </select>
        </label>

        <label className="text-sm">
          <span className="block text-gray-600">Сумма, ₽</span>
          <input
            value={amount}
            inputMode="decimal"
            onChange={(event) => setAmount(event.target.value.replace(/[^\d.,]/g, ""))}
            placeholder="7500"
            className="mt-1 w-32 rounded-md border px-2 py-1.5"
          />
        </label>

        <label className="text-sm">
          <span className="block text-gray-600">Срок</span>
          <input
            value={eta}
            onChange={(event) => setEta(event.target.value)}
            placeholder="завтра до 18:00"
            className="mt-1 w-56 rounded-md border px-2 py-1.5"
          />
        </label>

        <button
          type="button"
          disabled={pending}
          onClick={submit}
          className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        >
          Сохранить оценку
        </button>
      </div>

      <p className="mt-2 text-xs text-gray-500">
        Оценку можно уточнить: прежняя останется в истории, статус заявки не изменится.
      </p>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </section>
  );
}
