"""L1 thresholds — every tunable number the deterministic layer depends on, in one place.

Two rules govern what lives here:

* **A report records the config that produced it.** ``L1Config.fingerprint()`` is stable and
  goes into provenance, so a number can always be traced back to the thresholds behind it.
* **No weights.** The v0 prototype carried ``SIGNAL_WEIGHTS`` to blend signals into one
  score. The product has no overall score, so there is nothing for weights to feed and they
  are gone. Dimensional readouts are reported side by side, never summed.

Nothing here does I/O.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

__all__ = ["MinN", "Detection", "L1Config", "L1_CONFIG", "FIX_KEYWORDS"]

# Subject-line markers for a defect fix. These are **stems**: the matcher anchors them to a
# word start and allows any suffix, so "fix" catches fixes/fixed while "prefix", "suffix"
# and "dispatch" are correctly not fix commits (the prototype's plain substring match read
# "refactor prefix handling" as a bug fix).
#
# Deliberately conservative: this is a *proxy*, tuned to miss fixes phrased unusually
# rather than to invent them. L4 reads the diff and can say a keyword-matched commit was
# not actually a fix; it cannot recover one we never surfaced. A miss costs less than a
# false positive.
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

    # returned-to-fix: a self-fix must land at least this long after the code it repairs,
    # otherwise it is the same work session finishing, not a return.
    return_gap_days: int = 14
    # a test landing this soon after a fix counts as accompanying it.
    test_adjacency_hours: int = 24

    # solo_repo: subject authored at least this share of all human commits.
    solo_authorship_share: float = 0.95
    # squash_merge_history: share of commits whose subject ends in GitHub's " (#123)".
    squash_marker_share: float = 0.30
    # bot_dominated: share of commits authored by machines.
    bot_share: float = 0.20
    # vendored_or_generated_bulk: share of file touches that are noise.
    noise_touch_share: float = 0.30
    # rebase_rewritten_authorship: share of commits where committer date runs far ahead of
    # author date. Rebase preserves the author date and rewrites the committer date, so a
    # large gap across many commits means the history was replayed.
    rebase_skew_share: float = 0.30
    rebase_skew_days: int = 1
    # short_window: subject's activity spans fewer than this many days.
    short_window_days: int = 30

    # Blame is one git call per (commit, file); a squashed 400-file commit would otherwise
    # dominate runtime. Files are taken in sorted order so the cap is deterministic.
    max_blamed_files_per_commit: int = 25


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
