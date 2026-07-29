"""Confound detection — each fixture deforms the baseline along exactly one axis.

The discriminating assertion in every case is the *negative* one: the healthy baseline
must not trip the detector. A confound report that fires on a clean history is worse than
no confound report, because it teaches the reader to ignore it.
"""
from __future__ import annotations

from vouch.l1.facts import BiasDirection, ConfoundKey, FactStatus, Severity


def keys(facts) -> set[ConfoundKey]:
    return {c.key for c in facts.confounds}


def test_healthy_history_trips_nothing(l1) -> None:
    facts = l1("healthy")
    assert keys(facts) == set()
    assert all(f.status is FactStatus.MEASURED for f in facts.facts)


def test_solo_repo_invalidates_ownership(l1) -> None:
    """One human author: fixing your own bugs is the only option, so the loop says nothing."""
    facts = l1("solo")
    c = facts.confound(ConfoundKey.SOLO_REPO)

    assert c is not None
    assert c.severity is Severity.INVALIDATING
    assert c.direction is BiasDirection.OVERSTATES
    assert c.affects == ["ownership_loop"]
    assert "12/12" in c.detail  # the numbers, not just the label

    loop = facts.fact("ownership_loop")
    assert loop.status is FactStatus.NOT_ASSESSABLE
    assert loop.value is None
    # The ratio goes too: leaving 2/3 on the page invites the division we declined.
    assert loop.numerator is None and loop.denominator is None
    # Facts the confound does not bear on are untouched.
    assert facts.fact("revert_rate").status is FactStatus.MEASURED


def test_squash_merge_history_detected(l1) -> None:
    facts = l1("squash_merged")
    c = facts.confound(ConfoundKey.SQUASH_MERGE_HISTORY)

    assert c is not None
    assert c.severity is Severity.WARN
    assert c.direction is BiasDirection.UNDERSTATES
    assert set(c.affects) == {"ownership_loop", "followup_latency", "commit_scoping"}
    # WARN annotates; it does not suppress.
    assert facts.fact("ownership_loop").status is FactStatus.MEASURED


def test_linear_history_is_not_mistaken_for_squash_merging(l1) -> None:
    """A small project with no merge commits is not evidence of squash-merging.

    An earlier detector treated "zero merges across a long history" as a trigger and fired
    on a plain linear fixture. We under-detect rather than tell a reader to discount
    numbers that are fine.
    """
    assert ConfoundKey.SQUASH_MERGE_HISTORY not in keys(l1("noisy"))


def test_bot_dominated_is_reported_as_context(l1) -> None:
    """A repo can look collaborative while having one human contributor."""
    facts = l1("bot_heavy")
    c = facts.confound(ConfoundKey.BOT_DOMINATED)

    assert c is not None
    assert c.severity is Severity.INFO  # bots are already excluded from every fact
    assert c.affects == []
    assert "6/20" in c.detail


def test_bot_churn_does_not_double_count_as_noise(l1) -> None:
    """The bot's lockfile churn is the bot problem, already reported. Report it once."""
    assert ConfoundKey.VENDORED_OR_GENERATED_BULK not in keys(l1("bot_heavy"))


def test_vendored_and_generated_bulk_detected(l1) -> None:
    facts = l1("noisy")
    c = facts.confound(ConfoundKey.VENDORED_OR_GENERATED_BULK)

    assert c is not None
    assert c.affects == ["commit_scoping"]
    # What was excluded is reported rather than silently dropped.
    assert facts.excluded_paths["lockfile"] > 0
    assert facts.excluded_paths["vendored"] > 0
    assert facts.excluded_paths["generated"] > 0


def test_rebase_rewritten_authorship_detected(l1) -> None:
    """Committer dates far ahead of author dates mean the history was replayed."""
    facts = l1("rebased")
    c = facts.confound(ConfoundKey.REBASE_REWRITTEN_AUTHORSHIP)

    assert c is not None
    assert c.affects == ["followup_latency"]
    assert ConfoundKey.REBASE_REWRITTEN_AUTHORSHIP not in keys(l1("healthy"))


def test_unresolved_aliases_flagged_and_masked(l1) -> None:
    facts = l1("aliased")
    c = facts.confound(ConfoundKey.UNRESOLVED_IDENTITY_ALIASES)

    assert c is not None
    assert c.direction is BiasDirection.UNDERSTATES
    assert "a****@personal.dev" in c.detail
    assert "alice@personal.dev" not in c.detail  # masked, not published


def test_claiming_the_alias_clears_the_confound(l1) -> None:
    """The flag is actionable: pass the address and the work is counted."""
    without = l1("aliased")
    with_alias = l1("aliased", aliases=["alice@personal.dev"])

    assert ConfoundKey.UNRESOLVED_IDENTITY_ALIASES in keys(without)
    assert ConfoundKey.UNRESOLVED_IDENTITY_ALIASES not in keys(with_alias)
    assert with_alias.n_commits_by_subject == without.n_commits_by_subject + 1


def test_short_window_flagged_and_loop_suppressed(l1) -> None:
    """Returning to fix your own work needs elapsed time to be observable at all."""
    facts = l1("short_window")
    c = facts.confound(ConfoundKey.SHORT_WINDOW)

    assert c is not None
    assert set(c.affects) == {"ownership_loop", "followup_latency"}

    # No fix cleared the 14-day return gap, so there is nothing to divide by.
    loop = facts.fact("ownership_loop")
    assert loop.status is FactStatus.SUPPRESSED_LOW_N
    assert loop.denominator == 0

    # ...and that suppression is itself surfaced at the repo level.
    low_n = facts.confound(ConfoundKey.LOW_DENOMINATOR)
    assert low_n is not None
    assert low_n.affects == ["ownership_loop"]


def test_confounds_are_sorted(l1) -> None:
    """Deterministic ordering — the output is a golden-file input."""
    facts = l1("short_window")
    assert [c.key.value for c in facts.confounds] == sorted(
        c.key.value for c in facts.confounds
    )
