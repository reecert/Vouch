"""Confound detection — what would make L1's numbers wrong.

The v0 prototype computed ownership signals and reported them straight. It had no way to
notice that a repo was squash-merged (authorship collapses to whoever hit the button), or
solo (ownership is trivially 100% because nobody else wrote anything), or half lockfile
churn. Those histories produce confident, wrong numbers.

Every detector here answers three questions, because a flag that only names the problem is
useless to a reader:

* **How much?** — ``detail`` carries the counts, not adjectives.
* **Which facts?** — ``affects`` names them.
* **Which way is the number wrong?** — ``direction``.

Severity decides what the extractor does: ``INVALIDATING`` suppresses the affected facts
outright, ``WARN`` lets them through with the caveat attached, ``INFO`` is context.

Pure functions over an already-parsed snapshot. No I/O, no LLM, no wall-clock.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from vouch.l1.config import L1Config
from vouch.l1.facts import BiasDirection, Confound, ConfoundKey, Severity
from vouch.l1.identity import Identity, is_bot
from vouch.l1.paths import is_noise
from vouch.schemas import CommitRecord, RepoSnapshot

__all__ = ["RepoStats", "compute_stats", "detect_confounds", "mask_email"]

# GitHub's squash-merge convention appends the PR number to the subject line.
_SQUASH_MARKER_RE = re.compile(r"\(#\d+\)\s*$")

# Fact keys, kept here so a confound can name what it bears on without importing the
# extractor (which imports this module).
F_OWNERSHIP_LOOP = "ownership_loop"
F_REVERT_RATE = "revert_rate"
F_TEST_ACCOMPANIES_FIX = "test_accompanies_fix"
F_FOLLOWUP_LATENCY = "followup_latency"
F_COMMIT_SCOPING = "commit_scoping"

ALL_FACTS = [
    F_OWNERSHIP_LOOP,
    F_REVERT_RATE,
    F_TEST_ACCOMPANIES_FIX,
    F_FOLLOWUP_LATENCY,
    F_COMMIT_SCOPING,
]


def mask_email(email: str) -> str:
    """``jane.doe@corp.com`` -> ``j******@corp.com``.

    Heuristic identity near-matches name *other people's* addresses as often as the
    subject's own. A profile is a shareable document about a person; it should not be a
    vector for publishing a third party's contact details, even ones already in the git
    log.
    """
    local, sep, domain = email.partition("@")
    if not sep or not local:
        return "***"
    return f"{local[0]}{'*' * max(len(local) - 1, 1)}@{domain}"


@dataclass(frozen=True)
class RepoStats:
    """Counts every detector reads from. Computed once, deterministically."""

    n_total: int
    n_human: int
    n_bot: int
    n_subject: int
    distinct_human_authors: int
    n_squash_marked: int
    n_merges: int
    is_shallow: bool
    n_noise_touches: int
    n_touches: int
    n_rebase_skewed: int
    window_days: int | None


def compute_stats(
    snapshot: RepoSnapshot, identity: Identity, config: L1Config
) -> RepoStats:
    """Derive the repo-level counts the detectors need."""
    d = config.detection
    humans: list[CommitRecord] = []
    n_bot = 0
    for c in snapshot.commits:
        if is_bot(c.author_name, c.author_email):
            n_bot += 1
        else:
            humans.append(c)

    subject = [c for c in humans if identity.matches(c.author_email)]

    # Noise share is measured over *human* commits only. A dependency bot's lockfile churn
    # is already accounted for by bot_dominated; counting it here too would report the same
    # problem twice and mask whether the human work itself is noise-heavy.
    n_touches = 0
    n_noise = 0
    for c in humans:
        for path in c.files:
            n_touches += 1
            if is_noise(path):
                n_noise += 1

    n_skewed = 0
    for c in snapshot.commits:
        if c.committed_at is None:
            continue
        if (c.committed_at - c.authored_at).days > d.rebase_skew_days:
            n_skewed += 1

    window_days: int | None = None
    if subject:
        first = min(c.authored_at for c in subject)
        last = max(c.authored_at for c in subject)
        window_days = (last - first).days

    return RepoStats(
        n_total=len(snapshot.commits),
        n_human=len(humans),
        n_bot=n_bot,
        n_subject=len(subject),
        distinct_human_authors=len({c.author_email.lower() for c in humans}),
        n_squash_marked=sum(1 for c in humans if _SQUASH_MARKER_RE.search(c.subject)),
        n_merges=snapshot.n_merge_commits,
        is_shallow=snapshot.is_shallow,
        n_noise_touches=n_noise,
        n_touches=n_touches,
        n_rebase_skewed=n_skewed,
        window_days=window_days,
    )


def _pct(num: int, den: int) -> float:
    return (num / den) if den else 0.0


def detect_confounds(
    stats: RepoStats,
    unclaimed_aliases: list[str],
    config: L1Config,
) -> list[Confound]:
    """Run every detector. Returns confounds sorted by key, so output is reproducible."""
    d = config.detection
    found: list[Confound] = []

    # --- solo repo -------------------------------------------------------------------
    # Ownership means "returns to fix *their own* bugs rather than leaving them". With no
    # other human authors the predicate is vacuously true: there is nobody else's code to
    # not fix. The measurement is not weak here, it is meaningless — hence INVALIDATING.
    share = _pct(stats.n_subject, stats.n_human)
    if stats.distinct_human_authors <= 1 or share >= d.solo_authorship_share:
        found.append(
            Confound(
                key=ConfoundKey.SOLO_REPO,
                severity=Severity.INVALIDATING,
                direction=BiasDirection.OVERSTATES,
                detail=(
                    f"subject authored {stats.n_subject}/{stats.n_human} human commits "
                    f"({share:.0%}); {stats.distinct_human_authors} distinct human author(s). "
                    "With no other authors, fixing one's own bugs is the only option "
                    "available, so the loop carries no ownership signal."
                ),
                affects=[F_OWNERSHIP_LOOP],
            )
        )

    # --- squash-merge history --------------------------------------------------------
    # Squashing collapses a PR's commits into one, authored by whoever merged. The
    # intermediate fix-with-test commits that ownership_loop looks for stop existing.
    #
    # Detection rests solely on GitHub's " (#123)" subject convention. An earlier version
    # also treated "zero merge commits across a long history" as evidence, but that cannot
    # tell a squash-merged repo from a small project with a linear history and no PRs — it
    # fired on a plain fixture. We would rather miss a squash-merged repo whose team writes
    # its own subject lines than tell a reader to discount numbers that are fine.
    squash_share = _pct(stats.n_squash_marked, stats.n_human)
    if squash_share >= d.squash_marker_share:
        found.append(
            Confound(
                key=ConfoundKey.SQUASH_MERGE_HISTORY,
                severity=Severity.WARN,
                direction=BiasDirection.UNDERSTATES,
                detail=(
                    f"{stats.n_squash_marked} of {stats.n_human} human-authored commits "
                    f"(bots excluded) carry a squash marker in their subject line "
                    f"({squash_share:.0%}). Squash-merging collapses each "
                    "branch into a single commit attributed to the merger, so individual "
                    "fix-and-test commits are not visible and commits look larger than the "
                    "work behind them."
                ),
                affects=[F_OWNERSHIP_LOOP, F_FOLLOWUP_LATENCY, F_COMMIT_SCOPING],
            )
        )

    # --- bot noise -------------------------------------------------------------------
    # Reported for its interaction with solo-repo: a repo that looks collaborative may be
    # one human plus dependabot. Bot commits are already excluded from every fact.
    bot_share = _pct(stats.n_bot, stats.n_total)
    if bot_share >= d.bot_share:
        found.append(
            Confound(
                key=ConfoundKey.BOT_DOMINATED,
                severity=Severity.INFO,
                direction=BiasDirection.UNKNOWN,
                detail=(
                    f"{stats.n_bot}/{stats.n_total} commits ({bot_share:.0%}) are machine "
                    "authored and are excluded from every fact below. Reported because a "
                    "repo can look collaborative while having one human contributor."
                ),
                affects=[],
            )
        )

    # --- vendored / generated / lockfile bulk ----------------------------------------
    noise_share = _pct(stats.n_noise_touches, stats.n_touches)
    if noise_share >= d.noise_touch_share:
        found.append(
            Confound(
                key=ConfoundKey.VENDORED_OR_GENERATED_BULK,
                severity=Severity.WARN,
                direction=BiasDirection.UNKNOWN,
                detail=(
                    f"{stats.n_noise_touches}/{stats.n_touches} file touches "
                    f"({noise_share:.0%}) are lockfiles, vendored or generated code. They "
                    "are excluded from every fact, which shrinks the denominators the "
                    "remaining numbers rest on."
                ),
                affects=[F_COMMIT_SCOPING],
            )
        )

    # --- rebase-rewritten authorship -------------------------------------------------
    skew_share = _pct(stats.n_rebase_skewed, stats.n_total)
    if skew_share >= d.rebase_skew_share:
        found.append(
            Confound(
                key=ConfoundKey.REBASE_REWRITTEN_AUTHORSHIP,
                severity=Severity.WARN,
                direction=BiasDirection.UNKNOWN,
                detail=(
                    f"{stats.n_rebase_skewed}/{stats.n_total} commits ({skew_share:.0%}) "
                    f"were committed more than {d.rebase_skew_days} day(s) after they were "
                    "authored, so this history was rebased or replayed. Author dates "
                    "survive a rebase but the ordering they imply may not."
                ),
                affects=[F_FOLLOWUP_LATENCY],
            )
        )

    # --- shallow clone ---------------------------------------------------------------
    if stats.is_shallow:
        found.append(
            Confound(
                key=ConfoundKey.SHALLOW_HISTORY,
                severity=Severity.WARN,
                direction=BiasDirection.UNDERSTATES,
                detail=(
                    "this is a shallow clone: history is truncated, so every count is a "
                    "floor rather than a total and blame may attribute code to the "
                    "earliest retained commit."
                ),
                affects=list(ALL_FACTS),
            )
        )

    # --- unresolved identity aliases -------------------------------------------------
    # Deliberately not auto-merged: merging on a name match would silently change the
    # numbers on a guess. Surfaced so a human decides.
    if unclaimed_aliases:
        masked = ", ".join(mask_email(a) for a in unclaimed_aliases)
        found.append(
            Confound(
                key=ConfoundKey.UNRESOLVED_IDENTITY_ALIASES,
                severity=Severity.WARN,
                direction=BiasDirection.UNDERSTATES,
                detail=(
                    f"{len(unclaimed_aliases)} other address(es) in this history resemble "
                    f"the subject ({masked}) but were not claimed, so any work committed "
                    "under them is not counted. Pass them as aliases to include it."
                ),
                affects=list(ALL_FACTS),
            )
        )

    # --- short activity window -------------------------------------------------------
    if stats.window_days is not None and stats.window_days < d.short_window_days:
        found.append(
            Confound(
                key=ConfoundKey.SHORT_WINDOW,
                severity=Severity.WARN,
                direction=BiasDirection.UNDERSTATES,
                detail=(
                    f"the subject's activity spans {stats.window_days} day(s), under the "
                    f"{d.short_window_days}-day floor. Returning to fix one's own work is "
                    "a behaviour that needs elapsed time to be observable at all."
                ),
                affects=[F_OWNERSHIP_LOOP, F_FOLLOWUP_LATENCY],
            )
        )

    return sorted(found, key=lambda c: c.key.value)
