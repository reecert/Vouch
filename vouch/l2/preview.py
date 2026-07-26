"""Upload preview — show exactly what will leave, and what will not.

The brief requires printing exactly what will be uploaded and requiring confirmation. Two
choices make that mean something rather than being a formality:

* **The preview renders the real serialized payload**, not a summary of it. A summary is a
  second implementation that can drift from the thing actually sent; the bytes shown here
  are the bytes that go.
* **It also lists what stayed behind**, with counts. "We read 17,187 records across 54
  sessions and are sending 12 numbers" is the claim a user can actually check, and it is
  more convincing than an assurance.
"""
from __future__ import annotations

from vouch.l2.parser import EventKind, ParseResult
from vouch.l2.payload import SessionMetrics

__all__ = ["render_payload", "render_local_only", "render_preview"]

_RULE = "─" * 72


def render_payload(metrics: SessionMetrics) -> str:
    """The exact JSON that will be uploaded."""
    return metrics.model_dump_json(indent=2)


def render_local_only(result: ParseResult) -> str:
    """What was read and is staying on this machine. Counts only — no samples."""
    prompts = sum(len(s.of_kind(EventKind.HUMAN_PROMPT)) for s in result.sessions)
    commands = sum(
        1 for s in result.sessions for e in s.events if e.command is not None
    )
    paths = {p for s in result.sessions for e in s.events for p in e.paths}
    servers = {
        e.mcp_server for s in result.sessions for e in s.events if e.mcp_server
    }

    lines = [
        "Read locally and NOT uploaded:",
        f"  {result.n_records:>7,}  log records across {len(result.sessions)} session(s)",
        f"  {prompts:>7,}  prompt texts",
        f"  {commands:>7,}  shell commands",
        f"  {len(paths):>7,}  file paths",
        f"  {len(servers):>7,}  MCP server names (only the count is sent)",
        "",
        "  No prompt, command, path, server name, or line of source code appears in the",
        "  payload above. The payload schema has no free-text field for one to travel in.",
    ]
    return "\n".join(lines)


def render_preview(result: ParseResult, metrics: SessionMetrics) -> str:
    """The full confirmation screen."""
    blocks = [
        _RULE,
        "This is exactly what will be uploaded:",
        _RULE,
        render_payload(metrics),
        _RULE,
        render_local_only(result),
    ]
    if result.degraded:
        blocks += [
            _RULE,
            "DEGRADED — falling back to git-only mode.",
            f"  {result.degraded_reason}",
            "  Rates are omitted entirely rather than derived from a log format this",
            "  parser no longer understands.",
        ]
    blocks.append(_RULE)
    return "\n".join(blocks)
