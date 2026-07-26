/**
 * Profile snapshots on disk.
 *
 * A share link resolves to a frozen document, so profiles are plain JSON files read at
 * build time and pre-rendered. There is no database, no session, and nothing to log in
 * to — a recipient sees the document that was shared, not a live view of the subject's
 * ongoing activity.
 */
import fs from "node:fs";
import path from "node:path";

import type { Profile } from "./profile";

const PROFILE_DIR = path.join(process.cwd(), "data", "profiles");

export function listProfileIds(): string[] {
  if (!fs.existsSync(PROFILE_DIR)) return [];
  return fs
    .readdirSync(PROFILE_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.replace(/\.json$/, ""))
    .sort();
}

export function loadProfile(id: string): Profile | null {
  // Guard the path: `id` comes from the URL, and a share link must not be able to read
  // an arbitrary file off the host.
  if (!/^[a-f0-9]{8,64}$/.test(id)) return null;
  const file = path.join(PROFILE_DIR, `${id}.json`);
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, "utf8")) as Profile;
}
