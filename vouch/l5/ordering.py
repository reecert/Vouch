"""Where each dimension sits in the report, decided by how much its evidence supports.

The previous order was a constant. Verification discipline led every profile, because it is
the dimension that spans both the commit trail and the session trail and therefore best
demonstrates corroboration — a good reason to prefer it, and a bad reason to pin it.

Position is a claim. The first readout is the one a screener reads, quotes, and sometimes
decides on; leading with it asserts that it is the most informative thing here. When
`test_accompanies_fix` is 0 of 5 that assertion is false, and it is false in the direction
that costs the subject the interview. So the order follows the evidence:

1. **Verdict tier.** A dimension that reached a conclusion outranks one that declined.
   Declines are not failures — `insufficient_evidence` is meant to be frequent and
   unembarrassing — but they belong below the findings a reader can act on.
2. **Evidence strength.** Within a tier, whichever rests on more evidence and narrower
   intervals goes first. A dimension whose interval spans half the range has not earned
   the top of the page whatever its midpoint reads.
3. **The old constant, as a tie-break only.** Among genuinely comparable dimensions,
   verification discipline still leads, for the reason it always did.

Strength is deliberately computable from L1 and L2 alone, with no model in the loop: the
thing deciding what a reader sees first should be arithmetic they could check.
"""
from __future__ import annotations

from vouch.l1.facts import FactStatus, RepoFacts, Unit
from vouch.l2.payload import SessionMetrics
from vouch.l4.dimensions import DIMENSIONS, DimensionSpec
from vouch.l4.schema import DimensionFinding, DimensionKey, Verdict

__all__ = ["CONCLUDED", "evidence_strength", "order_findings"]

#: `contradicted` belongs here: "the evidence points the other way" is a conclusion.
CONCLUDED = frozenset(
    {Verdict.STRONG, Verdict.MODERATE, Verdict.LIMITED, Verdict.CONTRADICTED}
)

_FALLBACK_ORDER = {spec.key: i for i, spec in enumerate(DIMENSIONS)}


def _relative_width(low: float, high: float, unit: Unit) -> float:
    """An interval's width on a 0-1 scale, whatever it is measured in.

    A proportion's width is already comparable. A median in days or files is not — three
    days is wide for a same-week follow-up and narrow for a two-year one — so its spread is
    expressed relative to its own magnitude. Both end up as "how much room is left", which
    is the only quantity the ordering needs.
    """
    if unit is Unit.FRACTION:
        return max(0.0, min(1.0, high - low))
    total = high + low
    if total <= 0:
        return 0.0 if high == low else 1.0
    return max(0.0, min(1.0, (high - low) / total))


def evidence_strength(
    spec: DimensionSpec, facts: RepoFacts, metrics: SessionMetrics | None
) -> float:
    """How much this dimension's readout actually rests on, in [0, 1].

    Two factors, multiplied:

    * **Survival** — the share of the dimension's declared inputs that produced a value at
      all. A dimension with two of three facts suppressed is thin however tight the
      surviving one is, and multiplying rather than averaging keeps that visible.
    * **Precision** — the mean remaining room across the intervals that did survive.

    Zero inputs gives zero, not one: a dimension with nothing to divide by has no claim on
    the top of the report.
    """
    scoped = metrics is not None and metrics.scope is spec.scope
    # Uncollected L2 counts against nobody: that would rank on whether the CLI was run.
    declared = len(spec.l1_facts) + (len(spec.l2_metrics) if scoped else 0)
    if declared == 0:
        return 0.0

    precisions: list[float] = []
    survived = 0

    for key in spec.l1_facts:
        fact = facts.fact(key)
        if fact is None or fact.status is not FactStatus.MEASURED:
            continue
        survived += 1
        if fact.interval is not None:
            precisions.append(
                1.0
                - _relative_width(fact.interval.low, fact.interval.high, fact.unit)
            )

    for key in spec.l2_metrics:
        rate = metrics.rates.get(key) if scoped and metrics else None
        if rate is None or rate.suppressed:
            continue
        survived += 1
        if rate.low is not None and rate.high is not None:
            precisions.append(1.0 - _relative_width(rate.low, rate.high, Unit.FRACTION))

    if survived == 0:
        return 0.0
    precision = sum(precisions) / len(precisions) if precisions else 1.0
    return round((survived / declared) * precision, 6)


def order_findings(
    findings: list[DimensionFinding],
    facts: RepoFacts,
    metrics: SessionMetrics | None = None,
) -> list[DimensionFinding]:
    """Sort the report. Strongest evidence first; declines last; stable and reproducible."""
    by_key: dict[DimensionKey, DimensionSpec] = {s.key: s for s in DIMENSIONS}

    def sort_key(finding: DimensionFinding) -> tuple[int, float, int]:
        spec = by_key.get(finding.dimension)
        strength = evidence_strength(spec, facts, metrics) if spec else 0.0
        tier = 0 if finding.verdict in CONCLUDED else 1
        return (tier, -strength, _FALLBACK_ORDER.get(finding.dimension, len(by_key)))

    return sorted(findings, key=sort_key)
