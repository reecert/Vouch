"""The scoping contract: a metric is only evidence for the population it measured.

The defect: L2 reads `~/.claude/projects`, which is every project on the machine, while L1
and L3 read one repository. `planning_discipline` consumed the L2 payload directly, so a
profile headed with one repo's name could publish a planning rate dominated by unrelated —
often client — work, and nothing in the output distinguished the two.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures import joins
from vouch.l1.facts import Identity, RepoFacts
from vouch.l2.metrics import derive_metrics
from vouch.l2.parser import parse_log_dir
from vouch.l2.payload import MetricKey, MetricScope, Rate, SessionMetrics
from vouch.l3.join import sessions_in_repo
from vouch.l4.dimensions import DIMENSIONS, assess_availability
from vouch.l4.judge import apply_support_check
from vouch.l4.schema import (
    Claim,
    Confidence,
    DimensionFinding,
    DimensionKey,
    Locator,
    Verdict,
)


def _spec(key: DimensionKey):
    return next(s for s in DIMENSIONS if s.key is key)


def _facts() -> RepoFacts:
    return RepoFacts(
        repo="r", head_sha="a" * 40, subject=Identity(canonical_email="a@b.c")
    )


def _rates(**kw) -> dict[MetricKey, Rate]:
    return {
        MetricKey.PLAN_BEFORE_EXECUTE: Rate(
            numerator=8, denominator=20, floor=5, value=0.4
        ),
        **kw,
    }


# --- the contract itself ---------------------------------------------------------------


def test_every_dimension_declares_a_scope() -> None:
    """A dimension that did not declare one would inherit whatever it was handed."""
    assert all(spec.scope is MetricScope.REPO for spec in DIMENSIONS)


def test_machine_wide_telemetry_is_refused_not_discounted() -> None:
    """The rate is present, unsuppressed, and still unusable. Population beats denominator."""
    machine = SessionMetrics(scope=MetricScope.MACHINE, n_sessions=40, rates=_rates())

    availability = assess_availability(
        _spec(DimensionKey.PLANNING_DISCIPLINE), _facts(), machine, 0
    )

    assert availability.usable_metrics == ()
    assert availability.l2_out_of_scope is True
    assert availability.has_any is False
    assert availability.is_not_assessable is True


def test_repo_scoped_telemetry_is_admitted() -> None:
    scoped = SessionMetrics(scope=MetricScope.REPO, n_sessions=20, rates=_rates())

    availability = assess_availability(
        _spec(DimensionKey.PLANNING_DISCIPLINE), _facts(), scoped, 0
    )

    assert availability.usable_metrics == (MetricKey.PLAN_BEFORE_EXECUTE,)
    assert availability.is_not_assessable is False


def test_planning_discipline_is_not_assessable_on_machine_wide_input() -> None:
    """`not_assessable`, and specifically not `insufficient_evidence`.

    The distinction is the reader's next action. `insufficient_evidence` says "there wasn't
    much here"; `not_assessable` says "what is here cannot answer this question" — more
    sessions of the same kind would not help, only sessions from this repo would.
    """
    machine = SessionMetrics(scope=MetricScope.MACHINE, n_sessions=40, rates=_rates())
    availability = assess_availability(
        _spec(DimensionKey.PLANNING_DISCIPLINE), _facts(), machine, 0
    )
    claimed = DimensionFinding(
        dimension=DimensionKey.PLANNING_DISCIPLINE,
        verdict=Verdict.STRONG,
        confidence=Confidence.HIGH,
        summary="Plans consistently before executing.",
        claims=[Claim(text="x", locators=[Locator(sha="a" * 40)])],
    )

    checked, note = apply_support_check(claimed, availability)

    assert checked.verdict is Verdict.NOT_ASSESSABLE
    assert checked.confidence is Confidence.LOW
    assert note is not None and "not_assessable" in note


def test_a_dimension_with_its_own_repo_evidence_survives_out_of_scope_telemetry() -> None:
    """Scope removes the L2 term, not the dimension. Verification still has L1 and diffs."""
    machine = SessionMetrics(
        scope=MetricScope.MACHINE,
        n_sessions=40,
        rates=_rates(
            **{
                MetricKey.TEST_OR_BUILD_AFTER_EDIT: Rate(
                    numerator=15, denominator=20, floor=10, value=0.75
                )
            }
        ),
    )
    availability = assess_availability(
        _spec(DimensionKey.VERIFICATION_DISCIPLINE), _facts(), machine, n_commit_judgments=6
    )

    assert availability.usable_metrics == ()
    assert availability.l2_out_of_scope is True
    assert availability.has_any is True  # the commit judgments are repo-scoped by nature
    assert availability.is_not_assessable is False


# --- deriving a scoped population --------------------------------------------------------


@pytest.fixture
def two_projects(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    joins.build_repo_for_join(repo)
    logs = tmp_path / "logs"
    logs.mkdir()

    def write(name: str, edited: str) -> None:
        (logs / f"{name}.jsonl").write_text(
            "".join(
                json.dumps(r) + "\n"
                for r in [
                    {
                        "type": "user",
                        "sessionId": name,
                        "timestamp": joins.iso(-2),
                        "message": {"role": "user", "content": "go"},
                    },
                    {
                        "type": "assistant",
                        "sessionId": name,
                        "timestamp": joins.iso(-1),
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Edit",
                                    "input": {"file_path": edited},
                                }
                            ],
                        },
                    },
                ]
            )
        )

    write("OURS", str(repo / "src/a.py"))
    for i in range(4):
        write(f"THEIRS{i}", str(tmp_path / "client-work" / f"src/{i}.py"))
    return repo, logs


def test_scoping_selects_only_the_sessions_that_touched_this_repo(two_projects) -> None:
    repo, logs = two_projects
    parsed = parse_log_dir(logs)

    scoped, n_out = sessions_in_repo(parsed.sessions, repo)

    assert [s.session_id for s in scoped] == ["OURS"]
    assert n_out == 4


def test_the_excluded_population_stays_visible(two_projects) -> None:
    """A profile that narrowed from five sessions to one has to say so."""
    repo, logs = two_projects
    parsed = parse_log_dir(logs)
    scoped, n_out = sessions_in_repo(parsed.sessions, repo)

    metrics = derive_metrics(
        parsed.narrowed_to(scoped), scope=MetricScope.REPO, n_out_of_scope=n_out
    )

    assert metrics.scope is MetricScope.REPO
    assert metrics.n_sessions == 1
    assert metrics.n_sessions_out_of_scope == 4
    # ...and the coverage counters describe the narrowed set, not the wide one.
    assert metrics.n_records == sum(s.n_records for s in scoped)


def test_scoping_under_the_floor_yields_not_assessable_rather_than_a_number(
    two_projects,
) -> None:
    """The correct answer, and the one the brief asks for.

    Machine-wide there were five sessions — enough to clear the floor and publish a
    planning rate. Scoped to this repo there is one. The dimension declines instead of
    reporting a rate that four unrelated projects paid for.
    """
    repo, logs = two_projects
    parsed = parse_log_dir(logs)

    wide = derive_metrics(parsed, scope=MetricScope.MACHINE)
    assert wide.rates[MetricKey.PLAN_BEFORE_EXECUTE].suppressed is False

    scoped, n_out = sessions_in_repo(parsed.sessions, repo)
    narrow = derive_metrics(
        parsed.narrowed_to(scoped), scope=MetricScope.REPO, n_out_of_scope=n_out
    )
    assert narrow.rates[MetricKey.PLAN_BEFORE_EXECUTE].suppressed is True

    availability = assess_availability(
        _spec(DimensionKey.PLANNING_DISCIPLINE), _facts(), narrow, 0
    )
    assert availability.has_any is False
    assert availability.l2_narrowed_by_scope is True
    assert availability.is_not_assessable is True
