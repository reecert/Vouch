import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "vouch — engineering capability profile",
  description:
    "An evidence-backed profile of an engineer's observable behaviour, with its limitations stated.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        {children}
      </body>
    </html>
  );
}
