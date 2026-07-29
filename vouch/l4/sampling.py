"""Deterministic commit sampling — bound the judge's cost without hiding the bound.

Diff-level judgment costs per commit, so a 2,000-commit history would cost 200x a
100-commit one for a profile that is no better. The sample is capped, and three properties
make the cap defensible rather than a quiet corner-cut:

* **The evidence comes first.** Every commit L1 already cited as a self-fix is judged. Those
  are the commits `ownership_loop` rests on, so the dimension with the strongest claim is
  never judged on a sample of its own evidence.
* **The remainder is sampled reproducibly.** Selection is seeded on the repo's HEAD, so the
  same repo yields the same sample on every run and a report can be reproduced exactly.
  Nothing here calls an unseeded RNG or depends on set iteration order.
* **The reader is told.** The counts travel into the report, and the Limitations section
  says *N of M commits were read, chosen this way*.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from vouch.l1.facts import RepoFacts
from vouch.schemas import CommitRecord

__all__ = ["SamplingPolicy", "DEFAULT_POLICY", "Sample", "select_commits"]


@dataclass(frozen=True)
class SamplingPolicy:
    """How many commits the judge reads, and how they are chosen."""

    max_commits: int = 40
    always_include_cited: bool = True  # L1 already rests claims on those commits

    def fingerprint(self) -> str:
        return f"max{self.max_commits}-cited{int(self.always_include_cited)}"


DEFAULT_POLICY = SamplingPolicy()


@dataclass(frozen=True)
class Sample:
    """The chosen commits, with the counts a reader needs to weigh them."""

    commits: tuple[CommitRecord, ...]
    n_total: int
    n_cited: int
    policy: SamplingPolicy

    @property
    def n_sampled(self) -> int:
        return len(self.commits)

    @property
    def is_complete(self) -> bool:
        """True when every candidate commit was read — no sampling caveat applies."""
        return self.n_sampled == self.n_total

    def describe(self) -> str:
        """The sentence that goes in the report's Limitations section."""
        if self.is_complete:
            return f"All {self.n_total} of the subject's commits were read."
        return (
            f"{self.n_sampled} of {self.n_total} commits were read: all {self.n_cited} "
            "that back a measured fact, plus a reproducible sample of the remainder "
            "seeded on the repository head."
        )


def _seeded_rank(sha: str, seed: str) -> str:
    """A stable pseudo-random ordering key. Same repo, same sample, every run."""
    return hashlib.sha256(f"{seed}:{sha}".encode()).hexdigest()


def select_commits(
    commits: list[CommitRecord],
    facts: RepoFacts,
    policy: SamplingPolicy | None = None,
) -> Sample:
    """Choose which commits the judge reads.

    Cited commits are taken first in chronological order; the remainder fills the budget in
    a seeded pseudo-random order, then the whole sample is returned chronologically so the
    judge sees a coherent narrative rather than a shuffled one.
    """
    policy = policy or DEFAULT_POLICY
    candidates = sorted(commits, key=lambda c: (c.authored_at, c.sha))
    cited = facts.known_shas()

    chosen: list[CommitRecord] = []
    if policy.always_include_cited:
        chosen = [c for c in candidates if c.sha in cited][: policy.max_commits]

    taken = {c.sha for c in chosen}
    remaining = [c for c in candidates if c.sha not in taken]
    remaining.sort(key=lambda c: _seeded_rank(c.sha, facts.head_sha))

    budget = max(policy.max_commits - len(chosen), 0)
    chosen.extend(remaining[:budget])
    chosen.sort(key=lambda c: (c.authored_at, c.sha))

    return Sample(
        commits=tuple(chosen),
        n_total=len(candidates),
        n_cited=len([c for c in candidates if c.sha in cited]),
        policy=policy,
    )
