"""Session identity and reproducibility.

Two defects, one theme — the same inputs have to produce the same document.

* **A subagent transcript was counted as a session.** Claude Code writes delegated work to
  `<sid>/subagents/*.jsonl`, and the parser treated each file as its own session. Every
  per-session denominator was inflated by however much delegation happened, which is a
  property of how the work was done, not of the person doing it.
* **The logs were read live.** `vouch` is normally run from inside a session that is still
  appending to the directory being parsed, so the CLI observed its own writes: two runs
  seconds apart saw different bytes and minted different `profile_id`s for the same work.
  A share link that stops matching the profile it was generated from breaks the frozen
  snapshot promise L5 makes to a reader.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures import logs
from vouch.l2.metrics import derive_metrics
from vouch.l2.parser import MAIN_STREAM, parse_log_dir, parse_snapshot
from vouch.l2.snapshot import open_snapshot, snapshot_sessions

SID = "11111111-2222-3333-4444-555555555555"


def _log_dir(tmp_path: Path) -> Path:
    root = tmp_path / "projects" / "-Users-someone-thing"
    logs.write_session(root / f"{SID}.jsonl", logs.healthy_session())
    return tmp_path / "projects"


# --- subagents are not sessions ----------------------------------------------------------


def test_a_subagent_transcript_folds_into_its_parent(tmp_path: Path) -> None:
    root = _log_dir(tmp_path)
    logs.write_session(
        root / "-Users-someone-thing" / SID / "subagents" / "explorer.jsonl",
        logs.unverified_session(minute_base=10),
    )

    result = parse_log_dir(root)

    assert result.n_files == 2
    assert len(result.sessions) == 1  # not two
    assert result.n_subagent_files == 1
    session = result.sessions[0]
    assert session.session_id == SID
    assert session.n_subagents == 1


def test_per_session_denominators_do_not_double_count(tmp_path: Path) -> None:
    """The number that was wrong. One session's work, delegated, is still one session."""
    root = _log_dir(tmp_path)
    before = derive_metrics(parse_log_dir(root)).n_sessions

    logs.write_session(
        root / "-Users-someone-thing" / SID / "subagents" / "explorer.jsonl",
        logs.unverified_session(minute_base=10),
    )
    after = derive_metrics(parse_log_dir(root))

    assert before == 1
    assert after.n_sessions == 1
    # ...and the delegated edits are still counted, just not as another session.
    assert after.n_records > 0


def test_a_subagents_edits_are_kept_on_their_own_stream(tmp_path: Path) -> None:
    """Merged, not interleaved. The two transcripts ran concurrently."""
    root = _log_dir(tmp_path)
    logs.write_session(
        root / "-Users-someone-thing" / SID / "subagents" / "explorer.jsonl",
        logs.unverified_session(minute_base=10),
    )

    session = parse_log_dir(root).sessions[0]
    streams = {e.stream for e in session.events}

    assert streams == {MAIN_STREAM, "explorer"}
    assert len(session.streams()) == 2


def test_an_orphaned_subagent_still_reports_as_one_session(tmp_path: Path) -> None:
    """The parent's own file is missing. The work happened; it is not two sessions."""
    root = tmp_path / "projects"
    logs.write_session(
        root / "-Users-someone-thing" / SID / "subagents" / "explorer.jsonl",
        logs.healthy_session(),
    )

    result = parse_log_dir(root)

    assert len(result.sessions) == 1
    assert result.sessions[0].session_id == SID


# --- the snapshot -------------------------------------------------------------------------


def test_the_snapshot_is_a_copy_and_does_not_move_under_the_reader(
    tmp_path: Path,
) -> None:
    """The core property: appending to the live log cannot change what was already read."""
    root = _log_dir(tmp_path)
    live = root / "-Users-someone-thing" / f"{SID}.jsonl"

    frozen = snapshot_sessions(root, tmp_path / "cache")
    first = parse_snapshot(frozen)

    with live.open("a") as fh:
        fh.write(json.dumps({"type": "user", "sessionId": SID, "message": {}}) + "\n")

    second = parse_snapshot(frozen)

    assert first.n_records == second.n_records
    assert frozen.root != root


def test_two_runs_at_the_same_as_of_are_byte_identical(tmp_path: Path) -> None:
    """The acceptance criterion. Same as-of in, same derived metrics out."""
    root = _log_dir(tmp_path)
    cache = tmp_path / "cache"

    first = snapshot_sessions(root, cache)
    metrics_a = derive_metrics(parse_snapshot(first))

    # The live directory grows between the two runs, exactly as it does in practice.
    with (root / "-Users-someone-thing" / f"{SID}.jsonl").open("a") as fh:
        fh.write(json.dumps(logs.edit("src/late.py", minute=59)) + "\n")

    reopened = open_snapshot(first.digest, cache)
    metrics_b = derive_metrics(parse_snapshot(reopened))

    assert metrics_a.model_dump_json() == metrics_b.model_dump_json()
    assert metrics_a.as_of == metrics_b.as_of


def test_a_new_snapshot_of_changed_logs_gets_a_different_digest(tmp_path: Path) -> None:
    """Reproducibility must not mean staleness — a changed directory is a changed as-of."""
    root = _log_dir(tmp_path)
    cache = tmp_path / "cache"
    first = snapshot_sessions(root, cache)

    with (root / "-Users-someone-thing" / f"{SID}.jsonl").open("a") as fh:
        fh.write(json.dumps(logs.edit("src/late.py", minute=59)) + "\n")
    second = snapshot_sessions(root, cache)

    assert first.digest != second.digest
    assert second.reused is False


def test_an_unchanged_directory_reuses_its_snapshot(tmp_path: Path) -> None:
    root = _log_dir(tmp_path)
    cache = tmp_path / "cache"

    first = snapshot_sessions(root, cache)
    second = snapshot_sessions(root, cache)

    assert first.digest == second.digest
    assert second.reused is True


def test_a_tampered_snapshot_refuses_to_reproduce_a_run(tmp_path: Path) -> None:
    """Reproducing the *name* of a run whose contents changed is worse than not reproducing."""
    root = _log_dir(tmp_path)
    cache = tmp_path / "cache"
    frozen = snapshot_sessions(root, cache)

    copied = next(frozen.root.rglob("*.jsonl"))
    with copied.open("a") as fh:
        fh.write(json.dumps({"type": "user", "sessionId": SID, "message": {}}) + "\n")

    with pytest.raises(ValueError, match="contents changed"):
        open_snapshot(frozen.digest, cache)


def test_an_absent_log_directory_snapshots_to_empty_rather_than_raising(
    tmp_path: Path,
) -> None:
    """"You have no session logs" is a state the parser already reports, not a crash."""
    frozen = snapshot_sessions(tmp_path / "nope", tmp_path / "cache")

    assert frozen.n_files == 0
    assert parse_snapshot(frozen).degraded is True


def test_the_profile_id_is_stable_across_runs_at_the_same_as_of(tmp_path: Path) -> None:
    """The acceptance criterion, at the artifact a reader actually receives.

    `profile_id` is the content hash of everything except the wall-clock stamp, and it is
    what a share link resolves to. If it moves when nothing about the work moved, the link
    a candidate sent yesterday points at a document that no longer exists.
    """
    from vouch.l1.facts import Identity, RepoFacts
    from vouch.l5.profile import build_profile

    root = _log_dir(tmp_path)
    cache = tmp_path / "cache"
    facts = RepoFacts(
        repo="r", head_sha="a" * 40, subject=Identity(canonical_email="a@b.c")
    )

    frozen = snapshot_sessions(root, cache)
    first = build_profile(
        facts,
        metrics=derive_metrics(parse_snapshot(frozen)),
        session_digest=frozen.digest,
    )

    with (root / "-Users-someone-thing" / f"{SID}.jsonl").open("a") as fh:
        fh.write(json.dumps(logs.edit("src/late.py", minute=59)) + "\n")

    second = build_profile(
        facts,
        metrics=derive_metrics(parse_snapshot(open_snapshot(frozen.digest, cache))),
        session_digest=frozen.digest,
    )

    assert first.profile_id == second.profile_id
    assert first.provenance.session_snapshot == frozen.digest

    # ...and a genuinely different as-of is a genuinely different document, not a silent
    # overwrite of the old one.
    moved = snapshot_sessions(root, cache)
    third = build_profile(
        facts,
        metrics=derive_metrics(parse_snapshot(moved)),
        session_digest=moved.digest,
    )
    assert third.profile_id != first.profile_id
