"""Persist L1's output, so a labelling round costs seconds instead of forty-seven minutes.

L1 is expensive for one reason: `git blame` on every changed line of every fix commit,
across twelve real repos with histories in the thousands of commits. It is also *pure* —
`RepoFacts` is a deterministic function of (repo, pinned HEAD, subject identity, config),
with no wall-clock anywhere in the payload, which is what the golden-file tests already
rest on. A pure expensive function is exactly what a cache is for.

The reason this matters is not developer comfort. A labelling round that takes forty-seven
minutes is a round that gets done once, in one sitting, under time pressure — and the
corpus is the only thing standing between the judge and an unmeasured accuracy claim. Cheap
re-runs are what let a human label carefully, stop, and come back.

**The key is everything the output depends on**, so a stale entry is impossible rather than
unlikely:

* the repo and its **pinned HEAD** — a moving branch is a different measurement;
* the **subject identity**, canonical address plus resolved aliases;
* :data:`EXTRACTOR_VERSION`, bumped by hand when the computation changes;
* ``L1Config.fingerprint()``, which already covers every threshold.

A miss is silent and cheap. A *wrong hit* would be a golden file's worth of damage, so
everything that could make two runs differ is in the key rather than trusted to stay equal.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from vouch.l1.config import L1_CONFIG, L1Config
from vouch.l1.facts import RepoFacts

__all__ = [
    "EXTRACTOR_VERSION",
    "cache_key",
    "load_cached_facts",
    "store_facts",
    "cached_extract",
]

#: Bump when the *computation* changes — a predicate, a blame rule, a new fact, a changed
#: interval. Distinct from `SCHEMA_VERSION`, which describes the output's shape: a fix that
#: changes what `ownership_loop` counts leaves the shape identical and every cached value
#: wrong. When in doubt, bump it; the cost of a spurious miss is one re-run.
EXTRACTOR_VERSION = "l1-extract/2"

_KEY_LEN = 24


def cache_key(
    repo: str,
    head_sha: str,
    author: str,
    aliases: list[str] | None = None,
    config: L1Config | None = None,
) -> str:
    """Everything the facts depend on, hashed. Aliases are sorted so order cannot vary it."""
    config = config or L1_CONFIG
    parts = [
        EXTRACTOR_VERSION,
        config.fingerprint(),
        repo,
        head_sha,
        author.strip().lower(),
        ",".join(sorted(a.strip().lower() for a in (aliases or []))),
    ]
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:_KEY_LEN]


def _path(cache_dir: Path, key: str) -> Path:
    return cache_dir / "l1" / f"facts_{key}.json"


def load_cached_facts(key: str, cache_dir: Path) -> RepoFacts | None:
    """Return cached facts, or None. A corrupt entry is a miss, never a crash.

    Deleting the bad file matters: leaving it would make every future run pay the parse,
    fail, and recompute, which is a cache that costs more than it saves.
    """
    path = _path(cache_dir, key)
    if not path.is_file():
        return None
    try:
        return RepoFacts.model_validate_json(path.read_text())
    except Exception:
        path.unlink(missing_ok=True)
        return None


def store_facts(key: str, facts: RepoFacts, cache_dir: Path) -> Path:
    """Write facts to the cache. Published by rename so a reader never sees a partial file."""
    path = _path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(facts.model_dump_json())
    tmp.replace(path)
    return path


def cached_extract(
    repo: str,
    head_sha: str,
    author: str,
    compute,
    aliases: list[str] | None = None,
    cache_dir: Path | None = None,
    config: L1Config | None = None,
    refresh: bool = False,
) -> tuple[RepoFacts, bool]:
    """Return ``(facts, was_cached)``, computing via ``compute()`` only on a miss.

    ``compute`` is passed in rather than imported so this module stays free of the
    extractor and can be tested without a repo — and so a caller with its own idea of what
    "extract" means (a harness, a benchmark) can reuse the keying.
    """
    from vouch.ingest import DEFAULT_CACHE_DIR

    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    key = cache_key(repo, head_sha, author, aliases, config)

    if not refresh and (hit := load_cached_facts(key, cache_dir)) is not None:
        return hit, True

    facts = compute()
    store_facts(key, facts, cache_dir)
    return facts, False
