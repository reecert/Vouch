import { NextResponse } from "next/server";

import { destroySession } from "@/lib/session";
import { SITE_URL } from "@/lib/share";

export const dynamic = "force-dynamic";

/** POST, not GET: a link someone else embeds must not be able to sign you out. */
export async function POST() {
  await destroySession();
  return NextResponse.redirect(`${SITE_URL}/`, { status: 303 });
}
