import type { Metadata } from "next";

import { SHARE_CARD, SITE_URL } from "@/lib/share";

import "./globals.css";

const DESCRIPTION =
  "An evidence-backed profile of an engineer's observable behaviour, with its limitations stated.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "vouch engineering capability profile",
    template: "%s · vouch",
  },
  description: DESCRIPTION,
  // A share link is unlisted, and an indexed unlisted link is a listed one. Unfurlers read
  // og tags and ignore this, so cards still render; there is deliberately no robots.txt,
  // because Slackbot does honour that one and would stop unfurling entirely.
  robots: { index: false, follow: false },
  openGraph: {
    title: "vouch — engineering capability profile",
    description: DESCRIPTION,
    siteName: "vouch",
    type: "website",
    images: [SHARE_CARD],
  },
  twitter: {
    card: "summary_large_image",
    title: "vouch — engineering capability profile",
    description: DESCRIPTION,
    images: [SHARE_CARD],
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50/50 text-slate-900 antialiased selection:bg-slate-200">
        {children}
      </body>
    </html>
  );
}
