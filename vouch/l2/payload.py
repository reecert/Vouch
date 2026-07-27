"""The L2 upload payload — a closed schema.

This module defines the **only** thing that leaves the user's machine. The hard constraint
in the brief is "raw logs and source code NEVER leave"; the way that is kept is structural
rather than procedural:

* **Every field is a number, a boolean, a date, or a constant defined in this file.** There
  is no free-text field anywhere in the schema, so there is no channel through which a
  prompt, a file path, a bash command, or a snippet of source could travel — not by
  oversight, not by a future edit that forgets the rule. ``tests/test_l2_payload.py``
  walks the model and fails if a string field ever appears.
* **Dictionary keys are enums.** Tool usage is bucketed into constants declared here;
  a tool name read from a log is mapped into a bucket and then discarded.
* **MCP servers are counted, never named.** An MCP server name routinely identifies an
  employer, a client, or a vendor relationship — `mcp__AcmeCorp__…` is a disclosure, not a
  metric. The payload carries how many, never which.
* **Degradation reasons are codes.** The human-readable reason (which contains the log
  path) is rendered locally in the confirmation preview and is not part of the payload.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PAYLOAD_SCHEMA_VERSION",
    "MetricKey",
    "MetricScope",
    "ToolBucket",
    "DegradedReason",
    "Rate",
    "SessionMetrics",
    "bucket_for",
]

PAYLOAD_SCHEMA_VERSION = "l2/2"


class MetricScope(StrEnum):
    """What population a metric was computed over. Declared, never inferred.

    The defect this exists to prevent: L2 reads `~/.claude/projects`, which is every
    project on the machine, while L1 and L3 read one repo. A rate derived from the first
    was being handed to a dimension that claims something about the second, so
    `plan_before_execute` could be dominated by a client project the profile never mentions
    — and the reader had no way to see it, because a rate carries a denominator but not a
    population.

    ``MACHINE`` is honest and useful on its own terms (it is what the user sees in the
    upload preview). It is simply not admissible evidence about one repository, and the
    scope contract in :mod:`vouch.l4.dimensions` is what enforces that.
    """

    MACHINE = "machine"
    REPO = "repo"


class MetricKey(StrEnum):
    """The derived behaviours. Constants — never read from a log."""

    PLAN_BEFORE_EXECUTE = "plan_before_execute"
    TEST_OR_BUILD_AFTER_EDIT = "test_or_build_after_edit"
    EDIT_REVISION = "edit_revision"
    HUMAN_REDIRECT = "human_redirect"


class ToolBucket(StrEnum):
    """Coarse tool categories. A tool name from a log is mapped here, then dropped."""

    SHELL = "shell"
    EDIT = "edit"
    READ = "read"
    SEARCH = "search"
    WEB = "web"
    TASK = "task"
    AGENT = "agent"
    PLAN = "plan"
    MCP = "mcp"
    OTHER = "other"


class DegradedReason(StrEnum):
    """Why a run fell back to git-only mode. A code, so no path can ride along."""

    NONE = "none"
    NO_LOGS = "no_logs"
    UNPARSEABLE = "unparseable"
    NOT_A_SESSION_LOG = "not_a_session_log"


# Built-in tool names -> bucket. Anything absent maps to OTHER, so a tool introduced
# tomorrow is counted without its name ever reaching the payload.
_BUCKETS: dict[str, ToolBucket] = {
    "Bash": ToolBucket.SHELL,
    "Edit": ToolBucket.EDIT,
    "Write": ToolBucket.EDIT,
    "MultiEdit": ToolBucket.EDIT,
    "NotebookEdit": ToolBucket.EDIT,
    "Read": ToolBucket.READ,
    "Glob": ToolBucket.SEARCH,
    "Grep": ToolBucket.SEARCH,
    "ToolSearch": ToolBucket.SEARCH,
    "WebFetch": ToolBucket.WEB,
    "WebSearch": ToolBucket.WEB,
    "TaskCreate": ToolBucket.TASK,
    "TaskUpdate": ToolBucket.TASK,
    "TaskGet": ToolBucket.TASK,
    "TaskList": ToolBucket.TASK,
    "Agent": ToolBucket.AGENT,
    "Skill": ToolBucket.AGENT,
    "EnterPlanMode": ToolBucket.PLAN,
    "ExitPlanMode": ToolBucket.PLAN,
    "AskUserQuestion": ToolBucket.PLAN,
}


def bucket_for(tool: str) -> ToolBucket:
    """Map a tool name to its bucket. MCP tools bucket by prefix, never by name."""
    if tool.startswith("mcp__"):
        return ToolBucket.MCP
    return _BUCKETS.get(tool, ToolBucket.OTHER)


class Rate(BaseModel):
    """A numerator over a denominator, with its floor, its interval, and whether the point
    estimate was suppressed.

    ``value`` is ``None`` when the denominator is below ``floor``. The denominator travels
    regardless: the competitor publishes five percentages off 18 sessions with no visible
    floor, and the cheapest way to be more honest than that is to show the divisor.

    ``low``/``high`` are the range the observations actually support, drawn asymmetrically
    — the bound that would read badly for the subject is held to a stricter confidence
    level than the one that would read well. See :mod:`vouch.l1.interval` for why the two
    errors are not worth the same. Both are plain floats rather than a nested model so the
    payload stays flat and the closure test keeps working on scalars.
    """

    model_config = ConfigDict(extra="forbid")

    numerator: int = 0
    denominator: int = 0
    floor: int = 0
    suppressed: bool = False
    value: float | None = None
    low: float | None = None
    high: float | None = None


class SessionMetrics(BaseModel):
    """The complete upload payload. Nothing else leaves the machine."""

    model_config = ConfigDict(extra="forbid")

    # Constants from this codebase, so a number can be traced to the code that derived it.
    schema_version: str = PAYLOAD_SCHEMA_VERSION
    parser_version: str = ""
    log_format: str = ""

    # What population every rate below was computed over. A consumer that needs
    # repo-scoped evidence checks this rather than assuming.
    scope: MetricScope = MetricScope.MACHINE
    n_sessions_out_of_scope: int = 0  # seen on this machine, excluded from these rates

    # Coverage — reported so that partial parsing is visible rather than silent.
    degraded: bool = False
    degraded_reason: DegradedReason = DegradedReason.NONE
    n_sessions: int = 0
    n_records: int = 0
    n_records_unparsed: int = 0
    n_records_unrecognised: int = 0
    n_files_skipped: int = 0

    window_first: date | None = None
    window_last: date | None = None

    # The session snapshot these metrics were read from. `as_of` is the newest log
    # modification time seen; the digest that actually identifies the snapshot lives
    # in the profile's provenance, because a content hash of log bytes is not a thing
    # this payload should carry off the machine.
    as_of: datetime | None = None

    rates: dict[MetricKey, Rate] = Field(default_factory=dict)
    tool_usage: dict[ToolBucket, int] = Field(default_factory=dict)

    n_mcp_servers: int = 0  # how many, never which
    n_mcp_calls: int = 0

    median_prompts_per_session: float | None = None
    median_tool_calls_per_session: float | None = None
