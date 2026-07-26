"""L3 — join sessions to commits. The differentiator.

Answers one question per commit: **is there supervision evidence behind this, or not?**

Runs entirely on the user's machine (see docs/plan.md open question 3). It needs both
halves — the session's edited file paths and the repo's commit paths — and uploading
session paths would mean paths from *every* project in the log directory, including
private and client work unrelated to the connected repo, crossing the network. Only the
outcome travels.

The join is deliberately conservative in three ways, because a false corroboration is
worse than an absent one: it would attach supervision evidence to work that was never
supervised, which is the precise claim a reader is relying on.

* **Direction is a hard constraint.** Edits precede the commit. A session that touched the
  same files *after* the commit is not evidence for it.
* **Both signals must clear a floor**, rather than a blended score letting a strong path
  overlap rescue an implausible three-day lag.
* **Ambiguity is a verdict, not a coin flip.** When two sessions fit a commit equally well
  the answer is `ambiguous`, not whichever sorted first.

`uncorroborated` is the expected majority outcome for most repos, and says only that this
commit has no session evidence — never that the work was unsupervised.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from vouch.l1.paths import is_noise
from vouch.l2.parser import EDIT_TOOLS, Session
from vouch.schemas import CommitRecord

__all__ = [
    "L3_SCHEMA_VERSION",
    "L3Config",
    "L3_CONFIG",
    "CorroborationVerdict",
    "MatchBasis",
    "Corroboration",
    "CorroborationReport",
    "SessionEdits",
    "session_edits",
    "join",
]

L3_SCHEMA_VERSION = "l3/1"


@dataclass(frozen=True)
class L3Config:
    """Join thresholds. A report records these so a verdict can be reproduced."""

    # A commit cannot precede the edits that produced it — but clocks disagree, so allow a
    # small negative lag rather than discarding a genuine match over 90 seconds of drift.
    clock_skew_minutes: int = 10
    # Beyond this, "you edited these files at some point and later committed them" stops
    # being evidence that the session produced the commit.
    max_lag_hours: int = 48
    # Temporal score halves every this many hours of lag.
    half_life_hours: float = 4.0
    # Share of the commit's significant files the session must have touched.
    min_path_overlap: float = 0.5
    # Two candidates within this score of each other are ambiguous, not a winner.
    ambiguity_margin: float = 0.10
    # Weighting for the combined score. Path overlap is the stronger evidence: timing
    # alone corroborates nothing, since sessions and commits both cluster in work hours.
    path_weight: float = 0.6

    def fingerprint(self) -> str:
        return (
            f"skew{self.clock_skew_minutes}m-lag{self.max_lag_hours}h-"
            f"hl{self.half_life_hours}-ov{self.min_path_overlap}-"
            f"mg{self.ambiguity_margin}-pw{self.path_weight}"
        )


L3_CONFIG = L3Config()


class CorroborationVerdict(StrEnum):
    """Three-valued by design. A boolean would have to lie about the ambiguous case."""

    CORROBORATED = "corroborated"
    AMBIGUOUS = "ambiguous"
    UNCORROBORATED = "uncorroborated"


class MatchBasis(BaseModel):
    """Why the join reached its verdict — the inspectable part.

    The competitor advertises a "Corroborated experience" dimension but publishes nothing
    about how a session is matched to a commit or how confident that match is. This is the
    difference between a label and evidence.
    """

    model_config = ConfigDict(extra="forbid")

    session_ref: str | None = None  # opaque session id; never a path or a prompt
    lag_seconds: int | None = None
    path_overlap: float | None = None
    n_matched_paths: int = 0
    n_commit_paths: int = 0
    n_candidates: int = 0  # how many sessions cleared both floors
    runner_up_score: float | None = None


class Corroboration(BaseModel):
    """One commit's verdict."""

    model_config = ConfigDict(extra="forbid")

    sha: str
    verdict: CorroborationVerdict
    match_score: float | None = None
    basis: MatchBasis = Field(default_factory=MatchBasis)


class CorroborationReport(BaseModel):
    """Every commit considered, with the counts a reader needs to weigh it."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = L3_SCHEMA_VERSION
    config_fingerprint: str = ""
    n_commits: int = 0
    n_sessions: int = 0
    n_sessions_in_repo: int = 0  # sessions that touched this repo at all
    n_corroborated: int = 0
    n_ambiguous: int = 0
    n_uncorroborated: int = 0
    records: list[Corroboration] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Share of commits with supervision evidence. Zero is a normal answer."""
        return self.n_corroborated / self.n_commits if self.n_commits else 0.0


@dataclass(frozen=True)
class SessionEdits:
    """A session reduced to what the join needs: when it edited, and what."""

    session_id: str
    paths: frozenset[str]  # repo-relative
    first_edit_at: datetime | None
    last_edit_at: datetime | None

    def edits_before(self, when: datetime) -> datetime | None:
        """The latest edit at or before ``when``; None if the session started after it."""
        if self.first_edit_at is None or self.first_edit_at > when:
            return None
        return min(self.last_edit_at or self.first_edit_at, when)


def _relativize(path: str, repo_root: Path) -> str | None:
    """Absolute session path -> repo-relative, or None if outside this repo.

    Session logs cover every project on the machine. Restricting to paths under the repo
    root is what keeps an unrelated project's activity from corroborating these commits.
    """
    try:
        candidate = Path(path).resolve()
    except (OSError, ValueError):
        return None
    try:
        return PurePosixPath(candidate.relative_to(repo_root)).as_posix()
    except ValueError:
        return None


def session_edits(sessions: list[Session], repo_root: Path) -> list[SessionEdits]:
    """Reduce parsed sessions to their in-repo edits. Sessions that never touched this
    repo are dropped, not scored as evidence of nothing."""
    root = repo_root.resolve()
    out: list[SessionEdits] = []

    for session in sessions:
        paths: set[str] = set()
        times: list[datetime] = []
        for event in session.events:
            if event.tool not in EDIT_TOOLS:
                continue
            hits = [r for p in event.paths if (r := _relativize(p, root))]
            if not hits:
                continue
            paths.update(hits)
            if event.at is not None:
                times.append(event.at)
        if not paths:
            continue
        out.append(
            SessionEdits(
                session_id=session.session_id,
                paths=frozenset(paths),
                first_edit_at=min(times) if times else None,
                last_edit_at=max(times) if times else None,
            )
        )
    return sorted(out, key=lambda s: s.session_id)


def _significant(commit: CommitRecord) -> set[str]:
    """The commit's hand-written files. Lockfile churn corroborates nothing."""
    return {p for p in commit.files if not is_noise(p)}


def _temporal_score(lag: timedelta, config: L3Config) -> float:
    """1.0 for a commit made during the session, decaying by half every half-life."""
    hours = max(lag.total_seconds() / 3600.0, 0.0)
    return math.pow(0.5, hours / config.half_life_hours)


def _score_candidate(
    edits: SessionEdits, commit: CommitRecord, config: L3Config
) -> tuple[float, MatchBasis] | None:
    """Score one (session, commit) pair, or None if it fails either hard constraint."""
    commit_paths = _significant(commit)
    if not commit_paths:
        return None

    matched = commit_paths & edits.paths
    overlap = len(matched) / len(commit_paths)
    if overlap < config.min_path_overlap:
        return None

    if edits.first_edit_at is None:
        return None  # no timestamped edits; nothing to sequence against

    when = commit.authored_at
    # Measure the lag from the session's last edit *at or before* the commit. Falling back
    # to the first edit when there is none makes the lag negative, which the direction
    # check below then rejects — a session that only touched these files after the commit.
    reference = edits.edits_before(when) or edits.first_edit_at
    lag = when - reference
    if lag < -timedelta(minutes=config.clock_skew_minutes):
        return None  # the session edited these files only *after* the commit
    if lag > timedelta(hours=config.max_lag_hours):
        return None

    score = (
        config.path_weight * overlap
        + (1 - config.path_weight) * _temporal_score(lag, config)
    )
    basis = MatchBasis(
        session_ref=edits.session_id,
        lag_seconds=int(lag.total_seconds()),
        path_overlap=round(overlap, 4),
        n_matched_paths=len(matched),
        n_commit_paths=len(commit_paths),
    )
    return round(score, 4), basis


def join(
    commits: list[CommitRecord],
    sessions: list[Session],
    repo_root: Path,
    config: L3Config | None = None,
) -> CorroborationReport:
    """Correlate sessions with commits. Runs locally; only this report is uploaded.

    Many-to-many is the normal case, not an edge: one session commonly produces several
    commits, and one squashed commit can absorb several sessions. Nothing here assumes a
    session or a commit is claimed only once.
    """
    config = config or L3_CONFIG
    edits = session_edits(sessions, repo_root)

    records: list[Corroboration] = []
    for commit in sorted(commits, key=lambda c: (c.authored_at, c.sha)):
        scored = [
            result
            for e in edits
            if (result := _score_candidate(e, commit, config)) is not None
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].session_ref or ""))

        if not scored:
            records.append(
                Corroboration(
                    sha=commit.sha,
                    verdict=CorroborationVerdict.UNCORROBORATED,
                    basis=MatchBasis(n_commit_paths=len(_significant(commit))),
                )
            )
            continue

        best_score, best_basis = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else None
        basis = best_basis.model_copy(
            update={"n_candidates": len(scored), "runner_up_score": runner_up}
        )

        ambiguous = (
            runner_up is not None and (best_score - runner_up) < config.ambiguity_margin
        )
        records.append(
            Corroboration(
                sha=commit.sha,
                verdict=(
                    CorroborationVerdict.AMBIGUOUS
                    if ambiguous
                    else CorroborationVerdict.CORROBORATED
                ),
                match_score=best_score,
                basis=basis,
            )
        )

    counts = {v: 0 for v in CorroborationVerdict}
    for record in records:
        counts[record.verdict] += 1

    return CorroborationReport(
        config_fingerprint=config.fingerprint(),
        n_commits=len(records),
        n_sessions=len(sessions),
        n_sessions_in_repo=len(edits),
        n_corroborated=counts[CorroborationVerdict.CORROBORATED],
        n_ambiguous=counts[CorroborationVerdict.AMBIGUOUS],
        n_uncorroborated=counts[CorroborationVerdict.UNCORROBORATED],
        records=records,
    )
