"""Intervals, asymmetric evidence requirements, and evidence-led report ordering.

The failure this exists to prevent, in one line: **`test_accompanies_fix: 0.0`, computed
from five commits, printed at the top of a profile about an early-career engineer.**

Every guard the pipeline had fired correctly and the number still got out. `MinN.fix_commits`
is 3 and there were 5, so the floor was cleared. The floors were designed against "100%
from n=1" and are symmetric, which stops the flattering half of the problem and none of the
damning half — and the damning half is the one nobody in the loop is motivated to check.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures import repos
from vouch.ingest import ingest
from vouch.l1.extract import extract_facts
from vouch.l1.facts import FactStatus
from vouch.l1.interval import (
    LENIENT_LEVEL,
    STRICT_LEVEL,
    Polarity,
    asymmetric_interval,
    median_interval,
    wilson_bounds,
    z_for,
)
from vouch.l2.payload import MetricKey, MetricScope, Rate, SessionMetrics
from vouch.l4.dimensions import DIMENSIONS
from vouch.l4.judge import judge_profile
from vouch.l4.mock import MockJudgeProvider, MockMode
from vouch.l4.schema import DimensionKey
from vouch.l5.ordering import evidence_strength, order_findings
from vouch.l5.profile import build_profile

SUBJECT = "alice@example.com"


@pytest.fixture
def early_career(tmp_path: Path):
    """The wagtail shape: 45-ish commits, five fixes, none with a test."""
    repo = tmp_path / "early_career"
    repos.early_career(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    return repo, snapshot, extract_facts(snapshot, SUBJECT, repo)


# --- the arithmetic ---------------------------------------------------------------------


def test_z_values_match_the_standard_table() -> None:
    assert round(z_for(0.95), 4) == 1.9600
    assert round(z_for(0.80), 4) == 1.2816
    assert round(z_for(0.99), 4) == 2.5758


def test_wilson_never_leaves_the_unit_interval_at_the_extremes() -> None:
    """The reason for Wilson over the normal approximation, which goes negative at 0/n."""
    for n in (1, 3, 5, 20, 400):
        low, high = wilson_bounds(0, n, STRICT_LEVEL)
        assert low == pytest.approx(0.0, abs=1e-12)
        assert 0.0 < high <= 1.0
        low, high = wilson_bounds(n, n, STRICT_LEVEL)
        assert 0.0 <= low < 1.0
        assert high == pytest.approx(1.0, abs=1e-12)


def test_no_observations_is_maximally_uninformative() -> None:
    assert wilson_bounds(0, 0, STRICT_LEVEL) == (0.0, 1.0)


def test_intervals_narrow_as_evidence_accumulates() -> None:
    widths = [
        asymmetric_interval(n // 2, n, Polarity.HIGHER_IS_BETTER).width
        for n in (4, 10, 50, 500)
    ]
    assert widths == sorted(widths, reverse=True)


# --- the asymmetry ----------------------------------------------------------------------


def test_the_unfavourable_bound_is_held_to_the_stricter_level() -> None:
    """The design decision, stated as an assertion.

    For a higher-is-better rate the *upper* bound is what an unfavourable reading rests on
    — "it is at most this much" — so it is drawn at 95%, while the lower bound, which
    carries a favourable reading, is drawn at 80%.
    """
    higher = asymmetric_interval(0, 5, Polarity.HIGHER_IS_BETTER)
    assert higher.high_level == STRICT_LEVEL
    assert higher.low_level == LENIENT_LEVEL

    lower = asymmetric_interval(0, 5, Polarity.LOWER_IS_BETTER)
    assert lower.low_level == STRICT_LEVEL
    assert lower.high_level == LENIENT_LEVEL


def test_a_damning_claim_needs_more_evidence_than_a_flattering_one() -> None:
    """The requirement, measured.

    Both readings come off five observations. The flattering one ("at least 75%") is
    reachable; the damning one is not — the honest ceiling on 0 of 5 is around 43%, which
    is not a number anybody would call a deficit.
    """
    flattering = asymmetric_interval(5, 5, Polarity.HIGHER_IS_BETTER)
    damning = asymmetric_interval(0, 5, Polarity.HIGHER_IS_BETTER)

    assert flattering.low > 0.75  # "at least three quarters" is supportable at n=5
    assert damning.high > 0.4  # "essentially never" is not

    # The asymmetry is not an artefact of the sample: at the same level both bounds would
    # sit the same distance from the extreme. They do not.
    symmetric_low = wilson_bounds(5, 5, STRICT_LEVEL)[0]
    assert flattering.low > symmetric_low


def test_neutral_facts_get_a_symmetric_interval() -> None:
    """No favourable direction means no asymmetric cost to protect against."""
    neutral = asymmetric_interval(2, 8, Polarity.NEUTRAL)
    assert neutral.low_level == neutral.high_level == STRICT_LEVEL


def test_a_median_carries_an_interval_too() -> None:
    """`commit_scoping: 4.0` is a point estimate wearing different units."""
    interval = median_interval([1, 1, 2, 3, 4, 5, 8, 13, 21])
    assert interval is not None
    assert interval.method == "order-statistic"
    assert interval.low < 4 < interval.high

    # One observation is a point, not a range, and saying so beats inventing a spread.
    assert median_interval([4]) is None


# --- the acceptance case ------------------------------------------------------------------


def test_zero_of_five_publishes_as_a_wide_interval_from_zero(early_career) -> None:
    """The acceptance criterion. Not 0.0 — a range that reaches most of the way to a half."""
    _repo, _snapshot, facts = early_career
    fact = facts.fact("test_accompanies_fix")

    assert fact is not None
    assert (fact.numerator, fact.denominator) == (0, 5)
    assert fact.status is FactStatus.MEASURED
    assert fact.interval is not None
    assert fact.interval.low == 0.0
    assert fact.interval.high > 0.4
    # The point estimate still exists — it is just no longer the published quantity.
    assert fact.value == 0.0


def test_a_thin_dimension_does_not_lead_the_report(early_career) -> None:
    """The other half of the acceptance criterion: position is a claim, so it is earned."""
    repo, snapshot, facts = early_career
    judgment = judge_profile(
        MockJudgeProvider(MockMode.HONEST), facts, repo, snapshot.commits
    )
    profile = build_profile(facts, judgment)

    leader = profile.findings[0].dimension
    assert leader is not DimensionKey.VERIFICATION_DISCIPLINE

    # ...and it is below dimensions that genuinely rest on more.
    positions = {f.dimension: i for i, f in enumerate(profile.findings)}
    assert positions[DimensionKey.VERIFICATION_DISCIPLINE] > positions[
        DimensionKey.SCOPE_CONTROL
    ]


def test_evidence_strength_ranks_the_thin_dimension_below_the_others(
    early_career,
) -> None:
    _repo, _snapshot, facts = early_career
    strengths = {
        spec.key: evidence_strength(spec, facts, None) for spec in DIMENSIONS
    }

    assert strengths[DimensionKey.VERIFICATION_DISCIPLINE] < strengths[
        DimensionKey.OWNERSHIP
    ]
    assert strengths[DimensionKey.SCOPE_CONTROL] > strengths[
        DimensionKey.VERIFICATION_DISCIPLINE
    ]


# --- ordering rules ------------------------------------------------------------------------


def test_declines_sort_below_conclusions(early_career) -> None:
    repo, snapshot, facts = early_career
    judgment = judge_profile(
        MockJudgeProvider(MockMode.HONEST), facts, repo, snapshot.commits
    )
    ordered = order_findings(judgment.findings, facts)

    tiers = [f.verdict in {"strong", "moderate", "limited", "contradicted"} for f in ordered]
    assert tiers == sorted(tiers, reverse=True)


def test_an_uncollected_layer_does_not_count_against_a_dimension(early_career) -> None:
    """Whether the user ran the session CLI is a fact about the run, not the subject."""
    _repo, _snapshot, facts = early_career
    spec = next(s for s in DIMENSIONS if s.key is DimensionKey.SCOPE_CONTROL)

    without_l2 = evidence_strength(spec, facts, None)
    with_suppressed_l2 = evidence_strength(
        spec,
        facts,
        SessionMetrics(
            scope=MetricScope.REPO,
            rates={
                MetricKey.EDIT_REVISION: Rate(
                    numerator=1, denominator=2, floor=10, suppressed=True
                )
            },
        ),
    )

    # Collected-but-suppressed is genuinely weaker than never-collected: we looked.
    assert with_suppressed_l2 < without_l2


def test_out_of_scope_telemetry_contributes_no_strength(early_career) -> None:
    _repo, _snapshot, facts = early_career
    spec = next(s for s in DIMENSIONS if s.key is DimensionKey.SCOPE_CONTROL)
    machine_wide = SessionMetrics(
        scope=MetricScope.MACHINE,
        rates={
            MetricKey.EDIT_REVISION: Rate(
                numerator=40, denominator=100, floor=10, value=0.4, low=0.33, high=0.47
            )
        },
    )

    assert evidence_strength(spec, facts, machine_wide) == evidence_strength(
        spec, facts, None
    )


def test_suppressed_facts_still_publish_their_interval(tmp_path: Path) -> None:
    """Withholding the point estimate is right; withholding the range too is just silence."""
    repo = tmp_path / "short_window"
    repos.short_window(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    facts = extract_facts(snapshot, SUBJECT, repo)

    suppressed = [f for f in facts.facts if f.status is FactStatus.SUPPRESSED_LOW_N]
    assert suppressed, "fixture no longer suppresses anything — pick another"
    for fact in suppressed:
        assert fact.value is None
        assert fact.interval is not None
