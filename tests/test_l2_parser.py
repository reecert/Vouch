"""Session log parsing — and the ways it is allowed to fail.

The log format is internal to Claude Code and can change without notice. These tests pin
the two behaviours that matter when it does: unknown input is *counted*, and past a
threshold the parse degrades instead of producing plausible-looking numbers.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.fixtures import logs
from vouch.l2.parser import (
    EventKind,
    parse_log_dir,
    parse_session_file,
)


def test_tool_results_are_not_counted_as_prompts(tmp_path: Path) -> None:
    """Most `user` records are tool results. Counting them as prompts is off by ~15x."""
    path = logs.write_session(
        tmp_path / "s.jsonl",
        [
            logs.prompt("real prompt", 0),
            logs.tool_result(1),
            logs.tool_result(2),
            logs.tool_result(3),
        ],
    )
    session = parse_session_file(path)

    assert len(session.of_kind(EventKind.HUMAN_PROMPT)) == 1


def test_plan_signal_read_from_permission_mode(tmp_path: Path) -> None:
    """`mode` is always "normal"; the plan state lives in `permission-mode`."""
    path = logs.write_session(tmp_path / "s.jsonl", logs.healthy_session())
    session = parse_session_file(path)

    assert len(session.of_kind(EventKind.PLAN_SIGNAL)) == 1


def test_untimestamped_records_keep_their_place(tmp_path: Path) -> None:
    """`permission-mode` carries no timestamp — ordering on time would drop it entirely."""
    path = logs.write_session(tmp_path / "s.jsonl", logs.healthy_session())
    session = parse_session_file(path)

    plan = session.of_kind(EventKind.PLAN_SIGNAL)[0]
    first_edit = next(e for e in session.events if e.tool == "Edit")

    assert plan.at is None  # no timestamp on the record, as in the real logs
    assert plan.index < first_edit.index  # ...and it still sequences correctly


def test_edit_paths_and_commands_are_captured_locally(tmp_path: Path) -> None:
    """L3 needs these for the local join. They never reach the payload (see test_l2_payload)."""
    path = logs.write_session(tmp_path / "s.jsonl", logs.healthy_session())
    session = parse_session_file(path)

    edits = [e for e in session.events if e.tool == "Edit"]
    bashes = [e for e in session.events if e.tool == "Bash"]

    assert edits[0].paths == ("src/app.py",)
    assert bashes[0].command == "pytest -q"
    assert bashes[0].verifies is True


def test_verification_detection(tmp_path: Path) -> None:
    commands = {
        "pytest -q": True,
        "npm run build": True,
        "cargo test --all": True,
        "go test ./...": True,
        "ruff check .": True,
        "git status": False,
        "ls -la": False,
        "cat README.md": False,
    }
    path = logs.write_session(
        tmp_path / "s.jsonl", [logs.bash(c, i) for i, c in enumerate(commands)]
    )
    session = parse_session_file(path)

    assert {e.command: e.verifies for e in session.events} == commands


def test_interrupts_and_denials(tmp_path: Path) -> None:
    path = logs.write_session(
        tmp_path / "s.jsonl", [logs.prompt(), logs.interrupt(1), logs.denial(2)]
    )
    session = parse_session_file(path)

    assert len(session.of_kind(EventKind.INTERRUPT)) == 1
    assert len(session.of_kind(EventKind.DENIAL)) == 1


def test_mcp_server_extracted_locally_only(tmp_path: Path) -> None:
    path = logs.write_session(
        tmp_path / "s.jsonl", [logs.tool_use("mcp__AcmeCorp__query", 0)]
    )
    session = parse_session_file(path)
    event = session.events[0]

    assert event.is_mcp is True
    assert event.mcp_server == "AcmeCorp"  # local; only the count is uploaded


def test_unknown_record_types_are_counted_not_dropped_silently(tmp_path: Path) -> None:
    """A record type shipped tomorrow must be visible as unrecognised, not invisible."""
    path = logs.write_session(
        tmp_path / "s.jsonl",
        [
            logs.prompt(),
            logs.tool_use("Read", 1),
            {"type": "some-future-record", "sessionId": logs.SESSION_ID},
        ],
    )
    session = parse_session_file(path)

    assert session.n_unrecognised == 1
    assert session.n_records == 3


def test_malformed_lines_are_counted(tmp_path: Path) -> None:
    path = logs.write_lines(
        tmp_path / "s.jsonl",
        [
            json.dumps(logs.prompt()),
            "{not json at all",
            json.dumps(logs.tool_use("Read", 1)),
            "[]",  # valid JSON, wrong shape
        ],
    )
    session = parse_session_file(path)

    assert session.n_unparsed == 2
    assert len(session.of_kind(EventKind.HUMAN_PROMPT)) == 1


def test_non_session_files_are_skipped(tmp_path: Path) -> None:
    """A JSONL file without user/assistant records is not a session log."""
    logs.write_session(tmp_path / "notes.jsonl", [{"type": "mode", "mode": "normal"}])
    result = parse_log_dir(tmp_path)

    assert result.n_files == 1
    assert result.n_files_skipped == 1
    assert result.degraded is True


def test_missing_log_dir_degrades_rather_than_raising(tmp_path: Path) -> None:
    result = parse_log_dir(tmp_path / "does-not-exist")

    assert result.degraded is True
    assert result.sessions == []


def test_mostly_unparseable_input_degrades(tmp_path: Path) -> None:
    """The format changed under us. Say so; do not derive numbers from the wreckage."""
    lines = [json.dumps(logs.prompt()), json.dumps(logs.tool_use("Read", 1))]
    lines += ["<<< not json >>>"] * 30
    logs.write_lines(tmp_path / "s.jsonl", lines)

    result = parse_log_dir(tmp_path)

    assert result.degraded is True
    assert "log format has probably changed" in result.degraded_reason
    assert result.unparsed_share > 0.9


def test_healthy_dir_is_not_degraded(tmp_path: Path) -> None:
    for i in range(3):
        logs.write_session(tmp_path / f"s{i}.jsonl", logs.healthy_session(i * 10))
    result = parse_log_dir(tmp_path)

    assert result.degraded is False
    assert len(result.sessions) == 3
    assert result.n_unparsed == 0
