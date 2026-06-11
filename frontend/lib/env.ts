/**
 * Валидация обязательных переменных окружения фронтенда (fail-fast, config-driven).
 *
 * Значения (Keycloak client/секрет, базовый URL API kb-partners) задаются
 * окружением деплоя — в коде не хардкодятся. Отсутствие переменной останавливает
 * приложение с понятной ошибкой, а не падает глубже в auth-слое.
 */

const REQUIRED_ENV = [
  "AUTH_SECRET",
  "AUTH_KEYCLOAK_ID",
  "AUTH_KEYCLOAK_SECRET",
  "AUTH_KEYCLOAK_ISSUER",
  "KB_PARTNERS_API_BASE_URL",
] as const;

type RequiredEnvKey = (typeof REQUIRED_ENV)[number];

export interface FrontendEnv {
  authSecret: string;
  keycloakId: string;
  keycloakSecret: string;
  keycloakIssuer: string;
  /** Базовый URL API kb-partners (без завершающего слэша). */
  apiBaseUrl: string;
}

export function readEnv(source: Record<string, string | undefined> = process.env): FrontendEnv {
  const missing = REQUIRED_ENV.filter((key) => !source[key]?.trim());
  if (missing.length > 0) {
    throw new Error(
      `Отсутствуют обязательные переменные окружения: ${missing.join(", ")}. ` +
        "См. frontend/.env.example.",
    );
  }
  const get = (key: RequiredEnvKey): string => source[key] as string;
  return {
    authSecret: get("AUTH_SECRET"),
    keycloakId: get("AUTH_KEYCLOAK_ID"),
    keycloakSecret: get("AUTH_KEYCLOAK_SECRET"),
    keycloakIssuer: get("AUTH_KEYCLOAK_ISSUER"),
    apiBaseUrl: get("KB_PARTNERS_API_BASE_URL").replace(/\/+$/, ""),
  };
}
