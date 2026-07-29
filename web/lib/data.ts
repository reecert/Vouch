/**
 * Profile snapshots on disk.
 *
 * A share link resolves to a frozen document, so profiles are plain JSON files read from
 * disk. There is no database row behind the document and nothing to log in to in order to
 * read one — a recipient sees the document that was shared, not a live view of the
 * subject's ongoing activity.
 *
 * **Two directories, one lookup.** `data/profiles` is tracked and holds the synthetic
 * samples; `var/profiles` is gitignored and holds what the worker generated for real
 * people. They are separate so a real person's profile can never arrive in a commit because
 * something wrote it next to the samples, and so `deleteProfile` has nothing checked in
 * within reach.
 */
import fs from "node:fs";
import path from "node:path";

import type { Profile } from "./profile";

const SAMPLE_DIR = path.join(process.cwd(), "data", "profiles");

export const RUNTIME_DIR =
  process.env.VOUCH_PROFILE_DIR ?? path.join(process.cwd(), "..", "var", "profiles");

const DIRS = [RUNTIME_DIR, SAMPLE_DIR];

export function listProfileIds(): string[] {
  const ids = DIRS.flatMap((dir) =>
    fs.existsSync(dir)
      ? fs
          .readdirSync(dir)
          .filter((f) => f.endsWith(".json"))
          .map((f) => f.slice(0, -".json".length))
      : [],
  );
  return [...new Set(ids)].sort();
}

export function loadProfile(id: string): Profile | null {
  // `id` comes from the URL: a share link must not read an arbitrary file off the host.
  if (!/^[a-f0-9]{8,64}$/.test(id)) return null;
  for (const dir of DIRS) {
    const file = path.join(dir, `${id}.json`);
    if (fs.existsSync(file)) return JSON.parse(fs.readFileSync(file, "utf8")) as Profile;
  }
  return null;
}

/** Revoking deletes the document itself, so a retired link resolves to nothing, not to a stub. */
export function deleteProfile(id: string): boolean {
  if (!/^[a-f0-9]{8,64}$/.test(id)) return false;
  const file = path.join(RUNTIME_DIR, `${id}.json`);
  if (!fs.existsSync(file)) return false;
  fs.rmSync(file);
  return true;
}
