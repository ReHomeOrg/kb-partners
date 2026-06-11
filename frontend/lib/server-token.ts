import "server-only";

import { headers } from "next/headers";
import { getToken } from "next-auth/jwt";

import { readEnv } from "@/lib/env";

/**
 * Достаёт access token из серверного JWT (httpOnly cookie). `server-only` —
 * никогда не в клиентском бандле. Поведение `apiFetch` покрыто unit'ами через
 * инъекцию `getAccessToken`; сама обвязка над `getToken` — E2E.
 */
export async function getServerAccessToken(): Promise<string | undefined> {
  const env = readEnv();
  const requestHeaders = headers();
  const token = await getToken({
    req: { headers: Object.fromEntries(requestHeaders.entries()) },
    secret: env.authSecret,
    secureCookie: process.env.NODE_ENV === "production",
  });
  return token?.access_token as string | undefined;
}
