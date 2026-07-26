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
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

__all__ = [
    "PARSER_VERSION",
    "LOG_FORMAT",
    "EventKind",
    "Event",
    "Session",
    "ParseResult",
    "parse_session_file",
    "parse_log_dir",
    "default_log_dir",
]

# Bumped whenever the parsing rules change. Travels with every uploaded payload so a
# metric can be traced to the code that derived it.
PARSER_VERSION = "l2-parser/1"

# The log shape this parser was written against, recorded on 2026-07-26. If a future log
# stops matching, that is a fact worth reporting rather than papering over.
LOG_FORMAT = "claude-code/jsonl-2026-07"

# Record types we understand. Anything else is counted as unrecognised, not dropped.
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

# Record types that must appear for a file to be a session log at all.
REQUIRED_RECORD_TYPES = frozenset({"user", "assistant"})

# Above this share of unparseable lines the file is not what we think it is.
MAX_UNPARSED_SHARE = 0.10

# Tools that modify the working tree.
EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})

# Tools that signal an explicit planning step.
PLAN_TOOLS = frozenset({"EnterPlanMode", "ExitPlanMode"})

# Commands that verify work: test runners, builders, type checkers, linters.
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


@dataclass
class Session:
    """One session file, normalized."""

    session_id: str
    events: list[Event] = field(default_factory=list)
    first_at: datetime | None = None
    last_at: datetime | None = None
    n_records: int = 0
    n_unparsed: int = 0
    n_unrecognised: int = 0

    def of_kind(self, kind: EventKind) -> list[Event]:
        return [e for e in self.events if e.kind is kind]


@dataclass
class ParseResult:
    """Everything parsed, plus an honest account of what was not."""

    sessions: list[Session] = field(default_factory=list)
    n_files: int = 0
    n_files_skipped: int = 0
    n_records: int = 0
    n_unparsed: int = 0
    n_unrecognised: int = 0
    unrecognised_types: Counter[str] = field(default_factory=Counter)
    degraded: bool = False
    degraded_reason: str = ""

    @property
    def unparsed_share(self) -> float:
        return self.n_unparsed / self.n_records if self.n_records else 0.0


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


def _tool_events(record: dict, index: int) -> list[Event]:
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
            )
        )
    return out


def parse_session_file(path: Path) -> Session | None:
    """Parse one session JSONL file. Returns None if it is not a session log.

    Ordering is by line index throughout: `mode` and `permission-mode` records carry no
    timestamp, so a time-ordered parse would drop every plan signal on the floor.
    """
    session = Session(session_id=path.stem)
    seen_types: set[str] = set()

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

            if sid := record.get("sessionId"):
                session.session_id = str(sid)

            at = _ts(record)
            if at is not None:
                session.first_at = min(session.first_at or at, at)
                session.last_at = max(session.last_at or at, at)

            if kind == "user":
                if record.get("interruptedMessageId"):
                    session.events.append(
                        Event(EventKind.INTERRUPT, index, at)
                    )
                if record.get("toolDenialKind"):
                    session.events.append(Event(EventKind.DENIAL, index, at))
                if _human_prompt(record):
                    session.events.append(Event(EventKind.HUMAN_PROMPT, index, at))
            elif kind == "assistant":
                session.events.extend(_tool_events(record, index))
            elif kind == "permission-mode":
                # `mode` is always "normal" in practice; the plan state lives here.
                if record.get("permissionMode") == "plan":
                    session.events.append(Event(EventKind.PLAN_SIGNAL, index, at))

    if not (REQUIRED_RECORD_TYPES & seen_types):
        return None
    return session


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

    for path in sorted(root.rglob("*.jsonl")):
        result.n_files += 1
        try:
            session = parse_session_file(path)
        except OSError:
            session = None
        if session is None:
            result.n_files_skipped += 1
            continue

        result.sessions.append(session)
        result.n_records += session.n_records
        result.n_unparsed += session.n_unparsed
        result.n_unrecognised += session.n_unrecognised

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
