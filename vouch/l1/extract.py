"""L1 extractor — RepoSnapshot -> RepoFacts. Arithmetic only, byte-reproducible.

No LLM, no network, no wall-clock. Given the same repo at the same HEAD under the same
config, this module returns byte-identical output — that is what makes golden-file tests
possible and what lets a report trace a number back to the thresholds behind it.

Three disciplines the v0 prototype lacked, enforced here rather than hoped for:

* **Noise is excluded before anything is counted.** Lockfiles, vendored and generated code
  never reach a denominator, and what was excluded is reported.
* **Denominators have floors.** Below the floor a fact is *suppressed*, not rounded. There
  is no path that turns one fix commit into "100%".
* **Confounds can suppress a fact outright.** If the repo is solo, ``ownership_loop`` does
  not emit a weak number with a caveat — it emits ``not_assessable``, because in a solo repo
  the measurement is meaningless rather than merely thin.

The tightened predicates (see docs/plan.md open question 7) mean these numbers are lower
than the prototype's on the same repo. That is the point: the prototype's
``returned_to_own_code`` was satisfied by a repo merely existing for a fortnight.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from vouch.ingest import blame_ranges, changed_old_lines
from vouch.l1.config import L1_CONFIG, L1Config
from vouch.l1.confounds import (
    F_COMMIT_SCOPING,
    F_FOLLOWUP_LATENCY,
    F_OWNERSHIP_LOOP,
    F_REVERT_RATE,
    F_TEST_ACCOMPANIES_FIX,
    compute_stats,
    detect_confounds,
)
from vouch.l1.facts import (
    BiasDirection,
    Confound,
    ConfoundKey,
    Fact,
    FactStatus,
    Locator,
    RepoFacts,
    Severity,
    Unit,
)
from vouch.l1.identity import Identity, is_bot, resolve_identity
from vouch.l1.paths import PathKind, classify, is_noise, is_test
from vouch.schemas import CommitRecord, RepoSnapshot

__all__ = ["extract_facts", "SelfFix"]


def _fix_re(stems: tuple[str, ...]) -> re.Pattern[str]:
    """Word-start matching, so `prefix`/`suffix`/`dispatch` are not fix commits.

    The prototype used plain substring matching, which classified "refactor prefix
    handling" as a bug fix. Stems match their own inflections (`fix` -> fixes/fixed).
    """
    alts = "|".join(re.escape(s) for s in stems)
    return re.compile(rf"\b(?:{alts})\w*", re.IGNORECASE)


class SelfFix:
    """One observed instance of the subject fixing code the subject wrote.

    ``blamed_at`` is the author date of the most recent subject-authored commit that wrote
    a line this fix changed. Using the *most recent* one makes the derived latency the
    shortest defensible reading of how long the defect lived — we would rather understate
    the gap than inflate it.
    """

    __slots__ = (
        "fix",
        "path",
        "blamed_sha",
        "blamed_at",
        "has_test",
        "test_sha",
        "test_path",
    )

    def __init__(
        self,
        fix: CommitRecord,
        path: str,
        blamed_sha: str,
        blamed_at: datetime,
    ) -> None:
        self.fix = fix
        self.path = path
        self.blamed_sha = blamed_sha
        self.blamed_at = blamed_at
        self.has_test = False
        self.test_sha: str | None = None
        self.test_path: str | None = None

    @property
    def gap_days(self) -> int:
        return (self.fix.authored_at - self.blamed_at).days


def _subject_commits(snapshot: RepoSnapshot, identity: Identity) -> list[CommitRecord]:
    """The subject's non-merge, non-bot commits, oldest first. Deterministic order."""
    rows = [
        c
        for c in snapshot.commits
        if identity.matches(c.author_email) and not is_bot(c.author_name, c.author_email)
    ]
    return sorted(rows, key=lambda c: (c.authored_at, c.sha))


def _significant_sources(commit: CommitRecord) -> list[str]:
    """Hand-written non-test files in a commit, sorted. Blame targets."""
    return sorted(p for p in commit.files if classify(p) is PathKind.SOURCE)


def _find_self_fixes(
    snapshot: RepoSnapshot,
    identity: Identity,
    subject_commits: list[CommitRecord],
    repo_path: Path,
    config: L1Config,
) -> list[SelfFix]:
    """Blame each fix commit's changed lines; keep the ones that land on the subject.

    One ``git blame`` call per (commit, file) — see ``ingest.blame_ranges``. Files per
    commit are capped deterministically so a squashed 400-file commit cannot dominate the
    runtime; the cap is disclosed in the confound report when it bites.
    """
    fix_re = _fix_re(config.fix_keywords)
    by_sha = {c.sha: c for c in snapshot.commits}
    cap = config.detection.max_blamed_files_per_commit
    found: list[SelfFix] = []

    for commit in subject_commits:
        if not fix_re.search(commit.subject):
            continue

        best_sha: str | None = None
        best_at: datetime | None = None
        best_path: str | None = None

        for path in _significant_sources(commit)[:cap]:
            lines = changed_old_lines(repo_path, commit.sha, path)
            if not lines:
                continue  # pure addition — nothing pre-existing to have broken
            for _line, (email, blamed_sha) in sorted(
                blame_ranges(repo_path, commit.sha, path, lines).items()
            ):
                if not identity.matches(email):
                    continue
                blamed = by_sha.get(blamed_sha)
                if blamed is None:
                    continue  # blamed outside the walked history (shallow clone, merge)
                if best_at is None or blamed.authored_at > best_at:
                    best_sha, best_at, best_path = blamed_sha, blamed.authored_at, path

        if best_sha is not None and best_at is not None and best_path is not None:
            found.append(SelfFix(commit, best_path, best_sha, best_at))

    return found


def _attach_tests(
    self_fixes: list[SelfFix], subject_commits: list[CommitRecord], config: L1Config
) -> None:
    """Mark each self-fix that shipped a test, in the fix or a close follow-up commit.

    A test landing in the same commit is the clean case. A test landing in the subject's
    next commit within ``test_adjacency_hours`` counts too — splitting a fix and its
    regression test across two commits is normal practice, not an absence of a test.
    """
    window = timedelta(hours=config.detection.test_adjacency_hours)

    def first_test(commit: CommitRecord) -> str | None:
        return next(iter(sorted(p for p in commit.files if is_test(p))), None)

    for sf in self_fixes:
        own = first_test(sf.fix)
        if own is not None:
            sf.has_test, sf.test_sha, sf.test_path = True, sf.fix.sha, own
            continue
        for later in subject_commits:
            if later.authored_at <= sf.fix.authored_at:
                continue
            if later.authored_at - sf.fix.authored_at > window:
                break
            adjacent = first_test(later)
            if adjacent is not None:
                sf.has_test, sf.test_sha, sf.test_path = True, later.sha, adjacent
                break


def _locators(pairs: list[tuple[str, str | None]]) -> list[Locator]:
    """Build a sorted, deduped locator list. Sorting keeps output byte-reproducible.

    A path-less locator (the commit as a whole) sorts before the same commit's per-file
    locators, hence the empty-string sort key rather than comparing ``None`` to ``str``.
    """
    seen = sorted({(sha, path) for sha, path in pairs}, key=lambda p: (p[0], p[1] or ""))
    return [Locator(sha=sha, path=path) for sha, path in seen]


# --------------------------------------------------------------------------------------
# The facts
# --------------------------------------------------------------------------------------


def _fact_ownership_loop(self_fixes: list[SelfFix], config: L1Config) -> Fact:
    """Of the times the subject returned to fix their own older code, how often with a test.

    "Returned" is load-bearing: the fix must land at least ``return_gap_days`` after the
    code it repairs. Fixing something written the same afternoon is one work session
    finishing, not ownership — the prototype counted it as both.
    """
    returns = [sf for sf in self_fixes if sf.gap_days >= config.detection.return_gap_days]
    with_test = [sf for sf in returns if sf.has_test]
    # The fix locator names the source file that was repaired; the test locator names the
    # test that accompanied it. Both are (sha, path) so L4 can cite either and the
    # grounding validator can check both halves.
    evidence = _locators(
        [(sf.fix.sha, sf.path) for sf in returns]
        + [(sf.test_sha, sf.test_path) for sf in with_test if sf.test_sha]
    )
    return Fact(
        key=F_OWNERSHIP_LOOP,
        status=FactStatus.MEASURED,
        value=round(len(with_test) / len(returns), 4) if returns else None,
        unit=Unit.FRACTION,
        numerator=len(with_test),
        denominator=len(returns),
        evidence=evidence,
    )


def _fact_revert_rate(
    snapshot: RepoSnapshot, subject_commits: list[CommitRecord]
) -> Fact:
    """Share of the subject's commits that were later reverted. Lower is better."""
    subject_shas = {c.sha for c in subject_commits}
    reverted: list[tuple[str, str | None]] = []
    for rev in snapshot.commits:
        target = rev.reverts_sha
        if not target:
            continue
        match = next(
            (s for s in subject_shas if s == target or s.startswith(target)), None
        )
        if match:
            reverted.append((match, None))
    return Fact(
        key=F_REVERT_RATE,
        status=FactStatus.MEASURED,
        value=round(len(reverted) / len(subject_commits), 4) if subject_commits else None,
        unit=Unit.FRACTION,
        numerator=len(reverted),
        denominator=len(subject_commits),
        evidence=_locators(reverted),
    )


def _fact_test_accompanies_fix(
    subject_commits: list[CommitRecord], config: L1Config
) -> Fact:
    """Share of the subject's fix commits that also touch a test file."""
    fix_re = _fix_re(config.fix_keywords)
    fixes = [c for c in subject_commits if fix_re.search(c.subject)]
    with_tests = [c for c in fixes if any(is_test(p) for p in c.files)]
    return Fact(
        key=F_TEST_ACCOMPANIES_FIX,
        status=FactStatus.MEASURED,
        value=round(len(with_tests) / len(fixes), 4) if fixes else None,
        unit=Unit.FRACTION,
        numerator=len(with_tests),
        denominator=len(fixes),
        evidence=_locators([(c.sha, None) for c in with_tests]),
    )


def _fact_followup_latency(self_fixes: list[SelfFix]) -> Fact:
    """Median days between writing a line and returning to fix it.

    Reported as a median, not a mean: one two-year-old defect should not move the number
    that describes typical behaviour.
    """
    gaps = sorted(sf.gap_days for sf in self_fixes)
    return Fact(
        key=F_FOLLOWUP_LATENCY,
        status=FactStatus.MEASURED,
        value=round(statistics.median(gaps), 2) if gaps else None,
        unit=Unit.DAYS,
        numerator=None,
        denominator=len(gaps),
        evidence=_locators([(sf.fix.sha, sf.path) for sf in self_fixes]),
    )


def _fact_commit_scoping(subject_commits: list[CommitRecord]) -> Fact:
    """Median significant files per commit, after noise is excluded.

    A commit that touches one source file and a 4000-line lockfile is a one-file commit.
    """
    counts = sorted(
        len([p for p in c.files if not is_noise(p)])
        for c in subject_commits
        if any(not is_noise(p) for p in c.files)
    )
    return Fact(
        key=F_COMMIT_SCOPING,
        status=FactStatus.MEASURED,
        value=round(statistics.median(counts), 2) if counts else None,
        unit=Unit.FILES,
        numerator=None,
        denominator=len(counts),
        evidence=[],
    )


# --------------------------------------------------------------------------------------
# Suppression
# --------------------------------------------------------------------------------------

_FLOORS = {
    F_OWNERSHIP_LOOP: "fix_commits",
    F_TEST_ACCOMPANIES_FIX: "fix_commits",
    F_REVERT_RATE: "subject_commits",
    F_COMMIT_SCOPING: "subject_commits",
    F_FOLLOWUP_LATENCY: "latency_pairs",
}


def _apply_suppression(
    facts: list[Fact], confounds: list[Confound], config: L1Config
) -> list[Fact]:
    """Downgrade facts that a confound invalidates or that lack the denominator to stand.

    Invalidation wins over low-n: "this measurement is meaningless here" is a stronger and
    more useful statement to a reader than "we needed more of it".
    """
    invalidated: dict[str, Confound] = {}
    for c in confounds:
        if c.severity is Severity.INVALIDATING:
            for key in c.affects:
                invalidated.setdefault(key, c)

    out: list[Fact] = []
    for f in facts:
        blocker = invalidated.get(f.key)
        if blocker is not None:
            # Drop the ratio as well as the value. For a low-n suppression the denominator
            # *is* the honesty ("only 2 observations"); here the ratio itself is
            # meaningless, and leaving 2/3 on the page invites the reader to do the
            # division we just declined to do. Evidence stays: those commits were still
            # inspected, and L4 may still want to look at them.
            out.append(
                f.model_copy(
                    update={
                        "status": FactStatus.NOT_ASSESSABLE,
                        "value": None,
                        "numerator": None,
                        "denominator": None,
                        "note": f"not assessable here — {blocker.detail}",
                    }
                )
            )
            continue

        floor = getattr(config.min_n, _FLOORS[f.key])
        if (f.denominator or 0) < floor:
            out.append(
                f.model_copy(
                    update={
                        "status": FactStatus.SUPPRESSED_LOW_N,
                        "value": None,
                        "note": (
                            f"suppressed: {f.denominator or 0} observation(s), below the "
                            f"floor of {floor}. A rate this thin is not reported."
                        ),
                    }
                )
            )
            continue

        out.append(f)
    return out


def _low_denominator_confound(facts: list[Fact]) -> Confound | None:
    """A repo-level flag when the history was too thin to support several facts."""
    thin = sorted(f.key for f in facts if f.status is FactStatus.SUPPRESSED_LOW_N)
    if not thin:
        return None
    return Confound(
        key=ConfoundKey.LOW_DENOMINATOR,
        severity=Severity.WARN,
        direction=BiasDirection.UNKNOWN,
        detail=(
            f"{len(thin)} of {len(facts)} facts were suppressed for want of a large enough "
            f"denominator ({', '.join(thin)}). This history is too thin to support them."
        ),
        affects=thin,
    )


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def extract_facts(
    snapshot: RepoSnapshot,
    subject_email: str,
    repo_path: Path,
    aliases: list[str] | None = None,
    config: L1Config | None = None,
) -> RepoFacts:
    """Compute every L1 fact and confound for ``subject_email``.

    ``repo_path`` is required — blame is not optional here. The prototype degraded to a
    silent zero when it was missing, which is indistinguishable in the output from "this
    person never fixed their own bugs".
    """
    config = config or L1_CONFIG

    authors = [(c.author_name, c.author_email) for c in snapshot.commits]
    identity, unclaimed = resolve_identity(authors, subject_email, aliases)

    subject_commits = _subject_commits(snapshot, identity)
    stats = compute_stats(snapshot, identity, config)
    confounds = detect_confounds(stats, unclaimed, config)

    self_fixes = _find_self_fixes(snapshot, identity, subject_commits, repo_path, config)
    _attach_tests(self_fixes, subject_commits, config)

    facts = [
        _fact_ownership_loop(self_fixes, config),
        _fact_revert_rate(snapshot, subject_commits),
        _fact_test_accompanies_fix(subject_commits, config),
        _fact_followup_latency(self_fixes),
        _fact_commit_scoping(subject_commits),
    ]
    facts = _apply_suppression(facts, confounds, config)

    thin = _low_denominator_confound(facts)
    if thin is not None:
        confounds = sorted([*confounds, thin], key=lambda c: c.key.value)

    excluded = Counter(
        classify(p).value
        for c in subject_commits
        for p in c.files
        if is_noise(p) or classify(p) is PathKind.DOCS
    )

    return RepoFacts(
        repo=snapshot.repo,
        head_sha=snapshot.head_sha,
        subject=identity,
        window_first=subject_commits[0].authored_at.date() if subject_commits else None,
        window_last=subject_commits[-1].authored_at.date() if subject_commits else None,
        n_commits_by_subject=len(subject_commits),
        n_commits_total=stats.n_total,
        facts=facts,
        confounds=confounds,
        excluded_paths=dict(sorted(excluded.items())),
    )
