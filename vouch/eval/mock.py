"""Adversarial offline mock judge.

A harness that only ever sees well-behaved judge output is untested — the whole point of
the robustness contracts is to catch a judge that *misbehaves*. So the offline mock can be
told to misbehave, in exactly the ways a real LLM does:

  * ``HONEST``          — a plausible verdict derived from the signals, citing real SHAs.
                          Used to produce directional offline numbers.
  * ``MALFORMED_JSON``  — returns prose / broken JSON. The judge's structured-output
                          contract must catch this (retry, then fail loud).
  * ``HALLUCINATED_SHA``— cites a SHA absent from the bundle. The grounding validator must
                          catch this (retry, then fail loud).
  * ``INFLATED``        — a well-formed, *grounded* verdict (it cites nothing, so grounding
                          passes) that nonetheless claims a near-perfect score with no
                          supporting signals. The judge cannot catch this — it is a
                          semantic lie, not a schema/grounding defect — so the EVAL
                          HARNESS's support check must reject it. This is the failure mode
                          that proves the harness does more than trust the judge.

Each mock is a ``JudgeProvider`` (duck-typed), so it drops straight into
``judge(bundle, providers=[mock])`` and exercises the real judge code path — not a
shortcut around it.
"""
from __future__ import annotations

import enum
import json

from vouch.config import CONFIG, Config
from vouch.schemas import EvidenceBundle


class MockMode(enum.Enum):
    HONEST = "honest"
    MALFORMED_JSON = "malformed_json"
    HALLUCINATED_SHA = "hallucinated_sha"
    INFLATED = "inflated"


def _signal_score(bundle: EvidenceBundle, config: Config) -> float:
    """A crude, deterministic score from the weighted signals — the mock's 'reasoning'.

    Not the product's scoring model; just enough signal-tracking behavior that HONEST
    verdicts correlate with real evidence, so offline agreement numbers are meaningful.
    Booleans and counts are normalized to a 0..1 contribution; fractions pass through.
    """
    total = 0.0
    for s in bundle.signals:
        w = config.signal_weights.get(s.key, 0.0)
        v = s.value
        if isinstance(v, bool):
            contrib = 1.0 if v else 0.0
        elif isinstance(v, int):
            contrib = 1.0 if v > 0 else 0.0  # any evidence of the behavior
        else:
            contrib = max(0.0, min(1.0, float(v)))  # fractions already in range
        total += w * contrib
    return round(max(0.0, min(1.0, total)), 4)


def _honest_verdict_json(bundle: EvidenceBundle, config: Config) -> str:
    score = _signal_score(bundle, config)
    cited = sorted({sha for s in bundle.signals for sha in s.evidence})
    # Confidence tracks how much evidence there is, not how strong the verdict is.
    n = bundle.n_commits_by_subject
    confidence = round(max(0.05, min(0.9, n / 20.0)), 4) if cited else 0.1
    freshness = (bundle.window_last or bundle.window_first)
    freshness_s = freshness.isoformat() if freshness else "2020-01-01"
    verdict = {
        "dimension": "ownership",
        "score": score,
        "confidence": confidence,
        "freshness": freshness_s,
        "rationale": (
            f"score {score} from weighted signals; cited {len(cited)} backing commit(s)"
            if cited
            else "no backing commits; low-confidence weak verdict"
        ),
        "cited_evidence": cited,
    }
    return json.dumps(verdict)


def _inflated_verdict_json(bundle: EvidenceBundle) -> str:
    """Near-perfect score + confidence, but cites nothing and ignores the signals.

    Grounded (empty citation list can't be ungrounded) and schema-valid — so it sails past
    the judge. The harness support check is the only thing standing between this lie and a
    reported metric.
    """
    freshness = bundle.window_last or bundle.window_first
    freshness_s = freshness.isoformat() if freshness else "2020-01-01"
    verdict = {
        "dimension": "ownership",
        "score": 0.99,
        "confidence": 0.99,
        "freshness": freshness_s,
        "rationale": "clearly an excellent engineer with outstanding ownership.",
        "cited_evidence": [],
    }
    return json.dumps(verdict)


class MockJudgeProvider:
    """Offline ``JudgeProvider`` with selectable (mis)behavior. No network, ever."""

    def __init__(self, mode: MockMode = MockMode.HONEST, config: Config | None = None) -> None:
        self.name = "mock"
        self.model = f"mock-{mode.value}"
        self.mode = mode
        self.config = config or CONFIG
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def complete_json(self, prompt: str) -> str:
        self.calls += 1
        # The mock keys off the bundle, but the judge hands it a rendered prompt string.
        # We stash the current bundle on the instance via ``judge_for`` below; if that
        # wasn't used, fall back to emitting mode-appropriate junk that needs no bundle.
        bundle = getattr(self, "_bundle", None)
        if self.mode is MockMode.MALFORMED_JSON:
            return "Sure! Here is my assessment: the engineer is great. {score: high,,}"
        if bundle is None:
            # Shouldn't happen via ``judge_for``; keep it honest-ish and self-contained.
            return json.dumps(
                {
                    "dimension": "ownership", "score": 0.5, "confidence": 0.1,
                    "freshness": "2020-01-01", "rationale": "no bundle", "cited_evidence": [],
                }
            )
        if self.mode is MockMode.HALLUCINATED_SHA:
            v = json.loads(_honest_verdict_json(bundle, self.config))
            v["cited_evidence"] = ["deadbeef" * 5]  # 40 hex chars, guaranteed not in bundle
            v["rationale"] = "self-fix in deadbeef... (fabricated)"
            return json.dumps(v)
        if self.mode is MockMode.INFLATED:
            return _inflated_verdict_json(bundle)
        return _honest_verdict_json(bundle, self.config)

    def judge_for(self, bundle: EvidenceBundle) -> MockJudgeProvider:
        """Bind the bundle this mock is about to be asked about (so it can react to it)."""
        self._bundle = bundle
        return self
