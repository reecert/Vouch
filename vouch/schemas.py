"""Ingest-layer primitives — the normalized shape of a git history.

Plain Pydantic models: no logic, no I/O. These are the only types shared across layers, and
they describe *what git said*, never what anyone concluded from it. Each layer owns its own
output contract:

    ingest -> RepoSnapshot        (this module)
    L1     -> RepoFacts           (vouch.l1.facts)
    L2     -> SessionMetrics      (vouch.l2.payload)
    L3     -> CorroborationReport (vouch.l3.join)
    L4     -> JudgeResult         (vouch.l4.schema)
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------
# ingest output
# --------------------------------------------------------------------------------------


class CommitRecord(BaseModel):
    """One non-merge commit, normalized. The deterministic unit extractors reason over.

    Author identity is mailmap-resolved at parse time (git's own sanctioned aliasing).
    Committer fields are carried separately because the *gap* between author and committer
    date is how L1 detects a rebase-rewritten history.
    """

    sha: str
    author_name: str
    author_email: str  # canonical identity key, mailmap-resolved
    authored_at: datetime
    subject: str
    files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)  # subset of ``files``
    # If this commit is a git revert, the SHA it reverts (parsed from the body at
    # ingest time; the raw body is discarded). None otherwise.
    reverts_sha: str | None = None
    # Committer identity/date. Rebase preserves the author date and rewrites these, so a
    # large, widespread committed_at - authored_at gap means the history was replayed.
    committer_email: str = ""
    committed_at: datetime | None = None


class RepoSnapshot(BaseModel):
    """Deterministic, cacheable normalization of a repo at a pinned HEAD.

    Cached by ``repo + head_sha``. Contains everything the extractors need so they can
    run with no network. Blame is not precomputed for every line (too large); ingest
    exposes a blame helper the extractors call on demand, but the *snapshot* stays pure
    data so it can be serialized to cache.
    """

    repo: str
    head_sha: str
    commits: list[CommitRecord] = Field(default_factory=list)
    ingested_at: datetime
    # Repo-level facts the confound detectors need. Merge commits are excluded from
    # ``commits`` (we walk with --no-merges), but their *count* is evidence: a repo with
    # hundreds of commits and zero merges was squash-merged or rebase-merged.
    n_merge_commits: int = 0
    is_shallow: bool = False
