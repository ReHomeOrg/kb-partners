import "@testing-library/jest-dom/vitest";

// Заглушки env для тестов, читающих readEnv (не секреты — только инициализация).
process.env.AUTH_SECRET ||= "test-auth-secret-not-for-prod";
process.env.AUTH_KEYCLOAK_ID ||= "kb-partners-frontend";
process.env.AUTH_KEYCLOAK_SECRET ||= "test-client-secret";
process.env.AUTH_KEYCLOAK_ISSUER ||= "https://keycloak.local/realms/rehome";
process.env.KB_PARTNERS_API_BASE_URL ||= "https://kb-partners.local";
