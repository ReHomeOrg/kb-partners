import { signIn } from "@/auth";

/** Страница входа: редирект в Keycloak (authorization code flow). */
export default function LoginPage() {
  async function login() {
    "use server";
    await signIn("keycloak", { redirectTo: "/requests" });
  }

  return (
    <main className="mx-auto mt-24 max-w-sm text-center">
      <h1 className="text-2xl font-semibold">Портал партнёра reHome</h1>
      <p className="mt-2 text-sm text-gray-600">Войдите, чтобы видеть свои заявки.</p>
      <form action={login} className="mt-8">
        <button
          type="submit"
          className="w-full rounded-md bg-gray-900 px-4 py-2 text-white hover:bg-gray-700"
        >
          Войти через Keycloak
        </button>
      </form>
    </main>
  );
}
