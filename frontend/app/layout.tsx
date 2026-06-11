import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "reHome — портал партнёра",
  description: "Партнёрский портал обработки заявок (kb-partners, LIGHT)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body className="min-h-screen antialiased">
        <div className="mx-auto max-w-5xl px-4 py-6">{children}</div>
      </body>
    </html>
  );
}
