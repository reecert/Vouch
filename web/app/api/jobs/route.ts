import crypto from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";

import { db, nowIso, type Job } from "@/lib/db";
import { currentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * A repo is named here, never addressed.
 *
 * The worker builds `https://github.com/<full_name>` from this string, so anything that is
 * not a bare `owner/repo` has to be refused before it becomes a `git clone` argument: a
 * path, a URL with a different host, an ssh address, or a leading `--` that git would read
 * as an option. Mirrored from `GITHUB_FULL_NAME` in `vouch/serve/db.py`; a test asserts the
 * two patterns are the same string.
 */
const FULL_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

/** Deliberately loose — this is the address a git history is authored under, not a login. */
const EMAIL = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,20}$/;

/** Each run costs a judge call, so a queue one person can fill is a budget one person can spend. */
const MAX_OPEN_JOBS = 3;

export async function GET() {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const jobs = db()
    .prepare(
      `SELECT id, full_name, author_email, status, reason, profile_id, created_at, finished_at
       FROM jobs WHERE user_id = ? AND status != 'revoked' ORDER BY created_at DESC LIMIT 50`,
    )
    .all(user.id) as unknown as Job[];
  return NextResponse.json({ jobs });
}

export async function POST(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const body = (await req.json().catch(() => ({}))) as {
    full_name?: string;
    author_email?: string;
  };
  const fullName = (body.full_name ?? "").trim();
  const email = (body.author_email ?? "").trim();

  if (!FULL_NAME.test(fullName)) {
    return NextResponse.json({ error: "Pick a repository from the list." }, { status: 400 });
  }
  if (!EMAIL.test(email)) {
    return NextResponse.json({ error: "That does not look like an email address." }, { status: 400 });
  }

  const open = db()
    .prepare("SELECT COUNT(*) AS n FROM jobs WHERE user_id = ? AND status IN ('queued','running')")
    .get(user.id) as { n: number };
  if (open.n >= MAX_OPEN_JOBS) {
    return NextResponse.json(
      { error: `You already have ${open.n} profiles building. Wait for one to finish.` },
      { status: 429 },
    );
  }

  const id = crypto.randomBytes(16).toString("hex");
  db()
    .prepare(
      `INSERT INTO jobs (id, user_id, full_name, author_email, status, created_at)
       VALUES (?, ?, ?, ?, 'queued', ?)`,
    )
    .run(id, user.id, fullName, email, nowIso());

  return NextResponse.json({ id, status: "queued" }, { status: 202 });
}
