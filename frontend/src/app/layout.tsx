import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Finance AI Dashboard",
  description: "Dashboard analytique futuriste avec React et Node.js",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr">
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
