"""L2 metric derivation, floors, and degraded-mode behaviour."""
from __future__ import annotations

from pathlib import Path

from tests.fixtures import logs
from vouch.l2.metrics import L2MinN, derive_metrics
from vouch.l2.parser import parse_log_dir
from vouch.l2.payload import DegradedReason, MetricKey, ToolBucket
from vouch.l2.preview import render_local_only, render_payload

NO_FLOORS = L2MinN(sessions=0, edit_runs=0, edited_files=0)


def _metrics(tmp_path: Path, sessions: list[list[dict]], min_n: L2MinN = NO_FLOORS):
    for i, records in enumerate(sessions):
        logs.write_session(tmp_path / f"s{i}.jsonl", records)
    return derive_metrics(parse_log_dir(tmp_path), min_n=min_n)


def test_plan_before_execute(tmp_path: Path) -> None:
    """Only sessions that edited something are in the denominator."""
    metrics = _metrics(
        tmp_path,
        [
            logs.healthy_session(0),  # planned, then edited
            logs.unverified_session(10),  # edited without planning
            [logs.prompt("just a question", 20)],  # no edits: not counted either way
        ],
    )
    rate = metrics.rates[MetricKey.PLAN_BEFORE_EXECUTE]

    assert (rate.numerator, rate.denominator) == (1, 2)


def test_plan_after_the_first_edit_does_not_count(tmp_path: Path) -> None:
    """The claim is planning *before* executing, so ordering is the whole metric."""
    metrics = _metrics(
        tmp_path,
        [[logs.prompt(), logs.edit("src/a.py", 1), logs.plan_mode()]],
    )
    assert metrics.rates[MetricKey.PLAN_BEFORE_EXECUTE].numerator == 0


def test_test_or_build_after_edit(tmp_path: Path) -> None:
    """An edit run closes on a verifying command, or on the human moving on."""
    metrics = _metrics(
        tmp_path,
        [
            logs.healthy_session(0),  # edit -> pytest: verified
            logs.unverified_session(10),  # two runs, neither verified
        ],
    )
    rate = metrics.rates[MetricKey.TEST_OR_BUILD_AFTER_EDIT]

    assert (rate.numerator, rate.denominator) == (1, 3)


def test_edit_revision_counts_files_touched_twice(tmp_path: Path) -> None:
    metrics = _metrics(
        tmp_path,
        [
            [
                logs.prompt(),
                logs.edit("src/a.py", 1),
                logs.edit("src/a.py", 2),  # revised
                logs.edit("src/b.py", 3),  # one-shot
            ]
        ],
    )
    rate = metrics.rates[MetricKey.EDIT_REVISION]

    assert (rate.numerator, rate.denominator) == (1, 2)


def test_human_redirect(tmp_path: Path) -> None:
    metrics = _metrics(
        tmp_path,
        [
            [logs.prompt(), logs.interrupt(1)],
            [logs.prompt(), logs.denial(1)],
            logs.healthy_session(10),
        ],
    )
    rate = metrics.rates[MetricKey.HUMAN_REDIRECT]

    assert (rate.numerator, rate.denominator) == (2, 3)


def test_rates_below_the_floor_are_suppressed_not_rounded(tmp_path: Path) -> None:
    """The competitor prints five percentages off 18 sessions. We print the divisor."""
    metrics = _metrics(tmp_path, [logs.healthy_session(0)], min_n=L2MinN())
    rate = metrics.rates[MetricKey.PLAN_BEFORE_EXECUTE]

    assert rate.suppressed is True
    assert rate.value is None
    assert rate.denominator == 1  # the denominator survives; it is the honest part
    assert rate.floor == 5


def test_tool_usage_is_bucketed(tmp_path: Path) -> None:
    metrics = _metrics(tmp_path, [logs.healthy_session(0)])

    assert metrics.tool_usage[ToolBucket.EDIT] == 1
    assert metrics.tool_usage[ToolBucket.SHELL] == 1
    assert metrics.tool_usage[ToolBucket.READ] == 1
    assert all(isinstance(k, ToolBucket) for k in metrics.tool_usage)


def test_mcp_is_counted_never_named(tmp_path: Path) -> None:
    metrics = _metrics(
        tmp_path,
        [
            [
                logs.prompt(),
                logs.tool_use("mcp__AcmeCorp__query", 1),
                logs.tool_use("mcp__AcmeCorp__update", 2),
                logs.tool_use("mcp__OtherVendor__read", 3),
            ]
        ],
    )

    assert metrics.n_mcp_servers == 2
    assert metrics.n_mcp_calls == 3
    assert "AcmeCorp" not in metrics.model_dump_json()
    assert "OtherVendor" not in metrics.model_dump_json()


def test_medians_and_window(tmp_path: Path) -> None:
    metrics = _metrics(tmp_path, [logs.healthy_session(0), logs.unverified_session(10)])

    assert metrics.median_prompts_per_session == 1.5
    assert metrics.window_first.isoformat() == "2026-07-20"


def test_degraded_parse_emits_coverage_and_no_rates(tmp_path: Path) -> None:
    """Numbers from a format we no longer understand look exactly like good ones."""
    metrics = derive_metrics(parse_log_dir(tmp_path / "nothing-here"))

    assert metrics.degraded is True
    assert metrics.degraded_reason is DegradedReason.NO_LOGS
    assert metrics.rates == {}
    assert metrics.tool_usage == {}


def test_degraded_payload_carries_no_path(tmp_path: Path) -> None:
    """The human-readable reason names the log directory. The payload must not."""
    result = parse_log_dir(tmp_path / "secret-project-name")
    metrics = derive_metrics(result)

    assert "secret-project-name" in result.degraded_reason  # local preview text
    assert "secret-project-name" not in render_payload(metrics)  # uploaded bytes


class TestPreview:
    """The confirmation shows the real payload bytes, not a summary of them."""

    def test_preview_renders_the_actual_payload(self, tmp_path: Path) -> None:
        for i in range(2):
            logs.write_session(tmp_path / f"s{i}.jsonl", logs.healthy_session(i * 10))
        result = parse_log_dir(tmp_path)
        metrics = derive_metrics(result)

        assert render_payload(metrics) == metrics.model_dump_json(indent=2)

    def test_local_only_block_reports_counts_not_samples(self, tmp_path: Path) -> None:
        logs.write_session(tmp_path / "s.jsonl", logs.healthy_session())
        result = parse_log_dir(tmp_path)
        text = render_local_only(result)

        assert "1  shell commands" in text
        assert "pytest" not in text  # the command itself is never shown back
        assert "src/app.py" not in text
