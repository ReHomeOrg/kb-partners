/**
 * Аугментация типов next-auth: серверный JWT несёт токены Keycloak; клиентская
 * Session — только неконфиденциальные поля (expiresAt/error), без токенов.
 */
import "next-auth";
import "next-auth/jwt";

declare module "next-auth/jwt" {
  interface JWT {
    access_token?: string;
    refresh_token?: string;
    expires_at?: number;
    error?: string;
  }
}

declare module "next-auth" {
  interface Session {
    expiresAt?: number;
    error?: string;
  }
}
