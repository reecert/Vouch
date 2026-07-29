import { NextResponse } from "next/server";

import { db, type Job } from "@/lib/db";
import { deleteProfile } from "@/lib/data";
import { currentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

/** Ownership is read from the session, never from the request: `WHERE user_id` is the check. */
function ownedBy(userId: number, id: string): Job | null {
  return (db()
    .prepare("SELECT * FROM jobs WHERE id = ? AND user_id = ?")
    .get(id, userId) ?? null) as Job | null;
}

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const job = ownedBy(user.id, (await params).id);
  if (!job) return NextResponse.json({ error: "no such job" }, { status: 404 });
  return NextResponse.json({ job });
}

/**
 * Revoke: delete the document, then mark the row.
 *
 * The file goes first. If the two steps cannot both happen, a link that resolves to nothing
 * is the safe end state and a row that still claims a profile exists is not.
 */
export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const job = ownedBy(user.id, (await params).id);
  if (!job) return NextResponse.json({ error: "no such job" }, { status: 404 });

  if (job.profile_id) deleteProfile(job.profile_id);
  db()
    .prepare("UPDATE jobs SET status = 'revoked', profile_id = '' WHERE id = ?")
    .run(job.id);
  return NextResponse.json({ revoked: job.id });
}
