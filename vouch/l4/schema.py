"""L4 schema — what the model is allowed to say.

The brief's hard constraint: the judge must return `insufficient_evidence` when evidence is
thin, *"as an enum in the schema, not a prompt suggestion"*. That is what this module is
for. Every model output is constrained by a strict JSON schema derived from these types, so
`insufficient_evidence` is not a behaviour we ask for and hope to get — it is one of a
closed set of values the response can physically take, and a flattering conclusion outside
that set is unrepresentable rather than merely discouraged.

Two further shapes carry weight:

* **`Confidence` is a band, never a float.** A model asked for 0.0-1.0 will produce 0.82
  and mean nothing by it. Three bands are honest about the resolution actually available.
* **`Verdict` separates four different kinds of "no".** `insufficient_evidence` (we looked,
  there wasn't enough), `not_collected` (we didn't look — the input layer was absent),
  `out_of_scope` (we looked, and what exists describes a different population) and
  `contradicted` (we looked, and the evidence points the other way) are distinct facts about
  a candidate. Collapsing them, as a single "unknown" would, loses the one a reader most
  needs.
* **No two of those values look alike.** `not_assessed` and `not_assessable` were the
  earlier spellings of the first two, and they are near-homographs: one letter apart,
  identical for the first twelve characters, on a menu a human types by hand. A misread
  there does not produce a wrong number, it produces ground truth that says the opposite of
  what the labeller meant — "we never looked" recorded as "we looked and the data was
  unusable". The names now differ in their first syllable and describe what happened rather
  than negating a shared root.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "L4_SCHEMA_VERSION",
    "DimensionKey",
    "Verdict",
    "Confidence",
    "FixNature",
    "TestRelevance",
    "ScopeDiscipline",
    "Locator",
    "Claim",
    "CommitJudgment",
    "DimensionFinding",
    "JudgeResult",
    "CONCLUSIVE_VERDICTS",
]

#: Bumped to 2 when `not_assessed`/`not_assessable` became `not_collected`/`out_of_scope`.
#: The constrained output schema changed, so a stored result carrying the old spellings is
#: not readable as this one and says so rather than half-parsing.
L4_SCHEMA_VERSION = "l4/2"


class DimensionKey(StrEnum):
    """The four dimensions, each backed by facts we actually compute."""

    OWNERSHIP = "ownership"
    VERIFICATION_DISCIPLINE = "verification_discipline"
    PLANNING_DISCIPLINE = "planning_discipline"
    SCOPE_CONTROL = "scope_control"


class Verdict(StrEnum):
    """A dimension's outcome. Four of these seven are ways of declining to conclude."""

    STRONG = "strong"
    MODERATE = "moderate"
    LIMITED = "limited"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # looked; not enough to say
    NOT_COLLECTED = "not_collected"  # did not look; the input was never gathered
    # Looked, and the evidence that exists is not valid at the scope this dimension claims
    # — session telemetry from other projects cannot describe work in this repository.
    # Distinct from `insufficient_evidence` because the remedy is different: more data of
    # the same kind would not help, only data of the right kind would.
    OUT_OF_SCOPE = "out_of_scope"
    CONTRADICTED = "contradicted"  # looked; the evidence points the other way


#: Verdicts that assert something positive about the candidate. Only these are subject to
#: the support check, and only these can be downgraded by it.
CONCLUSIVE_VERDICTS = frozenset({Verdict.STRONG, Verdict.MODERATE})


class Confidence(StrEnum):
    """Banded on purpose. A model asked for a float will invent precision it does not have."""

    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class FixNature(StrEnum):
    """Was this a real fix or cosmetic? Only answerable by reading the diff."""

    REAL_FIX = "real_fix"
    COSMETIC = "cosmetic"
    NOT_A_FIX = "not_a_fix"  # the keyword proxy misfired; this commit fixes nothing
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class TestRelevance(StrEnum):
    """Does the added test exercise the failure it claims to?

    ``UNRELATED_TEST`` is the interesting value: a commit that ships a test which does not
    touch the repaired path counts as tested by every metadata-level tool, and does not
    count here.
    """

    EXERCISES_FAILURE = "exercises_failure"
    UNRELATED_TEST = "unrelated_test"
    NO_TEST = "no_test"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ScopeDiscipline(StrEnum):
    """Did the change stay inside what its message claims?"""

    FOCUSED = "focused"
    MINOR_CREEP = "minor_creep"
    SIGNIFICANT_CREEP = "significant_creep"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Locator(BaseModel):
    """Where a claim points. Validated against L1's allowlist before it is believed."""

    model_config = ConfigDict(extra="forbid")

    sha: str = Field(description="Full or abbreviated commit SHA, taken from the input.")
    path: str | None = Field(
        default=None, description="Repo-relative file path touched by that commit."
    )


class Claim(BaseModel):
    """One assertion with its receipt. A claim without a locator cannot be checked."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="One sentence, specific to this evidence.")
    locators: list[Locator] = Field(
        default_factory=list, description="At least one; each must appear in the input."
    )


class CommitJudgment(BaseModel):
    """The model's reading of one diff. Stage one — the only stage that sees diff text."""

    model_config = ConfigDict(extra="forbid")

    sha: str
    fix_nature: FixNature
    test_relevance: TestRelevance
    scope: ScopeDiscipline
    note: str = Field(default="", description="One sentence on what the diff actually did.")


class DimensionFinding(BaseModel):
    """One dimension's readout. Stage two — sees facts and commit judgments, not diffs."""

    model_config = ConfigDict(extra="forbid")

    dimension: DimensionKey
    verdict: Verdict
    confidence: Confidence
    summary: str = Field(description="One sentence a reader can act on.")
    claims: list[Claim] = Field(default_factory=list)
    limitations: list[str] = Field(
        default_factory=list, description="What this dimension cannot see here."
    )
    risks_to_probe: list[str] = Field(
        default_factory=list, description="What to ask about in an interview."
    )

    @property
    def is_conclusive(self) -> bool:
        return self.verdict in CONCLUSIVE_VERDICTS


class JudgeResult(BaseModel):
    """Everything L4 produced, with the provenance to reproduce it."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = L4_SCHEMA_VERSION
    judge_model: str = ""
    prompt_version: str = ""
    n_commits_sampled: int = 0
    n_commits_total: int = 0
    commit_judgments: list[CommitJudgment] = Field(default_factory=list)
    findings: list[DimensionFinding] = Field(default_factory=list)
    downgrades: list[str] = Field(
        default_factory=list,
        description="Support-check interventions: a verdict the evidence did not carry.",
    )

    def finding(self, dimension: DimensionKey) -> DimensionFinding | None:
        return next((f for f in self.findings if f.dimension is dimension), None)
