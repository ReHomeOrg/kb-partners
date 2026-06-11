"use client";

import { useState, useTransition } from "react";

import { operatorActions, type OperatorAction } from "../format";

import { addNoteAction, operatorAction } from "./actions";

/** Операторские действия по заявке (E2/E3/E4) + добавление сообщения/заметки. */
export function OperatorActions({ id, status }: { id: string; status: string }) {
  const actions = operatorActions(status);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [internal, setInternal] = useState(true);

  function run(action: OperatorAction) {
    setError(null);
    startTransition(async () => {
      try {
        await operatorAction(id, action.value);
      } catch {
        setError("Не удалось выполнить действие (проверьте статус заявки).");
      }
    });
  }

  function submitNote() {
    if (!note.trim()) {
      return;
    }
    setError(null);
    startTransition(async () => {
      try {
        await addNoteAction(id, note, internal);
        setNote("");
      } catch {
        setError("Не удалось добавить сообщение.");
      }
    });
  }

  return (
    <div className="mt-4 space-y-4">
      {actions.length > 0 && (
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
      )}

      <div className="rounded-md border bg-white p-3">
        <label htmlFor="note" className="text-sm font-medium text-gray-700">
          Сообщение / заметка
        </label>
        <textarea
          id="note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded-md border p-2 text-sm"
          placeholder="Текст…"
        />
        <div className="mt-2 flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={internal}
              onChange={(e) => setInternal(e.target.checked)}
            />
            Внутренняя заметка (не видна заявителю и партнёру)
          </label>
          <button
            type="button"
            disabled={pending || !note.trim()}
            onClick={submitNote}
            className="rounded-md bg-blue-700 px-3 py-1.5 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
          >
            Добавить
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
