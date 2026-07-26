"""The eval harness — and the numbers it refuses to print.

The v0 harness's disciplines carry over: refuse an empty holdout, warn below the evidence
threshold, never claim "calibrated". What is new is that a disagreement has a *direction*,
because overclaiming and underclaiming are not the same failure.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from vouch.eval import (
    EvalError,
    LabelValidationError,
    format_report,
    load_labels,
    run_eval,
)
from vouch.eval.harness import MIN_LABELS_FOR_CALIBRATION, MIN_LABELS_FOR_EVIDENCE
from vouch.eval.labels import DimensionLabel, LabelSet
from vouch.l4.schema import Confidence, DimensionFinding, DimensionKey, Verdict

REPO_ROOT = Path(__file__).resolve().parent.parent


def label(verdict: Verdict, dimension=DimensionKey.OWNERSHIP, repo="r") -> DimensionLabel:
    return DimensionLabel(
        repo=repo,
        author="a@b.com",
        dimension=dimension,
        verdict=verdict,
        reason="returns to their own defects with tests, see the commit trail",
    )


def finding(verdict: Verdict) -> DimensionFinding:
    return DimensionFinding(
        dimension=DimensionKey.OWNERSHIP,
        verdict=verdict,
        confidence=Confidence.MODERATE,
        summary="x",
    )


class TestLabelValidation:
    def test_reason_is_required(self) -> None:
        """A label without a justification is a guess, not ground truth."""
        with pytest.raises(ValidationError):
            DimensionLabel(
                repo="r",
                author="a@b.com",
                dimension=DimensionKey.OWNERSHIP,
                verdict=Verdict.STRONG,
                reason="   ",
            )

    def test_insufficient_evidence_is_a_valid_label(self) -> None:
        """"A careful human would decline here" is the judgement we most need reproduced."""
        row = label(Verdict.INSUFFICIENT_EVIDENCE)
        assert row.verdict is Verdict.INSUFFICIENT_EVIDENCE

    def test_holdout_leak_is_rejected(self, tmp_path: Path) -> None:
        """A row tuned on in train makes the holdout number meaningless."""
        row = {
            "repo": "r",
            "author": "a@b.com",
            "dimension": "ownership",
            "verdict": "strong",
            "reason": "because of the commit trail",
        }
        path = tmp_path / "labels.yaml"
        path.write_text(yaml.safe_dump({"train": [row], "holdout": [row]}))

        with pytest.raises(LabelValidationError, match="BOTH train and holdout"):
            load_labels(path)

    def test_missing_pools_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        path.write_text(yaml.safe_dump({"labels": []}))

        with pytest.raises(LabelValidationError, match="train"):
            load_labels(path)

    def test_repo_label_file_is_valid_and_still_empty(self) -> None:
        """The shipped label file parses — and is empty, which is the honest state.

        This is the test that keeps us honest: it fails the day someone populates the file
        without also updating the claims made about judge accuracy.
        """
        labels = load_labels(REPO_ROOT / "eval" / "labels.yaml")
        assert labels.total == 0


class TestRefusals:
    def test_empty_holdout_is_refused(self) -> None:
        """A silent 0/0 would masquerade as a result."""
        with pytest.raises(EvalError, match="holdout is empty"):
            run_eval(LabelSet(), lambda _l: None, split="holdout")

    def test_empty_train_is_refused(self) -> None:
        with pytest.raises(EvalError, match="empty"):
            run_eval(LabelSet(), lambda _l: None, split="train")

    def test_unknown_split_is_refused(self) -> None:
        with pytest.raises(EvalError, match="unknown split"):
            run_eval(
                LabelSet(holdout=[label(Verdict.STRONG)]), lambda _l: None, split="nope"
            )


class TestScoring:
    def test_exact_agreement(self) -> None:
        labels = LabelSet(holdout=[label(Verdict.STRONG), label(Verdict.MODERATE, repo="s")])
        report = run_eval(labels, lambda row: finding(row.verdict), split="holdout")

        assert report.metrics.exact_agreement == 1.0
        assert report.metrics.n_overclaim == 0
        assert report.metrics.n_underclaim == 0

    def test_overclaim_is_counted_and_warned_about(self) -> None:
        """Concluding where a human declined — the failure the quality bar exists for."""
        labels = LabelSet(holdout=[label(Verdict.INSUFFICIENT_EVIDENCE)])
        report = run_eval(labels, lambda _l: finding(Verdict.STRONG), split="holdout")

        assert report.metrics.n_overclaim == 1
        assert report.metrics.n_underclaim == 0
        assert report.metrics.overclaim_rate == 1.0
        assert any("OVERCLAIMED" in w for w in report.warnings)

    def test_underclaim_is_counted_separately(self) -> None:
        labels = LabelSet(holdout=[label(Verdict.STRONG)])
        report = run_eval(
            labels, lambda _l: finding(Verdict.INSUFFICIENT_EVIDENCE), split="holdout"
        )

        assert report.metrics.n_underclaim == 1
        assert report.metrics.n_overclaim == 0
        assert not any("OVERCLAIMED" in w for w in report.warnings)

    def test_adjacent_agreement_is_tracked(self) -> None:
        """strong vs moderate is a near miss; strong vs insufficient is not."""
        near = run_eval(
            LabelSet(holdout=[label(Verdict.STRONG)]),
            lambda _l: finding(Verdict.MODERATE),
            split="holdout",
        )
        far = run_eval(
            LabelSet(holdout=[label(Verdict.STRONG)]),
            lambda _l: finding(Verdict.INSUFFICIENT_EVIDENCE),
            split="holdout",
        )

        assert near.metrics.adjacent_agreement == 1.0
        assert near.metrics.exact_agreement == 0.0
        assert far.metrics.adjacent_agreement == 0.0

    def test_categorical_verdicts_have_no_direction(self) -> None:
        """`not_assessed` is not on the ordinal scale, so a mismatch has no direction."""
        labels = LabelSet(holdout=[label(Verdict.STRONG)])
        report = run_eval(labels, lambda _l: finding(Verdict.NOT_ASSESSED), split="holdout")

        assert report.results[0].direction is None
        assert report.metrics.n_overclaim == 0
        assert report.metrics.n_underclaim == 0

    def test_a_failing_row_is_reported_not_fatal(self) -> None:
        def boom(_label):
            raise RuntimeError("clone failed")

        labels = LabelSet(holdout=[label(Verdict.STRONG), label(Verdict.STRONG, repo="s")])
        report = run_eval(labels, boom, split="holdout")

        assert report.metrics.n_judge_failed == 2
        assert report.metrics.n_scored == 0
        assert any("failed to run" in w for w in report.warnings)

    def test_no_finding_is_its_own_outcome(self) -> None:
        labels = LabelSet(holdout=[label(Verdict.STRONG)])
        report = run_eval(labels, lambda _l: None, split="holdout")

        assert report.metrics.n_no_finding == 1
        assert report.metrics.n_scored == 0


class TestHonestyGuards:
    def test_small_corpus_is_flagged_as_directional(self) -> None:
        labels = LabelSet(holdout=[label(Verdict.STRONG)])
        report = run_eval(labels, lambda row: finding(row.verdict), split="holdout")

        assert labels.total < MIN_LABELS_FOR_EVIDENCE
        assert any("DIRECTIONAL, not evidence" in w for w in report.warnings)

    def test_calibration_is_never_claimed_at_small_n(self) -> None:
        labels = LabelSet(holdout=[label(Verdict.STRONG)])
        report = run_eval(labels, lambda row: finding(row.verdict), split="holdout")

        assert report.metrics.calibration_status == "insufficient_n"
        assert report.metrics.calibration_threshold == MIN_LABELS_FOR_CALIBRATION

    def test_report_renders_warnings_first(self) -> None:
        labels = LabelSet(holdout=[label(Verdict.INSUFFICIENT_EVIDENCE)])
        report = run_eval(labels, lambda _l: finding(Verdict.STRONG), split="holdout")
        text = format_report(report)

        assert text.index("WARNINGS") < text.index("METRICS")
        assert "OVERCLAIMED" in text
        assert "never described as 'calibrated'" in text
