/**
 * Sign-in state: an opaque id in a cookie, the truth in a row.
 *
 * Not a signed/encrypted cookie carrying claims. A row can be deleted — signing out, or
 * revoking after a mistake, takes effect on the next request instead of when a token that
 * was already handed out happens to expire. The cookie itself says nothing: it is 32 random
 * bytes with no meaning outside the `sessions` table, so a copy of it leaks no identity and
 * nothing about it is worth forging.
 *
 * Ownership checks read from here rather than from a request parameter, because every route
 * that mutates a job is one missing `WHERE user_id = ?` away from acting on someone else's.
 */
import { cookies } from "next/headers";
import crypto from "node:crypto";

import { db, nowIso, type User } from "./db";
import { SITE_URL } from "./share";

const COOKIE = "vouch_session";
const LIFETIME_DAYS = 30;

function expiry(): string {
  return new Date(Date.now() + LIFETIME_DAYS * 86_400_000).toISOString();
}

export async function createSession(userId: number): Promise<void> {
  const id = crypto.randomBytes(32).toString("hex");
  db()
    .prepare("INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)")
    .run(id, userId, nowIso(), expiry());

  (await cookies()).set(COOKIE, id, {
    httpOnly: true,
    sameSite: "lax",
    secure: SITE_URL.startsWith("https://"),
    path: "/",
    maxAge: LIFETIME_DAYS * 86_400,
  });
}

export async function currentUser(): Promise<User | null> {
  const id = (await cookies()).get(COOKIE)?.value;
  if (!id) return null;

  const row = db()
    .prepare(
      `SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
       WHERE s.id = ? AND s.expires_at > ?`,
    )
    .get(id, new Date().toISOString()) as User | undefined;
  return row ?? null;
}

export async function destroySession(): Promise<void> {
  const jar = await cookies();
  const id = jar.get(COOKIE)?.value;
  if (id) db().prepare("DELETE FROM sessions WHERE id = ?").run(id);
  jar.delete(COOKIE);
}
