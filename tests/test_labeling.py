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

import hashlib
import inspect
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from tests.fixtures import repos
from vouch.eval import labeling
from vouch.eval.labeling import (
    RENDER_VERSION,
    SPLIT_HOLDOUT_SHARE,
    append_label,
    assign_split,
    build_task,
    current_provenance,
    pending_tasks,
    render_task,
)
from vouch.eval.labels import LabelProvenance, LabelValidationError, load_labels
from vouch.ingest import ingest
from vouch.l1.extract import extract_facts
from vouch.l1.facts import (
    BiasDirection,
    Confound,
    ConfoundKey,
    Fact,
    FactStatus,
    Identity,
    Interval,
    Polarity,
    RepoFacts,
    Severity,
    Unit,
)
from vouch.l2.payload import MetricKey, MetricScope, Rate, SessionMetrics
from vouch.l4.dimensions import DIMENSIONS
from vouch.l4.schema import DimensionKey, Verdict

SUBJECT = "alice@example.com"

#: Repo-scoped and unsuppressed, so the rendering of a *present* metric is what is under
#: test rather than the scope contract that would refuse it.
_METRICS = SessionMetrics(
    scope=MetricScope.REPO,
    n_sessions=20,
    rates={
        key: Rate(numerator=8, denominator=20, floor=5, value=0.4, low=0.24, high=0.58)
        for key in MetricKey
    },
)


#: Facts written out by hand rather than extracted, so the render digest below depends on
#: the render alone. Extracting them would make an extractor change look like a render
#: change, and `extractor_version` already covers that.
_RENDER_FIXTURE = RepoFacts(
    repo="fixture",
    head_sha="a" * 40,
    subject=Identity(canonical_email=SUBJECT),
    window_first=date(2024, 1, 1),
    window_last=date(2024, 6, 30),
    n_commits_by_subject=45,
    n_commits_total=900,
    facts=[
        Fact(
            key="test_accompanies_fix", status=FactStatus.MEASURED, value=0.0,
            polarity=Polarity.HIGHER_IS_BETTER, numerator=0, denominator=5,
            interval=Interval(low=0.0, high=0.4295, low_level=0.8, high_level=0.95),
        ),
        Fact(
            # The note is the reason alone, exactly as `_apply_suppression` writes it: a
            # note that repeated the status is what produced the stutter this fixture now
            # guards against.
            key="ownership_loop", status=FactStatus.NOT_ASSESSABLE,
            polarity=Polarity.HIGHER_IS_BETTER,
            note="subject authored 45/45 human commits (100%); 1 distinct human author(s)",
        ),
        Fact(
            key="followup_latency", status=FactStatus.SUPPRESSED_LOW_N, unit=Unit.DAYS,
            polarity=Polarity.LOWER_IS_BETTER, denominator=2,
            interval=Interval(low=2.0, high=91.0, low_level=0.95, high_level=0.8),
        ),
        Fact(
            key="revert_rate", status=FactStatus.MEASURED, value=0.0385,
            polarity=Polarity.LOWER_IS_BETTER, numerator=1, denominator=26,
            interval=Interval(low=0.0003, high=0.005, low_level=0.95, high_level=0.8),
        ),
        Fact(
            key="commit_scoping", status=FactStatus.MEASURED, value=4.0, unit=Unit.FILES,
            polarity=Polarity.NEUTRAL, denominator=45,
            interval=Interval(low=2.0, high=2.0, low_level=0.95, high_level=0.95,
                              method="order-statistic"),
        ),
    ],
    confounds=[
        Confound(
            key=ConfoundKey.SOLO_REPO, severity=Severity.INVALIDATING,
            direction=BiasDirection.OVERSTATES, detail="98% of human commits",
            affects=["ownership_loop"],
        )
    ],
)

#: Bump with RENDER_VERSION. See test_the_render_version_tracks_what_is_actually_on_screen.
_RENDER_DIGEST = "a0edd6287ca909a5"


@pytest.fixture
def facts(tmp_path: Path):
    repo = tmp_path / "early_career"
    repos.early_career(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    return extract_facts(snapshot, SUBJECT, repo)


def _spec(key: DimensionKey):
    return next(s for s in DIMENSIONS if s.key is key)


def _extract(tmp_path: Path, variant: str) -> RepoFacts:
    """L1's real output for one fixture repo — notes and confound details included."""
    repo = tmp_path / variant
    getattr(repos, variant)(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    return extract_facts(snapshot, SUBJECT, repo)


# --- blindness -----------------------------------------------------------------------------


def test_the_harness_cannot_be_handed_a_judge_result() -> None:
    """Blindness is structural, not a convention someone remembers to follow.

    Shown a model's verdict first, a human agrees with it far more often than they would
    unprompted — and the eval then measures how persuasive the judge is, not how right.
    """
    params = inspect.signature(build_task).parameters
    assert set(params) == {"spec", "corpus_id", "facts", "metrics", "corroboration"}

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

    assert "0.00-0.43" in line
    assert "0/5" in line


def test_two_intervals_are_printed_at_the_same_precision(facts) -> None:
    """`%g` gave `0.0003-0.005` and `2-2` the same apparent exactness. They are not.

    A labeller comparing two dimensions was comparing two resolutions without being told
    which was which.
    """
    task = build_task(_spec(DimensionKey.OWNERSHIP), "row", facts)
    bands = [
        m for line in task.evidence
        if (m := re.search(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", line))
    ]

    assert bands, "no interval was rendered at all"
    for band in bands:
        low, high = band.group(1), band.group(2)
        decimals = [len(v.split(".")[1]) if "." in v else 0 for v in (low, high)]
        assert decimals[0] == decimals[1], band.group(0)


def test_every_layer_the_question_asks_about_is_rendered(facts) -> None:
    """The question spans L1 and L2, so the evidence has to.

    The harness rendered `spec.l1_facts` only, so `verification_discipline` — which asks
    "in the commit trail *and while working*?" — was labelled from the commit trail alone.
    The label that came back was ground truth for a narrower question than the one the
    judge is scored on, and nothing on screen said so.
    """
    for spec in DIMENSIONS:
        text = render_task(build_task(spec, "row", facts, _METRICS))
        missing = [key.value for key in spec.l2_metrics if key.value not in text]
        assert not missing, f"{spec.key.value} never renders {missing}"


def test_an_absent_layer_is_stated_rather_than_omitted(facts) -> None:
    """Omitting the section reads as "nothing to say here", which is the wrong claim."""
    spec = _spec(DimensionKey.VERIFICATION_DISCIPLINE)
    text = render_task(build_task(spec, "row", facts, metrics=None))

    assert "test_or_build_after_edit" in text
    assert "no session telemetry was supplied" in text


def test_a_suppressed_metric_shows_its_floor_not_a_silence(facts) -> None:
    thin = _METRICS.model_copy(
        update={
            "rates": {
                MetricKey.TEST_OR_BUILD_AFTER_EDIT: Rate(
                    numerator=1, denominator=2, floor=10, suppressed=True,
                    low=0.05, high=0.95,
                )
            }
        }
    )
    task = build_task(_spec(DimensionKey.VERIFICATION_DISCIPLINE), "row", facts, thin)
    line = next(line for line in task.session if "test_or_build_after_edit" in line)

    assert "1/2" in line and "floor of 10" in line
    assert "no point estimate" in line


def test_every_measure_states_which_way_to_read_it(facts) -> None:
    """`followup_latency: 92 days` is a complaint or a compliment. The render must say.

    The direction is also the asymmetry the interval was drawn on — the unfavourable end
    is held to the stricter confidence level — so a labeller who does not know it cannot
    know which end was made harder to reach.
    """
    for spec in DIMENSIONS:
        task = build_task(spec, "row", facts, _METRICS)
        measures = [
            line
            for line in (*task.evidence, *task.session)
            if "point estimate" in line or "too thin" in line
        ]
        assert measures, f"{spec.key.value} renders no measure at all"
        assert all("better]" in line for line in measures), measures


def test_a_days_fact_says_lower_is_better(facts) -> None:
    task = build_task(_spec(DimensionKey.OWNERSHIP), "row", facts)
    line = next(line for line in task.evidence if "followup_latency" in line)

    assert "days" in line and "[lower is better]" in line


def test_a_fact_with_no_better_direction_says_so_rather_than_going_quiet(facts) -> None:
    """A blank is indistinguishable from a forgotten one. `commit_scoping` has no polarity."""
    task = build_task(_spec(DimensionKey.SCOPE_CONTROL), "row", facts)
    line = next(line for line in task.evidence if "commit_scoping" in line)

    assert "[neither direction is better]" in line


def test_confounds_are_shown_with_their_direction(tmp_path: Path) -> None:
    task = build_task(
        _spec(DimensionKey.OWNERSHIP), "solo", _extract(tmp_path, "solo")
    )
    assert any("solo_repo" in c for c in task.confounds)


def test_a_fact_that_cannot_be_assessed_says_so_once(tmp_path: Path) -> None:
    """The status belongs to the line, the reason belongs to the note.

    Both used to say "not assessable", so a suppressed fact rendered as "not assessable —
    not assessable here — subject authored…" and the reason — the only part a labeller can
    act on — arrived third, behind two identical phrases.
    """
    task = build_task(
        _spec(DimensionKey.OWNERSHIP), "solo", _extract(tmp_path, "solo")
    )
    line = next(line for line in task.evidence if "ownership_loop" in line)

    assert line.count("not assessable") == 1
    assert "distinct human author" in line, "the reason did not survive the fix"


def test_a_commit_count_names_the_population_it_counts(tmp_path: Path) -> None:
    """Two denominators, adjacent, over different populations, is the missing-L2 failure.

    `subject activity` counts every author including bots; the confound lines beneath it
    count human commits only. Rendered as bare totals they read as one series — "671 of
    1482" above "1087 of 1335" — and a labeller who subtracts them, or who reads the
    subject's share off the wrong denominator, is drawing on a relationship nothing on
    screen ever stated.
    """
    facts = _extract(tmp_path, "squash_merged")
    task = build_task(_spec(DimensionKey.SCOPE_CONTROL), "squash", facts)

    activity = next(line for line in task.evidence if "subject activity" in line)
    squash = next(c for c in task.confounds if "squash_merge_history" in c)

    assert "by every author (bots included)" in activity
    assert "human-authored commits (bots excluded)" in squash


# --- what is not a judgement call is not offered as one ----------------------------------


def test_a_dimension_with_no_input_layer_forces_the_answer(facts) -> None:
    """`planning_discipline` reads from L2 alone. No CLI run means nothing was looked at.

    Offered mid-menu, `not_collected` is one of seven things to pick and reads as a
    judgement about thin evidence. It is not: it is a fact about what was collected, known
    before the labeller saw the row.
    """
    task = build_task(_spec(DimensionKey.PLANNING_DISCIPLINE), "row", facts, metrics=None)
    text = render_task(task)

    assert task.permitted == (Verdict.NOT_COLLECTED,)
    assert task.is_forced
    assert "CANNOT BE JUDGED HERE" in text
    assert "none was collected for this row" in text
    # The menu it would otherwise have sat in the middle of is gone.
    assert "insufficient_evidence" not in text


def test_out_of_scope_telemetry_forces_the_answer_too(facts) -> None:
    """Machine-wide sessions cannot describe work in one repo, however many there are."""
    machine_wide = _METRICS.model_copy(update={"scope": MetricScope.MACHINE})
    task = build_task(
        _spec(DimensionKey.PLANNING_DISCIPLINE), "row", facts, machine_wide
    )

    assert task.permitted == (Verdict.OUT_OF_SCOPE,)
    assert "different population" in render_task(task)


def test_a_dimension_that_was_looked_at_does_not_offer_not_collected(facts) -> None:
    """The converse: where a layer WAS read, "we did not look" is not an answer."""
    for key in (DimensionKey.OWNERSHIP, DimensionKey.VERIFICATION_DISCIPLINE):
        task = build_task(_spec(key), "row", facts, _METRICS)

        assert not task.is_forced
        assert Verdict.NOT_COLLECTED not in task.permitted
        assert Verdict.OUT_OF_SCOPE not in task.permitted
        assert Verdict.INSUFFICIENT_EVIDENCE in task.permitted


def test_evidence_that_decides_nothing_is_still_the_labeller_s_call() -> None:
    """"Present but not decisive" is a verdict on the menu, not a forced answer.

    Every corpus row renders `scope_control` this way: `commit_scoping` measured, neutral,
    and narrow — `2.0-2.0`, neither direction better — with `edit_revision` absent because
    a public repo has no session telemetry. The evidence is there, it is not thin, and it
    points nowhere.

    `insufficient_evidence` is that answer. It is not `not_collected` (the commit trail was
    read) and not `out_of_scope` (nothing was measured over the wrong population), and
    forcing either through `assess_availability` would write a harness assertion into the
    ground truth where a human judgement belongs — the harness knows what was collected, it
    does not know what decides a question.
    """
    task = build_task(_spec(DimensionKey.SCOPE_CONTROL), "row", _RENDER_FIXTURE, None)

    scoping = next(line for line in task.evidence if "commit_scoping" in line)
    assert "2.0-2.0" in scoping and "neither direction is better" in scoping
    assert any("no session telemetry" in line for line in task.session)

    assert not task.is_forced
    assert Verdict.INSUFFICIENT_EVIDENCE in task.permitted
    assert Verdict.NOT_COLLECTED not in task.permitted
    assert Verdict.OUT_OF_SCOPE not in task.permitted
    # Three distinct values, so a label recording one can never be read as another.
    assert len(
        {Verdict.INSUFFICIENT_EVIDENCE, Verdict.NOT_COLLECTED, Verdict.OUT_OF_SCOPE}
    ) == 3


def test_the_harness_and_the_judge_ask_the_same_availability_question(facts) -> None:
    """One function decides it for both, so the label and the verdict cannot disagree.

    If the harness reimplemented this, a labeller could be forced into `not_collected` on a
    dimension the judge went on to answer — and the disagreement would score as the judge
    being wrong.
    """
    source = inspect.getsource(labeling)
    assert "assess_availability" in source


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
        ["ownership_loop"],
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
        ["ownership_loop"],
        "train",
        provenance=_PROV,
    )

    labels = load_labels(path, known_ids={"hunter"})
    assert labels.total == 1
    assert labels.train[0].corpus_id == "hunter"


# --- provenance: naming the code the judgement was made against -----------------------------

_PROV = LabelProvenance(
    code_sha="0123456789abcdef",
    extractor_version="l1-extract/2",
    l1_config="abc123def456",
    render_version="label-render/1",
)


def _write(path: Path, prov: LabelProvenance, corpus_id: str = "hunter") -> None:
    append_label(
        path,
        corpus_id,
        DimensionKey.OWNERSHIP,
        Verdict.LIMITED,
        "two self-fixes over ten years, neither with a test in the same commit",
        ["ownership_loop"],
        "train",
        provenance=prov,
    )


def test_labels_without_a_code_sha_are_refused_on_load(tmp_path: Path) -> None:
    """An agreement number that cannot name the code it measured describes nothing."""
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    _write(path, LabelProvenance())  # no sha to stamp

    with pytest.raises(LabelValidationError, match="cannot name the code"):
        load_labels(path)


def test_the_first_write_stamps_the_code_it_was_made_against(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    _write(path, _PROV)

    assert load_labels(path).metadata.code_sha == "0123456789abcdef"
    # First, so a reader meets it before the judgements it qualifies.
    assert path.read_text().startswith("metadata:")


def test_a_later_write_does_not_restamp_the_round(tmp_path: Path) -> None:
    """The round is attributed to where it started, not to wherever it happened to end."""
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    _write(path, _PROV)
    _write(path, _PROV.model_copy(update={"code_sha": "ffffffffffffffff"}), "svcs")

    labels = load_labels(path)
    assert labels.total == 2
    assert labels.metadata.code_sha == "0123456789abcdef"


def test_an_extractor_bump_mid_round_is_refused(tmp_path: Path) -> None:
    """The labeller would be shown different numbers, so the two do not share a pool."""
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    _write(path, _PROV)

    with pytest.raises(ValueError, match="the code moved mid-round"):
        _write(path, _PROV.model_copy(update={"extractor_version": "l1-extract/3"}), "svcs")


def test_a_config_change_mid_round_is_refused_too(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    _write(path, _PROV)

    with pytest.raises(ValueError, match="l1_config"):
        _write(path, _PROV.model_copy(update={"l1_config": "999999999999"}), "svcs")


def test_a_dirty_tree_is_recorded_rather_than_refused(tmp_path: Path) -> None:
    """Labelling while the harness is being improved is normal; a silent sha is not."""
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    _write(path, _PROV.model_copy(update={"dirty": True}))

    assert load_labels(path).metadata.dirty is True


def test_provenance_reads_this_repo(tmp_path: Path) -> None:
    prov = current_provenance()

    assert len(prov.code_sha) == 40, "not a resolved git sha"
    assert prov.extractor_version and prov.l1_config
    assert prov.render_version == RENDER_VERSION
    # A label does not depend on how the JUDGE is prompted, so there is still no field for
    # that. `render_version` is the other thing entirely: what the human was shown.
    assert "prompt_version" not in LabelProvenance.model_fields


def test_a_render_change_mid_round_is_refused_like_an_extractor_bump(tmp_path: Path) -> None:
    """The missing-L2 bug is the proof: the render decides what a label means.

    Labels made under two renderers answer different questions while carrying an identical
    extractor version and an identical config, so nothing else in this stamp could catch it.
    """
    path = tmp_path / "labels.yaml"
    path.write_text("train: []\nholdout: []\n")
    _write(path, _PROV)

    with pytest.raises(ValueError, match="render_version"):
        _write(path, _PROV.model_copy(update={"render_version": "label-render/2"}), "svcs")


def test_the_render_version_tracks_what_is_actually_on_screen() -> None:
    """A version nobody remembers to bump is worse than none — it asserts a false sameness.

    The digest is over the rendered text for a fixed set of facts, so any change to what a
    labeller reads — a number's format, a section heading, a sentence of guidance — fails
    here until `RENDER_VERSION` moves with it.
    """
    rendered = "\n".join(
        render_task(build_task(spec, "row", _RENDER_FIXTURE, _METRICS))
        for spec in DIMENSIONS
    )
    digest = hashlib.sha256(rendered.encode()).hexdigest()[:16]

    assert digest == _RENDER_DIGEST, (
        f"the labelling render changed (digest {digest}). If that was deliberate, bump "
        "RENDER_VERSION in vouch/eval/labeling.py and this digest together — labels made "
        "under the old renderer are not comparable with labels made under the new one."
    )


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
        ["ownership_loop"],
        "train",
    )

    with pytest.raises(LabelValidationError, match="email-shaped"):
        load_labels(path)
