"""The four dimensions and the evidence each one is allowed to rest on.

Confirmed 2026-07-26 (docs/plan.md open question 2). Deliberately narrower than the
competitor's nine: every dimension here maps to facts we actually compute, so every claim
can point at a denominator.

`VERIFICATION_DISCIPLINE` is the one that spans both layers — the same behaviour observed
in the commit trail (`test_accompanies_fix`) and in the session trail
(`test_or_build_after_edit`). It is where corroboration is visible to a reader, so it leads
the report.

`PLANNING_DISCIPLINE` rests on L2 alone. When the CLI was not run it is `not_assessed`,
not `insufficient_evidence` — we did not look, rather than looked and found little. That
distinction is stated per dimension rather than in one global disclaimer.
"""
from __future__ import annotations

from dataclasses import dataclass

from vouch.l1.facts import FactStatus, RepoFacts
from vouch.l2.payload import MetricKey, SessionMetrics
from vouch.l4.schema import DimensionKey

__all__ = ["DimensionSpec", "DIMENSIONS", "EvidenceAvailability", "assess_availability"]


@dataclass(frozen=True)
class DimensionSpec:
    key: DimensionKey
    title: str
    question: str  # what the dimension actually asks, in one line
    l1_facts: tuple[str, ...]
    l2_metrics: tuple[MetricKey, ...]
    uses_commit_judgments: bool


DIMENSIONS: tuple[DimensionSpec, ...] = (
    DimensionSpec(
        key=DimensionKey.VERIFICATION_DISCIPLINE,
        title="Verification discipline",
        question="Does this engineer check their work, in the commit trail and while working?",
        l1_facts=("test_accompanies_fix",),
        l2_metrics=(MetricKey.TEST_OR_BUILD_AFTER_EDIT,),
        uses_commit_judgments=True,
    ),
    DimensionSpec(
        key=DimensionKey.OWNERSHIP,
        title="Ownership",
        question="Do they return to fix their own defects, with tests, over time?",
        l1_facts=("ownership_loop", "followup_latency", "revert_rate"),
        l2_metrics=(),
        uses_commit_judgments=True,
    ),
    DimensionSpec(
        key=DimensionKey.SCOPE_CONTROL,
        title="Scope control",
        question="Do changes stay inside what they claim to be?",
        l1_facts=("commit_scoping",),
        l2_metrics=(MetricKey.EDIT_REVISION,),
        uses_commit_judgments=True,
    ),
    DimensionSpec(
        key=DimensionKey.PLANNING_DISCIPLINE,
        title="Planning discipline",
        question="Do they plan before executing?",
        l1_facts=(),
        l2_metrics=(MetricKey.PLAN_BEFORE_EXECUTE,),
        uses_commit_judgments=False,
    ),
)


@dataclass(frozen=True)
class EvidenceAvailability:
    """What is actually available for one dimension, before any model sees it."""

    spec: DimensionSpec
    measured_facts: tuple[str, ...]
    usable_metrics: tuple[MetricKey, ...]
    n_commit_judgments: int
    l2_present: bool

    @property
    def has_any(self) -> bool:
        return bool(self.measured_facts or self.usable_metrics or self.n_commit_judgments)

    @property
    def was_looked_at(self) -> bool:
        """False means the input layer was absent — `not_assessed`, not `insufficient`."""
        if self.spec.l1_facts or self.spec.uses_commit_judgments:
            return True
        return self.l2_present


def assess_availability(
    spec: DimensionSpec,
    facts: RepoFacts,
    metrics: SessionMetrics | None,
    n_commit_judgments: int,
) -> EvidenceAvailability:
    """Decide what this dimension can be judged on. Deterministic; runs before the model."""
    measured = tuple(
        key
        for key in spec.l1_facts
        if (fact := facts.fact(key)) is not None and fact.status is FactStatus.MEASURED
    )

    usable: tuple[MetricKey, ...] = ()
    l2_present = metrics is not None and not metrics.degraded
    if l2_present and metrics is not None:
        usable = tuple(
            key
            for key in spec.l2_metrics
            if (rate := metrics.rates.get(key)) is not None and not rate.suppressed
        )

    return EvidenceAvailability(
        spec=spec,
        measured_facts=measured,
        usable_metrics=usable,
        n_commit_judgments=n_commit_judgments if spec.uses_commit_judgments else 0,
        l2_present=l2_present,
    )
