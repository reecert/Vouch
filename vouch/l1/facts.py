"""L1 schema — the deterministic layer's output contract.

Two artifacts, deliberately separated:

* :class:`RepoFacts` — the measurements.
* :class:`Confound` — what would make those measurements wrong.

Three properties are enforced structurally rather than by convention:

1. **No timestamps in the payload.** ``RepoFacts`` is a pure function of (repo, HEAD,
   config), so two runs are byte-identical and golden-file tests are possible. Wall-clock
   provenance lives in an envelope one level up, never inside the hashed facts.
2. **Denominators are always visible.** A :class:`Fact` carries its numerator and
   denominator, so "100%" off n=1 is impossible to render without also rendering the 1.
3. **A fact can decline to have a value.** ``status`` distinguishes *measured* from
   *suppressed because n was too small* from *not assessable because a confound
   invalidates it*. There is no path that turns thin evidence into a number.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from vouch.l1.identity import Identity

__all__ = [
    "SCHEMA_VERSION",
    "Locator",
    "FactStatus",
    "Unit",
    "Fact",
    "ConfoundKey",
    "Severity",
    "BiasDirection",
    "Confound",
    "RepoFacts",
]

SCHEMA_VERSION = "l1/1"


class Locator(BaseModel):
    """The atom of citability: where in the repo a claim points.

    L4 may only cite locators that appeared in L1's output; the grounding validator checks
    SHA *and* path, so "the fix in `auth.py`" cannot be attributed to a commit that never
    touched `auth.py`.
    """

    sha: str
    path: str | None = None
    hunk: tuple[int, int] | None = None

    def key(self) -> tuple[str, str | None]:
        return (self.sha, self.path)


class FactStatus(str, Enum):
    """Why a fact does or does not carry a value."""

    MEASURED = "measured"
    SUPPRESSED_LOW_N = "suppressed_low_n"  # we looked; there wasn't enough to divide by
    NOT_ASSESSABLE = "not_assessable"  # a confound invalidates the measurement itself


class Unit(str, Enum):
    FRACTION = "fraction"
    DAYS = "days"
    FILES = "files"
    COUNT = "count"


class Fact(BaseModel):
    """One measurement, with its receipts and its denominator.

    ``value`` is ``None`` unless ``status`` is ``MEASURED``. ``note`` explains a non-measured
    status in plain terms — it is rendered to the reader, so it says what was missing, not
    which code path fired.
    """

    key: str
    status: FactStatus
    value: float | None = None
    unit: Unit = Unit.FRACTION
    numerator: int | None = None
    denominator: int | None = None
    evidence: list[Locator] = Field(default_factory=list)
    note: str = ""

    @property
    def is_measured(self) -> bool:
        return self.status is FactStatus.MEASURED


class ConfoundKey(str, Enum):
    """The distortions L1 must detect before any of its numbers can be trusted."""

    SQUASH_MERGE_HISTORY = "squash_merge_history"
    SOLO_REPO = "solo_repo"
    BOT_DOMINATED = "bot_dominated"
    VENDORED_OR_GENERATED_BULK = "vendored_or_generated_bulk"
    REBASE_REWRITTEN_AUTHORSHIP = "rebase_rewritten_authorship"
    SHALLOW_HISTORY = "shallow_history"
    UNRESOLVED_IDENTITY_ALIASES = "unresolved_identity_aliases"
    SHORT_WINDOW = "short_window"
    LOW_DENOMINATOR = "low_denominator"


class Severity(str, Enum):
    INFO = "info"  # worth stating; changes nothing
    WARN = "warn"  # read the affected facts with caution
    INVALIDATING = "invalidating"  # the affected facts are suppressed outright


class BiasDirection(str, Enum):
    """Which way the confound pushes the affected facts.

    A flag that says only "this history was squash-merged" is useless to a reader. It has
    to say which way the number is wrong.
    """

    OVERSTATES = "overstates"
    UNDERSTATES = "understates"
    UNKNOWN = "unknown"


class Confound(BaseModel):
    """A reason to distrust specific facts, with the numbers behind it."""

    key: ConfoundKey
    severity: Severity
    direction: BiasDirection
    detail: str  # numbers, not adjectives
    invalidates: list[str] = Field(default_factory=list)  # fact keys


class RepoFacts(BaseModel):
    """L1's complete output for one subject in one repo. Byte-reproducible.

    Contains no wall-clock field by design — see the module docstring.
    """

    schema_version: str = SCHEMA_VERSION
    repo: str
    head_sha: str
    subject: Identity
    window_first: date | None = None
    window_last: date | None = None
    n_commits_by_subject: int = 0
    n_commits_total: int = 0
    facts: list[Fact] = Field(default_factory=list)
    confounds: list[Confound] = Field(default_factory=list)
    excluded_paths: dict[str, int] = Field(default_factory=dict)  # PathKind -> touch count

    def fact(self, key: str) -> Fact | None:
        return next((f for f in self.facts if f.key == key), None)

    def confound(self, key: ConfoundKey) -> Confound | None:
        return next((c for c in self.confounds if c.key is key), None)

    def known_locators(self) -> set[tuple[str, str | None]]:
        """Every (sha, path) L4 is allowed to cite. The grounding validator's allowlist."""
        return {loc.key() for f in self.facts for loc in f.evidence}

    def known_shas(self) -> set[str]:
        return {loc.sha for f in self.facts for loc in f.evidence}
