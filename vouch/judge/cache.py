"""Judge-call cache, keyed by evidence-bundle content hash.

Re-running eval metrics must not re-burn API quota. The judge is a pure function of
``(EvidenceBundle, prompt_version)``, so we cache its ``(Verdict, judge_model)`` output on
disk under a hash of exactly those inputs. A second run over the same labels reads every
verdict from disk and makes zero network calls.

Two subtleties this module gets right:

  * **Volatile fields are excluded from the hash.** ``Signal.computed_at`` (and any other
    wall-clock field) changes every extraction run even when the *evidence* is identical.
    Hashing it would defeat the cache. We hash the evidence, not the timestamp.
  * **The prompt version is part of the key.** A prompt change is a different question, so
    it must miss the cache — otherwise iterating on the prompt would silently reuse stale
    verdicts from the old prompt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from vouch.schemas import EvidenceBundle, Verdict

DEFAULT_CACHE_DIR = Path(".vouch_cache") / "judge"

# Bump when the cache *record* format changes (not when the prompt changes — that is part
# of the key). Keeps stale-format records from being misread as valid.
_CACHE_SCHEMA = "v1"


def bundle_hash(bundle: EvidenceBundle, prompt_version: str) -> str:
    """Stable content hash of the judge's inputs — evidence + prompt version.

    Deterministic across runs: signals are reduced to ``(key, value, sorted evidence)``
    with ``computed_at`` dropped, and the commit index to ``(sha, subject, date, n_files,
    touched_tests)``. Two extractions of the same repo state hash identically even though
    their ``computed_at`` timestamps differ.
    """
    payload = {
        "schema": _CACHE_SCHEMA,
        "prompt_version": prompt_version,
        "repo": bundle.repo,
        "subject": bundle.subject,
        "dimension": bundle.dimension,
        "n_commits_by_subject": bundle.n_commits_by_subject,
        "signals": sorted(
            (
                {
                    "key": s.key,
                    "value": s.value,
                    "evidence": sorted(s.evidence),
                }
                for s in bundle.signals
            ),
            key=lambda d: d["key"],
        ),
        "commit_index": {
            sha: {
                "subject": m.subject,
                "date": m.authored_at.date().isoformat(),
                "n_files": m.n_files,
                "touched_tests": m.touched_tests,
            }
            for sha, m in sorted(bundle.commit_index.items())
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


class JudgeCache:
    """Disk-backed store of ``hash -> (Verdict, judge_model)``.

    Keyed by :func:`bundle_hash`, so it is content-addressed and provider-agnostic. A
    ``JudgeCache(dir_=None)`` is a no-op cache (every ``get`` misses) — handy for tests
    and for forcing fresh judge calls.
    """

    def __init__(self, dir_: Path | None = DEFAULT_CACHE_DIR) -> None:
        self.dir = Path(dir_) if dir_ is not None else None
        self.hits = 0
        self.misses = 0
        if self.dir is not None:
            self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        assert self.dir is not None
        return self.dir / f"{key}.json"

    def get(self, key: str) -> tuple[Verdict, str] | None:
        """Return the cached ``(Verdict, judge_model)`` for ``key``, or None on miss."""
        if self.dir is None:
            self.misses += 1
            return None
        path = self._path(key)
        if not path.is_file():
            self.misses += 1
            return None
        try:
            rec = json.loads(path.read_text())
            verdict = Verdict.model_validate(rec["verdict"])
        except Exception:
            # A corrupt record is a miss, not a crash — the caller will recompute + rewrite.
            self.misses += 1
            return None
        self.hits += 1
        return verdict, rec["judge_model"]

    def put(self, key: str, verdict: Verdict, judge_model: str) -> None:
        """Persist ``(verdict, judge_model)`` under ``key``. No-op if caching disabled."""
        if self.dir is None:
            return
        rec = {"judge_model": judge_model, "verdict": verdict.model_dump(mode="json")}
        self._path(key).write_text(json.dumps(rec, indent=2))
