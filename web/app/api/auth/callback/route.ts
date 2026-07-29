import { NextResponse, type NextRequest } from "next/server";

import { db, nowIso, type User } from "@/lib/db";
import { exchangeCode, fetchViewer } from "@/lib/github";
import { createSession } from "@/lib/session";
import { SITE_URL } from "@/lib/share";

export const dynamic = "force-dynamic";

/**
 * Finish the dance: verify `state`, exchange the code, upsert the user, open a session.
 *
 * The state check is first and unconditional. Without it this endpoint will happily log
 * someone into an account chosen by whoever sent them the link, which is the login-CSRF the
 * parameter exists for.
 */
export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const stored = req.cookies.get("vouch_oauth")?.value ?? "";
  const [expectedState, verifier] = stored.split(".");

  const fail = (why: string) =>
    NextResponse.redirect(`${SITE_URL}/connect?error=${encodeURIComponent(why)}`);

  if (!code || !state || !expectedState || state !== expectedState) {
    return fail("Sign-in could not be verified. Start again from this page.");
  }

  let viewer;
  let token;
  try {
    token = await exchangeCode(code, verifier);
    viewer = await fetchViewer(token);
  } catch {
    // The exception carries the client secret's failure mode and GitHub's raw text.
    return fail("GitHub declined the sign-in. Nothing was saved.");
  }

  const handle = db();
  handle
    .prepare(
      // ponytail: the token is at rest in plaintext in a gitignored file; encrypt it behind
      // a KMS if this ever runs anywhere but one host. `read:user` is what limits the blast
      // radius today — it cannot read a private repo or write anything.
      `INSERT INTO users (gh_id, login, name, email, avatar_url, token, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(gh_id) DO UPDATE SET login = excluded.login, name = excluded.name,
                                        avatar_url = excluded.avatar_url,
                                        token = excluded.token`,
    )
    .run(viewer.id, viewer.login, viewer.name, viewer.email, viewer.avatar, token, nowIso());
  const user = handle
    .prepare("SELECT * FROM users WHERE gh_id = ?")
    .get(viewer.id) as User;

  await createSession(user.id);
  const res = NextResponse.redirect(`${SITE_URL}/connect`);
  res.cookies.delete("vouch_oauth");
  return res;
}
