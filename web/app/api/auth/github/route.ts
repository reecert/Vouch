import crypto from "node:crypto";
import { NextResponse } from "next/server";

import { authorizeUrl, pkcePair } from "@/lib/github";
import { SITE_URL } from "@/lib/share";

export const dynamic = "force-dynamic";

/**
 * Start the OAuth dance.
 *
 * `state` and the PKCE verifier go into one short-lived httpOnly cookie rather than the
 * database: there is no session yet, and a row created before anyone has proved anything is
 * a row an unauthenticated caller can make the server write.
 */
export async function GET() {
  const state = crypto.randomBytes(16).toString("hex");
  const { verifier, challenge } = pkcePair();

  try {
    const url = authorizeUrl(state, challenge);
    const res = NextResponse.redirect(url);
    res.cookies.set("vouch_oauth", `${state}.${verifier}`, {
      httpOnly: true,
      sameSite: "lax",
      secure: SITE_URL.startsWith("https://"),
      path: "/",
      maxAge: 600,
    });
    return res;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "GitHub Auth unavailable";
    return NextResponse.redirect(
      `${SITE_URL}/connect?error=${encodeURIComponent(
        message.includes("GITHUB_CLIENT_ID")
          ? "GitHub OAuth is not configured locally (GITHUB_CLIENT_ID is missing). Please use Quick Demo Sign-in."
          : message
      )}`
    );
  }
}
