"""Session log parser — `~/.claude/projects/**/*.jsonl` -> a normalized event stream.

**This module is the only thing that touches the logs, and nothing it returns is uploaded.**
It produces a local, in-memory event stream that `metrics` reduces to counts; the counts are
what leave the machine. Bash commands and file paths are retained here because L3 needs
them for the local session<->commit join, and they never reach the payload.

The log format is internal to Claude Code: undocumented, unversioned, and free to change
without notice. Three defences:

* **Order comes from the file, not from timestamps.** `mode` and `permission-mode` records
  carry no `timestamp` at all, so sequencing on time would silently drop every plan signal.
  JSONL is append-only, so line order is the reliable clock.
* **Unknown is counted, never guessed.** Unrecognised record types and unparseable lines
  are tallied and reported. Silent partial parsing is the failure mode that would quietly
  corrupt every downstream number.
* **Fail soft.** Past a threshold of unparseable input, or with the expected record types
  missing, the parse is marked degraded and the caller drops to git-only mode.

Two further properties the join and the metrics both depend on:

* **A session's working directory is recorded, per event.** Edit tools may be handed a
  relative path, and the only correct base for it is the directory *the session was in at
  that moment* — which the log records and which changes mid-session. Resolving against the
  CLI process's cwd instead would attribute whatever project the CLI was launched from.
  Events before the first `cwd` record carry ``None``, and downstream drops them.
* **A subagent transcript is not a session.** Claude Code writes subagent work to
  ``<session-id>/subagents/*.jsonl`` beside the parent's own file. Counting those as
  sessions double-counts every per-session denominator. They are folded into the parent as
  a separate ``stream`` — merged, because their edits are real, but not interleaved,
  because the two streams ran concurrently and file order across them means nothing.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from vouch.l2.snapshot import SessionSnapshot

__all__ = [
    "PARSER_VERSION",
    "LOG_FORMAT",
    "EventKind",
    "Event",
    "Session",
    "ParseResult",
    "parse_session_file",
    "parse_log_dir",
    "parse_snapshot",
    "default_log_dir",
]

PARSER_VERSION = "l2-parser/1"  # travels with the payload, so a metric names its parser
LOG_FORMAT = "claude-code/jsonl-2026-07"  # the log shape this was written against

KNOWN_RECORD_TYPES = frozenset(
    {
        "user",
        "assistant",
        "system",
        "attachment",
        "mode",
        "permission-mode",
        "file-history-snapshot",
        "file-history-delta",
        "last-prompt",
        "ai-title",
        "queue-operation",
        "agent-name",
        "agent-setting",
        "pr-link",
        "relocated",
        "worktree-state",
    }
)

REQUIRED_RECORD_TYPES = frozenset({"user", "assistant"})
MAX_UNPARSED_SHARE = 0.10

MAIN_STREAM = "main"
SUBAGENT_DIR = "subagents"

EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})
PLAN_TOOLS = frozenset({"EnterPlanMode", "ExitPlanMode"})

_VERIFY_RE = re.compile(
    r"""\b(
        pytest | tox | nox | unittest
      | jest | vitest | mocha | ava
      | npm\s+(run\s+)?(test|build|lint|typecheck)
      | (yarn|pnpm|bun)\s+(test|build|lint)
      | cargo\s+(test|build|check|clippy)
      | go\s+(test|build|vet)
      | make\b
      | gradle | mvn
      | ruff | mypy | pyright | tsc | eslint | golangci-lint
      | rspec | rake\s+test
      | dotnet\s+test
    )\b""",
    re.VERBOSE | re.IGNORECASE,
)


class EventKind(StrEnum):
    HUMAN_PROMPT = "human_prompt"
    TOOL_USE = "tool_use"
    PLAN_SIGNAL = "plan_signal"
    INTERRUPT = "interrupt"
    DENIAL = "denial"


@dataclass(frozen=True)
class Event:
    """One thing that happened in a session, in file order.

    ``paths`` and ``command`` stay on this machine — L3 joins on them locally. They are
    structurally unable to reach the upload payload, which carries no free-text field.
    """

    kind: EventKind
    index: int  # position in the file; the reliable clock
    at: datetime | None = None
    tool: str | None = None
    paths: tuple[str, ...] = ()
    command: str | None = None
    verifies: bool = False  # the command runs tests, a build, or a checker
    is_mcp: bool = False
    mcp_server: str | None = None  # kept local; only the *count* is ever uploaded
    cwd: str | None = None  # the session's own cwd: the only correct base for a relative path
    stream: str = MAIN_STREAM  # MAIN_STREAM, or the subagent id the work was delegated to


@dataclass
class Session:
    """One session, normalized — including any subagent transcripts folded into it."""

    session_id: str
    events: list[Event] = field(default_factory=list)
    first_at: datetime | None = None
    last_at: datetime | None = None
    n_records: int = 0
    n_unparsed: int = 0
    n_unrecognised: int = 0
    n_subagents: int = 0
    # The scope key, in first-seen order: never guessed from the log directory's name.
    cwds: tuple[str, ...] = ()

    def of_kind(self, kind: EventKind) -> list[Event]:
        return [e for e in self.events if e.kind is kind]

    def streams(self) -> list[list[Event]]:
        """Events grouped by transcript, each in file order. Never interleaved."""
        by_stream: dict[str, list[Event]] = {}
        for event in self.events:
            by_stream.setdefault(event.stream, []).append(event)
        return [by_stream[k] for k in sorted(by_stream)]

    def absorb(self, other: Session) -> None:
        """Fold a subagent transcript in. Its events keep their own stream and order.

        Coverage counters add up — a subagent's unparseable lines are still unparseable
        lines — but the session count does not, which is the double-counting this fixes.
        """
        self.events.extend(other.events)
        self.n_records += other.n_records
        self.n_unparsed += other.n_unparsed
        self.n_unrecognised += other.n_unrecognised
        self.n_subagents += 1
        for at in (other.first_at, other.last_at):
            if at is None:
                continue
            self.first_at = min(self.first_at or at, at)
            self.last_at = max(self.last_at or at, at)
        merged = list(self.cwds) + [c for c in other.cwds if c not in self.cwds]
        self.cwds = tuple(merged)


@dataclass
class ParseResult:
    """Everything parsed, plus an honest account of what was not."""

    sessions: list[Session] = field(default_factory=list)
    n_files: int = 0
    n_files_skipped: int = 0
    n_records: int = 0
    n_unparsed: int = 0
    n_unrecognised: int = 0
    n_subagent_files: int = 0  # folded into parents, not counted as sessions
    unrecognised_types: Counter[str] = field(default_factory=Counter)
    degraded: bool = False
    degraded_reason: str = ""
    # Empty only when the logs were read live, which is correct in tests and nowhere else.
    as_of: datetime | None = None
    snapshot_digest: str = ""

    @property
    def unparsed_share(self) -> float:
        return self.n_unparsed / self.n_records if self.n_records else 0.0

    def narrowed_to(self, sessions: list[Session]) -> ParseResult:
        """A result covering only ``sessions``, with every counter recomputed for them.

        Reusing the wide result's counters after narrowing the population would leave the
        coverage numbers describing one set and the rates another — a payload that reports
        17,000 records behind eight sessions' worth of behaviour.
        """
        return ParseResult(
            sessions=sessions,
            n_files=len(sessions),
            n_files_skipped=self.n_files_skipped,
            n_records=sum(s.n_records for s in sessions),
            n_unparsed=sum(s.n_unparsed for s in sessions),
            n_unrecognised=sum(s.n_unrecognised for s in sessions),
            n_subagent_files=sum(s.n_subagents for s in sessions),
            unrecognised_types=self.unrecognised_types,
            degraded=self.degraded or not sessions,
            degraded_reason=(
                self.degraded_reason
                if self.degraded
                else ("" if sessions else "no sessions touched this repository")
            ),
            as_of=self.as_of,
            snapshot_digest=self.snapshot_digest,
        )


def default_log_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _ts(record: dict) -> datetime | None:
    raw = record.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _mcp_server(tool: str) -> str | None:
    """`mcp__Sanity__query_documents` -> `Sanity`. Local only — never uploaded.

    An MCP server name routinely identifies an employer, a client, or a vendor
    relationship. Only the *number* of distinct servers reaches the payload.
    """
    parts = tool.split("__")
    return parts[1] if tool.startswith("mcp__") and len(parts) >= 3 else None


def _human_prompt(record: dict) -> bool:
    """A typed prompt, as opposed to a tool result wearing the `user` type.

    Most `user` records are tool results (3,779 of 4,044 in the sample this was written
    against). A real prompt has string or text content, no tool result, and is not a
    system-injected meta message.
    """
    if record.get("isMeta") or record.get("toolUseResult"):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(b.get("type") == "text" for b in content if isinstance(b, dict))
    return False


def _tool_events(record: dict, index: int, cwd: str | None, stream: str) -> list[Event]:
    """Extract tool_use blocks from an assistant record."""
    out: list[Event] = []
    at = _ts(record)
    for block in (record.get("message") or {}).get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name") or "unknown"
        params = block.get("input") if isinstance(block.get("input"), dict) else {}

        paths: tuple[str, ...] = ()
        if name in EDIT_TOOLS:
            target = params.get("file_path") or params.get("notebook_path")
            if isinstance(target, str) and target:
                paths = (target,)

        command = params.get("command") if name == "Bash" else None
        command = command if isinstance(command, str) else None
        server = _mcp_server(name)

        out.append(
            Event(
                kind=EventKind.PLAN_SIGNAL if name in PLAN_TOOLS else EventKind.TOOL_USE,
                index=index,
                at=at,
                tool=name,
                paths=paths,
                command=command,
                verifies=bool(command and _VERIFY_RE.search(command)),
                is_mcp=server is not None,
                mcp_server=server,
                cwd=cwd,
                stream=stream,
            )
        )
    return out


def parse_session_file(
    path: Path, session_id: str | None = None, stream: str = MAIN_STREAM
) -> Session | None:
    """Parse one session JSONL file. Returns None if it is not a session log.

    Ordering is by line index throughout: `mode` and `permission-mode` records carry no
    timestamp, so a time-ordered parse would drop every plan signal on the floor.

    ``session_id`` overrides the id the records claim. Subagent transcripts carry their own
    ``sessionId``, and honouring it is precisely how they became separate sessions.
    """
    session = Session(session_id=session_id or path.stem)
    seen_types: set[str] = set()
    cwd: str | None = None
    cwds: list[str] = []

    with path.open(errors="replace") as fh:
        for index, line in enumerate(fh):
            if not line.strip():
                continue
            session.n_records += 1
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                session.n_unparsed += 1
                continue
            if not isinstance(record, dict):
                session.n_unparsed += 1
                continue

            kind = record.get("type")
            seen_types.add(str(kind))
            if kind not in KNOWN_RECORD_TYPES:
                session.n_unrecognised += 1
                continue

            if session_id is None and (sid := record.get("sessionId")):
                session.session_id = str(sid)

            # Carried forward: a record without a `cwd` happened wherever the last one said.
            moved = record.get("relocatedCwd") if kind == "relocated" else record.get("cwd")
            if isinstance(moved, str) and moved:
                cwd = moved
                if moved not in cwds:
                    cwds.append(moved)

            at = _ts(record)
            if at is not None:
                session.first_at = min(session.first_at or at, at)
                session.last_at = max(session.last_at or at, at)

            if kind == "user":
                if record.get("interruptedMessageId"):
                    session.events.append(
                        Event(EventKind.INTERRUPT, index, at, cwd=cwd, stream=stream)
                    )
                if record.get("toolDenialKind"):
                    session.events.append(
                        Event(EventKind.DENIAL, index, at, cwd=cwd, stream=stream)
                    )
                if _human_prompt(record):
                    session.events.append(
                        Event(EventKind.HUMAN_PROMPT, index, at, cwd=cwd, stream=stream)
                    )
            elif kind == "assistant":
                session.events.extend(_tool_events(record, index, cwd, stream))
            elif kind == "permission-mode":
                # `mode` is always "normal" in practice; the plan state lives here.
                if record.get("permissionMode") == "plan":
                    session.events.append(
                        Event(EventKind.PLAN_SIGNAL, index, at, cwd=cwd, stream=stream)
                    )

    if not (REQUIRED_RECORD_TYPES & seen_types):
        return None
    session.cwds = tuple(cwds)
    return session


def parse_snapshot(snapshot: SessionSnapshot) -> ParseResult:
    """Parse a frozen snapshot and stamp the result with what it was read from.

    The entry point every caller that produces a shareable artifact should use. Parsing the
    live directory means parsing a file the running session is still appending to, which
    makes the output a function of when it was run rather than of what happened.
    """
    result = parse_log_dir(snapshot.root)
    result.as_of = snapshot.as_of
    result.snapshot_digest = snapshot.digest
    return result


def _parent_session_id(path: Path) -> str | None:
    """``<sid>/subagents/<agent>.jsonl`` -> ``<sid>``; None for a session's own file.

    The id comes from the directory layout rather than from the records inside, because
    the records carry the *subagent's* own ``sessionId`` — trusting it is exactly what
    turned one session into several.
    """
    parent = path.parent
    if parent.name != SUBAGENT_DIR:
        return None
    return parent.parent.name or None


def parse_log_dir(root: Path | None = None) -> ParseResult:
    """Parse every session log under ``root``. Never raises on a malformed log.

    A file that is not a session log is skipped and counted. Past
    ``MAX_UNPARSED_SHARE`` of unparseable lines the whole result is marked degraded, and
    the caller is expected to drop to git-only mode rather than upload numbers derived
    from a format we no longer understand.
    """
    root = root or default_log_dir()
    result = ParseResult()

    if not root.is_dir():
        result.degraded = True
        result.degraded_reason = f"no session logs found at {root}"
        return result

    by_id: dict[str, Session] = {}
    deferred: list[tuple[str, Path]] = []

    for path in sorted(root.rglob("*.jsonl")):
        result.n_files += 1
        parent_id = _parent_session_id(path)
        if parent_id is not None:
            # Held back so the parent exists to absorb it whatever order the walk reaches them in.
            deferred.append((parent_id, path))
            continue
        try:
            session = parse_session_file(path)
        except OSError:
            session = None
        if session is None:
            result.n_files_skipped += 1
            continue
        if (existing := by_id.get(session.session_id)) is not None:
            existing.absorb(session)
        else:
            by_id[session.session_id] = session

    for parent_id, path in deferred:
        try:
            sub = parse_session_file(path, session_id=parent_id, stream=path.stem)
        except OSError:
            sub = None
        if sub is None:
            result.n_files_skipped += 1
            continue
        if (parent := by_id.get(parent_id)) is not None:
            parent.absorb(sub)
        else:
            # The parent's transcript is missing: keep the work under its id, not as an extra.
            sub.n_subagents = 1
            by_id[parent_id] = sub

    for session in by_id.values():
        result.sessions.append(session)
        result.n_records += session.n_records
        result.n_unparsed += session.n_unparsed
        result.n_unrecognised += session.n_unrecognised
        result.n_subagent_files += session.n_subagents
    result.sessions.sort(key=lambda s: s.session_id)

    if not result.sessions:
        result.degraded = True
        result.degraded_reason = (
            f"no readable session logs under {root} "
            f"({result.n_files} file(s) seen, {result.n_files_skipped} unrecognised)"
        )
    elif result.unparsed_share > MAX_UNPARSED_SHARE:
        result.degraded = True
        result.degraded_reason = (
            f"{result.n_unparsed}/{result.n_records} records "
            f"({result.unparsed_share:.0%}) could not be parsed, over the "
            f"{MAX_UNPARSED_SHARE:.0%} threshold — the log format has probably changed"
        )

    return result
