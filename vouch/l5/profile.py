"""L5 — the profile document: what a reader actually sees.

Assembly is deterministic. Everything a model contributed arrived in
:class:`~vouch.l4.schema.JudgeResult`; this layer decides ordering, derives the sections
that must never be missing, and freezes the result.

Three properties are enforced by the type rather than by remembering:

* **No aggregate score.** :class:`Profile` has no field for one. "No overall single score"
  cannot be violated by a later edit that adds a helpful summary number, because there is
  nowhere to put it.
* **Evidence first.** ``evidence_inspected`` precedes any judgement, so the provenance is a
  headline rather than an appendix.
* **Frozen snapshots.** A share link resolves to an immutable ``profile_id`` — the content
  hash of everything except the wall-clock stamp. A recipient sees the document that was
  shared, not a live feed of the subject's ongoing activity. (Adopted from the
  competitor's "frozen profile projections"; it is the right default for a document about
  a person.)

Section order is set for a **hiring screener**: Risks to probe sits directly after the
dimension readouts, because generating the next question is the reader's actual job.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from vouch.l1.facts import Confound, FactStatus, RepoFacts
from vouch.l2.payload import SessionMetrics
from vouch.l3.join import CorroborationReport
from vouch.l4.dimensions import DIMENSIONS
from vouch.l4.schema import DimensionFinding, JudgeResult
from vouch.l5.limitations import derive_limitations, derive_risks

__all__ = [
    "L5_SCHEMA_VERSION",
    "EvidenceSummary",
    "CorroborationSummary",
    "Provenance",
    "Profile",
    "build_profile",
]

L5_SCHEMA_VERSION = "l5/1"

#: Dimension order in the report. Verification discipline leads because it is the one
#: measured in both the commit trail and the session trail, so it is where corroboration
#: is visible to a reader (docs/plan.md open question 2).
DIMENSION_ORDER = [spec.key for spec in DIMENSIONS]


class EvidenceSummary(BaseModel):
    """What was inspected, stated before anything is concluded from it."""

    model_config = ConfigDict(extra="forbid")

    repo: str
    head_sha: str
    window_first: date | None = None
    window_last: date | None = None
    n_commits_by_subject: int = 0
    n_commits_in_repo: int = 0
    n_diffs_read: int = 0
    n_diffs_available: int = 0
    n_sessions: int = 0
    session_telemetry: bool = False
    excluded_paths: dict[str, int] = Field(default_factory=dict)
    measured_facts: int = 0
    withheld_facts: int = 0


class CorroborationSummary(BaseModel):
    """Coverage as a count. Never presented as an accuracy claim — see plan.md q9."""

    model_config = ConfigDict(extra="forbid")

    ran: bool = False
    n_commits: int = 0
    n_corroborated: int = 0
    n_ambiguous: int = 0
    n_uncorroborated: int = 0


class Provenance(BaseModel):
    """Enough to reproduce this document, or to say why it cannot be."""

    model_config = ConfigDict(extra="forbid")

    l1_schema: str = ""
    judge_model: str = ""
    prompt_version: str = ""
    downgrades: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class Profile(BaseModel):
    """The shareable document.

    Deliberately has **no** aggregate score, rating, grade or rank field.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = L5_SCHEMA_VERSION
    profile_id: str = ""
    subject: str = ""
    evidence_inspected: EvidenceSummary
    findings: list[DimensionFinding] = Field(default_factory=list)
    risks_to_probe: list[str] = Field(default_factory=list)
    corroboration: CorroborationSummary = Field(default_factory=CorroborationSummary)
    confounds: list[Confound] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)

    def frozen_payload(self) -> str:
        """Canonical bytes of everything except the wall-clock stamp and the id itself."""
        data = json.loads(self.model_dump_json())
        data.pop("profile_id", None)
        data.get("provenance", {}).pop("generated_at", None)
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def compute_id(self) -> str:
        return hashlib.sha256(self.frozen_payload().encode()).hexdigest()[:16]

    @property
    def share_path(self) -> str:
        return f"/p/{self.profile_id}"


def _ordered(findings: list[DimensionFinding]) -> list[DimensionFinding]:
    index = {key: i for i, key in enumerate(DIMENSION_ORDER)}
    return sorted(findings, key=lambda f: index.get(f.dimension, len(index)))


def build_profile(
    facts: RepoFacts,
    judgment: JudgeResult | None = None,
    metrics: SessionMetrics | None = None,
    corroboration: CorroborationReport | None = None,
    generated_at: datetime | None = None,
) -> Profile:
    """Assemble the profile and freeze it.

    ``generated_at`` is deliberately outside the hash: the same inputs produce the same
    ``profile_id`` however many times they are rendered, so re-generating a profile does
    not silently invalidate a link someone already shared.
    """
    evidence = EvidenceSummary(
        repo=facts.repo,
        head_sha=facts.head_sha,
        window_first=facts.window_first,
        window_last=facts.window_last,
        n_commits_by_subject=facts.n_commits_by_subject,
        n_commits_in_repo=facts.n_commits_total,
        n_diffs_read=judgment.n_commits_sampled if judgment else 0,
        n_diffs_available=judgment.n_commits_total if judgment else 0,
        n_sessions=metrics.n_sessions if metrics else 0,
        session_telemetry=bool(metrics and not metrics.degraded),
        excluded_paths=dict(facts.excluded_paths),
        measured_facts=sum(1 for f in facts.facts if f.status is FactStatus.MEASURED),
        withheld_facts=sum(1 for f in facts.facts if f.status is not FactStatus.MEASURED),
    )

    corr = CorroborationSummary(
        ran=corroboration is not None,
        n_commits=corroboration.n_commits if corroboration else 0,
        n_corroborated=corroboration.n_corroborated if corroboration else 0,
        n_ambiguous=corroboration.n_ambiguous if corroboration else 0,
        n_uncorroborated=corroboration.n_uncorroborated if corroboration else 0,
    )

    profile = Profile(
        subject=facts.subject.canonical_email,
        evidence_inspected=evidence,
        findings=_ordered(judgment.findings) if judgment else [],
        risks_to_probe=derive_risks(judgment),
        corroboration=corr,
        confounds=list(facts.confounds),
        limitations=derive_limitations(facts, judgment, metrics, corroboration),
        provenance=Provenance(
            l1_schema=facts.schema_version,
            judge_model=judgment.judge_model if judgment else "",
            prompt_version=judgment.prompt_version if judgment else "",
            downgrades=list(judgment.downgrades) if judgment else [],
            generated_at=generated_at or datetime.now(),
        ),
    )
    return profile.model_copy(update={"profile_id": profile.compute_id()})
