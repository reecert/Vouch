"""Load ``eval/repos.yaml`` and resolve each row's subject address at run time.

**Why this module exists at all.** The corpus names ten real people. Their addresses are
already public in the git history of the public repos they wrote — but that is a statement
about *those* repositories, not a licence to copy ten third-party addresses into *this*
one, where they would be permanent, greppable, and attached to a file whose whole purpose
is to profile the people named in it. ``vouch.l1.confounds.mask_email`` already encodes
that position for the product's output; this module applies it to the corpus itself.

So the file stores a **selector**, not an address, and the address is resolved from the
clone at the moment it is needed:

``by: commit_rank`` — the *n*-th most prolific non-bot author at the pinned ``head``,
counted exactly the way the pipeline counts (``--no-merges``, mailmap-resolved, bots
dropped by :func:`vouch.l1.identity.is_bot`).

The rank alone would be a silent hazard: add a bot marker, change the merge handling, or
pin a different head, and rank 3 becomes a different human, with every denominator
downstream quietly recomputed for the wrong person. So each row also carries
``email_sha256`` — the first 12 hex of the SHA-256 of the normalized address — and
resolution **fails loudly** when the two disagree.

That digest is a consistency guard, not a privacy claim: anyone holding the clone can
enumerate its authors and match it in seconds, which is precisely what this module does.
The property being protected is narrow and worth stating exactly: *no third-party address
enters this repository's history*. Deriving one requires the public repo it already lives
in.

Git is read here (one ``git log`` per row) but nothing is written, and no address is ever
returned to a caller that did not ask to resolve one.
"""
from __future__ import annotations

import collections
import hashlib
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from vouch.l1.identity import is_bot, normalize_email

__all__ = [
    "CorpusError",
    "AuthorSelector",
    "RepoSpec",
    "Corpus",
    "ResolvedAuthor",
    "email_digest",
    "load_corpus",
    "ranked_authors",
    "resolve_author",
]

#: 48 bits, over the few hundred authors of one repo. A guard against drift, not a secret.
DIGEST_LEN = 12

# The log shape `vouch.ingest._parse_commits` uses, so a rank here matches its counts.
_FS = "\x1f"
_RS = "\x1e"


class CorpusError(Exception):
    """The corpus file is malformed, or a row no longer resolves to the person it pinned."""


def email_digest(email: str) -> str:
    """Stable short digest of a **normalized** address — the corpus row's identity guard."""
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()[:DIGEST_LEN]


class AuthorSelector(BaseModel):
    """How to find one person in one clone, without naming them.

    ``rank`` is what a reader can sanity-check by eye ("the third most prolific author");
    ``email_sha256`` is what the code trusts.
    """

    model_config = ConfigDict(extra="forbid")

    by: Literal["commit_rank"] = "commit_rank"
    rank: int = Field(ge=1)
    email_sha256: str = Field(pattern=rf"^[0-9a-f]{{{DIGEST_LEN}}}$")


class RepoSpec(BaseModel):
    """One corpus row: a repo, a pinned head, a selector, and the measurement behind it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    axis: str
    repo: str
    head: str
    author: AuthorSelector
    # Selectors, not addresses: an alias is an address, and one does not go in this file.
    aliases: list[AuthorSelector] = Field(default_factory=list)
    measured: dict[str, Any] = Field(default_factory=dict)
    why: str = ""


class Corpus(BaseModel):
    """A set of rows, and — required — what a number measured over them is about.

    ``name`` has no default. A corpus of public repositories can only ever calibrate the
    half of the pipeline that reads git, and an agreement number quoted as "the eval
    corpus" carries none of that: it reads as a statement about the judge, which is what
    everyone downstream will take it for. The name is the one field that travels with every
    citation, so the limit lives in it.

    ``calibrates`` says the same thing per dimension, in a form a test can check against
    :data:`vouch.l4.dimensions.DIMENSIONS` — the prose in ``notes`` cannot notice when a
    dimension gains a layer, and this can.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    name: str = Field(min_length=1)
    measured_at_config: str = ""
    calibrates: dict[str, Literal["full", "l1_half", "none"]] = Field(default_factory=dict)
    repos: list[RepoSpec] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)

    def by_id(self, repo_id: str) -> RepoSpec:
        for spec in self.repos:
            if spec.id == repo_id:
                return spec
        raise CorpusError(f"no corpus row with id {repo_id!r}")


class ResolvedAuthor(BaseModel):
    """The outcome of resolving one selector against one clone."""

    model_config = ConfigDict(extra="forbid")

    email: str
    rank: int
    commits: int
    digest: str


def load_corpus(path: Path) -> Corpus:
    """Load and validate the corpus file. Raises rather than half-accepting a bad one."""
    if not path.is_file():
        raise CorpusError(f"no corpus file at {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise CorpusError(f"{path}: not valid YAML: {e}") from e
    try:
        corpus = Corpus.model_validate(raw)
    except Exception as e:
        raise CorpusError(f"{path}: {e}") from e

    seen: set[str] = set()
    for spec in corpus.repos:
        if spec.id in seen:
            raise CorpusError(f"{path}: duplicate corpus id {spec.id!r}")
        seen.add(spec.id)
    return corpus


def ranked_authors(repo_path: Path, head: str) -> list[tuple[str, int]]:
    """``[(email, commits)]`` for every non-bot author at ``head``, most prolific first.

    Counted like the pipeline counts: ``--no-merges`` and mailmap-resolved, so a rank here
    means the same thing as a subject-commit count downstream. Ties break on the address so
    the ordering is total and byte-reproducible.
    """
    try:
        raw = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "log",
                "--no-merges",
                "--use-mailmap",
                f"--pretty=format:{_RS}%aN{_FS}%aE",
                head,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        raise CorpusError(
            f"{repo_path}: cannot read history at pinned head {head!r} "
            f"(is the clone shallow, or the commit gone?): {e.stderr.strip()}"
        ) from e

    counts: collections.Counter[str] = collections.Counter()
    for record in raw.split(_RS):
        if not record.strip():
            continue
        name, _, email = record.strip("\n").partition(_FS)
        if is_bot(name, email):
            continue
        counts[normalize_email(email)] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def resolve_author(spec: RepoSpec, repo_path: Path) -> ResolvedAuthor:
    """Resolve ``spec.author`` against a clone. Raises if rank and digest disagree.

    The mismatch case is deliberately fatal rather than "trust the digest and carry on".
    A row that no longer ranks where it was pinned means the counting changed under the
    corpus — and every ``measured:`` number in that row was computed under the old count,
    so silently continuing would score a judge against stale evidence.
    """
    ranked = ranked_authors(repo_path, spec.head)
    selector = spec.author

    at_rank = ranked[selector.rank - 1] if selector.rank <= len(ranked) else None
    if at_rank is not None and email_digest(at_rank[0]) == selector.email_sha256:
        return ResolvedAuthor(
            email=at_rank[0],
            rank=selector.rank,
            commits=at_rank[1],
            digest=selector.email_sha256,
        )

    # Rank and digest disagree: say how, without printing anyone's address.
    found = [
        (i, email, n)
        for i, (email, n) in enumerate(ranked, 1)
        if email_digest(email) == selector.email_sha256
    ]
    if not found:
        raise CorpusError(
            f"{spec.id}: no author at head {spec.head} matches digest "
            f"{selector.email_sha256} ({len(ranked)} non-bot authors scanned). The pinned "
            "subject is not in this history — wrong clone, or the address changed."
        )
    actual_rank, email, n = found[0]
    raise CorpusError(
        f"{spec.id}: digest {selector.email_sha256} is at rank {actual_rank} "
        f"({n} commits), not the pinned rank {selector.rank}. Author counting has changed "
        f"under the corpus; the row's `measured:` block was computed at the old rank. "
        f"Re-measure the row rather than editing the rank alone."
    )


def resolve_aliases(spec: RepoSpec, repo_path: Path) -> list[str]:
    """Resolve every alias selector on a row. Empty list for every row in the corpus today."""
    ranked = ranked_authors(repo_path, spec.head)
    by_digest = {email_digest(email): email for email, _ in ranked}
    out: list[str] = []
    for alias in spec.aliases:
        email = by_digest.get(alias.email_sha256)
        if email is None:
            raise CorpusError(
                f"{spec.id}: alias digest {alias.email_sha256} matches no author at "
                f"head {spec.head}."
            )
        out.append(email)
    return sorted(out)
