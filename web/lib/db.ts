/**
 * The other half of `vouch/serve/db.py`, in the runtime that serves requests.
 *
 * `node:sqlite` is standard library, so the web process shares state with the Python worker
 * without a broker, a driver dependency, or a service that has to be up for a page to
 * render. The schema lives in Python because the worker is what cannot run without it; this
 * side opens the same file and assumes the tables exist. `CREATE TABLE IF NOT EXISTS` is
 * repeated here only so a fresh checkout can sign in before the worker has ever started.
 *
 * WAL and a busy timeout are set on both sides: two writers on one file is the deployment,
 * and the default journal would turn a worker's transaction into a failed sign-in here.
 */
import { DatabaseSync } from "node:sqlite";
import path from "node:path";
import fs from "node:fs";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    gh_id       INTEGER NOT NULL UNIQUE,
    login       TEXT    NOT NULL,
    name        TEXT    NOT NULL DEFAULT '',
    email       TEXT    NOT NULL DEFAULT '',
    avatar_url  TEXT    NOT NULL DEFAULT '',
    token       TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT    PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    full_name    TEXT    NOT NULL,
    author_email TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    reason       TEXT    NOT NULL DEFAULT '',
    profile_id   TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL,
    started_at   TEXT    NOT NULL DEFAULT '',
    finished_at  TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS jobs_by_user ON jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_queued ON jobs(status, created_at);
`;

export type JobStatus = "queued" | "running" | "done" | "failed" | "revoked";

export type User = {
  id: number;
  gh_id: number;
  login: string;
  name: string;
  email: string;
  avatar_url: string;
  token: string;
};

export type Job = {
  id: string;
  user_id: number;
  full_name: string;
  author_email: string;
  status: JobStatus;
  reason: string;
  profile_id: string;
  created_at: string;
  finished_at: string;
};

let handle: DatabaseSync | null = null;

export function db(): DatabaseSync {
  if (handle) return handle;
  const file = process.env.VOUCH_DB ?? path.join(process.cwd(), "..", "var", "vouch.db");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  handle = new DatabaseSync(file);
  handle.exec("PRAGMA journal_mode=WAL");
  handle.exec("PRAGMA busy_timeout=10000");
  handle.exec("PRAGMA foreign_keys=ON");
  handle.exec(SCHEMA);
  return handle;
}

export function nowIso(): string {
  return new Date().toISOString().replace(/\.\d+Z$/, "+00:00");
}
