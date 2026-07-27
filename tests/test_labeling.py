"""The blind labelling harness.

Ground truth here is one human's judgement of a real engineer's history, so whether it is
worth scoring a model against is a property of the *procedure*. Three properties carry the
weight, and each has a test:

* the labeller never sees the judge's verdict;
* the train/holdout split is fixed before the evidence is drawn;
* the evidence is rendered as intervals, so a thin `0 of 5` cannot be read as a zero by the
  person writing the ground truth for it.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from tests.fixtures import repos
from vouch.eval import labeling
from vouch.eval.labeling import (
    SPLIT_HOLDOUT_SHARE,
    append_label,
    assign_split,
    build_task,
    pending_tasks,
    render_task,
)
from vouch.eval.labels import LabelValidationError, load_labels
from vouch.ingest import ingest
from vouch.l1.extract import extract_facts
from vouch.l4.dimensions import DIMENSIONS
from vouch.l4.schema import DimensionKey, Verdict

SUBJECT = "alice@example.com"


@pytest.fixture
def facts(tmp_path: Path):
    repo = tmp_path / "early_career"
    repos.early_career(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    return extract_facts(snapshot, SUBJECT, repo)


def _spec(key: DimensionKey):
    return next(s for s in DIMENSIONS if s.key is key)


# --- blindness -----------------------------------------------------------------------------


def test_the_harness_cannot_be_handed_a_judge_result() -> None:
    """Blindness is structural, not a convention someone remembers to follow.

    Shown a model's verdict first, a human agrees with it far more often than they would
    unprompted — and the eval then measures how persuasive the judge is, not how right.
    """
    params = inspect.signature(build_task).parameters
    assert set(params) == {"spec", "corpus_id", "facts", "corroboration"}

    source = inspect.getsource(labeling)
    assert "JudgeResult" not in source
    assert "vouch.l4.judge" not in source


def test_a_rendered_task_contains_no_verdict_language(facts) -> None:
    task = build_task(_spec(DimensionKey.VERIFICATION_DISCIPLINE), "row", facts)
    text = render_task(task)

    # The vocabulary appears once, as the menu of answers — never as an assertion.
    assert text.count("strong") == 1
    assert "the judge" not in text.lower()


# --- the split is fixed before anyone looks ---------------------------------------------------


def test_the_split_is_deterministic() -> None:
    a = assign_split("wagtail-contrib", DimensionKey.OWNERSHIP)
    b = assign_split("wagtail-contrib", DimensionKey.OWNERSHIP)
    assert a == b and a in {"train", "holdout"}


def test_the_split_differs_by_dimension_so_no_history_lands_wholly_on_one_side() -> None:
    ids = ["hunter", "svcs", "httpx", "black", "pytest", "flask", "wagtail-contrib"]
    both = [
        row
        for row in ids
        if len({assign_split(row, s.key) for s in DIMENSIONS}) > 1
    ]
    assert both, "every corpus row landed entirely in one pool — the split is not splitting"


def test_the_split_is_assigned_before_the_evidence_is_rendered(facts) -> None:
    """A holdout chosen after reading the evidence is not a holdout."""
    spec = _spec(DimensionKey.OWNERSHIP)
    task = build_task(spec, "row", facts)
    assert task.split == assign_split("row", spec.key)


def test_the_holdout_share_is_roughly_as_declared() -> None:
    rows = [f"row-{i}" for i in range(200)]
    splits = [assign_split(r, s.key) for r in rows for s in DIMENSIONS]
    share = splits.count("holdout") / len(splits)
    assert abs(share - SPLIT_HOLDOUT_SHARE) < 0.06


# --- what the labeller sees --------------------------------------------------------------------


def test_a_thin_fact_is_shown_as_an_interval_not_a_zero(facts) -> None:
    """The person writing ground truth must not read `0 of 5` as a zero either."""
    task = build_task(_spec(DimensionKey.VERIFICATION_DISCIPLINE), "row", facts)
    line = next(line for line in task.evidence if "test_accompanies_fix" in line)

    assert "0-0.4" in line.replace(" ", "")
    assert "0/5" in line


def test_confounds_are_shown_with_their_direction(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    repos.solo(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    solo_facts = extract_facts(snapshot, SUBJECT, repo)

    task = build_task(_spec(DimensionKey.OWNERSHIP), "solo", solo_facts)
    assert any("solo_repo" in c for c in task.confounds)


def test_insufficient_evidence_is_offered_as_a_first_class_answer(facts) -> None:
    task = build_task(_spec(DimensionKey.OWNERSHIP), "row", facts)
    text = render_task(task)

    assert "insufficient_evidence" in text
    assert "is a real answer" in text


def test_pending_skips_what_is_already_labelled() -> None:
    done = {("hunter", DimensionKey.OWNERSHIP)}
    pending = list(pending_tasks(done, ["hunter"]))

    assert ("hunter", DimensionKey.OWNERSHIP) not in [(i, s.key) for i, s in pending]
    assert len(pending) == len(DIMENSIONS) - 1


# --- writing labels ------------------------------------------------------------------------------


def test_a_label_is_written_into_the_pool_its_split_assigned(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")

    append_label(
        path,
        "hunter",
        DimensionKey.OWNERSHIP,
        Verdict.INSUFFICIENT_EVIDENCE,
        "solo repo, so there is nobody else's defect to have returned to",
        "holdout",
    )

    data = yaml.safe_load(path.read_text())
    assert data["train"] == []
    assert data["holdout"][0]["corpus_id"] == "hunter"
    assert "author" not in data["holdout"][0]


def test_a_written_label_reloads_through_the_validator(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    append_label(
        path,
        "hunter",
        DimensionKey.OWNERSHIP,
        Verdict.LIMITED,
        "two self-fixes over ten years, neither with a test in the same commit",
        "train",
    )

    labels = load_labels(path, known_ids={"hunter"})
    assert labels.total == 1
    assert labels.train[0].corpus_id == "hunter"


def test_a_reason_carrying_an_address_fails_on_reload(tmp_path: Path) -> None:
    """The write is naive on purpose; the loader is the gate, and the CLI reloads after each."""
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    append_label(
        path,
        "hunter",
        DimensionKey.OWNERSHIP,
        Verdict.STRONG,
        "someone@example.com fixes their own defects",
        "train",
    )

    with pytest.raises(LabelValidationError, match="email-shaped"):
        load_labels(path)
