"""L4 prompts, versioned. Two stages, and only the first one sees source code.

Stage 1 reads one diff and answers the three questions metadata cannot: was this a real fix
or cosmetic, does the added test exercise the failure, did scope creep.

Stage 2 never sees a diff. It receives the deterministic facts, the session metrics, the
corroboration counts and stage 1's verdicts, and produces one dimension's readout. Keeping
diffs out of stage 2 means a dimension summary cannot quietly rest on something the
grounding validator has no locator for.

The prompts do **not** ask for `insufficient_evidence` as a favour — the response schema
makes it one of a closed set of values. What the prompts do is describe when it is the
*right* answer, because a model that never uses it is as miscalibrated as one that always
does.
"""
from __future__ import annotations

from vouch.l1.facts import FactStatus, RepoFacts
from vouch.l2.payload import SessionMetrics
from vouch.l3.join import CorroborationReport
from vouch.l4.diffs import CommitDiff
from vouch.l4.dimensions import EvidenceAvailability
from vouch.l4.schema import CommitJudgment

__all__ = ["PROMPT_VERSION", "commit_system", "commit_user", "dimension_system",
           "dimension_user"]

PROMPT_VERSION = "l4-diff/1"


def commit_system() -> str:
    return """\
You assess one commit by reading its diff. You answer three questions and nothing else.

1. fix_nature — is this a real defect fix, a cosmetic change, or not a fix at all?
   The commit was selected because its subject line matched a fix keyword. That is a
   proxy and it misfires: "fix formatting" and "fix typo in comment" are not defect
   fixes. Judge the diff, not the message.

2. test_relevance — if a test was added or changed, does it exercise the failure this
   commit repairs? A test that ships alongside a fix but does not touch the repaired
   path is `unrelated_test`. Every metadata-level tool counts that as tested; you are
   here because you can tell the difference.

3. scope — did the change stay inside what its message claims? Unrelated refactoring,
   drive-by renames, or a second feature riding along are creep.

Rules:
- Judge only what is visible. Diffs may be truncated or have files omitted; when the
  visible portion does not support a call, answer insufficient_evidence. That is a
  correct answer, not a failure to answer.
- Do not infer intent from the commit message. The diff is the evidence.
- `note` is one factual sentence about what the diff did. No praise, no speculation."""


def commit_user(diff: CommitDiff) -> str:
    return f"Assess this commit.\n\n{diff.render()}"


def _render_facts(facts: RepoFacts, keys: tuple[str, ...]) -> str:
    if not keys:
        return "  (this dimension has no commit-trail facts)"
    lines = []
    for key in keys:
        fact = facts.fact(key)
        if fact is None:
            continue
        if fact.status is FactStatus.MEASURED:
            lines.append(
                f"  {key}: {fact.value} {fact.unit.value} "
                f"({fact.numerator}/{fact.denominator})"
            )
        else:
            lines.append(f"  {key}: {fact.status.value} — {fact.note}")
    return "\n".join(lines) or "  (none)"


def _render_metrics(metrics: SessionMetrics | None, availability: EvidenceAvailability) -> str:
    if metrics is None or metrics.degraded:
        return (
            "  (the local session CLI was not run, or its logs could not be read, so no\n"
            "   session evidence exists for this profile)"
        )
    lines = []
    for key in availability.spec.l2_metrics:
        rate = metrics.rates.get(key)
        if rate is None:
            continue
        if rate.suppressed:
            lines.append(
                f"  {key.value}: suppressed — {rate.denominator} observation(s), "
                f"below the floor of {rate.floor}"
            )
        else:
            lines.append(
                f"  {key.value}: {rate.value} ({rate.numerator}/{rate.denominator})"
            )
    return "\n".join(lines) or "  (none)"


def _render_confounds(facts: RepoFacts, keys: tuple[str, ...]) -> str:
    relevant = [c for c in facts.confounds if set(c.affects) & set(keys)]
    if not relevant:
        return "  (none affecting this dimension)"
    return "\n".join(
        f"  [{c.severity.value}] {c.key.value} ({c.direction.value}): {c.detail}"
        for c in relevant
    )


def _render_judgments(judgments: list[CommitJudgment]) -> str:
    if not judgments:
        return "  (no diffs were read for this dimension)"
    return "\n".join(
        f"  {j.sha[:8]}: fix={j.fix_nature.value} test={j.test_relevance.value} "
        f"scope={j.scope.value} — {j.note}"
        for j in judgments
    )


def dimension_system() -> str:
    return """\
You write one dimension of an engineering capability profile. The reader is a hiring
manager deciding what to ask in an interview, not whether to hire.

You are given deterministic measurements, session metrics, corroboration counts, and
per-commit diff verdicts produced earlier. You have NOT seen the diffs yourself.

Verdicts:
- strong / moderate / limited — the evidence supports a reading of this behaviour.
- insufficient_evidence — you looked and there is not enough to say. Use this freely.
  Thin evidence must stay insufficient rather than become a flattering conclusion.
- not_assessed — the input this dimension needs was absent entirely.
- contradicted — the evidence points against the behaviour.

Rules that are checked mechanically after you answer:
- Every claim must carry at least one locator (a commit SHA, optionally with a file path)
  drawn from the evidence below. A claim you cannot source will be rejected.
- A locator's path must be a file that commit actually touched.
- A strong or moderate verdict with no claims will be downgraded automatically.

Confounds are listed where they apply. If a confound undermines the reading, say so in
`limitations` and lower the verdict accordingly — do not report a number that a stated
confound invalidates.

`risks_to_probe` is the most useful thing you produce: what should the interviewer ask
to close the gap this evidence leaves? Be specific to what is missing here.

`summary` is one sentence. No score, no grade, no comparison to other engineers."""


def dimension_user(
    availability: EvidenceAvailability,
    facts: RepoFacts,
    metrics: SessionMetrics | None,
    corroboration: CorroborationReport | None,
    judgments: list[CommitJudgment],
) -> str:
    spec = availability.spec
    corr = (
        f"  {corroboration.n_corroborated} of {corroboration.n_commits} commits have "
        f"session evidence behind them ({corroboration.n_ambiguous} ambiguous). "
        "Uncorroborated means no session evidence exists, not that the work was "
        "unsupervised."
        if corroboration is not None
        else "  (no session correlation was run)"
    )

    return f"""\
DIMENSION: {spec.title}
QUESTION: {spec.question}

COMMIT-TRAIL FACTS (deterministic, computed from git):
{_render_facts(facts, spec.l1_facts)}

SESSION METRICS (derived on the engineer's machine):
{_render_metrics(metrics, availability)}

CORROBORATION:
{corr}

PER-COMMIT DIFF VERDICTS (from reading the actual diffs):
{_render_judgments(judgments)}

CONFOUNDS AFFECTING THIS DIMENSION:
{_render_confounds(facts, spec.l1_facts)}

SUBJECT ACTIVITY: {facts.n_commits_by_subject} commits between \
{facts.window_first} and {facts.window_last}.

Produce the readout for this dimension."""
