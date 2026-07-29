"""Intervals, asymmetric evidence requirements, and evidence-led report ordering.

The failure this exists to prevent, in one line: **`test_accompanies_fix: 0.0`, computed
from five commits, printed at the top of a profile about an early-career engineer.**

Every guard the pipeline had fired correctly and the number still got out. `MinN.fix_commits`
is 3 and there were 5, so the floor was cleared. The floors were designed against "100%
from n=1" and are symmetric, which stops the flattering half of the problem and none of the
damning half — and the damning half is the one nobody in the loop is motivated to check.

:data:`_CORPUS_INTERVALS` is every interval L1 produced for the ten corpus rows with a local
clone, at the heads pinned in `eval/repos.yaml`. Eighteen of the 46 rendered as different
numbers under the two formatters, and not the marginal ones: every `ownership_loop` and
every `test_accompanies_fix` that clears its floor is in the list. It is frozen rather than
recomputed because CI has no clones and a full corpus pass is ~45 minutes of blame; what it
preserves is the *shapes* a real corpus produces, which the sweep below generalises.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.fixtures import repos

# Private, and imported anyway: that these two renderings agree is the property under test.
from vouch.eval.labeling import _fact_line as fact_line
from vouch.eval.labeling import _metric_line as metric_line
from vouch.ingest import ingest
from vouch.l1.extract import extract_facts
from vouch.l1.facts import Fact, FactStatus, Identity, Interval, RepoFacts
from vouch.l1.interval import (
    LENIENT_LEVEL,
    STRICT_LEVEL,
    Polarity,
    asymmetric_interval,
    format_range,
    median_interval,
    wilson_bounds,
    z_for,
)
from vouch.l2.payload import MetricKey, MetricScope, Rate, SessionMetrics
from vouch.l4.dimensions import DIMENSIONS, assess_availability
from vouch.l4.judge import judge_profile
from vouch.l4.mock import MockJudgeProvider, MockMode
from vouch.l4.prompt import _band as prompt_band
from vouch.l4.prompt import _render_metrics as render_metrics
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

    # Not an artefact of the sample: at one level both bounds sit equidistant. They do not.
    symmetric_low = wilson_bounds(5, 5, STRICT_LEVEL)[0]
    assert flattering.low > symmetric_low


def test_an_interval_prints_both_ends_at_the_same_significant_figures() -> None:
    """`%g` varied its precision by magnitude and stripped trailing zeros.

    `0.0003-0.005` and `2-2` came off the same code path carrying quite different amounts
    of information, and looked equally exact on the page.
    """
    assert format_range(0.0003, 0.005) == "0.00030-0.00500"
    assert format_range(2, 2) == "2.0-2.0"
    # At this magnitude two significant figures IS the integer; no false decimals.
    assert format_range(92, 119) == "92-119"


def test_a_bound_of_zero_takes_its_precision_from_the_other_end() -> None:
    """0 has no magnitude of its own, and must not drag the pair down to `0-0.4`."""
    assert format_range(0.0, 0.4295) == "0.00-0.43"
    assert format_range(0.0, 0.0) == "0.0-0.0"


def test_a_bound_near_zero_stops_at_the_decimal_cap() -> None:
    """A run of zeros is not more informative than the cap, and is less readable."""
    printed = format_range(0.0000001, 0.5)
    assert len(printed.split("-")[0].split(".")[1]) <= 6


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


#: Frozen L1 output for the corpus rows with a local clone. See the module docstring.
_CORPUS_INTERVALS = [
    (0.0005, 0.0042),     # hunter        revert_rate
    (0.21, 0.3041),       # hunter        test_accompanies_fix  <- differed under %g
    (0.0, 6.0),           # hunter        followup_latency
    (2.0, 2.0),           # hunter        commit_scoping
    (0.0003, 0.005),      # svcs          revert_rate
    (0.1096, 0.2826),     # svcs          test_accompanies_fix  <- differed under %g
    (4.0, 117.0),         # svcs          followup_latency
    (1.0, 1.0),           # svcs          commit_scoping
    (0.7216, 0.9476),     # httpx         ownership_loop  <- differed under %g
    (0.0003, 0.005),      # httpx         revert_rate
    (0.5097, 0.7434),     # httpx         test_accompanies_fix  <- differed under %g
    (14.0, 197.0),        # httpx         followup_latency
    (2.0, 2.0),           # httpx         commit_scoping
    (0.5747, 0.9699),     # black         ownership_loop  <- differed under %g
    (0.0, 0.0081),        # black         revert_rate
    (0.5806, 0.7776),     # black         test_accompanies_fix  <- differed under %g
    (0.0, 775.0),         # black         followup_latency
    (2.0, 3.0),           # black         commit_scoping
    (0.4708, 0.6231),     # pytest        ownership_loop  <- differed under %g
    (0.0042, 0.0121),     # pytest        revert_rate
    (0.2676, 0.3574),     # pytest        test_accompanies_fix  <- differed under %g
    (69.0, 236.0),        # pytest        followup_latency
    (2.0, 2.0),           # pytest        commit_scoping
    (0.0, 0.7935),        # flask         ownership_loop  <- differed under %g
    (0.0013, 0.0248),     # flask         revert_rate
    (0.1448, 0.3981),     # flask         test_accompanies_fix  <- differed under %g
    (0.0, 37.0),          # flask         followup_latency
    (1.0, 1.0),           # flask         commit_scoping
    (0.0, 1.0),           # unp           ownership_loop
    (0.0, 0.1299),        # unp           revert_rate  <- differed under %g
    (0.0, 0.7935),        # unp           test_accompanies_fix  <- differed under %g
    (1.0, 2.0),           # unp           commit_scoping
    (0.0, 1.0),           # records       ownership_loop
    (0.0, 0.1299),        # records       revert_rate  <- differed under %g
    (0.5491, 1.0),        # records       test_accompanies_fix  <- differed under %g
    (1.0, 2.0),           # records       commit_scoping
    (0.5941, 0.8572),     # sqlite-utils  ownership_loop  <- differed under %g
    (0.0002, 0.0032),     # sqlite-utils  revert_rate
    (0.2487, 0.373),      # sqlite-utils  test_accompanies_fix  <- differed under %g
    (0.0, 34.0),          # sqlite-utils  followup_latency
    (2.0, 2.0),           # sqlite-utils  commit_scoping
    (0.554, 0.757),       # pyinfra       ownership_loop  <- differed under %g
    (0.0001, 0.0028),     # pyinfra       revert_rate
    (0.2939, 0.408),      # pyinfra       test_accompanies_fix  <- differed under %g
    (15.0, 100.0),        # pyinfra       followup_latency
    (1.0, 1.0),           # pyinfra       commit_scoping
]


def _band_numbers(rendered: str) -> tuple[float, float]:
    """The interval a reader takes away, as numbers — whatever the formatting around it."""
    match = re.search(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", rendered)
    assert match, f"no interval rendered in {rendered!r}"
    return float(match.group(1)), float(match.group(2))


def _one_fact(low: float, high: float) -> tuple[RepoFacts, Fact]:
    fact = Fact(
        key="test_accompanies_fix",
        status=FactStatus.MEASURED,
        value=low,
        polarity=Polarity.HIGHER_IS_BETTER,
        numerator=1,
        denominator=10,
        interval=Interval(
            low=low, high=high, low_level=LENIENT_LEVEL, high_level=STRICT_LEVEL
        ),
    )
    facts = RepoFacts(
        repo="fixture",
        head_sha="a" * 40,
        subject=Identity(canonical_email=SUBJECT),
        facts=[fact],
    )
    return facts, fact


@pytest.mark.parametrize(("low", "high"), _CORPUS_INTERVALS)
def test_the_judge_and_the_labeller_read_the_same_number(low: float, high: float) -> None:
    """One interval, two renderings, and they must agree as numbers — not just as text.

    The judge prompt formatted with `%g`, which prints up to six significant figures; the
    labelling harness prints two. On `test_accompanies_fix` in the hunter row that is
    `0.21-0.3041` for the model against `0.21-0.30` for the human, and 18 of the 46
    intervals this corpus produces differed the same way. An agreement study run across
    that gap measures the formatter as well as the judge, and nothing in the label or the
    finding records which one moved.

    The two renderings need not look alike — the prompt states the confidence levels, the
    labelling harness states the polarity — but the number under them is the evidence, and
    there is only one of it.
    """
    facts, fact = _one_fact(low, high)

    assert _band_numbers(prompt_band(fact)) == _band_numbers(fact_line(facts, fact.key))


def test_no_interval_the_extractor_can_produce_reads_differently_to_the_two_sides() -> None:
    """The corpus rows above are what we have; this is what the extractor can emit.

    Swept rather than sampled, because the next corpus will contain denominators this one
    does not, and a divergence that shows up only at some magnitudes is exactly the kind
    `%g` produced.
    """
    for n in (1, 2, 3, 5, 8, 13, 26, 45, 229, 1131):
        for successes in sorted({0, 1, n // 2, n}):
            for polarity in Polarity:
                interval = asymmetric_interval(successes, n, polarity)
                facts, fact = _one_fact(interval.low, interval.high)

                judge = _band_numbers(prompt_band(fact))
                labeller = _band_numbers(fact_line(facts, fact.key))
                assert judge == labeller, f"{successes}/{n} {polarity.value}: {judge} != {labeller}"


def test_a_session_metric_is_read_the_same_way_by_both_sides_too() -> None:
    """The third `%g` call site. No corpus row exercises it — a public repo has no L2 —
    so nothing else in this file would catch it drifting back."""
    rate = Rate(numerator=8, denominator=20, floor=5, value=0.4, low=0.2376, high=0.5824)
    metrics = SessionMetrics(scope=MetricScope.REPO, n_sessions=20, rates={
        MetricKey.TEST_OR_BUILD_AFTER_EDIT: rate
    })
    spec = next(s for s in DIMENSIONS if s.key is DimensionKey.VERIFICATION_DISCIPLINE)
    availability = assess_availability(spec, _one_fact(0.0, 1.0)[0], metrics, 0)

    judge = _band_numbers(render_metrics(metrics, availability))
    labeller = _band_numbers(metric_line(metrics, MetricKey.TEST_OR_BUILD_AFTER_EDIT))
    assert judge == labeller


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
