"""report assembly + serialization tests."""
from datetime import date, datetime

from vouch.report import build_report, to_json, to_markdown
from vouch.schemas import CapabilityReport, CommitMeta, EvidenceBundle, Signal, Verdict


def _bundle_and_verdict():
    sha = "a" * 40
    bundle = EvidenceBundle(
        repo="https://example.com/x.git",
        subject="alice@example.com",
        n_commits_by_subject=2,
        signals=[Signal(key="fixed_own_bug", value=1, evidence=[sha], computed_at=datetime.now())],
        commit_index={sha: CommitMeta(sha=sha, short=sha[:8], authored_at=datetime(2025, 1, 1),
                                      subject="fix", n_files=1, touched_tests=True)},
    )
    verdict = Verdict(dimension="ownership", score=0.8, confidence=0.6,
                      freshness=date(2025, 1, 1), rationale=f"self-fix in {sha[:8]}",
                      cited_evidence=[sha])
    return bundle, verdict


def test_build_report_carries_provenance():
    bundle, verdict = _bundle_and_verdict()
    report = build_report(bundle, verdict, "gemini:gemini-2.0-flash", "ownership-v0")
    assert report.judge_model == "gemini:gemini-2.0-flash"
    assert report.prompt_version == "ownership-v0"
    assert report.evidence == bundle.signals
    # round-trips
    assert CapabilityReport.model_validate_json(to_json(report)) == report


def test_markdown_renders_signals_and_citations():
    bundle, verdict = _bundle_and_verdict()
    report = build_report(bundle, verdict, "stub:1", "ownership-v0")
    md = to_markdown(report)
    assert "# Ownership report" in md
    assert "`fixed_own_bug`" in md
    assert "aaaaaaaa" in md  # short sha in table + citations
    assert "0.80" in md and "0.60" in md
