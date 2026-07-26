"""extract — RepoSnapshot -> EvidenceBundle. Deterministic ownership signals.

The honest, falsifiable heart of the tool. Each signal is a pure function of the snapshot
(plus on-demand blame) and carries the SHAs that back it. No hallucinated praise is
possible downstream because the judge only ever sees these facts.

v0 signals (review_followthrough dropped — not pure-git derivable):
    returned_to_own_code, fixed_own_bug, tests_accompany_fixes,
    revert_recovery, commit_atomicity
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from vouch.config import CONFIG, Config
from vouch.ingest import blame_line_author, changed_old_lines, is_test_path
from vouch.schemas import CommitMeta, CommitRecord, EvidenceBundle, RepoSnapshot, Signal


def _now() -> datetime:
    return datetime.now()


def _subject_commits(snapshot: RepoSnapshot, subject: str) -> list[CommitRecord]:
    """The subject's non-merge commits, oldest-first."""
    return sorted(
        (c for c in snapshot.commits if c.author_email == subject),
        key=lambda c: c.authored_at,
    )


def _is_fix(commit: CommitRecord, config: Config) -> bool:
    subj = commit.subject.lower()
    return any(k in subj for k in config.thresholds.fix_keywords)


def _source_files(files: list[str]) -> list[str]:
    return [f for f in files if not is_test_path(f)]


# --- individual signal extractors (each returns a Signal backed by SHAs) --------------


def signal_returned_to_own_code(snapshot: RepoSnapshot, subject: str, config: Config) -> Signal:
    """Author touched the same file again after a gap >= ``return_gap_days`` (sustained).

    Value = number of files the subject came back to after the gap. Evidence = the first
    and last SHA for each such file (the receipts for "sustained, not drive-by").
    """
    gap_days = config.thresholds.return_gap_days
    commits = _subject_commits(snapshot, subject)
    file_hist: dict[str, list[CommitRecord]] = {}
    for c in commits:
        for f in c.files:
            file_hist.setdefault(f, []).append(c)

    returned_files = 0
    evidence: list[str] = []
    for _file, hist in file_hist.items():
        if len(hist) < 2:
            continue
        span_days = (hist[-1].authored_at - hist[0].authored_at).days
        if span_days >= gap_days:
            returned_files += 1
            evidence.extend([hist[0].sha, hist[-1].sha])
    return Signal(
        key="returned_to_own_code",
        value=returned_files,
        evidence=sorted(set(evidence)),
        computed_at=_now(),
    )


def signal_fixed_own_bug(
    snapshot: RepoSnapshot, subject: str, repo_path: Path, config: Config
) -> Signal:
    """Fix-commit (keyword proxy) whose changed lines blame back to the same author.

    For each fix-commit by the subject, blame the modified source lines against the
    parent; if any line was authored by the subject, this is a self-fix. Value = count of
    such commits. Evidence = those fix SHAs.
    """
    hits: list[str] = []
    for c in _subject_commits(snapshot, subject):
        if not _is_fix(c, config):
            continue
        self_fix = False
        for f in _source_files(c.files):
            for ln in changed_old_lines(repo_path, c.sha, f):
                blamed = blame_line_author(repo_path, c.sha, f, ln)
                if blamed and blamed[0] == subject:
                    self_fix = True
                    break
            if self_fix:
                break
        if self_fix:
            hits.append(c.sha)
    return Signal(key="fixed_own_bug", value=len(hits), evidence=hits, computed_at=_now())


def signal_tests_accompany_fixes(snapshot: RepoSnapshot, subject: str, config: Config) -> Signal:
    """Fraction of the subject's fix-commits that also add/modify test files.

    Value = fraction in [0,1] (0.0 if there are no fix-commits). Evidence = the fix
    commits that DID include tests (the positive receipts).
    """
    fixes = [c for c in _subject_commits(snapshot, subject) if _is_fix(c, config)]
    with_tests = [c.sha for c in fixes if c.test_files]
    frac = (len(with_tests) / len(fixes)) if fixes else 0.0
    return Signal(
        key="tests_accompany_fixes",
        value=round(frac, 4),
        evidence=with_tests,
        computed_at=_now(),
    )


def signal_revert_recovery(snapshot: RepoSnapshot, subject: str, config: Config) -> Signal:
    """Subject's code reverted, then the same author re-touches those files afterward.

    Honest proxy for "reverted, then re-landed correctly": find reverts of the subject's
    own commits, then check for a later subject commit touching an overlapping file.
    Value = count of such recoveries. Evidence = [revert_sha, recovery_sha] per case.
    """
    by_sha = {c.sha: c for c in snapshot.commits}
    subject_commits = _subject_commits(snapshot, subject)
    recoveries = 0
    evidence: list[str] = []
    for rev in snapshot.commits:
        if not rev.reverts_sha:
            continue
        original = by_sha.get(rev.reverts_sha)
        # match by prefix too, since bodies may carry short SHAs
        if original is None:
            original = next(
                (c for c in snapshot.commits if c.sha.startswith(rev.reverts_sha)), None
            )
        if original is None or original.author_email != subject:
            continue
        reverted_files = set(original.files)
        recovery = next(
            (
                c
                for c in subject_commits
                if c.authored_at > rev.authored_at and set(c.files) & reverted_files
            ),
            None,
        )
        if recovery is not None:
            recoveries += 1
            evidence.extend([rev.sha, recovery.sha])
    return Signal(
        key="revert_recovery",
        value=recoveries,
        evidence=sorted(set(evidence)),
        computed_at=_now(),
    )


def signal_commit_atomicity(snapshot: RepoSnapshot, subject: str, config: Config) -> Signal:
    """Weak proxy: fraction of the subject's commits touching <= ``atomic_max_files``.

    Value = fraction in [0,1]. Evidence = up to a sample of the focused commit SHAs (the
    bundle stays small; the fraction is the claim, the SHAs are illustrative receipts).
    """
    commits = _subject_commits(snapshot, subject)
    max_files = config.thresholds.atomic_max_files
    focused = [c.sha for c in commits if 0 < len(c.files) <= max_files]
    frac = (len(focused) / len(commits)) if commits else 0.0
    return Signal(
        key="commit_atomicity",
        value=round(frac, 4),
        evidence=focused[:20],
        computed_at=_now(),
    )


def extract(
    snapshot: RepoSnapshot,
    subject_email: str,
    repo_path: Path | None = None,
    config: Config | None = None,
) -> EvidenceBundle:
    """Compute all ownership signals for ``subject_email`` and assemble the bundle.

    Populates ``commit_index`` with a ``CommitMeta`` for every SHA any signal cites, so
    the judge has SHA anchors without ever seeing a diff. ``repo_path`` is required for
    ``fixed_own_bug`` (needs blame); if omitted, that signal is computed as 0.
    """
    config = config or CONFIG
    signals: list[Signal] = [
        signal_returned_to_own_code(snapshot, subject_email, config),
        (
            signal_fixed_own_bug(snapshot, subject_email, repo_path, config)
            if repo_path is not None
            else Signal(key="fixed_own_bug", value=0, evidence=[], computed_at=_now())
        ),
        signal_tests_accompany_fixes(snapshot, subject_email, config),
        signal_revert_recovery(snapshot, subject_email, config),
        signal_commit_atomicity(snapshot, subject_email, config),
    ]

    subject_commits = _subject_commits(snapshot, subject_email)
    window_first = subject_commits[0].authored_at.date() if subject_commits else None
    window_last = subject_commits[-1].authored_at.date() if subject_commits else None

    # Build a CommitMeta index for every SHA any signal references — and nothing else.
    by_sha = {c.sha: c for c in snapshot.commits}
    cited = {sha for s in signals for sha in s.evidence}
    commit_index: dict[str, CommitMeta] = {}
    for sha in cited:
        c = by_sha.get(sha)
        if c is None:
            continue
        commit_index[sha] = CommitMeta(
            sha=c.sha,
            short=c.sha[:8],
            authored_at=c.authored_at,
            subject=c.subject,
            n_files=len(c.files),
            touched_tests=bool(c.test_files),
        )

    return EvidenceBundle(
        repo=snapshot.repo,
        subject=subject_email,
        dimension="ownership",
        window_first=window_first,
        window_last=window_last,
        n_commits_by_subject=len(subject_commits),
        signals=signals,
        commit_index=commit_index,
    )
