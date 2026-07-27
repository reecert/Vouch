"""L4 — the guard rails, tested against judges that lie.

The model is the least trustworthy component in the system, so almost every test here is
about what happens *after* it answers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures import repos
from vouch.ingest import ingest
from vouch.l1.extract import extract_facts
from vouch.l2.payload import MetricKey, MetricScope, Rate, SessionMetrics
from vouch.l4.dimensions import DIMENSIONS, assess_availability
from vouch.l4.grounding import build_allowlist, check_claims
from vouch.l4.judge import JudgeError, apply_support_check, judge_profile
from vouch.l4.mock import MockJudgeProvider, MockMode
from vouch.l4.sampling import SamplingPolicy, select_commits
from vouch.l4.schema import (
    Claim,
    Confidence,
    DimensionFinding,
    DimensionKey,
    Locator,
    Verdict,
)

SUBJECT = "alice@example.com"


@pytest.fixture
def repo_facts(tmp_path: Path):
    repo = tmp_path / "repo"
    repos.healthy(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    facts = extract_facts(snapshot, SUBJECT, repo)
    return repo, snapshot, facts


def _metrics(**rates) -> SessionMetrics:
    # Repo-scoped, as a profile's telemetry must be: every dimension declares
    # `MetricScope.REPO`, and machine-wide rates are refused rather than discounted.
    return SessionMetrics(
        scope=MetricScope.REPO,
        n_sessions=20,
        rates={
            MetricKey.PLAN_BEFORE_EXECUTE: Rate(
                numerator=8, denominator=20, floor=5, value=0.4
            ),
            MetricKey.TEST_OR_BUILD_AFTER_EDIT: Rate(
                numerator=15, denominator=20, floor=10, value=0.75
            ),
            MetricKey.EDIT_REVISION: Rate(
                numerator=6, denominator=20, floor=10, value=0.3
            ),
            MetricKey.HUMAN_REDIRECT: Rate(
                numerator=2, denominator=20, floor=5, value=0.1
            ),
            **rates,
        },
    )


def _run(repo, snapshot, facts, mode=MockMode.HONEST, metrics=None):
    provider = MockJudgeProvider(mode)
    sample = select_commits(snapshot.commits, facts)
    from vouch.l4.diffs import extract_diff

    diffs = [extract_diff(repo, c) for c in sample.commits]
    provider.bind(build_allowlist(facts, diffs))
    return provider, judge_profile(
        provider, facts, repo, snapshot.commits, metrics=metrics
    )


class TestSampling:
    def test_cited_commits_are_never_sampled_out(self, repo_facts) -> None:
        """The dimension with the strongest claim is not judged on a sample of its own
        evidence."""
        _repo, snapshot, facts = repo_facts
        sample = select_commits(snapshot.commits, facts, SamplingPolicy(max_commits=3))

        cited = facts.known_shas()
        assert cited
        assert all(c.sha in cited for c in sample.commits)

    def test_sample_is_reproducible(self, repo_facts) -> None:
        _repo, snapshot, facts = repo_facts
        policy = SamplingPolicy(max_commits=6)

        first = select_commits(snapshot.commits, facts, policy)
        second = select_commits(snapshot.commits, facts, policy)

        assert [c.sha for c in first.commits] == [c.sha for c in second.commits]

    def test_sample_describes_itself_for_the_reader(self, repo_facts) -> None:
        _repo, snapshot, facts = repo_facts

        partial = select_commits(snapshot.commits, facts, SamplingPolicy(max_commits=3))
        complete = select_commits(snapshot.commits, facts, SamplingPolicy(max_commits=99))

        assert "3 of" in partial.describe()
        assert partial.is_complete is False
        assert complete.is_complete is True
        assert "All" in complete.describe()


class TestDiffExtraction:
    def test_noise_is_excluded_but_disclosed(self, repo_facts) -> None:
        """A lockfile must not eat the budget — but the model should know it was there."""
        repo, snapshot, _facts = repo_facts
        from vouch.l4.diffs import extract_diff

        commit = next(c for c in snapshot.commits if "package-lock.json" in c.files)
        diff = extract_diff(repo, commit)

        assert "package-lock.json" in diff.files_omitted
        assert "package-lock.json" not in diff.files_shown

    def test_truncation_is_stated_in_the_text_the_model_reads(self, repo_facts) -> None:
        repo, snapshot, _facts = repo_facts
        from vouch.l4.diffs import DiffBudget, extract_diff

        commit = next(c for c in snapshot.commits if len(c.files) > 1)
        diff = extract_diff(repo, commit, DiffBudget(max_files=1))
        rendered = diff.render()

        assert diff.truncated is True
        assert "truncated" in rendered
        assert "insufficient_evidence" in rendered  # the model is told what to do about it


class TestGrounding:
    def test_hallucinated_commit_is_rejected(self, repo_facts) -> None:
        repo, snapshot, facts = repo_facts
        from vouch.l4.diffs import extract_diff

        sample = select_commits(snapshot.commits, facts)
        allowlist = build_allowlist(facts, [extract_diff(repo, c) for c in sample.commits])

        problems = check_claims(
            [Claim(text="x", locators=[Locator(sha="f" * 40)])], allowlist
        )
        assert problems and "unknown commit" in problems[0]

    def test_real_commit_with_a_file_it_never_touched_is_rejected(self, repo_facts) -> None:
        """The error a metadata-level check cannot catch and a diff-reader can make."""
        repo, snapshot, facts = repo_facts
        from vouch.l4.diffs import extract_diff

        sample = select_commits(snapshot.commits, facts)
        allowlist = build_allowlist(facts, [extract_diff(repo, c) for c in sample.commits])
        real_sha = sorted(allowlist.shas)[0]

        problems = check_claims(
            [Claim(text="x", locators=[Locator(sha=real_sha, path="src/nope.py")])],
            allowlist,
        )
        assert problems and "did not touch that file" in problems[0]

    def test_abbreviated_shas_are_accepted(self, repo_facts) -> None:
        repo, snapshot, facts = repo_facts
        from vouch.l4.diffs import extract_diff

        sample = select_commits(snapshot.commits, facts)
        allowlist = build_allowlist(facts, [extract_diff(repo, c) for c in sample.commits])
        full = sorted(allowlist.shas)[0]

        assert check_claims([Claim(text="x", locators=[Locator(sha=full[:8])])], allowlist) == []
        # ...but not so short they could collide.
        assert check_claims([Claim(text="x", locators=[Locator(sha=full[:4])])], allowlist)

    def test_a_claim_with_no_locator_is_a_problem(self, repo_facts) -> None:
        """An unsourced assertion is indistinguishable from a hallucination."""
        repo, snapshot, facts = repo_facts
        from vouch.l4.diffs import extract_diff

        sample = select_commits(snapshot.commits, facts)
        allowlist = build_allowlist(facts, [extract_diff(repo, c) for c in sample.commits])

        problems = check_claims([Claim(text="They are great.", locators=[])], allowlist)
        assert problems and "no locator" in problems[0]


class TestSupportCheck:
    def _availability(self, facts, metrics, spec_key=DimensionKey.OWNERSHIP):
        spec = next(s for s in DIMENSIONS if s.key is spec_key)
        return assess_availability(spec, facts, metrics, n_commit_judgments=3)

    def test_conclusive_verdict_without_claims_is_downgraded(self, repo_facts) -> None:
        _repo, _snapshot, facts = repo_facts
        finding = DimensionFinding(
            dimension=DimensionKey.OWNERSHIP,
            verdict=Verdict.STRONG,
            confidence=Confidence.HIGH,
            summary="Excellent ownership.",
            claims=[],
        )

        checked, note = apply_support_check(finding, self._availability(facts, None))

        assert checked.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert checked.confidence is Confidence.LOW
        assert "no sourced claim" in note

    def test_check_only_ever_downgrades(self, repo_facts) -> None:
        """A brake, never an accelerator: a bug here cannot flatter the candidate."""
        _repo, _snapshot, facts = repo_facts
        finding = DimensionFinding(
            dimension=DimensionKey.OWNERSHIP,
            verdict=Verdict.INSUFFICIENT_EVIDENCE,
            confidence=Confidence.LOW,
            summary="Not enough to say.",
            claims=[],
        )

        checked, note = apply_support_check(finding, self._availability(facts, None))

        assert checked.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert note is None

    def test_absent_input_layer_becomes_not_assessed(self, repo_facts) -> None:
        """"We didn't look" is a different fact from "we looked and found little"."""
        _repo, _snapshot, facts = repo_facts
        availability = self._availability(facts, None, DimensionKey.PLANNING_DISCIPLINE)
        finding = DimensionFinding(
            dimension=DimensionKey.PLANNING_DISCIPLINE,
            verdict=Verdict.STRONG,
            confidence=Confidence.HIGH,
            summary="Plans thoroughly.",
            claims=[Claim(text="x", locators=[Locator(sha="a" * 40)])],
        )

        checked, note = apply_support_check(finding, availability)

        assert checked.verdict is Verdict.NOT_ASSESSED
        assert "input layer absent" in note

    def test_all_evidence_suppressed_becomes_insufficient(self, repo_facts) -> None:
        _repo, _snapshot, facts = repo_facts
        suppressed = SessionMetrics(
            scope=MetricScope.REPO,
            rates={
                MetricKey.PLAN_BEFORE_EXECUTE: Rate(
                    numerator=1, denominator=2, floor=5, suppressed=True
                )
            }
        )
        availability = assess_availability(
            next(s for s in DIMENSIONS if s.key is DimensionKey.PLANNING_DISCIPLINE),
            facts,
            suppressed,
            n_commit_judgments=0,
        )
        finding = DimensionFinding(
            dimension=DimensionKey.PLANNING_DISCIPLINE,
            verdict=Verdict.MODERATE,
            confidence=Confidence.MODERATE,
            summary="Plans sometimes.",
            claims=[Claim(text="x", locators=[Locator(sha="a" * 40)])],
        )

        checked, note = apply_support_check(finding, availability)

        assert checked.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert "suppressed" in note


class TestOrchestration:
    def test_honest_run_produces_every_dimension(self, repo_facts) -> None:
        repo, snapshot, facts = repo_facts
        _provider, result = _run(repo, snapshot, facts, metrics=_metrics())

        assert {f.dimension for f in result.findings} == set(DimensionKey)
        assert result.n_commits_sampled > 0
        assert result.judge_model.startswith("mock:")
        assert result.prompt_version

    def test_planning_is_not_assessed_without_the_cli(self, repo_facts) -> None:
        """No session telemetry: the dimension says so rather than guessing."""
        repo, snapshot, facts = repo_facts
        _provider, result = _run(repo, snapshot, facts, metrics=None)

        planning = result.finding(DimensionKey.PLANNING_DISCIPLINE)
        assert planning.verdict is Verdict.NOT_ASSESSED
        assert "not collected" in planning.summary

    def test_hallucinating_judge_has_its_claims_dropped(self, repo_facts) -> None:
        repo, snapshot, facts = repo_facts
        _provider, result = _run(
            repo, snapshot, facts, MockMode.HALLUCINATING, metrics=_metrics()
        )

        assert any("ungrounded" in note for note in result.downgrades)
        for finding in result.findings:
            assert all(claim.locators for claim in finding.claims)

    def test_wrong_path_judge_is_caught(self, repo_facts) -> None:
        repo, snapshot, facts = repo_facts
        _provider, result = _run(
            repo, snapshot, facts, MockMode.WRONG_PATH, metrics=_metrics()
        )
        assert any("ungrounded" in note for note in result.downgrades)

    def test_unsourced_strong_verdicts_are_downgraded(self, repo_facts) -> None:
        """The over-eager judge: a confident verdict resting on nothing."""
        repo, snapshot, facts = repo_facts
        _provider, result = _run(
            repo, snapshot, facts, MockMode.UNSOURCED, metrics=_metrics()
        )

        assessed = [
            f for f in result.findings if f.verdict is not Verdict.NOT_ASSESSED
        ]
        assert assessed
        assert all(f.verdict is Verdict.INSUFFICIENT_EVIDENCE for f in assessed)
        assert len(result.downgrades) >= len(assessed)

    def test_grounding_retry_happens_before_dropping(self, repo_facts) -> None:
        repo, snapshot, facts = repo_facts
        provider, _result = _run(
            repo, snapshot, facts, MockMode.HALLUCINATING, metrics=_metrics()
        )
        # 3 assessable dimensions x (1 attempt + 1 retry) + one call per sampled commit.
        assert provider.calls > 3

    def test_flaky_provider_fails_loud_on_dimensions(self, repo_facts) -> None:
        repo, snapshot, facts = repo_facts
        provider = MockJudgeProvider(MockMode.FLAKY)

        with pytest.raises(JudgeError):
            judge_profile(provider, facts, repo, snapshot.commits, metrics=_metrics())

    def test_unavailable_provider_fails_loud(self, repo_facts) -> None:
        repo, _snapshot, facts = repo_facts

        class Unavailable:
            name = "none"
            model = "none"

            def is_available(self) -> bool:
                return False

            def complete(self, system, user, schema):  # pragma: no cover
                raise AssertionError("should not be called")

        with pytest.raises(JudgeError, match="unavailable"):
            judge_profile(Unavailable(), facts, repo, [])

    def test_insufficient_evidence_fires_on_a_genuinely_thin_history(
        self, tmp_path: Path
    ) -> None:
        """Observed, not merely supported: a thin repo produces the declining verdict.

        The `short_window` fixture compresses all activity into a few days, so no fix
        clears the 14-day return gap and `ownership_loop` is suppressed for want of a
        denominator. The dimension must decline rather than read the remaining scraps
        generously.
        """
        repo = tmp_path / "thin"
        repos.short_window(repo)
        snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
        facts = extract_facts(snapshot, SUBJECT, repo)

        assert facts.fact("ownership_loop").status.value == "suppressed_low_n"

        _provider, result = _run(repo, snapshot, facts, metrics=_metrics())
        ownership = result.finding(DimensionKey.OWNERSHIP)

        assert ownership.verdict is Verdict.INSUFFICIENT_EVIDENCE

    def test_downgrades_are_recorded_not_silent(self, repo_facts) -> None:
        """A silent correction would hide the calibration problem eval exists to measure."""
        repo, snapshot, facts = repo_facts
        _provider, result = _run(
            repo, snapshot, facts, MockMode.UNSOURCED, metrics=_metrics()
        )
        assert result.downgrades
        assert all(isinstance(note, str) and note for note in result.downgrades)
