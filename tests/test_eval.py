"""Eval-harness tests. The harness is only trustworthy if it catches a misbehaving judge,
so most of these drive the ADVERSARIAL mock and assert the failure is caught — not that a
clean mock passes. All offline: synthetic bundles, no git, no network.
"""
from datetime import datetime

import pytest
from pydantic import ValidationError

from vouch.config import CONFIG, MIN_LABELS_FOR_CALIBRATION
from vouch.eval import (
    EvalError,
    MockJudgeProvider,
    MockMode,
    check_support,
    evaluate_one,
    run_eval,
)
from vouch.eval.labels import LabeledRepo, LabelSet, LabelValidationError, load_labels
from vouch.judge.cache import JudgeCache, bundle_hash
from vouch.schemas import CommitMeta, EvidenceBundle, Signal, Verdict

# --------------------------------------------------------------------------------------
# synthetic bundles (stand in for ingest+extract so the harness runs fully offline)
# --------------------------------------------------------------------------------------

_STRONG_KEYS = (
    "returned_to_own_code", "fixed_own_bug", "tests_accompany_fixes",
    "revert_recovery", "commit_atomicity",
)


def make_bundle(repo="r", author="alice@example.com", *, strength="strong", n=10) -> EvidenceBundle:
    """A strong bundle has non-zero signals + backing SHAs; a weak bundle is all zeros."""
    ts = datetime(2025, 3, 1, 12, 0, 0)
    if strength == "strong":
        shas = [f"{i:040x}" for i in range(1, 4)]
        signals = [
            Signal(key=k, value=(2 if k in ("returned_to_own_code", "fixed_own_bug", "revert_recovery")
                                 else 1.0), evidence=shas, computed_at=ts)
            for k in _STRONG_KEYS
        ]
        index = {
            s: CommitMeta(sha=s, short=s[:8], authored_at=ts, subject="fix bug",
                          n_files=2, touched_tests=True)
            for s in shas
        }
    else:
        signals = [Signal(key=k, value=0, evidence=[], computed_at=ts) for k in _STRONG_KEYS]
        index = {}
    return EvidenceBundle(
        repo=repo, subject=author, n_commits_by_subject=n,
        window_first=ts.date(), window_last=ts.date(), signals=signals, commit_index=index,
    )


def bundle_fn_for(mapping: dict[tuple[str, str], EvidenceBundle]):
    """A harness bundle_fn that returns a pre-built bundle per (repo, author)."""
    def fn(labeled: LabeledRepo, config):
        return mapping[(labeled.repo, labeled.author)]
    return fn


def lbl(repo, author="alice@example.com", label="strong", reason="returns to fix own bugs w/ tests"):
    return LabeledRepo(repo=repo, author=author, label=label, reason=reason)


# --------------------------------------------------------------------------------------
# 1. label schema + validation
# --------------------------------------------------------------------------------------


def test_label_requires_reason():
    with pytest.raises(ValidationError, match="reason"):
        LabeledRepo(repo="r", author="a@x.com", label="strong", reason="")


def test_label_rejects_bad_label():
    with pytest.raises(ValidationError, match="label"):
        LabeledRepo(repo="r", author="a@x.com", label="excellent", reason="x")


def test_load_labels_missing_reason_fails_loud(tmp_path):
    p = tmp_path / "labels.yaml"
    p.write_text(
        "train:\n  - repo: r\n    author: a@x.com\n    label: strong\nholdout: []\n"
    )
    with pytest.raises(LabelValidationError, match="reason"):
        load_labels(p)


def test_load_labels_valid_split(tmp_path):
    p = tmp_path / "labels.yaml"
    p.write_text(
        "train:\n  - {repo: r1, author: a@x.com, label: strong, reason: fixes own bugs}\n"
        "holdout:\n  - {repo: r2, author: b@x.com, label: weak, reason: drive-by only}\n"
    )
    ls = load_labels(p)
    assert ls.total == 2
    assert ls.train[0].label_is_strong
    assert ls.holdout[0].label == "weak"


def test_load_labels_rejects_holdout_leak(tmp_path):
    p = tmp_path / "labels.yaml"
    p.write_text(
        "train:\n  - {repo: r1, author: a@x.com, label: strong, reason: x}\n"
        "holdout:\n  - {repo: r1, author: a@x.com, label: strong, reason: x}\n"
    )
    with pytest.raises(LabelValidationError, match="BOTH|leak"):
        load_labels(p)


def test_load_labels_rejects_legacy_flat_shape(tmp_path):
    p = tmp_path / "labels.yaml"
    p.write_text("labels:\n  - {repo: r1, author: a@x.com, label: strong, reason: x}\n")
    with pytest.raises(LabelValidationError, match="old flat"):
        load_labels(p)


def test_repo_labels_yaml_is_valid_and_empty():
    # The committed default must parse and be the tested empty-holdout state.
    from pathlib import Path
    ls = load_labels(Path("eval/labels.yaml"))
    assert ls.holdout == [] and ls.train == []


# --------------------------------------------------------------------------------------
# 2. bundle-hash judge cache
# --------------------------------------------------------------------------------------


def test_bundle_hash_ignores_volatile_computed_at():
    b1 = make_bundle()
    b2 = make_bundle()
    # perturb only computed_at
    for s in b2.signals:
        s.computed_at = datetime(1999, 1, 1)
    assert bundle_hash(b1, "p") == bundle_hash(b2, "p")


def test_bundle_hash_changes_with_prompt_version():
    b = make_bundle()
    assert bundle_hash(b, "v0") != bundle_hash(b, "v1")


def test_bundle_hash_changes_with_evidence():
    assert bundle_hash(make_bundle(strength="strong"), "p") != bundle_hash(
        make_bundle(strength="weak"), "p"
    )


def test_cache_roundtrip(tmp_path):
    cache = JudgeCache(tmp_path / "j")
    b = make_bundle()
    key = bundle_hash(b, "p")
    assert cache.get(key) is None
    v = Verdict(dimension="ownership", score=0.8, confidence=0.5,
                freshness="2025-03-01", rationale="x", cited_evidence=[])
    cache.put(key, v, "mock:honest")
    got = cache.get(key)
    assert got is not None and got[0].score == 0.8 and got[1] == "mock:honest"


def test_rerun_does_not_recall_judge(tmp_path):
    """The whole point of the cache: a second eval run makes zero judge calls."""
    labels = LabelSet(holdout=[lbl("r1")])
    bundles = {("r1", "alice@example.com"): make_bundle()}
    cache = JudgeCache(tmp_path / "j")

    p1 = MockJudgeProvider(MockMode.HONEST)
    run_eval(labels, [p1], split="holdout", bundle_fn=bundle_fn_for(bundles), cache=cache)
    assert p1.calls == 1

    p2 = MockJudgeProvider(MockMode.HONEST)  # fresh provider — proves calls hit disk, not it
    cache2 = JudgeCache(tmp_path / "j")
    rep = run_eval(labels, [p2], split="holdout", bundle_fn=bundle_fn_for(bundles), cache=cache2)
    assert p2.calls == 0
    assert rep.cache_hits == 1
    assert rep.results[0].from_cache is True


# --------------------------------------------------------------------------------------
# 3. adversarial mock — each failure mode must be CAUGHT
# --------------------------------------------------------------------------------------


def _one(mode, strength="strong", label="strong"):
    b = make_bundle(strength=strength)
    return evaluate_one(
        lbl("r1", label=label), [MockJudgeProvider(mode)],
        bundle_fn=bundle_fn_for({("r1", "alice@example.com"): b}),
    )


def test_catches_malformed_json():
    r = _one(MockMode.MALFORMED_JSON)
    assert r.outcome == "judge_failed"
    assert "structured-output" in r.detail


def test_catches_hallucinated_sha():
    r = _one(MockMode.HALLUCINATED_SHA)
    assert r.outcome == "judge_failed"
    assert "ungrounded" in r.detail


def test_catches_inflated_unsupported_score():
    # INFLATED is well-formed AND grounded (cites nothing) — the judge lets it through.
    # Only the harness support check stops it.
    r = _one(MockMode.INFLATED, strength="strong")
    assert r.outcome == "unsupported"
    assert "cites no evidence" in r.detail


def test_inflated_on_empty_signals_also_caught():
    r = _one(MockMode.INFLATED, strength="weak")
    assert r.outcome == "unsupported"


def test_honest_mock_scores_and_agrees_on_strong():
    r = _one(MockMode.HONEST, strength="strong", label="strong")
    assert r.outcome == "scored" and r.correct is True and r.predicted == "strong"


def test_honest_mock_scores_and_agrees_on_weak():
    r = _one(MockMode.HONEST, strength="weak", label="weak")
    assert r.outcome == "scored" and r.correct is True and r.predicted == "weak"


def test_support_check_passes_a_grounded_strong_verdict():
    b = make_bundle(strength="strong")
    v = Verdict(dimension="ownership", score=0.9, confidence=0.7, freshness="2025-03-01",
                rationale="cited", cited_evidence=[next(iter(b.commit_index))])
    assert check_support(v, b, CONFIG) == []


# --------------------------------------------------------------------------------------
# 4. train/holdout discipline + honest metrics
# --------------------------------------------------------------------------------------


def test_refuses_empty_holdout():
    labels = LabelSet(train=[lbl("r1")], holdout=[])
    with pytest.raises(EvalError, match="holdout is empty"):
        run_eval(labels, [MockJudgeProvider(MockMode.HONEST)], split="holdout",
                 bundle_fn=bundle_fn_for({("r1", "alice@example.com"): make_bundle()}))


def test_warns_loudly_below_evidence_threshold():
    labels = LabelSet(holdout=[lbl("r1")])
    rep = run_eval(labels, [MockJudgeProvider(MockMode.HONEST)], split="holdout",
                   bundle_fn=bundle_fn_for({("r1", "alice@example.com"): make_bundle()}))
    assert any("DIRECTIONAL" in w for w in rep.warnings)


def test_no_evidence_outcome_when_no_commits():
    b = make_bundle(n=0)
    r = evaluate_one(lbl("r1"), [MockJudgeProvider(MockMode.HONEST)],
                     bundle_fn=bundle_fn_for({("r1", "alice@example.com"): b}))
    assert r.outcome == "no_evidence"


def test_metrics_agreement_and_confidence_separation():
    # Two correct (strong->strong), one incorrect (a mislabeled weak-scoring bundle called
    # strong). Confidence tracks n_commits in the honest mock, so we set n to control it.
    mapping = {
        ("c1", "alice@example.com"): make_bundle("c1", strength="strong", n=18),  # correct, high conf
        ("c2", "alice@example.com"): make_bundle("c2", strength="strong", n=18),  # correct, high conf
        ("w1", "alice@example.com"): make_bundle("w1", strength="strong", n=2),   # scored strong, label weak -> incorrect, low conf
    }
    labels = LabelSet(holdout=[
        lbl("c1", label="strong"), lbl("c2", label="strong"), lbl("w1", label="weak"),
    ])
    rep = run_eval(labels, [MockJudgeProvider(MockMode.HONEST)], split="holdout",
                   bundle_fn=bundle_fn_for(mapping))
    m = rep.metrics
    assert m.n_scored == 3
    assert m.n_correct == 2 and m.n_incorrect == 1
    assert m.agreement == round(2 / 3, 4)
    # honest mock is more confident when it has more commits, and here that lines up with
    # being correct -> positive separation.
    assert m.confidence_separation is not None and m.confidence_separation > 0
    assert m.calibration_status == "insufficient_n"


def test_calibration_never_claims_calibrated():
    labels = LabelSet(holdout=[lbl("r1")])
    rep = run_eval(labels, [MockJudgeProvider(MockMode.HONEST)], split="holdout",
                   bundle_fn=bundle_fn_for({("r1", "alice@example.com"): make_bundle()}))
    assert rep.metrics.calibration_status == "insufficient_n"
    assert rep.metrics.calibration_threshold == MIN_LABELS_FOR_CALIBRATION


def test_mixed_run_surfaces_all_outcomes():
    mapping = {
        ("ok", "alice@example.com"): make_bundle("ok", strength="strong"),
        ("bad", "alice@example.com"): make_bundle("bad", strength="strong"),
    }
    labels = LabelSet(holdout=[lbl("ok", label="strong"), lbl("bad", label="strong")])
    # one honest provider path per row won't differ; instead evaluate_one per row with modes
    r_ok = evaluate_one(lbl("ok"), [MockJudgeProvider(MockMode.HONEST)],
                        bundle_fn=bundle_fn_for(mapping))
    r_bad = evaluate_one(lbl("bad"), [MockJudgeProvider(MockMode.INFLATED)],
                         bundle_fn=bundle_fn_for(mapping))
    assert r_ok.outcome == "scored"
    assert r_bad.outcome == "unsupported"
    assert labels.total == 2
