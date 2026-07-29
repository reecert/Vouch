"""Measure the join, under the same honest-at-small-n rules as the rest of the product.

The brief calls L3 the core differentiator and asks for real effort on accuracy. Effort on
accuracy means *measuring* it: a join that is never scored is a guess with a confident
schema around it.

Ground truth comes from cases where the correspondence is known by construction — a
synthetic repo built alongside the session logs that produced it. That is a real
measurement of the algorithm and an honest one about its scope: it says the scorer behaves
correctly on histories we built, not that it generalises to every real repo. Saying which
of those two things a number supports is the whole discipline.

Matching the *right* session is required for a true positive. A join that corroborates
every commit with whichever session sorted first would otherwise score perfectly on recall
while being worthless.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from vouch.l3.join import CorroborationReport, CorroborationVerdict

__all__ = [
    "MIN_LABELS_FOR_ACCURACY",
    "JoinLabel",
    "JoinOutcome",
    "JoinMetrics",
    "score_join",
]

MIN_LABELS_FOR_ACCURACY = 20  # below this, precision and recall are directional only


class JoinLabel(BaseModel):
    """Ground truth for one commit: which session produced it, if any."""

    model_config = ConfigDict(extra="forbid")

    sha: str
    session_id: str | None = None  # None: genuinely produced outside any session
    note: str = ""  # what this case is testing, for a human reading a failure


class JoinOutcome(StrEnum):
    TRUE_POSITIVE = "true_positive"  # corroborated, and to the right session
    WRONG_SESSION = "wrong_session"  # corroborated, but to the wrong session
    FALSE_POSITIVE = "false_positive"  # corroborated a commit with no session behind it
    FALSE_NEGATIVE = "false_negative"  # had a session; we did not corroborate it
    TRUE_NEGATIVE = "true_negative"  # correctly left uncorroborated
    AMBIGUOUS = "ambiguous"  # declined to choose — neither right nor wrong
    UNLABELLED = "unlabelled"


class JoinMetrics(BaseModel):
    """Accuracy with its n attached. A number without its n is not a result."""

    model_config = ConfigDict(extra="forbid")

    n_labelled: int = 0
    n_with_session: int = 0  # the recall denominator
    n_without_session: int = 0

    true_positive: int = 0
    wrong_session: int = 0
    false_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0
    ambiguous: int = 0

    precision: float | None = None
    recall: float | None = None
    status: str = "insufficient_n"
    threshold: int = MIN_LABELS_FOR_ACCURACY
    outcomes: dict[str, JoinOutcome] = Field(default_factory=dict)

    @property
    def is_evidence(self) -> bool:
        return self.status == "measured"


def _outcome(
    verdict: CorroborationVerdict, matched_session: str | None, truth: str | None
) -> JoinOutcome:
    if verdict is CorroborationVerdict.AMBIGUOUS:
        return JoinOutcome.AMBIGUOUS
    if verdict is CorroborationVerdict.CORROBORATED:
        if truth is None:
            return JoinOutcome.FALSE_POSITIVE
        return (
            JoinOutcome.TRUE_POSITIVE
            if matched_session == truth
            else JoinOutcome.WRONG_SESSION
        )
    # uncorroborated
    return JoinOutcome.TRUE_NEGATIVE if truth is None else JoinOutcome.FALSE_NEGATIVE


def score_join(report: CorroborationReport, labels: list[JoinLabel]) -> JoinMetrics:
    """Score a join against ground truth.

    Precision counts a wrong-session match as a false positive: corroborating a commit to
    the wrong session is not a partial success, it is an incorrect claim of the exact kind
    a reader would rely on.

    Ambiguous verdicts are excluded from *precision* — declining to choose is not a claim,
    so it cannot be a wrong one — but they stay in the *recall* denominator, which is every
    commit that truly had a session behind it. Otherwise a join could drive recall to 1.0
    by answering "ambiguous" whenever it was unsure.
    """
    by_sha = {r.sha: r for r in report.records}
    metrics = JoinMetrics(n_labelled=len(labels))

    for label in labels:
        record = by_sha.get(label.sha)
        if record is None:
            metrics.outcomes[label.sha] = JoinOutcome.UNLABELLED
            continue

        if label.session_id is None:
            metrics.n_without_session += 1
        else:
            metrics.n_with_session += 1

        outcome = _outcome(record.verdict, record.basis.session_ref, label.session_id)
        metrics.outcomes[label.sha] = outcome

        match outcome:
            case JoinOutcome.TRUE_POSITIVE:
                metrics.true_positive += 1
            case JoinOutcome.WRONG_SESSION:
                metrics.wrong_session += 1
            case JoinOutcome.FALSE_POSITIVE:
                metrics.false_positive += 1
            case JoinOutcome.FALSE_NEGATIVE:
                metrics.false_negative += 1
            case JoinOutcome.TRUE_NEGATIVE:
                metrics.true_negative += 1
            case JoinOutcome.AMBIGUOUS:
                metrics.ambiguous += 1

    claimed = metrics.true_positive + metrics.wrong_session + metrics.false_positive
    if claimed:
        metrics.precision = round(metrics.true_positive / claimed, 4)

    if metrics.n_with_session:
        metrics.recall = round(metrics.true_positive / metrics.n_with_session, 4)

    metrics.status = (
        "measured" if metrics.n_labelled >= MIN_LABELS_FOR_ACCURACY else "insufficient_n"
    )
    return metrics
