"""Evidence grounding — the model may only cite what it was actually shown.

Ported from the v0 prototype's `validate_grounding`, which was the single best piece of
code in it, and made stricter for diff-level judgment. The prototype checked SHAs only,
which was sufficient when the model saw metadata; now that it reads diffs it can produce a
plausible sentence about the wrong file, so the check is on **(SHA, path)** pairs.

Concretely: "the fix in `auth.py` at 9e66007" is rejected if 9e66007 never touched
`auth.py`, even though both the SHA and the path exist somewhere in the input. That is the
class of error a metadata-level check cannot catch and a diff-reading model can make.

Short SHAs are accepted — models routinely abbreviate — with a minimum prefix length so a
coincidental collision cannot pass.
"""
from __future__ import annotations

from dataclasses import dataclass

from vouch.l1.facts import RepoFacts
from vouch.l4.diffs import CommitDiff
from vouch.l4.schema import Claim, Locator

__all__ = ["MIN_SHA_PREFIX", "Allowlist", "build_allowlist", "check_claims"]

#: Below this, an abbreviated SHA could collide with an unrelated commit by chance.
MIN_SHA_PREFIX = 7


@dataclass(frozen=True)
class Allowlist:
    """Everything the model is permitted to cite, derived from what it was given."""

    shas: frozenset[str]
    pairs: frozenset[tuple[str, str]]  # (sha, path)

    def resolve(self, sha: str) -> str | None:
        """Expand an abbreviated SHA to the full one, or None if it matches nothing."""
        candidate = sha.strip().lower()
        if candidate in self.shas:
            return candidate
        if len(candidate) < MIN_SHA_PREFIX:
            return None
        matches = [s for s in self.shas if s.startswith(candidate)]
        return matches[0] if len(matches) == 1 else None


def build_allowlist(facts: RepoFacts, diffs: list[CommitDiff]) -> Allowlist:
    """The union of what L1 cited and what the model was actually shown.

    L1's locators are included even when the commit was not sampled: those are the facts
    the dimension synthesis reasons over, so it must be able to point at them.
    """
    shas: set[str] = set()
    pairs: set[tuple[str, str]] = set()

    for fact in facts.facts:
        for locator in fact.evidence:
            shas.add(locator.sha.lower())
            if locator.path:
                pairs.add((locator.sha.lower(), locator.path))

    for diff in diffs:
        shas.add(diff.sha.lower())
        for path in diff.files_shown:
            pairs.add((diff.sha.lower(), path))

    return Allowlist(shas=frozenset(shas), pairs=frozenset(pairs))


def _check_locator(locator: Locator, allowlist: Allowlist) -> str | None:
    """Return a problem description, or None if the locator is grounded."""
    resolved = allowlist.resolve(locator.sha)
    if resolved is None:
        return f"cites unknown commit {locator.sha!r}"
    if locator.path and (resolved, locator.path) not in allowlist.pairs:
        return (
            f"cites {locator.sha[:8]} with path {locator.path!r}, "
            "but that commit did not touch that file in the evidence provided"
        )
    return None


def check_claims(claims: list[Claim], allowlist: Allowlist) -> list[str]:
    """Return every grounding problem across ``claims``. Empty list means grounded.

    A claim with no locator at all is itself a problem: an unsourced assertion is exactly
    what the quality bar forbids, and it is indistinguishable from a hallucination.
    """
    problems: list[str] = []
    for index, claim in enumerate(claims):
        if not claim.locators:
            problems.append(f"claim {index} has no locator: {claim.text[:60]!r}")
            continue
        for locator in claim.locators:
            if (problem := _check_locator(locator, allowlist)) is not None:
                problems.append(f"claim {index} {problem}")
    return problems
