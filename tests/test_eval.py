"""The eval harness — and the numbers it refuses to print.

The v0 harness's disciplines carry over: refuse an empty holdout, warn below the evidence
threshold, never claim "calibrated". What is new is that a disagreement has a *direction*,
because overclaiming and underclaiming are not the same failure.
"""
from __future__ import annotations

import re
import subprocess
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


def label(
    verdict: Verdict, dimension=DimensionKey.OWNERSHIP, corpus_id="hunter"
) -> DimensionLabel:
    return DimensionLabel(
        corpus_id=corpus_id,
        dimension=dimension,
        verdict=verdict,
        reason="returns to their own defects with tests, see the commit trail",
        leaned_on=["ownership_loop"],
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
                corpus_id="hunter",
                dimension=DimensionKey.OWNERSHIP,
                verdict=Verdict.STRONG,
                reason="   ",
                leaned_on=["ownership_loop"],
            )

    def test_leaned_on_is_required(self) -> None:
        """`ownership` rests on three facts and no rule says how to combine them.

        Rather than invent a weighting — which would bake one person's intuition into the
        ground truth and then score the judge against it — the label records which measure
        the verdict actually rested on, so the underspecification is visible in the corpus.
        """
        with pytest.raises(ValidationError):
            DimensionLabel(
                corpus_id="hunter",
                dimension=DimensionKey.OWNERSHIP,
                verdict=Verdict.STRONG,
                reason="returns to their own defects with tests",
            )

    def test_leaned_on_must_name_a_measure_this_dimension_rests_on(self) -> None:
        """Free text here would be unanalysable, which defeats the point of collecting it."""
        with pytest.raises(ValidationError, match="does not rest on"):
            DimensionLabel(
                corpus_id="hunter",
                dimension=DimensionKey.OWNERSHIP,
                verdict=Verdict.STRONG,
                reason="returns to their own defects with tests",
                leaned_on=["plan_before_execute"],  # a different dimension's metric
            )

    def test_a_multi_fact_label_may_name_more_than_one(self) -> None:
        """Two labellers leaning on different facts is the finding, not a defect to hide."""
        row = DimensionLabel(
            corpus_id="httpx",
            dimension=DimensionKey.OWNERSHIP,
            verdict=Verdict.LIMITED,
            reason="the self-fix rate is high but every pair is a squash artefact",
            leaned_on=["ownership_loop", "followup_latency"],
        )
        assert row.leaned_on == ["ownership_loop", "followup_latency"]

    def test_none_cannot_share_the_field_with_a_measure(self) -> None:
        with pytest.raises(ValidationError, match="cannot share"):
            DimensionLabel(
                corpus_id="hunter",
                dimension=DimensionKey.OWNERSHIP,
                verdict=Verdict.INSUFFICIENT_EVIDENCE,
                reason="nothing in the trail speaks to this",
                leaned_on=["none", "revert_rate"],
            )

    def test_insufficient_evidence_is_a_valid_label(self) -> None:
        """"A careful human would decline here" is the judgement we most need reproduced."""
        row = label(Verdict.INSUFFICIENT_EVIDENCE)
        assert row.verdict is Verdict.INSUFFICIENT_EVIDENCE

    def test_holdout_leak_is_rejected(self, tmp_path: Path) -> None:
        """A row tuned on in train makes the holdout number meaningless."""
        row = {
            "corpus_id": "hunter",
            "dimension": "ownership",
            "verdict": "strong",
            "reason": "because of the commit trail",
            "leaned_on": ["ownership_loop"],
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

        It now serves a second purpose. Labels are one person's judgements about named
        engineers who did not ask to be judged, so a populated set must not ship in the
        public repository — real labelling goes in `eval/labels.local.yaml`, which is
        gitignored. The tracked file staying empty is what keeps that true.
        """
        labels = load_labels(REPO_ROOT / "eval" / "labels.yaml")
        assert labels.total == 0

    def test_a_local_label_set_cannot_be_committed_by_accident(self) -> None:
        """The escape hatch for real labelling is ignored by git, not merely conventional."""
        ignored = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "eval/labels.local.yaml"],
            capture_output=True,
            text=True,
        )
        assert ignored.returncode == 0, (
            "eval/labels.local.yaml is not gitignored — a populated label set would be "
            "one `git add .` away from a public repository."
        )


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
        labels = LabelSet(holdout=[label(Verdict.STRONG), label(Verdict.MODERATE, corpus_id="svcs")])
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
        """`not_collected` is not on the ordinal scale, so a mismatch has no direction."""
        labels = LabelSet(holdout=[label(Verdict.STRONG)])
        report = run_eval(labels, lambda _l: finding(Verdict.NOT_COLLECTED), split="holdout")

        assert report.results[0].direction is None
        assert report.metrics.n_overclaim == 0
        assert report.metrics.n_underclaim == 0

    def test_a_failing_row_is_reported_not_fatal(self) -> None:
        def boom(_label):
            raise RuntimeError("clone failed")

        labels = LabelSet(holdout=[label(Verdict.STRONG), label(Verdict.STRONG, corpus_id="svcs")])
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


class TestLabelPrivacy:
    """No third-party address may enter this repository, in any field or any comment.

    `eval/repos.yaml` already stores a selector rather than an address, for exactly this
    reason. A label file keyed on `(repo, author)` would have undone that guarantee in one
    line — and in the file whose entire purpose is to record judgements about the people it
    names, which is the worst possible place to keep one.
    """

    def test_a_label_has_nowhere_to_put_an_address(self) -> None:
        """The guarantee is the absent field, not the discipline of whoever fills it in."""
        fields = set(DimensionLabel.model_fields)
        assert "author" not in fields
        assert "aliases" not in fields
        assert "repo" not in fields
        assert "corpus_id" in fields

    def test_an_address_as_a_corpus_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="email address"):
            DimensionLabel(
                corpus_id="someone@example.com",
                dimension=DimensionKey.OWNERSHIP,
                verdict=Verdict.STRONG,
                reason="fixes their own defects, see the commit trail",
                leaned_on=["ownership_loop"],
            )

    def test_an_address_hidden_in_a_reason_is_rejected(self) -> None:
        """`reason` is hand-written free text — the one place a leak would actually happen."""
        with pytest.raises(ValidationError, match="email address"):
            DimensionLabel(
                corpus_id="hunter",
                dimension=DimensionKey.OWNERSHIP,
                verdict=Verdict.STRONG,
                reason="someone@example.com returns to their own defects with tests",
                leaned_on=["ownership_loop"],
            )

    def test_an_address_in_a_comment_is_rejected(self, tmp_path: Path) -> None:
        """The schema never sees a comment, so the raw bytes are checked before parsing."""
        path = tmp_path / "labels.yaml"
        path.write_text("# subject is someone@example.com\ntrain: []\nholdout: []\n")

        with pytest.raises(LabelValidationError, match="email-shaped"):
            load_labels(path)

    def test_an_unknown_corpus_id_is_rejected(self, tmp_path: Path) -> None:
        """An id is only a join key if it joins."""
        path = tmp_path / "labels.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "train": [
                        {
                            "corpus_id": "no-such-row",
                            "dimension": "ownership",
                            "verdict": "strong",
                            "reason": "returns to their own defects with tests",
                            "leaned_on": ["ownership_loop"],
                        }
                    ],
                    "holdout": [],
                }
            )
        )

        with pytest.raises(LabelValidationError, match="does not exist"):
            load_labels(path, known_ids={"hunter", "svcs"})

    def test_the_shipped_label_file_is_clean(self) -> None:
        """The real one, checked in CI rather than trusted."""
        text = (REPO_ROOT / "eval" / "labels.yaml").read_text()
        assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)

    def test_the_corpus_file_is_clean_too(self) -> None:
        text = (REPO_ROOT / "eval" / "repos.yaml").read_text()
        assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)

    def test_no_third_party_address_survives_in_any_committed_file(self) -> None:
        """The file being clean going forward is not sufficient — history is forever.

        A third-party address (a maintainer's, used as a `--author` example in the v0
        README) reached this repository's history at the import commit and was later
        deleted from the tree. Deleting it changed nothing: the old blob was still readable
        at its SHA, and still pushed. The history was rewritten; this test is what stops it
        coming back.

        Scope is **blob contents** — every version of every file ever committed. Commit
        *metadata* is deliberately out of scope: git cannot record a commit without an
        author address, so the repo owner's own identity is in every commit object by
        construction and is not a third party's to protect.
        """
        allowed = {
            # Reserved example domains and our own synthetic fixture identities. Anything
            # outside this set is presumed to belong to a real person.
            "example.com",
            "example.dev",
            "example.org",
            "personal.dev",
            "users.noreply.github.com",
            "x.com",
            "y.com",
            "b.com",
            "corp.com",
            "whitesourcesoftware.com",
        }
        objects = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-list", "--objects", "--all"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        shas = sorted(
            {o for o in objects if len(o) == 40 and all(c in "0123456789abcdef" for c in o)}
        )

        # `--batch-check` first so only blobs are paid for; some repos carry large trees.
        kinds = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "--batch-check"],
            input="\n".join(shas),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        blobs = [
            line.split()[0] for line in kinds.splitlines() if line.split()[1:2] == ["blob"]
        ]

        cat = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "--batch"],
            input="\n".join(blobs),
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout

        found = {
            m.group(0).split("@")[1].lower()
            for m in re.finditer(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cat)
        }
        leaked = sorted(d for d in found if d not in allowed)
        assert leaked == [], (
            f"real-looking email domain(s) in committed file content: {leaked}. A "
            "third-party address in this repository's history is exactly what the "
            "selector scheme in eval/repos.yaml exists to prevent, and deleting it from "
            "the working tree does not remove it from history."
        )
