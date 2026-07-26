"""Config over code.

Signal weights, thresholds, provider order, and the prompt version live here — not
scattered as literals across modules. A ``CapabilityReport`` records which config +
prompt produced it, so any report is reproducible.

Nothing here does I/O. Reading env vars for API keys happens in the judge providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------
# Ownership signals — v0 has 5 (review_followthrough dropped: not pure-git derivable).
# --------------------------------------------------------------------------------------

# key -> weight, used to sketch a prior/score context. The judge is handed these weights
# but is the final arbiter; weights are guidance, not a formula it must obey.
SIGNAL_WEIGHTS: dict[str, float] = {
    "returned_to_own_code": 0.30,
    "fixed_own_bug": 0.30,
    "tests_accompany_fixes": 0.25,
    "revert_recovery": 0.10,
    "commit_atomicity": 0.05,
}


@dataclass(frozen=True)
class Thresholds:
    """Tunable knobs for the deterministic extractors."""

    # returned_to_own_code: min gap to count a re-touch as "sustained", not drive-by.
    return_gap_days: int = 14
    # fixed_own_bug / tests_accompany_fixes: subject-line keywords that mark a fix commit.
    fix_keywords: tuple[str, ...] = (
        "fix",
        "bug",
        "resolve",
        "patch",
        "regression",
        "hotfix",
        "correct",
    )
    # commit_atomicity: a commit touching <= this many files counts as "focused".
    atomic_max_files: int = 3
    # revert_recovery: body marker git writes for a revert.
    revert_marker: str = "This reverts commit"


THRESHOLDS = Thresholds()


# --------------------------------------------------------------------------------------
# Provider fallback chain (fail forward on 429/error). Free-tier native.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderSpec:
    name: str  # "gemini" | "groq" | "ollama"
    model: str
    api_key_env: str | None  # None for local Ollama


PROVIDER_CHAIN: tuple[ProviderSpec, ...] = (
    ProviderSpec("gemini", "gemini-2.0-flash", "GEMINI_API_KEY"),
    ProviderSpec("groq", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
    ProviderSpec("ollama", "qwen2.5-coder", None),
)


# --------------------------------------------------------------------------------------
# Prompt / retry
# --------------------------------------------------------------------------------------

PROMPT_VERSION = "ownership-v0"

# One bounded retry on structured-output parse failure; one retry on grounding failure.
MAX_STRUCTURED_RETRIES = 1
MAX_GROUNDING_RETRIES = 1


# --------------------------------------------------------------------------------------
# Eval knobs (Phase 5). Honest-at-this-n policy lives here, not scattered in the harness.
# --------------------------------------------------------------------------------------

# A verdict's continuous score maps to a strong/weak prediction at this cut. Recorded on
# Config so a reported agreement number is reproducible from the config that produced it.
VERDICT_STRONG_THRESHOLD = 0.5

# Below this many *total* labeled repos, numbers are directional, not evidence — the
# harness warns loudly rather than presenting them as a result.
MIN_LABELS_FOR_EVIDENCE = 15

# Below this many *scored* repos, full calibration (a reliability curve) is meaningless;
# the harness reports calibration as ``insufficient_n`` and never claims "calibrated".
MIN_LABELS_FOR_CALIBRATION = 30


@dataclass(frozen=True)
class Config:
    """Everything a report needs to be reproducible, in one fingerprintable object."""

    signal_weights: dict[str, float] = field(default_factory=lambda: dict(SIGNAL_WEIGHTS))
    thresholds: Thresholds = THRESHOLDS
    provider_chain: tuple[ProviderSpec, ...] = PROVIDER_CHAIN
    prompt_version: str = PROMPT_VERSION
    verdict_strong_threshold: float = VERDICT_STRONG_THRESHOLD


CONFIG = Config()
