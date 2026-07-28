"""L4 orchestration — run the two stages, then check the model's homework.

Three guarantees are enforced here, outside the model, because a model cannot be trusted to
enforce them about itself:

* **Grounding.** Every claim's locators must resolve against what the model was shown,
  SHA *and* path. One bounded retry with the specific problems fed back, then the offending
  claims are dropped rather than published.
* **Support.** A conclusive verdict must rest on something. The check can only ever
  *downgrade* — it is a brake, never an accelerator — so a bug here can make the profile
  more cautious but never more flattering.
* **Availability.** A dimension whose input layer was absent is `not_collected` before the
  model is consulted at all, and the model is not given the chance to invent a reading of
  data that does not exist.

Every downgrade is recorded on the result. A silent correction would hide exactly the
calibration problem the eval harness exists to measure.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vouch.l1.facts import RepoFacts
from vouch.l2.payload import SessionMetrics
from vouch.l3.join import CorroborationReport
from vouch.l4.diffs import DEFAULT_BUDGET, CommitDiff, DiffBudget, extract_diff
from vouch.l4.dimensions import DIMENSIONS, EvidenceAvailability, assess_availability
from vouch.l4.grounding import Allowlist, build_allowlist, check_claims
from vouch.l4.prompt import (
    PROMPT_VERSION,
    commit_system,
    commit_user,
    dimension_system,
    dimension_user,
)
from vouch.l4.providers import JudgeProvider, ProviderError
from vouch.l4.sampling import DEFAULT_POLICY, Sample, SamplingPolicy, select_commits
from vouch.l4.schema import (
    CONCLUSIVE_VERDICTS,
    CommitJudgment,
    Confidence,
    DimensionFinding,
    JudgeResult,
    Verdict,
)
from vouch.schemas import CommitRecord

__all__ = ["JudgeError", "MAX_GROUNDING_RETRIES", "judge_profile", "apply_support_check"]

#: One bounded retry, as in the v0 prototype. A model that cites a phantom commit twice is
#: not going to get it right on the third attempt.
MAX_GROUNDING_RETRIES = 1


class JudgeError(Exception):
    """Unrecoverable: the provider is unavailable, or retries were exhausted."""


@dataclass
class _Stage2Input:
    availability: EvidenceAvailability
    judgments: list[CommitJudgment]


def _judge_commits(
    provider: JudgeProvider,
    repo_path: Path,
    sample: Sample,
    budget: DiffBudget,
) -> tuple[list[CommitJudgment], list[CommitDiff]]:
    """Stage one: read each sampled diff.

    A provider failure on one commit is not fatal to the profile — that commit simply has
    no diff verdict, and the dimensions that would have used it see a smaller n. Losing one
    reading is a coverage gap; aborting the whole profile over it is a worse outcome.
    """
    judgments: list[CommitJudgment] = []
    diffs: list[CommitDiff] = []

    for commit in sample.commits:
        diff = extract_diff(repo_path, commit, budget)
        diffs.append(diff)
        try:
            judgment = provider.complete(
                commit_system(), commit_user(diff), CommitJudgment
            )
        except ProviderError:
            continue
        judgments.append(judgment.model_copy(update={"sha": commit.sha}))

    return judgments, diffs


def _relevant_judgments(
    judgments: list[CommitJudgment], availability: EvidenceAvailability
) -> list[CommitJudgment]:
    return judgments if availability.spec.uses_commit_judgments else []


def _judge_dimension(
    provider: JudgeProvider,
    stage2: _Stage2Input,
    facts: RepoFacts,
    metrics: SessionMetrics | None,
    corroboration: CorroborationReport | None,
    allowlist: Allowlist,
) -> tuple[DimensionFinding, list[str]]:
    """Stage two: one dimension's readout, with grounding enforced after the fact."""
    system = dimension_system()
    user = dimension_user(
        stage2.availability, facts, metrics, corroboration, stage2.judgments
    )

    notes: list[str] = []
    budget = MAX_GROUNDING_RETRIES
    prompt = user

    while True:
        try:
            finding = provider.complete(system, prompt, DimensionFinding)
        except ProviderError as e:
            raise JudgeError(f"provider failed on {stage2.availability.spec.key}: {e}") from e

        finding = finding.model_copy(update={"dimension": stage2.availability.spec.key})
        problems = check_claims(finding.claims, allowlist)
        if not problems:
            return finding, notes

        if budget > 0:
            budget -= 1
            prompt = (
                f"{user}\n\nYour previous answer had ungrounded claims:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\nCite only commits and paths that appear in the evidence above."
            )
            continue

        # Retry exhausted: drop the unsourced claims rather than publish them, and record
        # that we did. A claim that cannot be checked is worth less than no claim.
        grounded = [
            claim
            for claim in finding.claims
            if not check_claims([claim], allowlist)
        ]
        notes.append(
            f"{stage2.availability.spec.key.value}: dropped "
            f"{len(finding.claims) - len(grounded)} ungrounded claim(s) after retry"
        )
        return finding.model_copy(update={"claims": grounded}), notes


def apply_support_check(
    finding: DimensionFinding, availability: EvidenceAvailability
) -> tuple[DimensionFinding, str | None]:
    """Downgrade a verdict the evidence does not carry. Never upgrades.

    Four ways a conclusive verdict fails to stand:

    * the input layer was absent — `not_collected`;
    * the only input was measured at the wrong scope — `out_of_scope`;
    * nothing measurable survived suppression — `insufficient_evidence`;
    * the model asserted something but sourced none of it — `insufficient_evidence`.
    """
    spec = availability.spec

    if availability.forces_out_of_scope:
        if finding.verdict is Verdict.OUT_OF_SCOPE:
            return finding, None
        return (
            finding.model_copy(
                update={
                    "verdict": Verdict.OUT_OF_SCOPE,
                    "confidence": Confidence.LOW,
                    "limitations": [
                        *finding.limitations,
                        "The session telemetry available covers this machine rather than "
                        "this repository, so it cannot speak to work done here.",
                    ],
                }
            ),
            f"{spec.key.value}: {finding.verdict.value} -> out_of_scope "
            f"(evidence measured at {spec.scope.value} scope was unavailable)",
        )

    if not availability.was_looked_at:
        if finding.verdict is Verdict.NOT_COLLECTED:
            return finding, None
        return (
            finding.model_copy(
                update={
                    "verdict": Verdict.NOT_COLLECTED,
                    "confidence": Confidence.LOW,
                    "limitations": [
                        *finding.limitations,
                        "The session telemetry this dimension depends on was not collected.",
                    ],
                }
            ),
            f"{spec.key.value}: {finding.verdict.value} -> not_collected (input layer absent)",
        )

    if finding.verdict not in CONCLUSIVE_VERDICTS:
        return finding, None

    if not availability.has_any:
        return (
            finding.model_copy(
                update={
                    "verdict": Verdict.INSUFFICIENT_EVIDENCE,
                    "confidence": Confidence.LOW,
                }
            ),
            f"{spec.key.value}: {finding.verdict.value} -> insufficient_evidence "
            "(every supporting measurement was suppressed or unmeasurable)",
        )

    if not finding.claims:
        return (
            finding.model_copy(
                update={
                    "verdict": Verdict.INSUFFICIENT_EVIDENCE,
                    "confidence": Confidence.LOW,
                }
            ),
            f"{spec.key.value}: {finding.verdict.value} -> insufficient_evidence "
            "(conclusive verdict with no sourced claim)",
        )

    return finding, None


def judge_profile(
    provider: JudgeProvider,
    facts: RepoFacts,
    repo_path: Path,
    commits: list[CommitRecord],
    metrics: SessionMetrics | None = None,
    corroboration: CorroborationReport | None = None,
    policy: SamplingPolicy | None = None,
    budget: DiffBudget | None = None,
) -> JudgeResult:
    """Run L4 end to end: sample, read diffs, synthesise dimensions, check the result."""
    if not provider.is_available():
        raise JudgeError(
            f"judge provider {provider.name!r} is unavailable "
            "(set ANTHROPIC_API_KEY or run `ant auth login`)"
        )

    policy = policy or DEFAULT_POLICY
    budget = budget or DEFAULT_BUDGET

    sample = select_commits(commits, facts, policy)
    judgments, diffs = _judge_commits(provider, repo_path, sample, budget)
    allowlist = build_allowlist(facts, diffs)

    findings: list[DimensionFinding] = []
    downgrades: list[str] = []

    for spec in DIMENSIONS:
        availability = assess_availability(spec, facts, metrics, len(judgments))

        if availability.forces_out_of_scope:
            findings.append(
                DimensionFinding(
                    dimension=spec.key,
                    verdict=Verdict.OUT_OF_SCOPE,
                    confidence=Confidence.LOW,
                    summary=(
                        "Not assessable: the session telemetry supplied was measured "
                        "across this machine, not this repository, so it cannot support "
                        "a claim about work done here."
                    ),
                    limitations=[
                        "Re-run the local session CLI scoped to this repository to make "
                        "this dimension assessable."
                    ],
                )
            )
            continue

        if not availability.was_looked_at:
            findings.append(
                DimensionFinding(
                    dimension=spec.key,
                    verdict=Verdict.NOT_COLLECTED,
                    confidence=Confidence.LOW,
                    summary=(
                        "Not assessed: this dimension is read from local session "
                        "telemetry, which was not collected for this profile."
                    ),
                    limitations=[
                        "Run the local session CLI to make this dimension assessable."
                    ],
                )
            )
            continue

        finding, notes = _judge_dimension(
            provider,
            _Stage2Input(availability, _relevant_judgments(judgments, availability)),
            facts,
            metrics,
            corroboration,
            allowlist,
        )
        downgrades.extend(notes)

        finding, downgrade = apply_support_check(finding, availability)
        if downgrade:
            downgrades.append(downgrade)
        findings.append(finding)

    return JudgeResult(
        judge_model=f"{provider.name}:{provider.model}",
        prompt_version=PROMPT_VERSION,
        n_commits_sampled=sample.n_sampled,
        n_commits_total=sample.n_total,
        commit_judgments=judgments,
        findings=findings,
        downgrades=downgrades,
    )
