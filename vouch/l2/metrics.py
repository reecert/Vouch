"""Derive the L2 metrics from a parsed event stream.

Reduces the local event stream to the closed payload in :mod:`vouch.l2.payload`. Every
rate carries its denominator and a floor below which it is suppressed rather than rounded.

Sequencing is by event index (file order), never by timestamp — `permission-mode` records
carry no timestamp, so a time-ordered pass would drop every plan signal on the floor.
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

from vouch.l1.interval import Polarity, asymmetric_interval
from vouch.l2.parser import EDIT_TOOLS, EventKind, ParseResult, Session
from vouch.l2.payload import (
    DegradedReason,
    MetricKey,
    MetricScope,
    Rate,
    SessionMetrics,
    ToolBucket,
    bucket_for,
)

__all__ = ["L2MinN", "L2_MIN_N", "METRIC_POLARITY", "derive_metrics"]


#: Which direction of each metric is the unfavourable one for the person being profiled.
#:
#: Declared here, once, rather than passed at each `_rate` call: the polarity decides which
#: end of the interval was held to the strict confidence level, so anything that *renders* a
#: metric has to be able to state it. "92 days" says nothing on its own — a reader cannot
#: tell whether it is a complaint or a compliment — and the number was drawn asymmetrically
#: on the strength of an answer the reader was never shown.
#:
#: `EDIT_REVISION` is deliberately not neutral: revisiting a file within a session is the
#: measurable half of revision-before-acceptance, so more of it reads as better here. That
#: is a modelling claim, and stating it in one place is what makes it arguable.
METRIC_POLARITY: dict[MetricKey, Polarity] = {
    MetricKey.PLAN_BEFORE_EXECUTE: Polarity.HIGHER_IS_BETTER,
    MetricKey.TEST_OR_BUILD_AFTER_EDIT: Polarity.HIGHER_IS_BETTER,
    MetricKey.EDIT_REVISION: Polarity.HIGHER_IS_BETTER,
    # Neither direction is a claim about the person: a human who redirects is engaged, and
    # one who does not may be either trusting or absent.
    MetricKey.HUMAN_REDIRECT: Polarity.NEUTRAL,
}


@dataclass(frozen=True)
class L2MinN:
    """Denominator floors. Below these a rate is suppressed, not rounded."""

    sessions: int = 5
    edit_runs: int = 10
    edited_files: int = 10


L2_MIN_N = L2MinN()


def _rate(
    numerator: int,
    denominator: int,
    floor: int,
    key: MetricKey,
) -> Rate:
    """A rate whose *point estimate* is suppressed below its floor, and always at zero n.

    The zero case is not just division safety: "0 observations" carries no information
    whatever floor is configured, so there is nothing to report either way.

    The interval is attached regardless of suppression. Withholding the point estimate is
    right — thin evidence does not support one — but withholding the range too leaves a
    reader with silence where there was something honest to say.
    """
    suppressed = denominator == 0 or denominator < floor
    interval = asymmetric_interval(numerator, denominator, METRIC_POLARITY[key])
    return Rate(
        numerator=numerator,
        denominator=denominator,
        floor=floor,
        suppressed=suppressed,
        value=None if suppressed else round(numerator / denominator, 4),
        low=interval.low,
        high=interval.high,
    )


def _plan_before_execute(sessions: list[Session]) -> tuple[int, int]:
    """Sessions where a plan signal preceded the first edit.

    Denominator counts only sessions that edited anything: a read-only session had no
    execution to plan before, so scoring it either way would be noise.
    """
    considered = planned = 0
    for session in sessions:
        edits = [e.index for e in session.events if e.tool in EDIT_TOOLS]
        if not edits:
            continue
        considered += 1
        plans = [e.index for e in session.of_kind(EventKind.PLAN_SIGNAL)]
        if plans and min(plans) < min(edits):
            planned += 1
    return planned, considered


def _test_or_build_after_edit(sessions: list[Session]) -> tuple[int, int]:
    """Of the runs of edits, how many were followed by a test, build or checker.

    An "edit run" opens at the first edit and closes at whichever comes first: a verifying
    command (counted as verified), a human prompt (counted as unverified — the human moved
    on before anything was checked), or the end of the session.

    Runs are closed per *transcript*. A subagent's work is folded into its parent session,
    but the two ran concurrently, so a subagent's test run does not close an edit the main
    thread had open — and would otherwise credit verification that never happened.
    """
    verified = total = 0
    for session in sessions:
        for stream in session.streams():
            pending = False
            for event in stream:
                if event.tool in EDIT_TOOLS:
                    pending = True
                elif pending and event.verifies:
                    verified += 1
                    total += 1
                    pending = False
                elif pending and event.kind is EventKind.HUMAN_PROMPT:
                    total += 1
                    pending = False
            if pending:
                total += 1
    return verified, total


def _edit_revision(sessions: list[Session]) -> tuple[int, int]:
    """Files edited more than once in the same session — revised rather than one-shot.

    A proxy, and named for what it measures. The brief asks for
    "revision-before-acceptance", which would need accept/reject telemetry; the logs carry
    only `toolDenialKind`, which is far too sparse to divide by (2 occurrences across
    17,187 records in the sample this was written against). See docs/plan.md.
    """
    revised = total = 0
    for session in sessions:
        touches: Counter[str] = Counter()
        for event in session.events:
            if event.tool in EDIT_TOOLS:
                touches.update(event.paths)
        total += len(touches)
        revised += sum(1 for n in touches.values() if n > 1)
    return revised, total


def _human_redirect(sessions: list[Session]) -> tuple[int, int]:
    """Sessions in which the human interrupted or denied a tool call."""
    redirected = sum(
        1
        for s in sessions
        if s.of_kind(EventKind.INTERRUPT) or s.of_kind(EventKind.DENIAL)
    )
    return redirected, len(sessions)


def _median(values: list[int]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def derive_metrics(
    result: ParseResult,
    min_n: L2MinN | None = None,
    scope: MetricScope = MetricScope.MACHINE,
    n_out_of_scope: int = 0,
) -> SessionMetrics:
    """Reduce a parse result to the upload payload.

    A degraded parse produces coverage counters and nothing else — no rates, no tool
    usage. Numbers derived from a log format we no longer understand are worse than no
    numbers, because they look the same as good ones.

    ``scope`` states what population ``result`` covers; it is recorded on the payload and
    is not inferred anywhere downstream. Callers that scope to a repo are expected to have
    filtered ``result.sessions`` already — this function does not know what a repo is, and
    keeping it that way is what stops L2 from reaching into L3.
    """
    from vouch.l2.parser import LOG_FORMAT, PARSER_VERSION

    min_n = min_n or L2_MIN_N

    if result.degraded:
        reason = (
            DegradedReason.NO_LOGS
            if not result.sessions
            else DegradedReason.UNPARSEABLE
        )
        if not result.sessions and result.n_files > 0:
            reason = DegradedReason.NOT_A_SESSION_LOG
        return SessionMetrics(
            parser_version=PARSER_VERSION,
            log_format=LOG_FORMAT,
            scope=scope,
            n_sessions_out_of_scope=n_out_of_scope,
            as_of=result.as_of,
            degraded=True,
            degraded_reason=reason,
            n_sessions=len(result.sessions),
            n_records=result.n_records,
            n_records_unparsed=result.n_unparsed,
            n_records_unrecognised=result.n_unrecognised,
            n_files_skipped=result.n_files_skipped,
        )

    sessions = result.sessions

    tools: Counter[ToolBucket] = Counter()
    mcp_servers: set[str] = set()
    n_mcp_calls = 0
    for session in sessions:
        for event in session.events:
            if event.kind not in (EventKind.TOOL_USE, EventKind.PLAN_SIGNAL):
                continue
            if event.tool is None:
                continue
            tools[bucket_for(event.tool)] += 1
            if event.is_mcp:
                n_mcp_calls += 1
                if event.mcp_server:
                    mcp_servers.add(event.mcp_server)

    starts = [s.first_at for s in sessions if s.first_at]
    ends = [s.last_at for s in sessions if s.last_at]

    plan_n, plan_d = _plan_before_execute(sessions)
    verify_n, verify_d = _test_or_build_after_edit(sessions)
    revise_n, revise_d = _edit_revision(sessions)
    redirect_n, redirect_d = _human_redirect(sessions)

    return SessionMetrics(
        parser_version=PARSER_VERSION,
        log_format=LOG_FORMAT,
        scope=scope,
        n_sessions_out_of_scope=n_out_of_scope,
        as_of=result.as_of,
        degraded=False,
        degraded_reason=DegradedReason.NONE,
        n_sessions=len(sessions),
        n_records=result.n_records,
        n_records_unparsed=result.n_unparsed,
        n_records_unrecognised=result.n_unrecognised,
        n_files_skipped=result.n_files_skipped,
        window_first=min(starts).date() if starts else None,
        window_last=max(ends).date() if ends else None,
        rates={
            # Polarity comes from METRIC_POLARITY rather than from these call sites, so the
            # direction a renderer states is necessarily the one the interval was drawn on.
            MetricKey.PLAN_BEFORE_EXECUTE: _rate(
                plan_n, plan_d, min_n.sessions, MetricKey.PLAN_BEFORE_EXECUTE
            ),
            MetricKey.TEST_OR_BUILD_AFTER_EDIT: _rate(
                verify_n, verify_d, min_n.edit_runs, MetricKey.TEST_OR_BUILD_AFTER_EDIT
            ),
            MetricKey.EDIT_REVISION: _rate(
                revise_n, revise_d, min_n.edited_files, MetricKey.EDIT_REVISION
            ),
            MetricKey.HUMAN_REDIRECT: _rate(
                redirect_n, redirect_d, min_n.sessions, MetricKey.HUMAN_REDIRECT
            ),
        },
        tool_usage=dict(sorted(tools.items())),
        n_mcp_servers=len(mcp_servers),
        n_mcp_calls=n_mcp_calls,
        median_prompts_per_session=_median(
            [len(s.of_kind(EventKind.HUMAN_PROMPT)) for s in sessions]
        ),
        median_tool_calls_per_session=_median(
            [len([e for e in s.events if e.kind is EventKind.TOOL_USE]) for s in sessions]
        ),
    )
