"""Freeze the session log directory before reading it.

**The CLI must not observe its own writes.** `vouch` is normally run from inside a Claude
Code session, and that session is appending to a file in the very directory being parsed.
Reading it live means the input changes underneath the run: two invocations a second apart
see different bytes, produce different denominators, and mint different `profile_id`s for
what is meant to be the same document. A share link that silently stops matching the
profile it was generated from is not a cosmetic bug — the frozen-snapshot promise in L5 is
the whole reason a reader can trust what they were sent.

So the read is done against a copy, and the copy is identified by a content digest:

* **``digest``** — over every file's relative path, size, and content hash, sorted. Two
  snapshots with the same digest hold identical bytes, so the whole pipeline downstream is
  a pure function of it. This is the *as-of* marker; it travels into the profile.
* **``as_of``** — the newest modification time seen, for a human reading the report. It is
  a description, not the identity: mtimes are not stable across a copy or a restore.

Snapshots are content-addressed under the cache directory, so an unchanged log directory
costs one hash pass and no copy on the second run, and an explicit ``--as-of`` can re-read
an earlier one exactly.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "SNAPSHOT_VERSION",
    "MANIFEST",
    "SessionSnapshot",
    "snapshot_sessions",
    "open_snapshot",
]

SNAPSHOT_VERSION = "l2-snap/1"  # part of the digest, so an old layout is a miss
MANIFEST = "snapshot.json"  # records what the digest cannot: the newest log mtime

_DIGEST_LEN = 16


@dataclass(frozen=True)
class SessionSnapshot:
    """An immutable copy of a session log directory, and what identifies it."""

    root: Path
    digest: str
    as_of: datetime | None
    n_files: int
    reused: bool = False


def _index(source: Path) -> tuple[list[Path], str, datetime | None]:
    """Every session file under ``source``, its collective digest, and the newest mtime."""
    files = sorted(p for p in source.rglob("*.jsonl") if p.is_file())
    hasher = hashlib.sha256()
    hasher.update(SNAPSHOT_VERSION.encode())
    newest: float | None = None

    for path in files:
        rel = path.relative_to(source).as_posix()
        stat = path.stat()
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        # Path and size too: a moved file changes what the parse means at identical bytes.
        hasher.update(f"{rel}\0{stat.st_size}\0{content}\0".encode())
        newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)

    as_of = datetime.fromtimestamp(newest, UTC) if newest is not None else None
    return files, hasher.hexdigest()[:_DIGEST_LEN], as_of


def snapshot_sessions(source: Path, cache_dir: Path) -> SessionSnapshot:
    """Copy ``source`` into a content-addressed snapshot and return its identity.

    A missing source is not an error here: an empty snapshot is a legitimate state that the
    parser already reports as degraded, and failing early would turn "you have no session
    logs" into a crash.
    """
    if not source.is_dir():
        return SessionSnapshot(root=source, digest="empty", as_of=None, n_files=0)

    files, digest, as_of = _index(source)
    root = cache_dir / "sessions" / digest

    # No manifest means an older layout: a miss, rather than a half-read of an unknown shape.
    if root.is_dir() and (root / MANIFEST).is_file():
        # The recorded `as_of` is returned, so touching a log cannot shift it under one digest.
        return open_snapshot(digest, cache_dir)

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.with_name(f".{digest}.partial")
    for stale in (staging, root):
        if stale.exists():
            shutil.rmtree(stale)
    staging.mkdir(parents=True)
    for path in files:
        target = staging / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    # `as_of` is recorded now because the copy does not carry the source mtimes.
    (staging / MANIFEST).write_text(
        json.dumps(
            {
                "version": SNAPSHOT_VERSION,
                "digest": digest,
                "as_of": as_of.isoformat() if as_of else None,
                "n_files": len(files),
            },
            indent=2,
        )
    )
    # Published by rename, so a snapshot directory is never half-written under its digest.
    staging.replace(root)

    return SessionSnapshot(root=root, digest=digest, as_of=as_of, n_files=len(files))


def open_snapshot(digest: str, cache_dir: Path) -> SessionSnapshot:
    """Re-open a snapshot taken earlier. The way to reproduce a run exactly.

    The digest is re-derived from the copy and checked. A snapshot whose contents no longer
    hash to the name it is filed under has been edited, and re-reading it would reproduce
    the *name* of an earlier run rather than the run — which is worse than not reproducing
    it at all, because the output would carry the old marker.
    """
    root = cache_dir / "sessions" / digest
    if not root.is_dir():
        raise FileNotFoundError(
            f"no session snapshot {digest!r} under {cache_dir / 'sessions'} — "
            "it was taken on another machine, or the cache was cleared"
        )
    files, actual, _mtime = _index(root)
    if actual != digest:
        raise ValueError(
            f"session snapshot {digest!r} now hashes to {actual!r}: its contents changed "
            "after it was frozen, so it cannot reproduce the run it is named for"
        )
    manifest = json.loads((root / MANIFEST).read_text())
    recorded = manifest.get("as_of")
    return SessionSnapshot(
        root=root,
        digest=digest,
        as_of=datetime.fromisoformat(recorded) if recorded else None,
        n_files=len(files),
        reused=True,
    )
