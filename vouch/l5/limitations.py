"""Limitations and risks-to-probe — derived, not written.

The competitor's public surface carries a standing Limitations section, which is the right
habit. What this module adds is that most of ours are **computed**: they fall out of the
confounds L1 detected, the commits L4 did not read, and the layers that were absent. A
limitation a model was asked to volunteer is one it can forget to mention; a limitation
derived from the evidence cannot go missing on a bad day.

The model still contributes — each dimension supplies its own limitations and interview
questions from what it saw. Those are merged with these, and these come first.

For the reader (a hiring screener, per docs/plan.md), *Risks to probe* is the most
actionable thing in the profile: it converts what the evidence cannot show into a question
worth asking. Every dimension that declined to conclude therefore produces one, because a
gap the reader does not know to ask about is a gap the profile has hidden.
"""
from __future__ import annotations

from vouch.l1.facts import FactStatus, RepoFacts, Severity
from vouch.l2.payload import SessionMetrics
from vouch.l3.join import CorroborationReport
from vouch.l4.dimensions import DIMENSIONS
from vouch.l4.schema import JudgeResult, Verdict

__all__ = ["derive_limitations", "derive_risks"]

#: Stated on every profile regardless of inputs — the boundary of the whole method.
STANDING_LIMITATIONS = (
    "This profile reads a git history and, with consent, local session telemetry. "
    "No private production logs, employer references, code review discussion, or "
    "live pair-programming evidence were used.",
    "It describes observable behaviour in the evidence provided. It does not predict "
    "performance, and it is not a hiring decision.",
)


def derive_limitations(
    facts: RepoFacts,
    judgment: JudgeResult | None,
    metrics: SessionMetrics | None,
    corroboration: CorroborationReport | None,
) -> list[str]:
    """Everything this profile cannot see, in the order a reader needs it."""
    out: list[str] = list(STANDING_LIMITATIONS)

    out.append(
        f"Based on a single repository ({facts.repo}) and the "
        f"{facts.n_commits_by_subject} commits authored there by this person."
    )

    if judgment is not None and judgment.n_commits_sampled < judgment.n_commits_total:
        out.append(
            f"Diffs were read for {judgment.n_commits_sampled} of "
            f"{judgment.n_commits_total} commits: every commit backing a measured fact, "
            "plus a reproducible sample of the remainder seeded on the repository head."
        )

    order = {Severity.INVALIDATING: 0, Severity.WARN: 1, Severity.INFO: 2}
    for confound in sorted(facts.confounds, key=lambda c: order[c.severity]):
        if confound.severity is Severity.INFO:
            continue
        out.append(f"{confound.detail}")

    suppressed = [f for f in facts.facts if f.status is FactStatus.SUPPRESSED_LOW_N]
    if suppressed:
        names = ", ".join(sorted(f.key for f in suppressed))
        out.append(
            f"{len(suppressed)} measurement(s) were withheld for want of a large enough "
            f"denominator ({names}). A rate that thin is not reported rather than rounded."
        )

    if metrics is None:
        out.append(
            "No session telemetry was collected, so nothing here reflects how this "
            "person works while writing the code — only what the commit trail shows."
        )
    elif metrics.degraded:
        out.append(
            "Session telemetry could not be read (the local log format was not "
            "recognised), so this profile fell back to git evidence only."
        )
    elif metrics.n_records_unparsed:
        out.append(
            f"{metrics.n_records_unparsed} of {metrics.n_records} session log records "
            "could not be parsed and were excluded from the rates above."
        )

    # A count, never an accuracy claim (docs/plan.md q9).
    if corroboration is None:
        out.append(
            "Commits were not correlated with session activity, so no claim here is "
            "corroborated by a second source."
        )
    elif corroboration.n_commits:
        out.append(
            f"{corroboration.n_corroborated} of {corroboration.n_commits} commits have "
            "session evidence behind them. Uncorroborated means no session was recorded "
            "for that work — not that the work was unsupervised."
        )

    return out


def derive_risks(judgment: JudgeResult | None) -> list[str]:
    """Questions worth asking, led by what the evidence could not settle.

    A dimension that declined to conclude is not a dead end for the reader — it is the
    most useful thing in the profile, provided it is turned into a question.
    """
    if judgment is None:
        return [
            "No diff-level judgment was run for this profile. Ask the candidate to walk "
            "through a defect they fixed in their own code, and what the test proved."
        ]

    titles = {spec.key: spec.title for spec in DIMENSIONS}
    out: list[str] = []

    for finding in judgment.findings:
        title = titles.get(finding.dimension, finding.dimension.value)
        if finding.verdict is Verdict.NOT_COLLECTED:
            out.append(
                f"{title} could not be assessed from this evidence. Ask about it "
                "directly rather than reading anything into its absence."
            )
        elif finding.verdict is Verdict.INSUFFICIENT_EVIDENCE:
            out.append(
                f"{title} had too little evidence to call either way. Probe it in "
                "interview before treating the rest of this profile as complete."
            )
        elif finding.verdict is Verdict.CONTRADICTED:
            out.append(
                f"{title}: the evidence points against this behaviour. Worth "
                "understanding the context before drawing a conclusion."
            )

    for finding in judgment.findings:
        out.extend(finding.risks_to_probe)

    # Order-preserving dedupe, so the derived risks stay ahead of the model's own.
    seen: set[str] = set()
    unique: list[str] = []
    for risk in out:
        if risk not in seen:
            seen.add(risk)
            unique.append(risk)
    return unique
