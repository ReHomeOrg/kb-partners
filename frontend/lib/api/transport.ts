import "server-only";

import { readEnv } from "@/lib/env";
import { getServerAccessToken } from "@/lib/server-token";

/** Бросается, когда серверный вызов API делается без аутентифицированной сессии. */
export class UnauthenticatedError extends Error {
  constructor(message = "Нет access token в сессии") {
    super(message);
    this.name = "UnauthenticatedError";
  }
}

export interface ApiFetchDeps {
  /** Источник access token (по умолчанию — серверный JWT). Инъекция для тестов. */
  getAccessToken?: () => Promise<string | undefined>;
  fetchImpl?: typeof fetch;
}

/**
 * Серверный HTTP-клиент к API kb-partners: берёт access token из серверной сессии
 * и ставит `Authorization: Bearer`. Токен в браузер не отдаётся (вызов только на
 * сервере — RSC/Route Handlers). Базовый URL — из конфига, не хардкод.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
  deps: ApiFetchDeps = {},
): Promise<Response> {
  const getAccessToken = deps.getAccessToken ?? getServerAccessToken;
  const fetchImpl = deps.fetchImpl ?? fetch;

  const accessToken = await getAccessToken();
  if (!accessToken) {
    throw new UnauthenticatedError();
  }

  const { apiBaseUrl } = readEnv();
  const requestHeaders = new Headers(init.headers);
  requestHeaders.set("Authorization", `Bearer ${accessToken}`);

  return fetchImpl(`${apiBaseUrl}${path}`, { ...init, headers: requestHeaders });
}
