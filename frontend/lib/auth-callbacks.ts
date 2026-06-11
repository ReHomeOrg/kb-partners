/**
 * Чистые функции callback'ов Auth.js — без инициализации NextAuth, под unit-тесты.
 *
 * Инвариант безопасности: access/refresh токены живут ТОЛЬКО в серверном
 * (httpOnly, зашифрованном) JWT и НИКОГДА не попадают в клиентскую сессию
 * (`shapeClientSession`).
 */

import type { OidcTokenSet } from "@/lib/keycloak";

export interface AccountLike {
  access_token?: string;
  refresh_token?: string;
  expires_at?: number;
}

/** Первый вход: переносим токены провайдера в серверный JWT. */
export function applyAccountTokens<T extends OidcTokenSet>(token: T, account: AccountLike): T {
  return {
    ...token,
    access_token: account.access_token,
    refresh_token: account.refresh_token,
    expires_at: account.expires_at,
  };
}

export interface ClientSessionExtras {
  expiresAt?: number;
  error?: string;
}

/**
 * Сессия, отдаваемая КЛИЕНТУ: намеренно БЕЗ access/refresh токенов (остаются
 * только в серверном JWT). Защита «токен не утекает в браузер» — security-тест.
 */
export function shapeClientSession<S extends object>(
  session: S,
  token: OidcTokenSet,
): S & ClientSessionExtras {
  return { ...session, expiresAt: token.expires_at, error: token.error };
}

/** Guard: доступ только при аутентифицированном пользователе. */
export function isAuthorized(auth: { user?: unknown } | null | undefined): boolean {
  return Boolean(auth?.user);
}
