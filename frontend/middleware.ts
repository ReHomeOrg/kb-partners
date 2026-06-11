/**
 * Guard защищённых маршрутов. Неавторизованный → редирект на /login → Keycloak.
 * Использует edge-совместимый `authConfig` (без провайдеров/секретов).
 */

import NextAuth from "next-auth";

import { authConfig } from "@/auth.config";

const { auth } = NextAuth(authConfig);

export default auth;

export const config = {
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico).*)"],
};
