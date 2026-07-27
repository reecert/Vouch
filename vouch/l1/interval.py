"""Intervals, and the asymmetry in what it takes to publish one.

**The defect.** Minimum-denominator floors were designed against one failure — "100% of
fixes came with a test" printed off a single fix commit. They are symmetric, so they stop
that and nothing else. `test_accompanies_fix` at 0 of 5 clears a floor of 3 and publishes
as a flat **0.0**, on the dimension that leads the report, about a person who is being
screened for a job. Five observations do not support "never writes tests"; they support
"somewhere between none and about two in five", which is a different sentence and invites
a different question in the interview.

A point estimate at small n is not a small error. It is a confident statement of something
the data does not contain, and rounding it to one decimal place makes it look measured.

**What replaces it.** Every proportion carries a Wilson score interval, and the interval is
the published quantity. At n=400 it is narrow and reads like a point; at n=5 it is wide and
reads like the shrug it should be. Wilson rather than the textbook normal approximation
because the normal one produces intervals that extend below zero exactly where this
product needs to be trustworthy — at 0 successes.

**The asymmetry, and why it is a values choice rather than a statistical one.** The Wilson
interval is symmetric in its treatment of the two tails; nothing in the statistics says a
low reading deserves more scepticism than a high one. The asymmetry here comes from the
cost of being wrong, which is not symmetric at all:

* A falsely *flattering* reading costs the reader an interview loop. They ask a question,
  the answer is thin, they move on. The error is self-correcting on contact.
* A falsely *unflattering* reading costs the subject the interview. Nobody probes a number
  that says "don't bother", the subject is never told which number it was, and the error
  never gets a chance to correct itself.

So the bound that would support an unfavourable reading is drawn at the **strict**
confidence level, and the bound that would support a favourable one at the **lenient**
level. Concretely, for a higher-is-better rate the upper bound (the one whose smallness
would damn the subject) is computed at 95% and the lower bound at 80%. For a
lower-is-better rate it is the mirror image. It takes less evidence to say "at least 65%"
than to say "at most 43%", by construction.

This is deliberately a **graded** requirement rather than a second, higher denominator
floor for unfavourable readings. A second floor would recreate the exact failure the first
one caused: a cliff, with a confident number on one side of it and silence on the other.
"""
from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

__all__ = [
    "Polarity",
    "Interval",
    "LENIENT_LEVEL",
    "STRICT_LEVEL",
    "wilson_bounds",
    "asymmetric_interval",
    "median_interval",
    "z_for",
]

#: Confidence level for the bound that would support a *favourable* reading. Lower, so a
#: flattering claim is reachable on ordinary evidence.
LENIENT_LEVEL = 0.80

#: Confidence level for the bound that would support an *unfavourable* reading. Higher, so
#: a damning claim has to be earned. See the module docstring for why these differ.
STRICT_LEVEL = 0.95


class Polarity(StrEnum):
    """Which direction of a fact is the unfavourable one, for the reader of a profile.

    ``NEUTRAL`` is not a cop-out: `commit_scoping` (median files per commit) has no good
    direction — small commits are focused or trivial, large ones thorough or sprawling —
    and a fact with no bad direction gets a symmetric interval, because there is no
    asymmetric cost to protect against.
    """

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    NEUTRAL = "neutral"


class Interval(BaseModel):
    """A range the evidence supports, and how each end of it was drawn.

    ``low_level`` and ``high_level`` are recorded separately because they usually differ.
    A reader — or a later reviewer of this code — should not have to know the convention to
    see that one end was held to a stricter standard than the other.
    """

    model_config = ConfigDict(extra="forbid")

    low: float
    high: float
    low_level: float
    high_level: float
    method: str = "wilson"

    @property
    def width(self) -> float:
        return self.high - self.low

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


def z_for(level: float) -> float:
    """Two-sided normal quantile for ``level``.

    Computed rather than looked up so an arbitrary level is expressible, via the inverse
    error function — ``statistics.NormalDist().inv_cdf`` would do too, but this keeps the
    module free of a dependency on distribution objects for one number.
    """
    return math.sqrt(2.0) * _erfinv(level)


def _erfinv(x: float) -> float:
    """Inverse error function, Newton-refined from a standard rational initial guess.

    Accurate to well past the precision any of these intervals are rendered at.
    """
    a = 0.147
    ln = math.log(1.0 - x * x)
    term = 2.0 / (math.pi * a) + ln / 2.0
    guess = math.copysign(math.sqrt(math.sqrt(term * term - ln / a) - term), x)
    for _ in range(3):
        err = math.erf(guess) - x
        guess -= err / (2.0 / math.sqrt(math.pi) * math.exp(-guess * guess))
    return guess


def wilson_bounds(successes: int, n: int, level: float) -> tuple[float, float]:
    """Wilson score interval for ``successes`` out of ``n`` at ``level``.

    Zero observations give ``(0.0, 1.0)`` — the honest answer, and the one that makes any
    downstream width test treat "no evidence" as maximally uninformative rather than as a
    suspiciously tidy zero.
    """
    if n <= 0:
        return 0.0, 1.0
    z = z_for(level)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    spread = (z / denom) * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, centre - spread), min(1.0, centre + spread)


def asymmetric_interval(
    successes: int,
    n: int,
    polarity: Polarity,
    lenient: float = LENIENT_LEVEL,
    strict: float = STRICT_LEVEL,
) -> Interval:
    """The published range: each end drawn at the level its direction has to earn.

    For ``HIGHER_IS_BETTER`` the *upper* bound is what an unfavourable reading rests on —
    "it is at most this much" — so it is drawn at ``strict``, and the lower bound, which
    carries the favourable reading, at ``lenient``. ``LOWER_IS_BETTER`` is the mirror.
    ``NEUTRAL`` uses ``strict`` at both ends, since neither direction is a claim about the
    person and there is no asymmetric cost to weigh.
    """
    if polarity is Polarity.HIGHER_IS_BETTER:
        low_level, high_level = lenient, strict
    elif polarity is Polarity.LOWER_IS_BETTER:
        low_level, high_level = strict, lenient
    else:
        low_level = high_level = strict

    low = wilson_bounds(successes, n, low_level)[0]
    high = wilson_bounds(successes, n, high_level)[1]
    return Interval(
        low=round(low, 4),
        high=round(high, 4),
        low_level=low_level,
        high_level=high_level,
    )


def median_interval(values: list[float], level: float = STRICT_LEVEL) -> Interval | None:
    """Distribution-free confidence interval for a median, from order statistics.

    A median is a point estimate too, and `commit_scoping: 4.0` off eleven commits is the
    same kind of overstatement as `test_accompanies_fix: 0.0` off five — it just looks less
    like one because it is not a percentage.

    The interval is the pair of ranks whose enclosed probability reaches ``level`` under
    the binomial that governs how many observations fall below the true median. No
    distribution is assumed about the values themselves, which matters: files-per-commit is
    skewed, bounded below at 1, and nothing like normal.

    Returns ``None`` for fewer than two observations — an interval spanning a single point
    would assert precision rather than describe it. Both bounds are drawn at the same level:
    there is no favourable direction to a median file count, so there is no asymmetric cost
    to weigh (see :class:`Polarity`).
    """
    if len(values) < 2:
        return None
    ordered = sorted(values)
    n = len(ordered)
    # Normal approximation to the binomial rank, the standard construction. Clamped into
    # range so tiny samples give the widest available interval rather than an error.
    z = z_for(level)
    half = z * math.sqrt(n) / 2.0
    lower_rank = max(0, math.floor(n / 2.0 - half))
    upper_rank = min(n - 1, math.ceil(n / 2.0 + half - 1))
    return Interval(
        low=round(float(ordered[lower_rank]), 4),
        high=round(float(ordered[upper_rank]), 4),
        low_level=level,
        high_level=level,
        method="order-statistic",
    )
