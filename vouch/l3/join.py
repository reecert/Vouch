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
* **A path is held by one session, not shared.** Each of the commit's files is credited to
  whichever session touched it *last* before the commit; a session whose edits were
  superseded holds nothing. This is what makes the match temporal without a separate
  temporal term — see :func:`_attribute` for what that replaced and why.
* **Ambiguity is a verdict, not a coin flip.** When two sessions fit a commit equally well
  the answer is `ambiguous`, not whichever sorted first.
* **Every dropped path is counted.** :class:`PathCoverage` travels in the report, because
  coverage that falls silently is indistinguishable from work that was never supervised.

`uncorroborated` is the expected majority outcome for most repos, and says only that this
commit has no session evidence — never that the work was unsupervised.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vouch.l1.paths import is_noise
from vouch.l2.parser import EDIT_TOOLS, Session
from vouch.l3.repo_identity import PathOutcome, RepoIdentity, resolve_identity
from vouch.schemas import CommitRecord

__all__ = [
    "L3_SCHEMA_VERSION",
    "L3Config",
    "L3_CONFIG",
    "CorroborationVerdict",
    "MatchBasis",
    "Corroboration",
    "CorroborationReport",
    "PathCoverage",
    "SessionEdits",
    "session_edits",
    "sessions_in_repo",
    "join",
]

L3_SCHEMA_VERSION = "l3/1"


@dataclass(frozen=True)
class L3Config:
    """Join thresholds. A report records these so a verdict can be reproduced."""

    # A commit cannot precede the edits that produced it — but clocks disagree, so allow a
    # small negative lag rather than discarding a genuine match over 90 seconds of drift.
    clock_skew_minutes: int = 10
    # Share of the commit's significant files the session must have *last touched* before
    # the commit. Unchanged from the previous model, where it was a share of files merely
    # touched — a strictly weaker predicate, so this floor is now harder to clear, not
    # easier. Deliberately not restated downward to compensate.
    min_path_overlap: float = 0.5
    # Two candidates within this score of each other are ambiguous, not a winner.
    ambiguity_margin: float = 0.10

    def fingerprint(self) -> str:
        return (
            f"skew{self.clock_skew_minutes}m-ov{self.min_path_overlap}-"
            f"mg{self.ambiguity_margin}-attr1"
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


class PathCoverage(BaseModel):
    """Where every session-edited path went. Loud by design.

    Coverage that drops silently is a defect, not a detail: a path the resolver could not
    place looks downstream exactly like a commit nobody supervised. ``n_unresolvable`` in
    particular is the number to watch — it means the log did not record a working
    directory, so a relative edit path had no base and was dropped rather than guessed.
    """

    model_config = ConfigDict(extra="forbid")

    n_in_repo: int = 0
    n_outside: int = 0  # another project on the same machine. Correct, not a loss.
    n_unresolvable: int = 0  # relative path, no recorded cwd — dropped, never guessed
    n_unknown_to_history: int = 0  # under a declared historical root git never saw
    n_untimed: int = 0  # in-repo, but the record carried no timestamp to sequence on

    @property
    def n_total(self) -> int:
        # `n_untimed` is a subset of `n_in_repo`, not a fourth disjoint bucket: the path
        # resolved, it just cannot be sequenced. Counting it here would double it.
        return (
            self.n_in_repo
            + self.n_outside
            + self.n_unresolvable
            + self.n_unknown_to_history
        )

    @property
    def n_dropped(self) -> int:
        """Paths lost to a defect rather than to correct scoping."""
        return self.n_unresolvable + self.n_unknown_to_history + self.n_untimed

    def record(self, outcome: PathOutcome) -> None:
        field_name = {
            PathOutcome.IN_REPO: "n_in_repo",
            PathOutcome.OUTSIDE: "n_outside",
            PathOutcome.UNRESOLVABLE: "n_unresolvable",
            PathOutcome.UNKNOWN_TO_HISTORY: "n_unknown_to_history",
        }[outcome]
        setattr(self, field_name, getattr(self, field_name) + 1)


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
    path_coverage: PathCoverage = Field(default_factory=PathCoverage)
    records: list[Corroboration] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Share of commits with supervision evidence. Zero is a normal answer."""
        return self.n_corroborated / self.n_commits if self.n_commits else 0.0


@dataclass(frozen=True)
class SessionEdits:
    """A session reduced to what the join needs: which paths it edited, and *when* each.

    Per-path timestamps, not one session-wide envelope. The envelope was the defect behind
    the old temporal score: a session that ran for six days "edited these files" at every
    moment in that span, so every commit inside it scored a lag of zero.
    """

    session_id: str
    edits: Mapping[str, tuple[datetime, ...]]  # repo-relative path -> sorted edit times

    @property
    def paths(self) -> frozenset[str]:
        return frozenset(self.edits)

    @property
    def first_edit_at(self) -> datetime | None:
        times = [t[0] for t in self.edits.values() if t]
        return min(times) if times else None

    @property
    def last_edit_at(self) -> datetime | None:
        times = [t[-1] for t in self.edits.values() if t]
        return max(times) if times else None

    def last_edit_of(self, path: str, at_or_before: datetime) -> datetime | None:
        """When this session last touched ``path`` without being in the commit's future."""
        times = self.edits.get(path)
        if not times:
            return None
        candidates = [t for t in times if t <= at_or_before]
        return candidates[-1] if candidates else None


def session_edits(
    sessions: list[Session],
    repo_root: Path | RepoIdentity,
) -> tuple[list[SessionEdits], PathCoverage]:
    """Reduce parsed sessions to their in-repo edits, and account for every path dropped.

    Sessions that never touched this repo are dropped rather than scored as evidence of
    nothing. What is *not* acceptable is dropping a path this repo produced and saying
    nothing: that reads downstream as "no supervision evidence", which is the claim a
    reader acts on. So the second return value is the ledger — every edited path lands in
    exactly one bucket, and the counts travel into the report.
    """
    identity = (
        repo_root
        if isinstance(repo_root, RepoIdentity)
        else resolve_identity(repo_root)
    )
    coverage = PathCoverage()
    out: list[SessionEdits] = []

    for session in sessions:
        edits: dict[str, list[datetime]] = {}
        for event in session.events:
            if event.tool not in EDIT_TOOLS:
                continue
            for raw in event.paths:
                outcome, rel = identity.relativize(raw, event.cwd)
                coverage.record(outcome)
                if outcome is not PathOutcome.IN_REPO or not rel:
                    continue
                if event.at is None:
                    # An edit that cannot be placed in time cannot be sequenced against a
                    # commit, and the join is entirely about sequence. Counted, not guessed.
                    coverage.n_untimed += 1
                    continue
                edits.setdefault(rel, []).append(event.at)
        if not edits:
            continue
        out.append(
            SessionEdits(
                session_id=session.session_id,
                edits={p: tuple(sorted(t)) for p, t in sorted(edits.items())},
            )
        )
    return sorted(out, key=lambda s: s.session_id), coverage


def sessions_in_repo(
    sessions: list[Session], repo_root: Path | RepoIdentity
) -> tuple[list[Session], int]:
    """Split sessions into those that touched this repo and a count of those that did not.

    The scoping primitive the L2 metrics are computed over. Membership is decided by what a
    session *edited*, resolved through the repo identity — not by the name of the log
    directory, which is derived from a path and therefore stale the moment a repo moves,
    and not by the recorded cwd alone, which a session sets by opening a shell anywhere.

    Returns ``(in_scope, n_out_of_scope)`` so the excluded population stays visible. A
    profile that quietly narrowed from 60 sessions to 8 should say so.
    """
    identity = (
        repo_root
        if isinstance(repo_root, RepoIdentity)
        else resolve_identity(repo_root)
    )
    in_scope: list[Session] = []
    for session in sessions:
        touched = any(
            identity.relativize(raw, event.cwd)[0] is PathOutcome.IN_REPO
            for event in session.events
            if event.tool in EDIT_TOOLS
            for raw in event.paths
        )
        if touched:
            in_scope.append(session)
    return in_scope, len(sessions) - len(in_scope)


def _significant(commit: CommitRecord) -> set[str]:
    """The commit's hand-written files. Lockfile churn corroborates nothing."""
    return {p for p in commit.files if not is_noise(p)}


def _attribute(
    commit: CommitRecord, edits: list[SessionEdits], config: L3Config
) -> dict[str, tuple[frozenset[str], datetime]]:
    """For each of the commit's paths, the session that last edited it before the commit.

    This is where the temporal signal now lives, and why it discriminates.

    The old model asked each session "did you ever touch these files, and roughly when?"
    Two sessions that both touched a file were both credited, and the tie was broken by a
    session-wide lag that clamped to zero for anything still open — so a long session
    matched everything inside it perfectly, and a stale session that happened to have
    written those files months earlier matched them just as well as the session that had
    just changed them.

    Asking instead "who touched this file *last* before the commit" makes the answer
    exclusive per path, and makes it temporal without a separate temporal term. A session
    whose edits were superseded by later ones holds nothing, however many files it once
    touched. That is the direction of causation the join is trying to capture: an edit is
    evidence for the next commit that carries it, not for every later commit that happens
    to name the same file.

    Clock skew is allowed on the boundary, not on the ordering: a commit may appear a few
    minutes before the edit that produced it because two clocks disagree, but a session
    that touched the file *days* later is in the commit's future and holds nothing.

    A path with two sessions tied for last is held by **both**. Breaking the tie on session
    id would be a coin flip wearing a sort order, and the whole point of the `ambiguous`
    verdict is that the join says so instead.
    """
    horizon = commit.authored_at + timedelta(minutes=config.clock_skew_minutes)
    held: dict[str, tuple[frozenset[str], datetime]] = {}
    for path in _significant(commit):
        latest: datetime | None = None
        holders: set[str] = set()
        for session in edits:
            at = session.last_edit_of(path, horizon)
            if at is None:
                continue
            if latest is None or at > latest:
                latest, holders = at, {session.session_id}
            elif at == latest:
                holders.add(session.session_id)
        if latest is not None:
            held[path] = (frozenset(holders), latest)
    return held


def _score_candidate(
    edits: SessionEdits,
    commit: CommitRecord,
    held: dict[str, tuple[frozenset[str], datetime]],
    config: L3Config,
) -> tuple[float, MatchBasis] | None:
    """Score one (session, commit) pair, or None if it fails the overlap floor.

    The score *is* the path overlap. There is no longer a weighted temporal term: the old
    one contributed 40% of the score while doing no discriminating (see :func:`_attribute`),
    and a term that cannot separate two candidates is not a weak prior, it is a constant.
    Its weight is redistributed into the signal that does the work rather than kept for the
    look of the thing. Lag is still measured and still reported in the basis — a reader
    weighing a match wants it — but it no longer moves the number.
    """
    commit_paths = _significant(commit)
    if not commit_paths:
        return None

    matched = {p for p, (sids, _) in held.items() if edits.session_id in sids}
    if not matched:
        return None
    overlap = len(matched) / len(commit_paths)
    if overlap < config.min_path_overlap:
        return None

    latest = max(held[p][1] for p in matched)
    lag = commit.authored_at - latest
    return round(overlap, 4), MatchBasis(
        session_ref=edits.session_id,
        lag_seconds=int(lag.total_seconds()),
        path_overlap=round(overlap, 4),
        n_matched_paths=len(matched),
        n_commit_paths=len(commit_paths),
    )


def join(
    commits: list[CommitRecord],
    sessions: list[Session],
    repo_root: Path | RepoIdentity,
    config: L3Config | None = None,
) -> CorroborationReport:
    """Correlate sessions with commits. Runs locally; only this report is uploaded.

    Many-to-many is the normal case, not an edge: one session commonly produces several
    commits, and one squashed commit can absorb several sessions. Nothing here assumes a
    session or a commit is claimed only once.
    """
    config = config or L3_CONFIG
    edits, coverage = session_edits(sessions, repo_root)

    records: list[Corroboration] = []
    for commit in sorted(commits, key=lambda c: (c.authored_at, c.sha)):
        held = _attribute(commit, edits, config)
        scored = [
            result
            for e in edits
            if (result := _score_candidate(e, commit, held, config)) is not None
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
        path_coverage=coverage,
        records=records,
    )
