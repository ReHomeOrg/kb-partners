import { describe, expect, it, vi } from "vitest";

import { isAccessTokenValid, refreshAccessToken, REFRESH_ERROR } from "./keycloak";
import type { OidcTokenSet } from "./keycloak";

const config = { issuer: "https://kc/realms/r", clientId: "cid", clientSecret: "sec" };

describe("isAccessTokenValid", () => {
  it("валиден, пока не истёк (expires_at в секундах)", () => {
    expect(isAccessTokenValid({ expires_at: 200 }, 100_000)).toBe(true); // 100s < 200s
    expect(isAccessTokenValid({ expires_at: 100 }, 200_000)).toBe(false); // 200s > 100s
    expect(isAccessTokenValid({}, 0)).toBe(false);
  });
});

describe("refreshAccessToken", () => {
  it("обновляет токен по refresh_token", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "new", expires_in: 300, refresh_token: "new-r" }),
    });
    const token = await refreshAccessToken<OidcTokenSet>(
      { access_token: "old", refresh_token: "r" },
      config,
      { fetch: fetchImpl as unknown as typeof fetch, now: () => 1_000_000 },
    );
    expect(token.access_token).toBe("new");
    expect(token.refresh_token).toBe("new-r");
    expect(token.expires_at).toBe(1000 + 300);
    expect(token.error).toBeUndefined();
  });

  it("сохраняет прежний refresh_token, если новый не пришёл", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "new", expires_in: 60 }),
    });
    const token = await refreshAccessToken<OidcTokenSet>({ refresh_token: "keep" }, config, {
      fetch: fetchImpl as unknown as typeof fetch,
      now: () => 0,
    });
    expect(token.refresh_token).toBe("keep");
  });

  it("без refresh_token → маркер ошибки (деградация, не исключение)", async () => {
    const token = await refreshAccessToken<OidcTokenSet>({}, config, {
      fetch: (async () => new Response()) as unknown as typeof fetch,
      now: () => 0,
    });
    expect(token.error).toBe(REFRESH_ERROR);
  });

  it("сетевой сбой → маркер ошибки", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("down"));
    const token = await refreshAccessToken<OidcTokenSet>({ refresh_token: "r" }, config, {
      fetch: fetchImpl as unknown as typeof fetch,
      now: () => 0,
    });
    expect(token.error).toBe(REFRESH_ERROR);
  });
});
