"""The session<->commit join.

Each case is one way a naive join goes wrong. The negative cases matter more than the
positive ones: a false corroboration attaches supervision evidence to work that was never
supervised, which is exactly the claim a reader would be relying on.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tests.fixtures import joins
from vouch.ingest import ingest
from vouch.l2.parser import parse_log_dir
from vouch.l3.join import (
    CorroborationVerdict,
    L3Config,
    join,
    session_edits,
)


@pytest.fixture
def joined(tmp_path: Path):
    """Build the repo and its session logs together, then join them."""
    repo = tmp_path / "repo"
    shas = joins.build_repo_for_join(repo)
    joins.write_sessions(repo, tmp_path / "logs")

    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    sessions = parse_log_dir(tmp_path / "logs").sessions
    report = join(snapshot.commits, sessions, repo)

    return report, shas, repo, sessions


def verdict_for(report, sha):
    return next(r for r in report.records if r.sha == sha)


def test_session_shortly_before_a_commit_corroborates_it(joined) -> None:
    report, shas, _repo, _sessions = joined
    record = verdict_for(report, shas[0])

    assert record.verdict is CorroborationVerdict.CORROBORATED
    assert record.basis.session_ref == "S1"
    assert record.basis.path_overlap == 1.0
    assert record.basis.lag_seconds == 3600


def test_commit_with_no_session_stays_uncorroborated(joined) -> None:
    """The expected majority outcome. Absence of evidence, stated as such."""
    report, shas, _repo, _sessions = joined
    record = verdict_for(report, shas[1])

    assert record.verdict is CorroborationVerdict.UNCORROBORATED
    assert record.basis.session_ref is None
    assert record.match_score is None


def test_two_equally_good_sessions_are_ambiguous_not_a_coin_flip(joined) -> None:
    report, shas, _repo, _sessions = joined
    record = verdict_for(report, shas[3])

    assert record.verdict is CorroborationVerdict.AMBIGUOUS
    assert record.basis.n_candidates == 2
    # The runner-up is reported, so a reader can see how close the call was.
    assert record.basis.runner_up_score == record.match_score


def test_edits_after_the_commit_do_not_corroborate_it(joined) -> None:
    """Direction is a hard constraint: a commit cannot be produced by later edits."""
    report, shas, _repo, _sessions = joined
    assert verdict_for(report, shas[4]).verdict is CorroborationVerdict.UNCORROBORATED


def test_high_overlap_is_not_rejected_on_lag_alone(joined) -> None:
    """A sole editor five days out corroborates, and the lag is reported, not hidden.

    The previous scorer capped lag at 48 hours and dropped this match outright. Nothing
    else ever touched `src/f.py`, so dropping it did not withhold a *doubtful* claim — it
    manufactured "no session evidence" for a commit that had some, which is the reading a
    screener acts on. Time is now a weak prior carried in the basis, not a gate.
    """
    report, shas, _repo, _sessions = joined
    record = verdict_for(report, shas[5])

    assert record.verdict is CorroborationVerdict.CORROBORATED
    assert record.basis.session_ref == "S6"
    assert record.basis.path_overlap == 1.0
    # Five days, stated plainly, for a reader to weigh.
    assert record.basis.lag_seconds == 120 * 3600


def test_partial_overlap_at_and_below_the_floor(joined) -> None:
    report, shas, _repo, _sessions = joined

    at_floor = verdict_for(report, shas[6])  # 1 of 2 files
    below_floor = verdict_for(report, shas[7])  # 1 of 3 files

    assert at_floor.verdict is CorroborationVerdict.CORROBORATED
    assert at_floor.basis.path_overlap == 0.5
    assert below_floor.verdict is CorroborationVerdict.UNCORROBORATED


def test_lockfile_only_commit_cannot_be_corroborated(joined) -> None:
    """Noise carries no signal, so a commit made entirely of it has nothing to match on."""
    report, shas, _repo, _sessions = joined
    record = verdict_for(report, shas[8])

    assert record.verdict is CorroborationVerdict.UNCORROBORATED
    assert record.basis.n_commit_paths == 0


def test_session_from_another_project_is_excluded(joined) -> None:
    """Logs cover every project on the machine. Only this repo's paths may corroborate."""
    report, shas, _repo, _sessions = joined

    assert verdict_for(report, shas[9]).verdict is CorroborationVerdict.UNCORROBORATED
    # ...and the out-of-repo session is dropped before scoring, not scored and rejected.
    assert report.n_sessions == 12
    assert report.n_sessions_in_repo == 11
    # The drop is loud: that path is accounted for as another project's, not as a gap.
    assert report.path_coverage.n_outside == 1
    assert report.path_coverage.n_dropped == 0


def test_one_session_can_corroborate_several_commits(tmp_path: Path) -> None:
    """Many-to-many is the normal case: one session commonly produces several commits."""
    repo = tmp_path / "repo"
    shas = joins.build_repo_for_join(repo)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    records = []
    for rel, hours in [("src/a.py", -1), ("src/c.py", 47.5)]:
        records.append(
            {
                "type": "assistant",
                "sessionId": "MULTI",
                "timestamp": joins.iso(hours),
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": str(repo / rel)},
                        }
                    ],
                },
            }
        )
    records.append(
        {
            "type": "user",
            "sessionId": "MULTI",
            "timestamp": joins.iso(-1.5),
            "message": {"role": "user", "content": "do both"},
        }
    )
    (log_dir / "multi.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records)
    )

    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    report = join(snapshot.commits, parse_log_dir(log_dir).sessions, repo)

    corroborated = [
        r.sha for r in report.records if r.verdict is CorroborationVerdict.CORROBORATED
    ]
    assert set(corroborated) == {shas[0], shas[2]}


def test_clock_skew_tolerance(tmp_path: Path) -> None:
    """A commit timestamped slightly before its edits is drift, not time travel."""
    repo = tmp_path / "repo"
    shas = joins.build_repo_for_join(repo)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    # Edit five minutes AFTER the commit's timestamp — inside the 10-minute tolerance.
    (log_dir / "skew.jsonl").write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in [
                {
                    "type": "user",
                    "sessionId": "SKEW",
                    "timestamp": joins.iso(-0.5),
                    "message": {"role": "user", "content": "go"},
                },
                {
                    "type": "assistant",
                    "sessionId": "SKEW",
                    "timestamp": joins.iso(5 / 60),
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {"file_path": str(repo / "src/a.py")},
                            }
                        ],
                    },
                },
            ]
        )
    )

    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    report = join(snapshot.commits, parse_log_dir(log_dir).sessions, repo)

    assert verdict_for(report, shas[0]).verdict is CorroborationVerdict.CORROBORATED

    # ...but outside the tolerance it is rejected.
    strict = join(
        snapshot.commits,
        parse_log_dir(log_dir).sessions,
        repo,
        config=L3Config(clock_skew_minutes=1),
    )
    assert verdict_for(strict, shas[0]).verdict is CorroborationVerdict.UNCORROBORATED


def test_session_edits_are_relativized_to_the_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    joins.build_repo_for_join(repo)
    joins.write_sessions(repo, tmp_path / "logs")

    edits, coverage = session_edits(parse_log_dir(tmp_path / "logs").sessions, repo)
    by_id = {e.session_id: e for e in edits}

    assert by_id["S1"].paths == frozenset({"src/a.py"})  # not the absolute path
    assert "S10" not in by_id  # the other project never enters the join
    assert coverage.n_outside == 1  # and its path is counted, not silently discarded


def test_report_counts_and_coverage(joined) -> None:
    report, _shas, _repo, _sessions = joined

    assert report.n_commits == 11
    assert report.n_corroborated == 5
    assert report.n_ambiguous == 1
    assert report.n_uncorroborated == 5
    assert report.coverage == pytest.approx(5 / 11)
    assert report.config_fingerprint  # the thresholds behind the verdicts are recorded
    # Every edited path lands in exactly one bucket; a ledger that does not add up is the bug.
    assert report.path_coverage.n_total == 14


def test_temporal_decay_prefers_the_closer_session(tmp_path: Path) -> None:
    """When two sessions both fit, the nearer one wins by more than the margin."""
    repo = tmp_path / "repo"
    shas = joins.build_repo_for_join(repo)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for name, hours in [("NEAR", -0.25), ("FAR", -20)]:
        (log_dir / f"{name}.jsonl").write_text(
            "".join(
                json.dumps(r) + "\n"
                for r in [
                    {
                        "type": "user",
                        "sessionId": name,
                        "timestamp": joins.iso(hours - 0.1),
                        "message": {"role": "user", "content": "go"},
                    },
                    {
                        "type": "assistant",
                        "sessionId": name,
                        "timestamp": joins.iso(hours),
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {"file_path": str(repo / "src/a.py")},
                                }
                            ],
                        },
                    },
                ]
            )
        )

    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    report = join(snapshot.commits, parse_log_dir(log_dir).sessions, repo)
    record = verdict_for(report, shas[0])

    assert record.verdict is CorroborationVerdict.CORROBORATED
    assert record.basis.session_ref == "NEAR"
    assert record.basis.lag_seconds == int(timedelta(minutes=15).total_seconds())


def test_an_open_session_does_not_win_on_unrelated_later_activity(joined) -> None:
    """The clamp, and why the temporal term was doing no work.

    `S11long` touched `src/p.py` thirty hours before the commit and then kept going, ending
    with an edit to an *unrelated* file after the commit landed. The previous scorer
    measured lag from the session envelope and clamped it to zero whenever the session was
    still open at commit time, so `S11long` scored a perfect temporal 1.0 — earned entirely
    by activity that had nothing to do with this commit — and beat `S11short`, which had
    edited `src/p.py` an hour earlier and actually produced it.

    That clamp is why roughly 40% of the match score did no discriminating: any session
    spanning the commit scored full marks on it. Attribution replaces it — the path goes to
    whoever touched *that path* last, so unrelated later activity buys nothing.
    """
    report, shas, _repo, _sessions = joined
    record = verdict_for(report, shas[10])

    assert record.verdict is CorroborationVerdict.CORROBORATED
    assert record.basis.session_ref == "S11short"
    # S11long holds no path at all, so this cannot degrade into an `ambiguous` coin flip.
    assert record.basis.n_candidates == 1
    assert record.basis.lag_seconds == 3600
