"""Trivial harness-proof test: package imports and schemas round-trip."""
from datetime import date, datetime

from vouch.config import CONFIG, PROVIDER_CHAIN, SIGNAL_WEIGHTS
from vouch.schemas import CapabilityReport, Signal, Verdict


def test_config_has_five_ownership_signals():
    # review_followthrough dropped in v0 -> exactly five git-derivable signals.
    assert set(SIGNAL_WEIGHTS) == {
        "returned_to_own_code",
        "fixed_own_bug",
        "tests_accompany_fixes",
        "revert_recovery",
        "commit_atomicity",
    }
    assert CONFIG.prompt_version == "ownership-v0"
    assert [p.name for p in PROVIDER_CHAIN] == ["gemini", "groq", "ollama"]


def test_report_round_trips_through_json():
    verdict = Verdict(
        dimension="ownership",
        score=0.7,
        confidence=0.6,
        freshness=date(2025, 1, 1),
        rationale="cites abc123",
        cited_evidence=["abc123"],
    )
    report = CapabilityReport(
        repo="https://example.com/x.git",
        subject="dev@example.com",
        dimension="ownership",
        verdict=verdict,
        evidence=[Signal(key="fixed_own_bug", value=True, evidence=["abc123"], computed_at=datetime.now())],
        judge_model="stub",
        prompt_version="ownership-v0",
        generated_at=datetime.now(),
    )
    assert CapabilityReport.model_validate_json(report.model_dump_json()) == report
