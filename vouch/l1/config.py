"""L1 thresholds — every tunable number the deterministic layer depends on, in one place.

Two rules govern what lives here:

* **A report records the config that produced it.** ``L1Config.fingerprint()`` is stable and
  goes into provenance, so a number can always be traced back to the thresholds behind it.
* **No weights.** The v0 prototype carried ``SIGNAL_WEIGHTS`` to blend signals into one
  score. The product has no overall score, so there is nothing for weights to feed and they
  are gone. Dimensional readouts are reported side by side, never summed.

:data:`FIX_KEYWORDS` is a deliberately conservative proxy, tuned to miss fixes phrased
unusually rather than to invent them. L4 reads the diff and can say a keyword-matched commit
was not actually a fix; it cannot recover one we never surfaced.

Nothing here does I/O.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

__all__ = ["MinN", "Detection", "L1Config", "L1_CONFIG", "FIX_KEYWORDS"]

# Stems, matched at a word start: plain substring matching read "prefix" and "dispatch" as fixes.
FIX_KEYWORDS: tuple[str, ...] = (
    "fix",
    "hotfix",
    "bug",
    "patch",
    "regress",
    "repair",
    "resolv",
    "correct",
    "broke",
    "crash",
)


@dataclass(frozen=True)
class MinN:
    """Denominator floors. Below these a rate is **suppressed, not rounded**.

    The competitor publishes five percentages derived from 18 sessions with no visible
    floor (see docs/baseline-competitor.md §4). Suppression is the cheapest place we are
    strictly more honest than the baseline.
    """

    fix_commits: int = 3  # test_accompanies_fix, ownership_loop
    subject_commits: int = 10  # revert_rate, commit_scoping
    latency_pairs: int = 3  # followup_latency


@dataclass(frozen=True)
class Detection:
    """Thresholds for the confound detectors."""

    return_gap_days: int = 14  # sooner than this, a self-fix is the same session finishing
    test_adjacency_hours: int = 24

    solo_authorship_share: float = 0.95
    squash_marker_share: float = 0.30  # subjects ending in GitHub's " (#123)"
    bot_share: float = 0.20
    noise_touch_share: float = 0.30
    rebase_skew_share: float = 0.30  # rebase keeps the author date and rewrites the committer's
    rebase_skew_days: int = 1
    short_window_days: int = 30

    max_blamed_files_per_commit: int = 25  # blame is one git call per (commit, file)


@dataclass(frozen=True)
class L1Config:
    """Everything L1 needs to be reproducible, in one fingerprintable object."""

    min_n: MinN = field(default_factory=MinN)
    detection: Detection = field(default_factory=Detection)
    fix_keywords: tuple[str, ...] = FIX_KEYWORDS

    def fingerprint(self) -> str:
        """Stable short hash of the config. Goes into report provenance."""
        blob = json.dumps(asdict(self), sort_keys=True, default=list)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


L1_CONFIG = L1Config()
