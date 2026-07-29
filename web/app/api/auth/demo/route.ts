import { NextResponse } from "next/server";
import { db, nowIso, type User } from "@/lib/db";
import { createSession } from "@/lib/session";
import { SITE_URL } from "@/lib/share";

export const dynamic = "force-dynamic";

export async function GET() {
  const handle = db();
  let user = handle.prepare("SELECT * FROM users WHERE gh_id = 999999").get() as User | undefined;

  if (!user) {
    handle
      .prepare(
        `INSERT INTO users (gh_id, login, name, email, avatar_url, token, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        999999,
        "demo-user",
        "Demo Engineer",
        "demo@vouch.dev",
        "https://github.com/ghost.png",
        "demo_token",
        nowIso(),
      );
    user = handle.prepare("SELECT * FROM users WHERE gh_id = 999999").get() as User;
  }

  await createSession(user.id);
  return NextResponse.redirect(`${SITE_URL}/connect`);
}

export async function POST() {
  return GET();
}
