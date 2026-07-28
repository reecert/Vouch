"""Score L4's dimension verdicts against hand-labelled ground truth.

The v0 harness measured agreement on a strong/weak binary. That is the wrong shape for this
product: what matters is not only *whether* the judge agrees with a careful human but **in
which direction it disagrees**.

* **Overclaiming** — the judge concludes where a human declined — is the failure the whole
  quality bar is aimed at. One overclaim costs more than several underclaims, because it is
  the one that produces a flattering profile from thin evidence.
* **Underclaiming** — the judge declines where a human concluded — is a product problem
  (a profile that says nothing is not useful) but not an honesty problem.

Reporting them separately is the difference between "72% agreement" and a number a reader
can act on.

The guard rails from v0 survive intact: the harness refuses to report an empty holdout,
warns loudly below the evidence threshold, and never claims "calibrated".
"""
from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from vouch.eval.labels import DimensionLabel, LabelSet
from vouch.l4.schema import DimensionFinding, Verdict

__all__ = [
    "MIN_LABELS_FOR_EVIDENCE",
    "MIN_LABELS_FOR_CALIBRATION",
    "EvalError",
    "BAND_ORDER",
    "RowResult",
    "EvalMetrics",
    "EvalReport",
    "run_eval",
]

#: Below this many labels in total, the numbers are directional, not evidence.
MIN_LABELS_FOR_EVIDENCE = 15
#: Below this many scored rows, calibration is not computed and never claimed.
MIN_LABELS_FOR_CALIBRATION = 30

#: The conclusive verdicts are ordinal, so "adjacent" is meaningful and a disagreement has a
#: direction. `not_collected` and `contradicted` are categorical — exact match or nothing.
BAND_ORDER: dict[Verdict, int] = {
    Verdict.INSUFFICIENT_EVIDENCE: 0,
    Verdict.LIMITED: 1,
    Verdict.MODERATE: 2,
    Verdict.STRONG: 3,
}

OUTCOME_SCORED = "scored"
OUTCOME_JUDGE_FAILED = "judge_failed"
OUTCOME_NO_FINDING = "no_finding"


class EvalError(Exception):
    """The harness refuses to produce a result (e.g. reporting an empty holdout)."""


class RowResult(BaseModel):
    """One label's outcome.

    Identified by corpus id, like the label it scores. An eval report is a natural place to
    print "we judged <person> wrong", and printing it by address would put one in a log, a
    terminal scrollback, or a pasted snippet — the report inherits the label file's rule.
    """

    model_config = ConfigDict(extra="forbid")

    corpus_id: str
    dimension: str
    expected: str
    predicted: str | None = None
    outcome: str = OUTCOME_SCORED
    exact: bool | None = None
    adjacent: bool | None = None
    direction: str | None = None  # "overclaim" | "underclaim" | None
    detail: str = ""


class EvalMetrics(BaseModel):
    """Agreement, with its n and its direction. A number without both is not a result."""

    model_config = ConfigDict(extra="forbid")

    n_labelled: int = 0
    n_scored: int = 0
    n_judge_failed: int = 0
    n_no_finding: int = 0

    exact_agreement: float | None = None
    adjacent_agreement: float | None = None
    n_exact: int = 0
    n_adjacent: int = 0

    # The direction of disagreement — the number this product actually turns on.
    n_overclaim: int = 0
    n_underclaim: int = 0
    overclaim_rate: float | None = None
    underclaim_rate: float | None = None

    calibration_status: str = "insufficient_n"
    calibration_threshold: int = MIN_LABELS_FOR_CALIBRATION


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split: str
    prompt_version: str = ""
    total_labelled: int = 0
    metrics: EvalMetrics = Field(default_factory=EvalMetrics)
    results: list[RowResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _compare(expected: Verdict, predicted: Verdict) -> tuple[bool, bool, str | None]:
    """Return (exact, adjacent, direction)."""
    if expected is predicted:
        return True, True, None

    exp_band = BAND_ORDER.get(expected)
    pred_band = BAND_ORDER.get(predicted)
    if exp_band is None or pred_band is None:
        # One side is categorical (not_collected / contradicted): no meaningful distance.
        return False, False, None

    delta = pred_band - exp_band
    return False, abs(delta) <= 1, "overclaim" if delta > 0 else "underclaim"


def _score_row(label: DimensionLabel, finding: DimensionFinding | None) -> RowResult:
    base = dict(
        corpus_id=label.corpus_id,
        dimension=label.dimension.value,
        expected=label.verdict.value,
    )
    if finding is None:
        return RowResult(
            **base, outcome=OUTCOME_NO_FINDING, detail="judge produced no finding"
        )

    exact, adjacent, direction = _compare(label.verdict, finding.verdict)
    return RowResult(
        **base,
        predicted=finding.verdict.value,
        outcome=OUTCOME_SCORED,
        exact=exact,
        adjacent=adjacent,
        direction=direction,
    )


def _metrics(results: list[RowResult]) -> EvalMetrics:
    scored = [r for r in results if r.outcome == OUTCOME_SCORED]
    n = len(scored)
    n_exact = sum(1 for r in scored if r.exact)
    n_adjacent = sum(1 for r in scored if r.adjacent)
    n_over = sum(1 for r in scored if r.direction == "overclaim")
    n_under = sum(1 for r in scored if r.direction == "underclaim")

    def ratio(count: int) -> float | None:
        return round(count / n, 4) if n else None

    return EvalMetrics(
        n_labelled=len(results),
        n_scored=n,
        n_judge_failed=sum(1 for r in results if r.outcome == OUTCOME_JUDGE_FAILED),
        n_no_finding=sum(1 for r in results if r.outcome == OUTCOME_NO_FINDING),
        exact_agreement=ratio(n_exact),
        adjacent_agreement=ratio(n_adjacent),
        n_exact=n_exact,
        n_adjacent=n_adjacent,
        n_overclaim=n_over,
        n_underclaim=n_under,
        overclaim_rate=ratio(n_over),
        underclaim_rate=ratio(n_under),
        calibration_status=(
            "insufficient_n" if n < MIN_LABELS_FOR_CALIBRATION else "deferred"
        ),
    )


def run_eval(
    labels: LabelSet,
    judge_fn: Callable[[DimensionLabel], DimensionFinding | None],
    *,
    split: str = "holdout",
    prompt_version: str = "",
) -> EvalReport:
    """Score a split. ``judge_fn`` runs the pipeline for one label and returns its finding.

    Refuses an empty holdout: a silent 0/0 would masquerade as a result. Warns loudly when
    the whole labelled corpus is too small to be evidence.
    """
    if split == "holdout":
        rows = labels.holdout
    elif split == "train":
        rows = labels.train
    elif split == "all":
        rows = labels.all_rows()
    else:
        raise EvalError(f"unknown split {split!r}; use 'train', 'holdout' or 'all'")

    if split == "holdout" and not rows:
        raise EvalError(
            "refusing to report holdout metrics: the holdout is empty. "
            "Populate eval/labels.yaml before reporting any number about judge accuracy."
        )
    if not rows:
        raise EvalError(f"the {split!r} split is empty; nothing to evaluate")

    results: list[RowResult] = []
    for label in rows:
        try:
            finding = judge_fn(label)
        except Exception as e:  # a failed row is reported, never fatal to the run
            results.append(
                RowResult(
                    corpus_id=label.corpus_id,
                    dimension=label.dimension.value,
                    expected=label.verdict.value,
                    outcome=OUTCOME_JUDGE_FAILED,
                    detail=str(e),
                )
            )
            continue
        results.append(_score_row(label, finding))

    metrics = _metrics(results)

    warnings: list[str] = []
    if labels.total < MIN_LABELS_FOR_EVIDENCE:
        warnings.append(
            f"only {labels.total} labels in total (< {MIN_LABELS_FOR_EVIDENCE}): "
            "these numbers are DIRECTIONAL, not evidence."
        )
    if metrics.n_scored == 0:
        warnings.append("no row produced a finding — every metric below is empty.")
    if metrics.n_overclaim:
        warnings.append(
            f"{metrics.n_overclaim} row(s) OVERCLAIMED — the judge concluded where a "
            "human declined. This is the failure mode the quality bar exists to prevent."
        )
    if metrics.n_judge_failed:
        warnings.append(f"{metrics.n_judge_failed} row(s) failed to run.")

    return EvalReport(
        split=split,
        prompt_version=prompt_version,
        total_labelled=labels.total,
        metrics=metrics,
        results=results,
        warnings=warnings,
    )
