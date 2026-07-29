import { NextResponse } from "next/server";

import { listRepos } from "@/lib/github";
import { currentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

/** The repos the signed-in user can pick from. Public only — the token has no other scope. */
export async function GET() {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  try {
    return NextResponse.json({ repos: await listRepos(user.token), email: user.email });
  } catch {
    return NextResponse.json({ error: "GitHub could not be reached" }, { status: 502 });
  }
}
