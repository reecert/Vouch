"""Judge tests: structured-output enforcement, evidence-grounding, provider fallback.
Driven by a scripted stub provider — no network, no real LLM."""
from datetime import datetime

import pytest

from vouch.config import CONFIG
from vouch.judge import (
    JudgeError,
    ProviderError,
    judge,
    render_prompt,
    validate_grounding,
)
from vouch.schemas import CommitMeta, EvidenceBundle, Signal, Verdict


def make_bundle() -> EvidenceBundle:
    sha = "a" * 40
    return EvidenceBundle(
        repo="https://example.com/x.git",
        subject="alice@example.com",
        n_commits_by_subject=3,
        signals=[Signal(key="fixed_own_bug", value=2, evidence=[sha], computed_at=datetime.now())],
        commit_index={
            sha: CommitMeta(
                sha=sha, short=sha[:8], authored_at=datetime(2025, 1, 1),
                subject="fix bug", n_files=1, touched_tests=True,
            )
        },
    )


class StubProvider:
    """Returns queued responses; optionally raises ProviderError first."""

    def __init__(self, responses, name="stub", available=True, raise_first=False):
        self.name = name
        self.model = "stub-1"
        self._responses = list(responses)
        self._available = available
        self._raise_first = raise_first
        self.calls = 0

    def is_available(self):
        return self._available

    def complete_json(self, prompt):
        self.calls += 1
        if self._raise_first and self.calls == 1:
            raise ProviderError("simulated 429")
        return self._responses.pop(0)


def good_json(sha="a" * 40):
    return Verdict(
        dimension="ownership", score=0.8, confidence=0.7,
        freshness="2025-01-01", rationale=f"self-fix in {sha}", cited_evidence=[sha],
    ).model_dump_json()


# --- grounding validator -------------------------------------------------------------


def test_validate_grounding_accepts_prefix():
    bundle = make_bundle()
    full = "a" * 40
    v = Verdict(dimension="ownership", score=0.5, confidence=0.5,
                freshness="2025-01-01", rationale="x", cited_evidence=[full[:8]])
    assert validate_grounding(v, bundle) == []


def test_validate_grounding_flags_unknown():
    bundle = make_bundle()
    v = Verdict(dimension="ownership", score=0.5, confidence=0.5,
                freshness="2025-01-01", rationale="x", cited_evidence=["deadbeef" * 5])
    assert validate_grounding(v, bundle) == ["deadbeef" * 5]


# --- happy path ----------------------------------------------------------------------


def test_judge_returns_grounded_verdict():
    bundle = make_bundle()
    p = StubProvider([good_json()])
    verdict, model = judge(bundle, providers=[p])
    assert verdict.score == 0.8
    assert model == "stub:stub-1"


# --- structured-output enforcement ---------------------------------------------------


def test_judge_retries_on_bad_json_then_succeeds():
    bundle = make_bundle()
    p = StubProvider(["not json at all", good_json()])
    verdict, _ = judge(bundle, providers=[p])
    assert verdict.score == 0.8
    assert p.calls == 2  # one retry consumed


def test_judge_fails_loud_on_persistent_bad_json():
    bundle = make_bundle()
    p = StubProvider(["nope", "still nope"])
    with pytest.raises(JudgeError, match="structured-output failed"):
        judge(bundle, providers=[p])


# --- evidence-grounding enforcement --------------------------------------------------


def test_judge_retries_on_ungrounded_then_succeeds():
    bundle = make_bundle()
    bad = good_json("f" * 40)  # cites a SHA not in the bundle
    p = StubProvider([bad, good_json()])
    verdict, _ = judge(bundle, providers=[p])
    assert verdict.cited_evidence == ["a" * 40]
    assert p.calls == 2


def test_judge_fails_loud_on_persistent_ungrounded():
    bundle = make_bundle()
    bad = good_json("f" * 40)
    p = StubProvider([bad, bad])
    with pytest.raises(JudgeError, match="ungrounded"):
        judge(bundle, providers=[p])


# --- provider fallback ---------------------------------------------------------------


def test_judge_fails_forward_on_provider_error():
    bundle = make_bundle()
    p1 = StubProvider([], name="p1", raise_first=True)  # raises ProviderError
    p2 = StubProvider([good_json()], name="p2")
    verdict, model = judge(bundle, providers=[p1, p2])
    assert model == "p2:stub-1"


def test_judge_skips_unavailable_providers():
    bundle = make_bundle()
    down = StubProvider([good_json()], name="down", available=False)
    up = StubProvider([good_json()], name="up")
    _, model = judge(bundle, providers=[down, up])
    assert model == "up:stub-1"


def test_judge_raises_when_no_provider_available():
    bundle = make_bundle()
    down = StubProvider([], name="down", available=False)
    with pytest.raises(JudgeError, match="no judge provider available"):
        judge(bundle, providers=[down])


# --- prompt --------------------------------------------------------------------------


def test_prompt_includes_version_and_only_indexed_shas():
    bundle = make_bundle()
    text = render_prompt(bundle, CONFIG)
    assert "ownership-v0" in text
    assert ("a" * 40) in text
    # the prompt must explicitly deny the model any diff/repo access
    assert "seen the diffs" in text and "NOT" in text
