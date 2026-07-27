"""A labelled session<->commit correspondence, known by construction.

Each case below pins one behaviour of the join, and the ground truth is not inferred — the
repo and the session logs are generated together, so we know which session produced which
commit because we decided it.

The cases deliberately include the ones that would flatter a naive join: a session that
touched the files only *after* the commit, two sessions that fit equally well, a session
separated from its commit by days, and partial file overlap on either side of the floor.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from tests.fixtures.builder import Step, build_repo
from vouch.l3.accuracy import JoinLabel

ALICE = ("Alice Dev", "alice@example.com")
_EPOCH = datetime.fromisoformat("2024-03-01T12:00:00+00:00")


def at(hours: float) -> datetime:
    return _EPOCH + timedelta(hours=hours)


def iso(hours: float) -> str:
    return at(hours).isoformat()


def _src(marker: str) -> str:
    return f"value = {marker}\n"


# (commit subject, files, commit time in hours from epoch)
_COMMITS: list[tuple[str, list[str], float]] = [
    ("feat: add a", ["src/a.py"], 0),
    ("feat: add b", ["src/b.py"], 24),
    ("feat: add c", ["src/c.py"], 48),
    ("feat: add d", ["src/d.py"], 72),
    ("feat: add e", ["src/e.py"], 96),
    ("feat: add f", ["src/f.py"], 120),
    ("feat: add g and h", ["src/g.py", "src/h.py"], 144),
    ("feat: add i j k", ["src/i.py", "src/j.py", "src/k.py"], 168),
    ("chore: bump deps", ["package-lock.json"], 192),
    ("feat: add m", ["src/m.py"], 216),
    ("feat: add p", ["src/p.py"], 240),
]


def build_repo_for_join(path: Path) -> list[str]:
    """Build the repo half. Returns commit SHAs in order."""
    steps = [
        Step(ALICE, iso(hours), subject, {f: _src(str(i)) for f in files})
        for i, (subject, files, hours) in enumerate(_COMMITS)
    ]
    return build_repo(path, steps)


def _session(session_id: str, repo: Path, edits: list[tuple[str, float]]) -> list[dict]:
    """A session log whose Edit calls carry absolute paths, as the real logs do."""
    records: list[dict] = [
        {
            "type": "user",
            "sessionId": session_id,
            "timestamp": iso(edits[0][1] - 0.1),
            "message": {"role": "user", "content": "work on it"},
        }
    ]
    for rel, hours in edits:
        records.append(
            {
                "type": "assistant",
                "sessionId": session_id,
                "timestamp": iso(hours),
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
    return records


def write_sessions(repo: Path, log_dir: Path) -> None:
    """Write the session half. Timings are relative to the commits above."""
    plans: dict[str, list[tuple[str, float]]] = {
        # C1: edited an hour before the commit -> corroborated to S1.
        "S1": [("src/a.py", -1)],
        # C2 (src/b.py): no session at all -> must stay uncorroborated.
        # C3: edited 30 minutes before -> corroborated to S3.
        "S3": [("src/c.py", 47.5)],
        # C4: two sessions fit equally well -> ambiguous, not a coin flip.
        "S4a": [("src/d.py", 71.0)],
        "S4b": [("src/d.py", 71.0)],
        # C5: edited only AFTER the commit -> direction constraint rejects it.
        "S5": [("src/e.py", 100)],
        # C6: edited five days before -> beyond max_lag.
        "S6": [("src/f.py", 0)],
        # C7: touched 1 of the commit's 2 files -> overlap 0.5, at the floor.
        "S7": [("src/g.py", 143)],
        # C8: touched 1 of the commit's 3 files -> overlap 0.33, below the floor.
        "S8": [("src/i.py", 167)],
        # C9 is lockfile-only: no significant paths, so nothing can corroborate it.
        "S9": [("package-lock.json", 191)],
        # C10: a session in a different project entirely -> must not corroborate.
        "S10": [("../elsewhere/src/m.py", 215)],
        # C11: the open-session case. S11long was still running when the commit landed —
        # it edited an unrelated file after it — but its own touch of src/p.py is thirty
        # hours stale, and S11short edited src/p.py an hour before the commit. S11short
        # produced this commit. The previous scorer measured lag from the session envelope
        # and clamped it to zero for anything still open, so S11long scored a perfect
        # temporal 1.0 on the strength of unrelated later activity and took the commit.
        "S11long": [("src/p.py", 210), ("src/q.py", 200), ("src/q.py", 260)],
        "S11short": [("src/p.py", 239)],
    }
    log_dir.mkdir(parents=True, exist_ok=True)
    for session_id, edits in plans.items():
        records = _session(session_id, repo, edits)
        (log_dir / f"{session_id}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in records)
        )


def labels(shas: list[str]) -> list[JoinLabel]:
    """Ground truth, in commit order. ``None`` means no session produced this commit.

    Ground truth here is what **construction** knows, not what any scorer would say. One
    row used to violate that and is corrected below (`src/f.py`): it was labelled `None`
    because the join of the day capped lag at 48 hours, which made the labelled set score
    the scorer against its own threshold. A label that encodes the algorithm cannot detect
    the algorithm being wrong.
    """
    truth: list[tuple[str | None, str]] = [
        ("S1", "edited an hour before the commit"),
        (None, "no session touched this file"),
        ("S3", "edited 30 minutes before the commit"),
        (None, "two sessions fit equally well — the join must decline"),
        (None, "session edited the file only after the commit"),
        # Corrected. S6 is the only session that ever touched src/f.py and it did so
        # before the commit; by construction it produced it. Five days is a reason for a
        # reader to weigh the match, not a reason to withhold it — and withholding it is a
        # silent false negative, which reads as "this work was unsupervised".
        ("S6", "sole editor of the file, five days before the commit"),
        ("S7", "session touched 1 of 2 files — overlap at the floor"),
        (None, "session touched 1 of 3 files — overlap below the floor"),
        (None, "lockfile-only commit has no significant paths"),
        (None, "session belongs to a different project"),
        ("S11short", "edited the file last; S11long's touch of it was superseded"),
    ]
    return [
        JoinLabel(sha=sha, session_id=session, note=note)
        for sha, (session, note) in zip(shas, truth, strict=True)
    ]
