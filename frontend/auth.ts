/**
 * Полная конфигурация Auth.js (node runtime): Keycloak OIDC (auth code + PKCE),
 * JWT-сессия в httpOnly cookie, прокидывание/обновление токенов Keycloak.
 * Lazy-инициализация: env читается на запросе, не на верхнем уровне (иначе
 * `next build` падал бы без переменных окружения).
 */

import NextAuth from "next-auth";
import Keycloak from "next-auth/providers/keycloak";

import { authConfig } from "@/auth.config";
import { applyAccountTokens, shapeClientSession } from "@/lib/auth-callbacks";
import { readEnv } from "@/lib/env";
import { isAccessTokenValid, refreshAccessToken } from "@/lib/keycloak";

export const { handlers, auth, signIn, signOut } = NextAuth(() => {
  const env = readEnv();
  const client = {
    issuer: env.keycloakIssuer,
    clientId: env.keycloakId,
    clientSecret: env.keycloakSecret,
  };
  return {
    ...authConfig,
    providers: [
      Keycloak({
        clientId: client.clientId,
        clientSecret: client.clientSecret,
        issuer: client.issuer,
      }),
    ],
    session: { strategy: "jwt" },
    callbacks: {
      ...authConfig.callbacks,
      async jwt({ token, account }) {
        if (account) {
          return applyAccountTokens(token, account);
        }
        if (isAccessTokenValid(token, Date.now())) {
          return token;
        }
        return refreshAccessToken(token, client, { fetch, now: Date.now });
      },
      session({ session, token }) {
        return shapeClientSession(session, token);
      },
    },
  };
});
