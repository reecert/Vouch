"""The server's state: one SQLite file, written by two languages.

Next.js owns the session and enqueues; a Python worker runs the pipeline. Both need the
same rows, and the cheapest correct way to share them between a Node process and a Python
process on one host is the database both runtimes already have — ``node:sqlite`` and
``sqlite3`` are standard library on each side. No broker, no ORM, no service to keep alive.

**WAL, because there are two writers.** The default rollback journal takes a lock over the
whole file, so a worker mid-transaction would make the web process fail a queue insert
instead of waiting. WAL lets the reader and the writer proceed together, and
``busy_timeout`` turns the remaining contention into a short wait rather than an error.

**One table does jobs and ownership.** A finished job *is* the profile record — it already
carries who asked for it and what came out — so a separate ``profiles`` table would only
restate ``jobs`` and add a way for the two to disagree about who owns a document.

**What is deliberately here and not in a profile:** the repo address, the subject's email,
and the GitHub token. This file is machine-local and gitignored; the document generated
from it carries a label, never an address (``vouch.ingest.repo_label``).
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "DEFAULT_DB_PATH",
    "JobStatus",
    "GITHUB_FULL_NAME",
    "claim_next_job",
    "connect",
    "db_path",
    "finish_job",
    "new_id",
    "now",
]

DEFAULT_DB_PATH = Path("var/vouch.db")

#: A repo is named, never addressed. The server builds the URL from this, so nothing a
#: browser sends can become a `file://` path, an ssh host, or a `git clone` option.
GITHUB_FULL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

SCHEMA = """
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
"""


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    REVOKED = "revoked"


def db_path() -> Path:
    """``VOUCH_DB`` if set, so the web process and the worker can be pointed at one file."""
    return Path(os.environ.get("VOUCH_DB") or DEFAULT_DB_PATH)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return secrets.token_hex(16)


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """An initialized connection. Cheap enough to open per unit of work."""
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        yield conn
    finally:
        conn.close()


def claim_next_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Take the oldest queued job, atomically.

    ``UPDATE ... RETURNING`` over a subquery is one statement, so two workers cannot both
    see the same row as queued — the check and the claim are not separable.
    """
    row = conn.execute(
        """
        UPDATE jobs SET status = ?, started_at = ?
        WHERE id = (SELECT id FROM jobs WHERE status = ? ORDER BY created_at LIMIT 1)
        RETURNING *
        """,
        (JobStatus.RUNNING, now(), JobStatus.QUEUED),
    ).fetchone()
    return row


def finish_job(
    conn: sqlite3.Connection, job_id: str, status: str, *, profile_id: str = "", reason: str = ""
) -> None:
    conn.execute(
        "UPDATE jobs SET status = ?, profile_id = ?, reason = ?, finished_at = ? WHERE id = ?",
        (status, profile_id, reason, now(), job_id),
    )
