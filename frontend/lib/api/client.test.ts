import { describe, expect, it, vi } from "vitest";

import { listRequests, partnerRespond } from "./client";

const token = async () => "test-token";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("listRequests", () => {
  it("ставит Bearer и парсит ответ", async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer test-token");
      expect(String(url)).toContain("/api/v1/partners/requests");
      return jsonResponse(200, {
        items: [{ id: "1", number: "RQ-1", status: "DISPATCHED" }],
        next_cursor: null,
      });
    });
    const data = await listRequests(
      {},
      { getAccessToken: token, fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(data.items?.[0]?.number).toBe("RQ-1");
  });

  it("прокидывает query-параметры", async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request) => {
      expect(String(url)).toContain("status=DISPATCHED");
      return jsonResponse(200, { items: [], next_cursor: null });
    });
    await listRequests(
      { status: "DISPATCHED" },
      { getAccessToken: token, fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(fetchImpl).toHaveBeenCalledOnce();
  });
});

describe("partnerRespond", () => {
  it("POST'ит тело и возвращает карточку", async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toEqual({ status: "accepted" });
      return jsonResponse(200, { id: "1", number: "RQ-1", status: "ACCEPTED" });
    });
    const detail = await partnerRespond(
      "1",
      { status: "accepted" },
      { getAccessToken: token, fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(detail.status).toBe("ACCEPTED");
  });

  it("не-2xx → ApiError со status/title (без detail в message)", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(409, { type: "t", title: "Conflict", status: 409, detail: "секрет-детали" }),
    );
    await expect(
      partnerRespond(
        "1",
        { status: "done" },
        { getAccessToken: token, fetchImpl: fetchImpl as unknown as typeof fetch },
      ),
    ).rejects.toMatchObject({ status: 409, title: "Conflict" });
  });
});
