import { describe, expect, it } from "vitest";

import { applyAccountTokens, isAuthorized, shapeClientSession } from "./auth-callbacks";
import type { OidcTokenSet } from "./keycloak";

describe("applyAccountTokens", () => {
  it("переносит токены провайдера в серверный JWT", () => {
    const token = applyAccountTokens<OidcTokenSet>(
      {},
      { access_token: "a", refresh_token: "r", expires_at: 100 },
    );
    expect(token.access_token).toBe("a");
    expect(token.refresh_token).toBe("r");
    expect(token.expires_at).toBe(100);
  });
});

describe("shapeClientSession (security)", () => {
  it("НЕ отдаёт access/refresh токены клиенту", () => {
    const session = shapeClientSession(
      { user: { name: "Партнёр" } },
      { access_token: "secret-access", refresh_token: "secret-refresh", expires_at: 100 },
    );
    const serialized = JSON.stringify(session);
    expect(serialized).not.toContain("secret-access");
    expect(serialized).not.toContain("secret-refresh");
    expect(session.expiresAt).toBe(100);
  });

  it("прокидывает маркер ошибки refresh для повторного входа", () => {
    const session = shapeClientSession({}, { error: "RefreshAccessTokenError" });
    expect(session.error).toBe("RefreshAccessTokenError");
  });
});

describe("isAuthorized", () => {
  it("требует наличия пользователя", () => {
    expect(isAuthorized({ user: { id: "1" } })).toBe(true);
    expect(isAuthorized(null)).toBe(false);
    expect(isAuthorized({})).toBe(false);
  });
});
