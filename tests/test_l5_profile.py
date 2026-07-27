"""The profile document — ordering, freezing, and the sections that must never go missing."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from tests.fixtures import repos
from vouch.ingest import ingest
from vouch.l1.extract import extract_facts
from vouch.l2.payload import (
    DegradedReason,
    MetricKey,
    MetricScope,
    Rate,
    SessionMetrics,
)
from vouch.l3.join import CorroborationReport
from vouch.l4.dimensions import DIMENSIONS
from vouch.l4.judge import judge_profile
from vouch.l4.mock import MockJudgeProvider, MockMode
from vouch.l4.schema import DimensionKey, JudgeResult, Verdict
from vouch.l5.limitations import STANDING_LIMITATIONS
from vouch.l5.ordering import evidence_strength
from vouch.l5.profile import DIMENSION_ORDER, Profile, build_profile

SUBJECT = "alice@example.com"


@pytest.fixture
def facts_for(tmp_path: Path):
    def _build(variant: str = "healthy"):
        repo = tmp_path / variant
        getattr(repos, variant)(repo)
        snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
        return repo, snapshot, extract_facts(snapshot, SUBJECT, repo)

    return _build


def _judgment(repo, snapshot, facts, metrics=None) -> JudgeResult:
    return judge_profile(
        MockJudgeProvider(MockMode.HONEST), facts, repo, snapshot.commits, metrics=metrics
    )


def _metrics() -> SessionMetrics:
    return SessionMetrics(
        scope=MetricScope.REPO,
        n_sessions=20,
        n_records=5000,
        rates={
            MetricKey.PLAN_BEFORE_EXECUTE: Rate(
                numerator=8, denominator=20, floor=5, value=0.4
            )
        },
    )


class TestStructure:
    def test_has_no_aggregate_score_field(self, facts_for) -> None:
        """"No overall single score" is enforced by the type, not by remembering."""
        fields = Profile.model_fields
        for forbidden in ("score", "overall", "rating", "grade", "rank", "percentile"):
            assert forbidden not in fields

    def test_dimension_order_follows_the_evidence(self, facts_for) -> None:
        """Position is a claim, so it is earned rather than assigned.

        Verification discipline used to lead unconditionally — it is the dimension measured
        in both trails, which is a good reason to prefer it and a bad reason to pin it. A
        fixed first slot asserts "this is the most informative readout here" even when it
        rests on five observations. The order now sorts on evidence strength, with the old
        preference kept only as the tie-break between comparable dimensions.
        """
        repo, snapshot, facts = facts_for()
        profile = build_profile(
            facts, _judgment(repo, snapshot, facts, _metrics()), _metrics()
        )

        assert DIMENSION_ORDER[0] is DimensionKey.VERIFICATION_DISCIPLINE  # the tie-break
        strengths = [
            evidence_strength(
                next(s for s in DIMENSIONS if s.key is f.dimension), facts, _metrics()
            )
            for f in profile.findings
        ]
        assert strengths == sorted(strengths, reverse=True)

    def test_evidence_is_summarised_before_any_judgement(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        profile = build_profile(facts, _judgment(repo, snapshot, facts, _metrics()))
        summary = profile.evidence_inspected

        assert summary.n_commits_by_subject == 12
        assert summary.n_diffs_read > 0
        assert summary.n_diffs_read <= summary.n_diffs_available
        assert summary.measured_facts + summary.withheld_facts == len(facts.facts)


class TestFreezing:
    def test_profile_id_is_stable_across_regeneration(self, facts_for) -> None:
        """Re-generating must not invalidate a link someone already shared."""
        repo, snapshot, facts = facts_for()
        judgment = _judgment(repo, snapshot, facts, _metrics())

        first = build_profile(facts, judgment, generated_at=datetime(2026, 1, 1))
        second = build_profile(facts, judgment, generated_at=datetime(2030, 6, 30))

        assert first.profile_id == second.profile_id
        assert first.provenance.generated_at != second.provenance.generated_at

    def test_profile_id_changes_when_the_evidence_changes(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        judgment = _judgment(repo, snapshot, facts, _metrics())

        baseline = build_profile(facts, judgment)
        altered = build_profile(
            facts.model_copy(update={"n_commits_by_subject": 999}), judgment
        )

        assert baseline.profile_id != altered.profile_id

    def test_share_path_uses_the_frozen_id(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        profile = build_profile(facts, _judgment(repo, snapshot, facts))

        assert profile.share_path == f"/p/{profile.profile_id}"
        assert len(profile.profile_id) == 16


class TestLimitations:
    def test_standing_limitations_always_present(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        profile = build_profile(facts, _judgment(repo, snapshot, facts, _metrics()))

        for standing in STANDING_LIMITATIONS:
            assert standing in profile.limitations

    def test_confounds_become_limitations(self, facts_for) -> None:
        """The section the competitor's public surface has no equivalent to."""
        repo, snapshot, facts = facts_for("solo")
        profile = build_profile(facts, _judgment(repo, snapshot, facts))

        assert any("only option available" in lim for lim in profile.limitations)

    def test_sampling_is_disclosed_when_incomplete(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        judgment = _judgment(repo, snapshot, facts).model_copy(
            update={"n_commits_sampled": 5, "n_commits_total": 40}
        )
        profile = build_profile(facts, judgment)

        assert any("5 of 40 commits" in lim for lim in profile.limitations)

    def test_absent_session_telemetry_is_stated(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        profile = build_profile(facts, _judgment(repo, snapshot, facts), metrics=None)

        assert any("No session telemetry" in lim for lim in profile.limitations)

    def test_degraded_telemetry_is_stated_differently(self, facts_for) -> None:
        """"Could not read the logs" is a different fact from "did not collect them"."""
        repo, snapshot, facts = facts_for()
        degraded = SessionMetrics(degraded=True, degraded_reason=DegradedReason.UNPARSEABLE)
        profile = build_profile(facts, _judgment(repo, snapshot, facts), metrics=degraded)

        assert any("could not be read" in lim for lim in profile.limitations)

    def test_withheld_facts_are_named(self, facts_for) -> None:
        repo, snapshot, facts = facts_for("short_window")
        profile = build_profile(facts, _judgment(repo, snapshot, facts))

        assert any("withheld" in lim and "ownership_loop" in lim for lim in profile.limitations)

    def test_corroboration_absence_is_stated(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        profile = build_profile(facts, _judgment(repo, snapshot, facts))

        assert any("not corroborated" in lim or "no claim here is" in lim
                   for lim in profile.limitations)

    def test_corroboration_coverage_never_reads_as_an_accuracy_claim(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        corr = CorroborationReport(n_commits=10, n_corroborated=3, n_uncorroborated=7)
        profile = build_profile(facts, _judgment(repo, snapshot, facts), corroboration=corr)

        text = " ".join(profile.limitations)
        assert "3 of 10 commits" in text
        assert "not that the work was unsupervised" in text
        # Coverage is a count; nothing here should imply the join was validated.
        assert "accura" not in text.lower()


class TestRisksToProbe:
    def test_declining_dimensions_generate_questions(self, facts_for) -> None:
        """A gap the reader does not know to ask about is a gap the profile has hidden."""
        repo, snapshot, facts = facts_for()
        profile = build_profile(facts, _judgment(repo, snapshot, facts), metrics=None)

        planning = profile.findings and next(
            f for f in profile.findings if f.dimension is DimensionKey.PLANNING_DISCIPLINE
        )
        assert planning.verdict is Verdict.NOT_ASSESSED
        assert any("Planning discipline could not be assessed" in r
                   for r in profile.risks_to_probe)

    def test_risks_are_deduplicated_but_ordered(self, facts_for) -> None:
        repo, snapshot, facts = facts_for()
        profile = build_profile(facts, _judgment(repo, snapshot, facts, _metrics()))

        assert len(profile.risks_to_probe) == len(set(profile.risks_to_probe))

    def test_risks_exist_even_without_a_judge(self, facts_for) -> None:
        _repo, _snapshot, facts = facts_for()
        profile = build_profile(facts, judgment=None)

        assert profile.risks_to_probe
        assert profile.findings == []


def test_downgrades_travel_into_provenance(facts_for) -> None:
    """A reader can see where the pipeline overruled the model."""
    repo, snapshot, facts = facts_for()
    judgment = judge_profile(
        MockJudgeProvider(MockMode.UNSOURCED), facts, repo, snapshot.commits
    )
    profile = build_profile(facts, judgment)

    assert profile.provenance.downgrades
    assert any("insufficient_evidence" in note for note in profile.provenance.downgrades)
