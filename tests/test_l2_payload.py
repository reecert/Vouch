"""The payload-closure test — the load-bearing guarantee of the whole layer.

The brief's hard constraint is that raw logs and source code never leave the machine. That
is kept structurally: the payload schema has **no free-text field**, so there is no channel
a prompt, path, command or snippet of source could travel through — including via a future
edit that forgets the rule.

This test walks the schema and fails if a string field ever appears outside a tiny
allow-list of constants defined in our own code. It is deliberately written against the
*schema* rather than against a sample payload: a sample only proves that this run leaked
nothing, while the schema proves no run can.
"""
from __future__ import annotations

import types
import typing
from datetime import date

import pytest
from pydantic import BaseModel, ValidationError

from vouch.l2.payload import (
    DegradedReason,
    MetricKey,
    Rate,
    SessionMetrics,
    ToolBucket,
    bucket_for,
)

# Strings whose values are constants in this codebase, never a value read from a log.
CONSTANT_STRING_FIELDS = frozenset({"schema_version", "parser_version", "log_format"})

SCALARS = (int, float, bool, date, type(None))


def _leaf_types(annotation) -> list:
    """Flatten an annotation into the leaf types it can hold."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return [t for arg in typing.get_args(annotation) for t in _leaf_types(arg)]
    if origin in (list, set, tuple):
        return [t for arg in typing.get_args(annotation) for t in _leaf_types(arg)]
    if origin is dict:
        return [t for arg in typing.get_args(annotation) for t in _leaf_types(arg)]
    return [annotation]


def _walk(model: type[BaseModel], path: str = "") -> list[tuple[str, type]]:
    """Every (field path, leaf type) in a nested pydantic model."""
    found: list[tuple[str, type]] = []
    for name, info in model.model_fields.items():
        where = f"{path}.{name}" if path else name
        for leaf in _leaf_types(info.annotation):
            if isinstance(leaf, type) and issubclass(leaf, BaseModel):
                found.extend(_walk(leaf, where))
            else:
                found.append((where, leaf))
    return found


def test_payload_has_no_free_text_field() -> None:
    """No string field anywhere except the three constants. This is the guarantee."""
    offenders = [
        where
        for where, leaf in _walk(SessionMetrics)
        if leaf is str and where.rsplit(".", 1)[-1] not in CONSTANT_STRING_FIELDS
    ]
    assert offenders == [], (
        f"free-text field(s) in the upload payload: {offenders}. "
        "Every payload field must be numeric, boolean, a date, or a constant enum — "
        "a str field is a channel for a prompt or a path to leave the machine."
    )


def test_every_leaf_is_a_scalar_or_a_constant_enum() -> None:
    """Nothing exotic sneaks in either — no Any, no dict[str, Any], no bytes."""
    from enum import Enum

    for where, leaf in _walk(SessionMetrics):
        assert isinstance(leaf, type), f"{where}: non-type annotation {leaf!r}"
        allowed = issubclass(leaf, SCALARS) or issubclass(leaf, Enum) or leaf is str
        assert allowed, f"{where}: disallowed payload type {leaf!r}"


def test_dictionary_keys_are_enums_not_log_strings() -> None:
    """Tool names and metric names are constants; a log-derived key would be a leak."""
    assert typing.get_args(SessionMetrics.model_fields["rates"].annotation)[0] is MetricKey
    assert (
        typing.get_args(SessionMetrics.model_fields["tool_usage"].annotation)[0]
        is ToolBucket
    )


def test_extra_fields_are_forbidden() -> None:
    """A future caller cannot smuggle a field in at construction time."""
    with pytest.raises(ValidationError):
        SessionMetrics(prompt_text="something private")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Rate(note="something private")  # type: ignore[call-arg]


def test_degraded_reason_is_a_code_not_a_message() -> None:
    """The human-readable reason contains the log path; only the code may be uploaded."""
    assert isinstance(SessionMetrics().degraded_reason, DegradedReason)
    assert set(DegradedReason) == {
        DegradedReason.NONE,
        DegradedReason.NO_LOGS,
        DegradedReason.UNPARSEABLE,
        DegradedReason.NOT_A_SESSION_LOG,
    }


class TestToolBucketing:
    """A tool name from a log is mapped to a constant and then discarded."""

    def test_known_tools_bucket(self) -> None:
        assert bucket_for("Bash") is ToolBucket.SHELL
        assert bucket_for("Edit") is ToolBucket.EDIT
        assert bucket_for("ExitPlanMode") is ToolBucket.PLAN

    def test_unknown_tool_buckets_to_other(self) -> None:
        """A tool shipped tomorrow is counted without its name reaching the payload."""
        assert bucket_for("SomeToolInventedNextYear") is ToolBucket.OTHER

    def test_mcp_server_name_never_survives_bucketing(self) -> None:
        """`mcp__AcmeCorp__query` names an employer or client. Only the count is sent."""
        assert bucket_for("mcp__AcmeCorp__query_documents") is ToolBucket.MCP
        assert "AcmeCorp" not in str(ToolBucket.MCP.value)
