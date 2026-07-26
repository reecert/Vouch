"""Core data primitives for vouch.

The whole product reduces to one object: **claim + evidence + confidence + freshness**.
Everything here is a plain Pydantic model — no logic, no I/O. These types define the
contracts between the pipeline stages:

    ingest  -> RepoSnapshot
    extract -> EvidenceBundle (Signals + CommitMeta index)
    judge   -> Verdict
    report  -> CapabilityReport

Hard rule encoded structurally: the judge only ever sees an ``EvidenceBundle`` — signals
plus SHA-anchored ``CommitMeta``. It never sees a raw diff, and never the repo.
"""
from __future__ import annotations

from datetime import date, datetime

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


# --------------------------------------------------------------------------------------
# extract output
# --------------------------------------------------------------------------------------


class Signal(BaseModel):
    """A single computed ownership signal, carrying the SHAs that back it.

    ``evidence`` is the receipts: every SHA here must also appear in the enclosing
    bundle's ``commit_index``, so the judge can cite it and the grounding validator can
    verify it.
    """

    key: str  # e.g. "fixed_own_bug"
    value: float | int | bool
    evidence: list[str] = Field(default_factory=list)  # commit SHAs / PR refs
    computed_at: datetime


class CommitMeta(BaseModel):
    """Human-readable anchor for one SHA the judge may cite. **No diff, ever.**"""

    sha: str
    short: str
    authored_at: datetime
    subject: str
    n_files: int
    touched_tests: bool


class EvidenceBundle(BaseModel):
    """The exact payload handed to the judge. The deterministic/LLM contract.

    The judge reasons ONLY over this. ``commit_index`` holds a ``CommitMeta`` for every
    SHA referenced by any signal — the anchors the rationale may cite — and nothing else.
    """

    repo: str
    subject: str  # canonical author email under evaluation
    dimension: str = "ownership"
    window_first: date | None = None
    window_last: date | None = None
    n_commits_by_subject: int = 0
    signals: list[Signal] = Field(default_factory=list)
    commit_index: dict[str, CommitMeta] = Field(default_factory=dict)

    def known_shas(self) -> set[str]:
        """Every SHA the judge is allowed to cite (grounding validator uses this)."""
        return set(self.commit_index.keys())


# --------------------------------------------------------------------------------------
# judge output
# --------------------------------------------------------------------------------------


class Verdict(BaseModel):
    """The model's judgment. Must cite only SHAs present in the input bundle."""

    dimension: str  # "ownership"
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)  # calibrated, not vibes
    freshness: date  # most recent supporting evidence
    rationale: str  # must reference cited SHAs
    cited_evidence: list[str] = Field(default_factory=list)  # SHAs actually used


# --------------------------------------------------------------------------------------
# report output
# --------------------------------------------------------------------------------------


class CapabilityReport(BaseModel):
    """Final artifact: verdict + the evidence that produced it + full provenance."""

    repo: str
    subject: str
    dimension: str
    verdict: Verdict
    evidence: list[Signal] = Field(default_factory=list)
    judge_model: str  # which provider/model produced the judgment
    prompt_version: str
    generated_at: datetime
