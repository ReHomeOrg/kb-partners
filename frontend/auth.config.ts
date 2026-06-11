/**
 * Edge-совместимая часть конфигурации Auth.js: guard защищённых маршрутов +
 * страница входа. Без провайдеров/секретов (грузится в middleware, edge runtime).
 * Полная конфигурация (Keycloak provider, callbacks) — в `auth.ts` (node runtime).
 */

import type { NextAuthConfig } from "next-auth";

import { isAuthorized } from "@/lib/auth-callbacks";

export const authConfig = {
  pages: { signIn: "/login" },
  providers: [],
  callbacks: {
    authorized({ auth }) {
      return isAuthorized(auth);
    },
  },
} satisfies NextAuthConfig;
