"""Scoring the join against ground truth — and refusing to overclaim from it."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures import joins
from vouch.ingest import ingest
from vouch.l2.parser import parse_log_dir
from vouch.l3.accuracy import (
    MIN_LABELS_FOR_ACCURACY,
    JoinLabel,
    JoinOutcome,
    score_join,
)
from vouch.l3.join import (
    Corroboration,
    CorroborationReport,
    CorroborationVerdict,
    MatchBasis,
    join,
)


@pytest.fixture
def scored(tmp_path: Path):
    repo = tmp_path / "repo"
    shas = joins.build_repo_for_join(repo)
    joins.write_sessions(repo, tmp_path / "logs")

    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    sessions = parse_log_dir(tmp_path / "logs").sessions
    report = join(snapshot.commits, sessions, repo)
    return score_join(report, joins.labels(shas)), shas


def test_join_is_correct_on_every_labelled_case(scored) -> None:
    metrics, _shas = scored

    assert metrics.true_positive == 5
    assert metrics.true_negative == 5
    assert metrics.ambiguous == 1
    assert metrics.wrong_session == 0
    assert metrics.false_positive == 0
    assert metrics.false_negative == 0


def test_accuracy_is_reported_but_not_claimed_as_evidence(scored) -> None:
    """1.0/1.0 on eleven labels is not a result. The harness says so itself."""
    metrics, _shas = scored

    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.n_labelled == 11
    assert metrics.status == "insufficient_n"
    assert metrics.is_evidence is False
    assert metrics.threshold == MIN_LABELS_FOR_ACCURACY


def test_every_labelled_commit_gets_an_outcome(scored) -> None:
    metrics, shas = scored
    assert set(metrics.outcomes) == set(shas)
    assert JoinOutcome.UNLABELLED not in metrics.outcomes.values()


def _report(*rows: tuple[str, CorroborationVerdict, str | None]) -> CorroborationReport:
    return CorroborationReport(
        n_commits=len(rows),
        records=[
            Corroboration(
                sha=sha,
                verdict=verdict,
                match_score=0.9 if session else None,
                basis=MatchBasis(session_ref=session),
            )
            for sha, verdict, session in rows
        ],
    )


def test_matching_the_wrong_session_is_not_a_partial_success() -> None:
    """Corroborating to the wrong session is an incorrect claim, not a near miss."""
    report = _report(("aaa", CorroborationVerdict.CORROBORATED, "WRONG"))
    metrics = score_join(report, [JoinLabel(sha="aaa", session_id="RIGHT")])

    assert metrics.wrong_session == 1
    assert metrics.true_positive == 0
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0


def test_corroborating_a_commit_with_no_session_is_a_false_positive() -> None:
    report = _report(("aaa", CorroborationVerdict.CORROBORATED, "S1"))
    metrics = score_join(report, [JoinLabel(sha="aaa", session_id=None)])

    assert metrics.false_positive == 1
    assert metrics.precision == 0.0


def test_ambiguous_cannot_be_used_to_inflate_recall() -> None:
    """Answering "ambiguous" everywhere must not look like a perfect join.

    Ambiguity is excluded from precision — declining to choose is not a claim — but stays
    in the recall denominator, which is every commit that genuinely had a session.
    """
    report = _report(
        ("aaa", CorroborationVerdict.AMBIGUOUS, None),
        ("bbb", CorroborationVerdict.AMBIGUOUS, None),
    )
    metrics = score_join(
        report,
        [
            JoinLabel(sha="aaa", session_id="S1"),
            JoinLabel(sha="bbb", session_id="S2"),
        ],
    )

    assert metrics.ambiguous == 2
    assert metrics.recall == 0.0
    assert metrics.precision is None  # no claims were made, so precision is undefined


def test_missing_the_join_entirely_is_a_false_negative() -> None:
    report = _report(("aaa", CorroborationVerdict.UNCORROBORATED, None))
    metrics = score_join(report, [JoinLabel(sha="aaa", session_id="S1")])

    assert metrics.false_negative == 1
    assert metrics.recall == 0.0


def test_status_flips_to_measured_once_there_are_enough_labels() -> None:
    rows = [
        (f"sha{i:03d}", CorroborationVerdict.UNCORROBORATED, None)
        for i in range(MIN_LABELS_FOR_ACCURACY)
    ]
    metrics = score_join(
        _report(*rows), [JoinLabel(sha=sha, session_id=None) for sha, _, _ in rows]
    )

    assert metrics.n_labelled == MIN_LABELS_FOR_ACCURACY
    assert metrics.status == "measured"
    assert metrics.is_evidence is True
