"""eval — labeled repos -> judge-quality metrics. The crux.

Runs the full pipeline over a frozen, hand-labeled set and scores the judge against the
labels. Two disciplines are enforced structurally, because they are the whole point:

  * **Train/holdout split.** The prompt is iterated on ``train`` only; the reported numbers
    come from ``holdout``. The harness *refuses* to report holdout metrics when the holdout
    is empty (there is nothing to report), and warns loudly when the total labeled set is
    below :data:`~vouch.config.MIN_LABELS_FOR_EVIDENCE` — below that, numbers are
    directional, not evidence.

  * **Honest metrics at small n.** We report (a) **agreement** — verdict vs label — and
    (b) **confidence separation** — mean confidence on correct vs incorrect verdicts. We do
    NOT print a reliability curve or claim "calibrated": calibration is labeled
    ``insufficient_n`` until n is large. Every metric is printed with its n.

The harness does more than trust the judge. It re-runs the judge's own robustness
contracts (malformed JSON, hallucinated SHAs -> ``JudgeError``) AND adds a **support
check**: a well-formed, grounded verdict that claims a high score with no supporting
evidence is rejected, not scored. See :mod:`vouch.eval.mock` for the adversary.

Judge calls are cached by evidence-bundle hash (:mod:`vouch.judge.cache`), so re-running
metrics re-burns no quota.
"""
from __future__ import annotations

from pydantic import BaseModel

from vouch.config import (
    CONFIG,
    MIN_LABELS_FOR_CALIBRATION,
    MIN_LABELS_FOR_EVIDENCE,
    Config,
)
from vouch.eval.labels import (
    LabeledRepo,
    LabelSet,
    LabelValidationError,
    load_labels,
)
from vouch.eval.mock import MockJudgeProvider, MockMode
from vouch.extract import extract
from vouch.ingest import ingest, resolve_repo
from vouch.judge import JudgeError, JudgeProvider, judge
from vouch.judge.cache import JudgeCache, bundle_hash
from vouch.schemas import EvidenceBundle, Verdict

__all__ = [
    "LabeledRepo",
    "LabelSet",
    "LabelValidationError",
    "load_labels",
    "MockJudgeProvider",
    "MockMode",
    "RepoResult",
    "Metrics",
    "EvalReport",
    "EvalError",
    "check_support",
    "evaluate_one",
    "run_eval",
    "default_bundle_fn",
]


class EvalError(Exception):
    """The harness refuses to produce a result (e.g. reporting an empty holdout)."""


# Per-repo outcomes. Only ``scored`` rows feed the metrics; the rest are surfaced, not
# silently dropped — a run that judged nothing must not look like a perfect run.
OUTCOME_SCORED = "scored"
OUTCOME_JUDGE_FAILED = "judge_failed"  # malformed JSON / hallucinated SHA caught by judge
OUTCOME_UNSUPPORTED = "unsupported"  # grounded but inflated — caught by the support check
OUTCOME_NO_EVIDENCE = "no_evidence"  # no commits by the subject; nothing to judge


class RepoResult(BaseModel):
    """The outcome of evaluating one labeled repo."""

    repo: str
    author: str
    label: str
    reason: str
    outcome: str  # one of the OUTCOME_* constants
    predicted: str | None = None  # "strong"|"weak" for scored rows
    correct: bool | None = None
    score: float | None = None
    confidence: float | None = None
    judge_model: str | None = None
    from_cache: bool = False
    detail: str = ""  # failure/rejection explanation


class Metrics(BaseModel):
    """Judge-quality summary. Every field carries its n — numbers without n are dishonest."""

    n_labeled: int  # total rows in the evaluated split
    n_scored: int  # rows that produced an accepted verdict (metric denominator)
    n_judge_failed: int
    n_unsupported: int
    n_no_evidence: int

    # (a) agreement — accepted verdicts whose strong/weak prediction matched the label.
    agreement: float | None = None  # None when n_scored == 0
    n_correct: int = 0
    n_incorrect: int = 0

    # (b) confidence separation — does the judge report higher confidence when it is right?
    mean_confidence_correct: float | None = None
    mean_confidence_incorrect: float | None = None
    confidence_separation: float | None = None  # correct - incorrect; None if either empty

    # calibration is deliberately NOT computed at this n. Never claim "calibrated".
    calibration_status: str = "insufficient_n"
    calibration_threshold: int = MIN_LABELS_FOR_CALIBRATION


class EvalReport(BaseModel):
    """A full eval run: which split, the config fingerprint, per-repo results, metrics."""

    split: str  # "train" | "holdout" | "all"
    prompt_version: str
    verdict_strong_threshold: float
    total_labeled: int  # across the WHOLE corpus, for the <15 evidence gate
    metrics: Metrics
    results: list[RepoResult]
    warnings: list[str] = []
    cache_hits: int = 0
    cache_misses: int = 0


# --------------------------------------------------------------------------------------
# Acceptance: the support check the judge itself cannot perform
# --------------------------------------------------------------------------------------


def check_support(verdict: Verdict, bundle: EvidenceBundle, config: Config) -> list[str]:
    """Return reasons a verdict is unsupported by its evidence. Empty == supported.

    The judge enforces schema + grounding, but a *grounded* verdict can still be a lie:
    a near-perfect score citing nothing, or a strong score while every signal is zero.
    Those are semantic failures only the harness (which holds both the verdict and the
    bundle) can catch. A high score MUST rest on cited receipts and non-zero signals.
    """
    problems: list[str] = []
    strong = verdict.score >= config.verdict_strong_threshold
    if strong and not verdict.cited_evidence:
        problems.append(
            f"score {verdict.score} >= {config.verdict_strong_threshold} but cites no evidence"
        )
    if strong:
        any_signal = any(_signal_truthy(s.value) for s in bundle.signals)
        if not any_signal:
            problems.append(
                f"score {verdict.score} >= {config.verdict_strong_threshold} but every signal is zero/empty"
            )
    return problems


def _signal_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return bool(value)


# --------------------------------------------------------------------------------------
# The pipeline per label
# --------------------------------------------------------------------------------------


def default_bundle_fn(labeled: LabeledRepo, config: Config) -> EvidenceBundle:
    """Real pipeline: ingest + extract for one label. Requires git/network for the clone.

    Tests inject a synthetic ``bundle_fn`` instead so the harness runs fully offline.
    """
    repo_path = resolve_repo(labeled.repo)
    snapshot = ingest(labeled.repo)
    return extract(snapshot, labeled.author, repo_path=repo_path, config=config)


def evaluate_one(
    labeled: LabeledRepo,
    providers: list[JudgeProvider],
    *,
    bundle_fn=default_bundle_fn,
    cache: JudgeCache | None = None,
    config: Config | None = None,
) -> RepoResult:
    """Run the full pipeline for one label and classify the outcome.

    Never raises for a judge/support failure — those become ``RepoResult`` outcomes so a
    bad row is *reported*, not swallowed and not fatal to the whole run.
    """
    config = config or CONFIG
    cache = cache if cache is not None else JudgeCache(None)

    base = dict(
        repo=labeled.repo, author=labeled.author, label=labeled.label, reason=labeled.reason
    )

    bundle = bundle_fn(labeled, config)
    if bundle.n_commits_by_subject == 0:
        return RepoResult(**base, outcome=OUTCOME_NO_EVIDENCE, detail="no commits by subject")

    key = bundle_hash(bundle, config.prompt_version)
    cached = cache.get(key)
    from_cache = cached is not None

    if cached is not None:
        verdict, judge_model = cached
    else:
        # Bind the bundle to any mock providers so they can react to it (real providers
        # ignore this — they only see the rendered prompt).
        for p in providers:
            bind = getattr(p, "judge_for", None)
            if callable(bind):
                bind(bundle)
        try:
            verdict, judge_model = judge(bundle, providers=providers, config=config)
        except JudgeError as e:
            # malformed JSON / hallucinated SHA / all providers down — caught, not fatal.
            return RepoResult(**base, outcome=OUTCOME_JUDGE_FAILED, detail=str(e))
        cache.put(key, verdict, judge_model)

    problems = check_support(verdict, bundle, config)
    if problems:
        return RepoResult(
            **base,
            outcome=OUTCOME_UNSUPPORTED,
            score=verdict.score,
            confidence=verdict.confidence,
            judge_model=judge_model,
            from_cache=from_cache,
            detail="; ".join(problems),
        )

    predicted = "strong" if verdict.score >= config.verdict_strong_threshold else "weak"
    return RepoResult(
        **base,
        outcome=OUTCOME_SCORED,
        predicted=predicted,
        correct=(predicted == labeled.label),
        score=verdict.score,
        confidence=verdict.confidence,
        judge_model=judge_model,
        from_cache=from_cache,
    )


# --------------------------------------------------------------------------------------
# The run + metrics
# --------------------------------------------------------------------------------------


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def _compute_metrics(results: list[RepoResult]) -> Metrics:
    scored = [r for r in results if r.outcome == OUTCOME_SCORED]
    correct = [r for r in scored if r.correct]
    incorrect = [r for r in scored if r.correct is False]

    conf_correct = [r.confidence for r in correct if r.confidence is not None]
    conf_incorrect = [r.confidence for r in incorrect if r.confidence is not None]
    mc = _mean(conf_correct)
    mi = _mean(conf_incorrect)
    sep = round(mc - mi, 4) if (mc is not None and mi is not None) else None

    n_scored = len(scored)
    calib = "insufficient_n" if n_scored < MIN_LABELS_FOR_CALIBRATION else "deferred"

    return Metrics(
        n_labeled=len(results),
        n_scored=n_scored,
        n_judge_failed=sum(r.outcome == OUTCOME_JUDGE_FAILED for r in results),
        n_unsupported=sum(r.outcome == OUTCOME_UNSUPPORTED for r in results),
        n_no_evidence=sum(r.outcome == OUTCOME_NO_EVIDENCE for r in results),
        agreement=(round(len(correct) / n_scored, 4) if n_scored else None),
        n_correct=len(correct),
        n_incorrect=len(incorrect),
        mean_confidence_correct=mc,
        mean_confidence_incorrect=mi,
        confidence_separation=sep,
        calibration_status=calib,
    )


def run_eval(
    labels: LabelSet,
    providers: list[JudgeProvider],
    *,
    split: str = "holdout",
    bundle_fn=default_bundle_fn,
    cache: JudgeCache | None = None,
    config: Config | None = None,
) -> EvalReport:
    """Evaluate a split of the labeled set and score the judge.

    ``split`` selects the pool: ``"train"`` (iterate here), ``"holdout"`` (report here), or
    ``"all"``. Refuses (``EvalError``) to report an empty holdout — there is nothing to
    report, and a silent 0/0 would masquerade as a result. Emits a loud warning when the
    total labeled corpus is below the evidence threshold.
    """
    config = config or CONFIG
    cache = cache if cache is not None else JudgeCache(None)

    if split == "holdout":
        rows = labels.holdout
    elif split == "train":
        rows = labels.train
    elif split == "all":
        rows = labels.all_rows()
    else:
        raise EvalError(f"unknown split {split!r}; use 'train', 'holdout', or 'all'")

    if split == "holdout" and not rows:
        raise EvalError(
            "refusing to report holdout metrics: the holdout is empty. "
            "Populate eval/labels.yaml's 'holdout:' pool before reporting final numbers."
        )
    if not rows:
        raise EvalError(f"the '{split}' split is empty; nothing to evaluate")

    results = [
        evaluate_one(r, providers, bundle_fn=bundle_fn, cache=cache, config=config)
        for r in rows
    ]
    metrics = _compute_metrics(results)

    warnings: list[str] = []
    if labels.total < MIN_LABELS_FOR_EVIDENCE:
        warnings.append(
            f"only {labels.total} labeled repos total (< {MIN_LABELS_FOR_EVIDENCE}): "
            "these numbers are DIRECTIONAL, not evidence."
        )
    if metrics.n_scored == 0:
        warnings.append("no repos produced an accepted verdict — every metric below is empty.")
    if metrics.n_judge_failed:
        warnings.append(f"{metrics.n_judge_failed} repo(s) failed the judge's own contracts.")
    if metrics.n_unsupported:
        warnings.append(
            f"{metrics.n_unsupported} repo(s) returned inflated/unsupported verdicts (rejected)."
        )

    return EvalReport(
        split=split,
        prompt_version=config.prompt_version,
        verdict_strong_threshold=config.verdict_strong_threshold,
        total_labeled=labels.total,
        metrics=metrics,
        results=results,
        warnings=warnings,
        cache_hits=cache.hits,
        cache_misses=cache.misses,
    )
