"""L1 facts — the measurements, their floors, and the predicates behind them."""
from __future__ import annotations

from dataclasses import replace

import pytest

from vouch.l1.config import L1_CONFIG, MinN
from vouch.l1.extract import _fix_re
from vouch.l1.facts import FactStatus, Unit


def test_ownership_loop_counts_returns_with_tests(l1) -> None:
    """Three returns to own code past the gap; two shipped a test."""
    loop = l1("healthy").fact("ownership_loop")

    assert loop.status is FactStatus.MEASURED
    assert loop.numerator == 2
    assert loop.denominator == 3
    assert loop.value == pytest.approx(0.6667, abs=1e-4)
    assert loop.unit is Unit.FRACTION


def test_ownership_loop_evidence_carries_paths(l1) -> None:
    """Locators are (sha, path) so L4's grounding check can verify both halves.

    Each return names the source file that was repaired; each accompanying test names the
    test file. A path-less locator would let L4 attribute "the fix in auth.py" to a commit
    that never touched auth.py.
    """
    loop = l1("healthy").fact("ownership_loop")

    assert {loc.path for loc in loop.evidence} == {
        "src/auth.py",
        "src/search.py",
        "src/cache.py",  # the return that shipped no test
        "tests/test_auth.py",
        "tests/test_search.py",
    }
    assert all(len(loc.sha) == 40 for loc in loop.evidence)


def test_same_day_fix_is_not_a_return(l1) -> None:
    """The tightened predicate: fixing what you wrote this morning is one work session.

    The v0 prototype counted it as ownership. Compressing the same history into a few days
    leaves nothing above the 14-day gap.
    """
    assert l1("short_window").fact("ownership_loop").denominator == 0


def test_followup_latency_is_a_median_in_days(l1) -> None:
    latency = l1("healthy").fact("followup_latency")

    assert latency.unit is Unit.DAYS
    assert latency.value == pytest.approx(23.0)  # gaps of 20, 23, 27
    assert latency.denominator == 3


def test_commit_scoping_ignores_noise(l1) -> None:
    """A commit touching one source file and a 4000-line lockfile is a one-file commit."""
    scoping = l1("noisy").fact("commit_scoping")

    assert scoping.unit is Unit.FILES
    assert scoping.value == pytest.approx(1.0)
    # The eight pure-noise commits contribute nothing to the denominator.
    assert scoping.denominator == 11


def test_revert_rate_measured_over_subject_commits(l1) -> None:
    rate = l1("healthy").fact("revert_rate")

    assert rate.status is FactStatus.MEASURED
    assert rate.numerator == 0
    assert rate.denominator == 12


def test_low_denominators_are_suppressed_not_rounded(l1) -> None:
    """The n=1 "100%" failure. Raising the floor above the fixture must suppress, not round."""
    strict = replace(L1_CONFIG, min_n=MinN(fix_commits=99, subject_commits=99, latency_pairs=99))
    facts = l1("healthy", config=strict)

    assert all(f.status is FactStatus.SUPPRESSED_LOW_N for f in facts.facts)
    assert all(f.value is None for f in facts.facts)
    # The denominator survives suppression: "3 observations, below a floor of 99" is the
    # honest statement, and the reader needs the 3 to see why.
    assert facts.fact("ownership_loop").denominator == 3
    assert "below the floor of 99" in facts.fact("ownership_loop").note


def test_every_fact_is_accounted_for(l1) -> None:
    facts = l1("healthy")
    assert [f.key for f in facts.facts] == [
        "ownership_loop",
        "revert_rate",
        "test_accompanies_fix",
        "followup_latency",
        "commit_scoping",
    ]


def test_window_and_counts(l1) -> None:
    facts = l1("healthy")
    assert facts.n_commits_by_subject == 12
    assert facts.n_commits_total == 14
    assert facts.window_first.isoformat() == "2024-01-01"
    assert facts.window_last.isoformat() == "2024-02-20"


def test_excluded_paths_are_reported(l1) -> None:
    """What we dropped is stated, never silently dropped."""
    assert l1("healthy").excluded_paths == {"docs": 1, "lockfile": 1}


def test_no_wallclock_in_the_payload(l1) -> None:
    """Byte-reproducibility depends on there being no `datetime.now()` anywhere inside."""
    blob = l1("healthy").model_dump_json()
    assert "computed_at" not in blob
    assert "generated_at" not in blob


def test_unknown_subject_yields_empty_not_zero(l1) -> None:
    """Nobody by that name: every fact declines to have a value rather than reading 0.0."""
    facts = l1("healthy", subject="nobody@example.com")

    assert facts.n_commits_by_subject == 0
    assert all(f.status is not FactStatus.MEASURED for f in facts.facts)


class TestFixKeywordMatching:
    """The prototype's substring match read "refactor prefix handling" as a bug fix."""

    @pytest.mark.parametrize(
        "subject",
        [
            "fix: handle expired token",
            "Fixes the crash on startup",
            "fixed a regression in search",
            "patch the broken migration",
            "resolving the cache bug",
            "repair corrupt index",
        ],
    )
    def test_matches_real_fixes(self, subject: str) -> None:
        assert _fix_re(L1_CONFIG.fix_keywords).search(subject)

    @pytest.mark.parametrize(
        "subject",
        [
            "refactor prefix handling",
            "add suffix support to parser",
            "dispatch events asynchronously",
            "feat: add affix rules",
            "docs: describe the auth flow",
        ],
    )
    def test_rejects_lookalikes(self, subject: str) -> None:
        assert not _fix_re(L1_CONFIG.fix_keywords).search(subject)
