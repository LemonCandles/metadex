import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Metadex",
  description: "Catálogo estatístico do meta de Dota 2",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
