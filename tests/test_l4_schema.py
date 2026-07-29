"""`insufficient_evidence` is enforced by the schema, not requested by the prompt.

The brief is explicit: *"must return `insufficient_evidence` when evidence is thin. Never
produce a flattering conclusion from weak data. Build this as an enum in the schema, not a
prompt suggestion."*

These tests assert the mechanism rather than the behaviour. A prompt that asks nicely can
be ignored by a model having an off day; a JSON schema handed to structured-output mode
cannot. What is proved here is that the verdict vocabulary is closed and that every way of
declining to conclude is inside it.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from vouch.l4.schema import (
    CONCLUSIVE_VERDICTS,
    Claim,
    CommitJudgment,
    Confidence,
    DimensionFinding,
    DimensionKey,
    FixNature,
    ScopeDiscipline,
    Verdict,
)

# Aliased: pytest collects any module-level `Test*` name as a class, and this is an enum.
from vouch.l4.schema import TestRelevance as RelevanceEnum


def _enum_values(schema: dict, field: str) -> list[str]:
    """Pull a field's permitted values out of the generated JSON schema.

    This is the schema the provider's structured-output mode is given, so whatever this
    returns is the complete set of values the model can physically emit.
    """
    node = schema["properties"][field]
    ref = node.get("$ref") or node.get("allOf", [{}])[0].get("$ref")
    if ref:
        return schema["$defs"][ref.split("/")[-1]]["enum"]
    return node["enum"]


def test_verdict_vocabulary_is_closed_and_includes_the_declines() -> None:
    values = _enum_values(DimensionFinding.model_json_schema(), "verdict")

    assert set(values) == {
        "strong",
        "moderate",
        "limited",
        "insufficient_evidence",
        "not_collected",
        "out_of_scope",
        "contradicted",
    }


def test_the_three_declines_are_distinct_values() -> None:
    """Collapsing them into one "unknown" would lose the distinction a reader needs."""
    assert Verdict.INSUFFICIENT_EVIDENCE != Verdict.NOT_COLLECTED
    assert Verdict.NOT_COLLECTED != Verdict.CONTRADICTED
    assert not CONCLUSIVE_VERDICTS & {
        Verdict.INSUFFICIENT_EVIDENCE,
        Verdict.NOT_COLLECTED,
        Verdict.CONTRADICTED,
        Verdict.LIMITED,
    }


def test_a_verdict_outside_the_enum_is_unrepresentable() -> None:
    with pytest.raises(ValidationError):
        DimensionFinding(
            dimension=DimensionKey.OWNERSHIP,
            verdict="excellent",  # type: ignore[arg-type]
            confidence=Confidence.HIGH,
            summary="x",
        )


def test_confidence_is_banded_not_a_float() -> None:
    """A model asked for 0.0-1.0 will answer 0.82 and mean nothing by it."""
    assert _enum_values(DimensionFinding.model_json_schema(), "confidence") == [
        "high",
        "moderate",
        "low",
    ]
    with pytest.raises(ValidationError):
        DimensionFinding(
            dimension=DimensionKey.OWNERSHIP,
            verdict=Verdict.STRONG,
            confidence=0.82,  # type: ignore[arg-type]
            summary="x",
        )


@pytest.mark.parametrize(
    "field,enum",
    [
        ("fix_nature", FixNature),
        ("test_relevance", RelevanceEnum),
        ("scope", ScopeDiscipline),
    ],
)
def test_every_commit_level_question_can_answer_insufficient(field, enum) -> None:
    """Each diff-level question has its own escape hatch, not just the dimension verdict."""
    values = _enum_values(CommitJudgment.model_json_schema(), field)
    assert "insufficient_evidence" in values
    assert enum.INSUFFICIENT_EVIDENCE.value in values


def test_test_relevance_distinguishes_an_unrelated_test() -> None:
    """The value that only a diff-reader can produce, and the reason L4 exists."""
    values = _enum_values(CommitJudgment.model_json_schema(), "test_relevance")
    assert "unrelated_test" in values
    assert "no_test" in values


def test_findings_carry_no_numeric_score() -> None:
    """No overall single score — enforced by the type, not by remembering not to add one."""
    fields = DimensionFinding.model_fields
    assert "score" not in fields
    assert not any(f in fields for f in ("rating", "grade", "rank", "percentile"))


def test_a_claim_can_carry_a_path_not_just_a_sha() -> None:
    claim = Claim(text="x", locators=[{"sha": "a" * 40, "path": "src/auth.py"}])
    assert claim.locators[0].path == "src/auth.py"
