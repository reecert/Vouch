"""Synthetic Claude Code session logs.

Modelled on the real format (17,187 records across 54 files), but
built here so the suite runs offline and CI needs no session history.

The shapes that matter and are easy to get wrong:

* Most ``user`` records are **tool results**, not prompts — 3,779 of 4,044 in the sample.
  A parser that counts every ``user`` record as a prompt is wrong by an order of magnitude.
* ``mode`` records are always ``normal``; the plan state lives in ``permission-mode``.
* ``mode`` and ``permission-mode`` records carry **no timestamp**, which is why the parser
  sequences on file order.
"""
from __future__ import annotations

import json
from pathlib import Path

SESSION_ID = "0000-session"


def _at(minute: int) -> str:
    return f"2026-07-20T10:{minute:02d}:00.000Z"


def prompt(text: str = "do the thing", minute: int = 0) -> dict:
    """A human-typed prompt."""
    return {
        "type": "user",
        "sessionId": SESSION_ID,
        "timestamp": _at(minute),
        "message": {"role": "user", "content": text},
    }


def tool_result(minute: int = 0) -> dict:
    """A tool result — a `user` record that is emphatically not a prompt."""
    return {
        "type": "user",
        "sessionId": SESSION_ID,
        "timestamp": _at(minute),
        "toolUseResult": {"stdout": "ok"},
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": "ok"}],
        },
    }


def tool_use(name: str, minute: int = 0, **params) -> dict:
    """An assistant record invoking one tool."""
    return {
        "type": "assistant",
        "sessionId": SESSION_ID,
        "timestamp": _at(minute),
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": params}],
        },
    }


def edit(path: str = "src/app.py", minute: int = 0) -> dict:
    return tool_use("Edit", minute, file_path=path)


def bash(command: str, minute: int = 0) -> dict:
    return tool_use("Bash", minute, command=command)


def plan_mode() -> dict:
    """A plan-mode switch. Note: no timestamp, exactly like the real record."""
    return {"type": "permission-mode", "permissionMode": "plan", "sessionId": SESSION_ID}


def normal_mode() -> dict:
    return {"type": "mode", "mode": "normal", "sessionId": SESSION_ID}


def interrupt(minute: int = 0) -> dict:
    return {
        "type": "user",
        "sessionId": SESSION_ID,
        "timestamp": _at(minute),
        "interruptedMessageId": "abc",
        "message": {"role": "user", "content": [{"type": "tool_result"}]},
    }


def denial(minute: int = 0) -> dict:
    return {
        "type": "user",
        "sessionId": SESSION_ID,
        "timestamp": _at(minute),
        "toolDenialKind": "user-rejected",
        "message": {"role": "user", "content": [{"type": "tool_result"}]},
    }


def write_session(path: Path, records: list[dict]) -> Path:
    """Write one session file. Records are written in order — order is the clock.

    Every record is stamped with a session id taken from the filename, as the real logs
    are. The builders above share one placeholder id for readability; leaving it in place
    would make every fixture file claim to be the *same* session, which the parser now
    correctly merges — and which would quietly turn a five-session fixture into a
    one-session one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = [{**r, "sessionId": path.stem} for r in records]
    path.write_text("".join(json.dumps(r) + "\n" for r in stamped))
    return path


def write_lines(path: Path, lines: list[str]) -> Path:
    """Write raw lines, for malformed-input tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines))
    return path


def healthy_session(minute_base: int = 0) -> list[dict]:
    """Plan, then edit, then verify — the shape every rate should score well on."""
    return [
        normal_mode(),
        prompt("add the feature", minute_base),
        plan_mode(),
        tool_use("Read", minute_base + 1, file_path="src/app.py"),
        edit("src/app.py", minute_base + 2),
        tool_result(minute_base + 2),
        bash("pytest -q", minute_base + 3),
        tool_result(minute_base + 3),
    ]


def unverified_session(minute_base: int = 0) -> list[dict]:
    """Edits, then the human moves on without anything being checked."""
    return [
        prompt("tweak it", minute_base),
        edit("src/other.py", minute_base + 1),
        tool_result(minute_base + 1),
        prompt("now do something else", minute_base + 2),
        edit("src/third.py", minute_base + 3),
    ]
