"""Identity resolution — who counts as "the subject", and who is a machine.

The v0 prototype filtered commits by exact `author_email ==` match, so everything an
engineer committed under a second address (work laptop, GitHub `users.noreply`, an old
personal address) was invisible — which reads as *low ownership* rather than as missing
data. That is the exact failure mode the quality bar forbids.

Three tiers, deliberately ordered by how much we trust them:

1. **git mailmap** — the repo's own sanctioned mapping. Applied upstream in `ingest`
   (commits are parsed with mailmap-resolved `%aN`/`%aE`), so it is already reflected here.
2. **Explicit aliases** — addresses the caller vouched for. Merged.
3. **Heuristic matches** — same display name, or the same GitHub login behind a noreply
   address. **Never merged silently.** They are surfaced as the ``unresolved_identity_aliases``
   confound so a human decides, because auto-merging would quietly change the numbers on a
   guess.

Pure functions over already-parsed commits. No I/O.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

__all__ = ["Identity", "is_bot", "normalize_email", "github_login", "resolve_identity"]

# Machine committers. Matched against the display name and the address.
_BOT_MARKERS = (
    "[bot]",
    "dependabot",
    "renovate",
    "greenkeeper",
    "snyk-bot",
    "mergify",
    "codecov",
    "semantic-release",
    "allcontributors",
    "github-actions",
    "imgbot",
    "pre-commit-ci",
)

# 12345+login@users.noreply.github.com  /  login@users.noreply.github.com
_GH_NOREPLY_RE = re.compile(r"^(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$", re.IGNORECASE)


class Identity(BaseModel):
    """The subject, as a set of addresses and display names rather than one string.

    ``canonical_email`` is what the caller asked for and what the report is keyed on;
    ``emails`` is every address whose commits are attributed to this person.
    """

    canonical_email: str
    emails: list[str] = Field(default_factory=list)  # sorted, includes canonical
    names: list[str] = Field(default_factory=list)  # sorted display names seen

    def matches(self, email: str) -> bool:
        return normalize_email(email) in self.emails


def normalize_email(email: str) -> str:
    """Lowercase and strip an address. Git addresses are case-insensitive in practice."""
    return email.strip().strip("<>").lower()


def is_bot(name: str, email: str) -> bool:
    """True if this committer is a machine (dependabot, CI, release automation…)."""
    blob = f"{name} {email}".lower()
    return any(marker in blob for marker in _BOT_MARKERS)


def github_login(email: str) -> str | None:
    """Extract the GitHub login from a `users.noreply.github.com` address, else None."""
    m = _GH_NOREPLY_RE.match(normalize_email(email))
    return m.group(1).lower() if m else None


def _identity_keys(emails: set[str], names: set[str]) -> tuple[set[str], set[str]]:
    """The (login-ish, name) keys a candidate address could match against."""
    logins = {github_login(e) or e.split("@")[0] for e in emails}
    return logins, {n.strip().lower() for n in names if n.strip()}


def resolve_identity(
    authors: list[tuple[str, str]],
    subject_email: str,
    aliases: list[str] | None = None,
) -> tuple[Identity, list[str]]:
    """Resolve the subject against every (name, email) pair seen in the history.

    ``authors`` is every ``(author_name, author_email)`` in the snapshot, mailmap-resolved.
    ``aliases`` are addresses the caller explicitly vouched for; they are merged.

    Returns ``(identity, unclaimed)`` where ``unclaimed`` is the heuristic near-matches that
    were deliberately **not** merged — the caller turns these into a confound flag. Both
    return values are sorted, so this function is byte-reproducible.
    """
    canonical = normalize_email(subject_email)
    claimed = {canonical} | {normalize_email(a) for a in (aliases or [])}

    # Names attached to the claimed addresses; used to find near-matches below.
    names: set[str] = set()
    for name, email in authors:
        if normalize_email(email) in claimed:
            names.add(name.strip())

    logins, lower_names = _identity_keys(claimed, names)

    unclaimed: set[str] = set()
    for name, email in authors:
        e = normalize_email(email)
        if e in claimed or is_bot(name, email):
            continue
        # Same display name, or the same GitHub login behind a different address.
        candidate_login = github_login(e) or e.split("@")[0]
        if name.strip().lower() in lower_names or candidate_login in logins:
            unclaimed.add(e)

    identity = Identity(
        canonical_email=canonical,
        emails=sorted(claimed),
        names=sorted(names),
    )
    return identity, sorted(unclaimed)
