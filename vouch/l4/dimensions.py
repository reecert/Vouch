"""The four dimensions and the evidence each one is allowed to rest on.

Deliberately narrower than the
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
from vouch.l2.payload import MetricKey, MetricScope, SessionMetrics
from vouch.l4.schema import DimensionKey

__all__ = ["DimensionSpec", "DIMENSIONS", "EvidenceAvailability", "assess_availability"]


@dataclass(frozen=True)
class DimensionSpec:
    """One dimension, and the evidence it is allowed to rest on — including at what scope.

    ``scope`` is the contract. Every dimension in this product is a claim about one person
    in **one repository**: the profile names that repo, states its commit window, and lists
    what was excluded from it. A metric computed over a different population is not weaker
    evidence for such a claim, it is evidence for a different claim, and
    :func:`assess_availability` refuses it rather than discounting it.

    This is not hypothetical. `plan_before_execute` was read straight from a machine-wide
    L2 payload — every project in `~/.claude/projects`, most of them nothing to do with the
    repo under the heading — and published under `planning_discipline` as if it described
    work on that repo.
    """

    key: DimensionKey
    title: str
    question: str  # what the dimension actually asks, in one line
    scope: MetricScope
    l1_facts: tuple[str, ...]
    l2_metrics: tuple[MetricKey, ...]
    uses_commit_judgments: bool


DIMENSIONS: tuple[DimensionSpec, ...] = (
    DimensionSpec(
        key=DimensionKey.VERIFICATION_DISCIPLINE,
        scope=MetricScope.REPO,
        title="Verification discipline",
        question="Does this engineer check their work, in the commit trail and while working?",
        l1_facts=("test_accompanies_fix",),
        l2_metrics=(MetricKey.TEST_OR_BUILD_AFTER_EDIT,),
        uses_commit_judgments=True,
    ),
    DimensionSpec(
        key=DimensionKey.OWNERSHIP,
        scope=MetricScope.REPO,
        title="Ownership",
        question="Do they return to fix their own defects, with tests, over time?",
        l1_facts=("ownership_loop", "followup_latency", "revert_rate"),
        l2_metrics=(),
        uses_commit_judgments=True,
    ),
    DimensionSpec(
        key=DimensionKey.SCOPE_CONTROL,
        scope=MetricScope.REPO,
        title="Scope control",
        question="Do changes stay inside what they claim to be?",
        l1_facts=("commit_scoping",),
        l2_metrics=(MetricKey.EDIT_REVISION,),
        uses_commit_judgments=True,
    ),
    DimensionSpec(
        key=DimensionKey.PLANNING_DISCIPLINE,
        scope=MetricScope.REPO,
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
    #: Session telemetry was supplied, but computed over a population this dimension may
    #: not read from. Distinct from ``not l2_present``: we have data and are declining it.
    l2_out_of_scope: bool = False
    #: Telemetry was correctly scoped, and scoping is what removed the evidence — sessions
    #: existed on this machine but not in this repo.
    l2_narrowed_by_scope: bool = False

    @property
    def has_any(self) -> bool:
        return bool(self.measured_facts or self.usable_metrics or self.n_commit_judgments)

    @property
    def was_looked_at(self) -> bool:
        """False means the input layer was absent — `not_assessed`, not `insufficient`."""
        if self.spec.l1_facts or self.spec.uses_commit_judgments:
            return True
        return self.l2_present

    @property
    def is_not_assessable(self) -> bool:
        """True when scoping, not scarcity, is what leaves this dimension with nothing.

        The honest verdict here is `not_assessable`, not `insufficient_evidence`, and the
        difference is what it tells the reader to do. `insufficient_evidence` says there
        was little to read. `not_assessable` says the question cannot be answered from what
        exists: either the telemetry describes the wrong population, or it described the
        right one and this repo simply is not where this person's sessions happened. More
        data of the same kind would not move either.

        A dimension with no telemetry at all is *not* covered here — that is ordinary
        scarcity, and `insufficient_evidence` remains the right answer for it.
        """
        return (self.l2_out_of_scope or self.l2_narrowed_by_scope) and not self.has_any


def assess_availability(
    spec: DimensionSpec,
    facts: RepoFacts,
    metrics: SessionMetrics | None,
    n_commit_judgments: int,
) -> EvidenceAvailability:
    """Decide what this dimension can be judged on. Deterministic; runs before the model.

    Scope is checked before anything else about the metrics: a rate computed over the wrong
    population is discarded whole, not discounted, and no amount of denominator rescues it.
    """
    measured = tuple(
        key
        for key in spec.l1_facts
        if (fact := facts.fact(key)) is not None and fact.status is FactStatus.MEASURED
    )

    usable: tuple[MetricKey, ...] = ()
    l2_present = metrics is not None and not metrics.degraded
    out_of_scope = bool(
        l2_present and metrics is not None and metrics.scope is not spec.scope
    )
    if l2_present and metrics is not None and not out_of_scope:
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
        l2_out_of_scope=out_of_scope and bool(spec.l2_metrics),
        l2_narrowed_by_scope=bool(
            spec.l2_metrics
            and not out_of_scope
            and metrics is not None
            and metrics.n_sessions_out_of_scope > 0
        ),
    )
