"""Which filesystem paths *are* this repo — and which only look like it.

The join's previous path handling assumed a repo has always lived at exactly one absolute
path, under exactly one spelling. Every one of those assumptions is false in practice, and
each falsehood shows up as a different defect:

* **A repo moves.** This one was `~/Projects/Aiapp` until it was renamed to
  `~/Projects/vouch`. Sessions recorded under the old root matched nothing, so the commits
  they produced read as `uncorroborated` — a **silent false negative**, the worst kind,
  because absent evidence is indistinguishable from unsupervised work.
* **Case-insensitive filesystems.** macOS resolves `~/projects/vouch` and
  `~/Projects/vouch` to the same directory but `os.path.realpath` preserves whichever
  spelling it was handed, so a plain `relative_to` misses half the paths.
* **Symlinks.** `/tmp` is `/private/tmp` here. Comparing one resolved path against one
  unresolved root drops real edits.
* **Relative edit paths.** `Path("cli.py").resolve()` resolves against *the CLI process's*
  working directory, which has nothing to do with where the session was running. That is
  not a near-miss; it silently attributes another project's file to this repo whenever the
  CLI happens to be run from the right place — a **false positive**.

The contract here is deliberately asymmetric, and the asymmetry is the whole safety story:

**The canonical root is ground truth.** A path under it is in this repo because the
filesystem says so. Nothing is inferred.

**A historical root is a claim, and claims are checked.** Historical roots are *declared*
as data (`.vouch/identity.yaml`, or `--historical-root`), never rewritten in code — there
is no `if "Aiapp" in path` anywhere, because the next user's rename is not this one's. A
path resolved under a declared historical root is accepted only if git has *ever* seen that
repo-relative path in this history. That is what stops `~/Projects/Aiapp-fork/setup.py`
from corroborating these commits on the strength of a shared prefix.

**Anything else is dropped and counted.** A relative path with no recorded working
directory is unresolvable, and unresolvable means dropped — never guessed against whatever
directory the CLI happens to be sitting in. Coverage that falls silently is a defect, so
every drop lands in a counter that reaches the L3 report.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "IDENTITY_SCHEMA_VERSION",
    "IDENTITY_FILE",
    "PathOutcome",
    "HistoricalRoot",
    "RepoIdentityFile",
    "RepoIdentity",
    "RootCandidate",
    "detect_case_insensitive",
    "history_paths",
    "load_identity_file",
    "resolve_identity",
    "discover_candidate_roots",
]

IDENTITY_SCHEMA_VERSION = "repo-identity/1"

#: Declared historical roots live here, relative to the repo root. Data, not code.
IDENTITY_FILE = Path(".vouch") / "identity.yaml"


class PathOutcome(StrEnum):
    """What happened to one session-edited path. Every path gets exactly one of these.

    The three failure outcomes are kept distinct because they call for different fixes:
    ``OUTSIDE`` is correct behaviour (another project), ``UNRESOLVABLE`` means the log did
    not record enough to place the path, and ``UNKNOWN_TO_HISTORY`` means a declared
    historical root is matching paths this repo has never contained — which usually means
    the declaration is wrong.
    """

    IN_REPO = "in_repo"
    OUTSIDE = "outside"
    UNRESOLVABLE = "unresolvable"
    UNKNOWN_TO_HISTORY = "unknown_to_history"


class HistoricalRoot(BaseModel):
    """One declared previous home of this repo."""

    model_config = ConfigDict(extra="forbid")

    path: str
    why: str = ""


class RepoIdentityFile(BaseModel):
    """`.vouch/identity.yaml` — the declared, checkable part of a repo's identity."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = IDENTITY_SCHEMA_VERSION
    historical_roots: list[HistoricalRoot] = Field(default_factory=list)


def detect_case_insensitive(probe: Path) -> bool:
    """Does this filesystem treat `Projects` and `projects` as the same directory?

    Answered by asking the filesystem about a path that exists, rather than by branching on
    ``sys.platform`` — a case-sensitive volume mounted on macOS is a normal setup, and
    guessing from the OS name would be wrong on it.
    """
    swapped = str(probe).swapcase()
    try:
        return os.path.samefile(str(probe), swapped)
    except OSError:
        return False


def _real(path: str | Path) -> str:
    """Symlink- and `..`-resolved absolute path. Works on paths that no longer exist.

    A historical root usually does *not* exist any more, which rules out anything that
    stats the whole path; ``os.path.realpath`` resolves what it can and normalizes the rest.
    """
    return os.path.realpath(os.path.abspath(str(path)))


def history_paths(repo_path: Path) -> frozenset[str]:
    """Every repo-relative path this history has ever contained, at any commit.

    The allowlist a declared historical root is checked against. Deletions and renames are
    included on purpose: a session that edited a file which was later deleted is still
    evidence about the commit that deleted it.
    """
    try:
        raw = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "log",
                "--all",
                "--pretty=format:",
                "--name-only",
                "--no-renames",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return frozenset()
    return frozenset(line.strip() for line in raw.splitlines() if line.strip())


def load_identity_file(repo_root: Path) -> RepoIdentityFile:
    """Read `.vouch/identity.yaml`. A missing file is the normal case, not an error."""
    path = repo_root / IDENTITY_FILE
    if not path.is_file():
        return RepoIdentityFile()
    raw = yaml.safe_load(path.read_text()) or {}
    return RepoIdentityFile.model_validate(raw)


@dataclass(frozen=True)
class RepoIdentity:
    """The set of paths that are this repo, and the rule for testing membership.

    ``canonical_key`` and ``historical_keys`` are comparison keys — case-folded when the
    filesystem is case-insensitive — not display paths. ``canonical_root`` is kept in its
    real spelling for messages.
    """

    canonical_root: Path
    canonical_key: str
    historical_keys: tuple[str, ...] = ()
    historical_display: tuple[str, ...] = ()
    known_paths: frozenset[str] = frozenset()
    case_insensitive: bool = False

    def _key(self, path: str) -> str:
        return path.casefold() if self.case_insensitive else path

    def _under(self, key: str, root_key: str) -> str | None:
        """`key` relative to `root_key`, or None if it is not beneath it.

        Segment-aware: `/a/vouch-old/x` is not under `/a/vouch`, which a bare
        ``startswith`` would happily accept.
        """
        if key == root_key:
            return ""
        prefix = root_key.rstrip("/") + "/"
        if not key.startswith(prefix):
            return None
        return key[len(prefix) :]

    def relativize(self, raw: str, base: str | None) -> tuple[PathOutcome, str | None]:
        """Place one session-edited path inside this repo, or explain why it cannot be.

        ``base`` is the working directory *the session recorded for that event* — never the
        CLI process's cwd. A relative path with no base is unresolvable by construction:
        the log did not record enough to place it, and inventing a base is exactly the
        guess that produces false corroboration.
        """
        if not raw:
            return PathOutcome.UNRESOLVABLE, None

        if not os.path.isabs(raw):
            if not base:
                return PathOutcome.UNRESOLVABLE, None
            raw = os.path.join(base, raw)

        key = self._key(_real(raw))

        if (rel := self._under(key, self.canonical_key)) is not None:
            # Ground truth: the filesystem says this path is in the repo.
            return PathOutcome.IN_REPO, PurePosixPath(rel).as_posix() if rel else None

        for root_key in self.historical_keys:
            rel = self._under(key, root_key)
            if rel is None or not rel:
                continue
            posix = PurePosixPath(rel).as_posix()
            # A declared root is a claim. Git history is what settles it.
            if self._key_in_history(posix):
                return PathOutcome.IN_REPO, posix
            return PathOutcome.UNKNOWN_TO_HISTORY, None

        return PathOutcome.OUTSIDE, None

    def _key_in_history(self, rel: str) -> bool:
        if rel in self.known_paths:
            return True
        if not self.case_insensitive:
            return False
        folded = rel.casefold()
        return any(p.casefold() == folded for p in self.known_paths)


def resolve_identity(
    repo_root: Path,
    declared: list[HistoricalRoot] | None = None,
    known_paths: frozenset[str] | None = None,
) -> RepoIdentity:
    """Build the identity for one repo.

    ``known_paths`` is computed from git only when a historical root is actually declared —
    the overwhelmingly common case declares none, and should not pay for a full-history
    path walk to learn that.
    """
    declared = declared if declared is not None else load_identity_file(repo_root).historical_roots
    canonical = Path(_real(repo_root))
    insensitive = detect_case_insensitive(canonical)

    def key(p: str) -> str:
        return p.casefold() if insensitive else p

    canonical_key = key(str(canonical))

    seen = {canonical_key}
    hist_keys: list[str] = []
    hist_display: list[str] = []
    for root in declared:
        k = key(_real(root.path))
        if k in seen:
            continue  # the canonical root, spelled differently. Not an error.
        seen.add(k)
        hist_keys.append(k)
        hist_display.append(_real(root.path))

    paths = known_paths
    if paths is None:
        paths = history_paths(canonical) if hist_keys else frozenset()

    return RepoIdentity(
        canonical_root=canonical,
        canonical_key=canonical_key,
        historical_keys=tuple(hist_keys),
        historical_display=tuple(hist_display),
        known_paths=paths,
        case_insensitive=insensitive,
    )


@dataclass
class RootCandidate:
    """A directory that *might* be a former home of this repo. A proposal, never a fact."""

    root: str
    n_paths: int = 0  # distinct repo-relative paths edited under this root
    n_known: int = 0  # of those, how many git has ever seen here
    examples: list[str] = field(default_factory=list)

    @property
    def share_known(self) -> float:
        return self.n_known / self.n_paths if self.n_paths else 0.0


def discover_candidate_roots(
    observed: list[tuple[str, str | None]],
    identity: RepoIdentity,
    known_paths: frozenset[str],
) -> list[RootCandidate]:
    """Propose historical roots from observed session paths. **Proposes only.**

    Deliberately not wired into the join. A directory whose files happen to share names
    with this repo's — a fork, a template, a copy made before the rename — would score
    well here, and promoting a guess to evidence is the exact failure the join exists to
    avoid. The output is for a human to read and, if they agree, write into
    `.vouch/identity.yaml`, where it becomes a declaration this code will check.
    """
    outside: list[str] = []
    for raw, base in observed:
        if not raw:
            continue
        full = raw if os.path.isabs(raw) else (os.path.join(base, raw) if base else None)
        if full is None:
            continue
        real = _real(full)
        if identity.relativize(real, None)[0] is not PathOutcome.OUTSIDE:
            continue
        outside.append(real)

    # Pass 1 — every ancestor under which *some* path git recognises appears. The suffix
    # below the ancestor is what git would have to know for it to be a former home.
    by_root: dict[str, RootCandidate] = {}
    for real in outside:
        parts = PurePosixPath(real).parts
        for cut in range(2, len(parts)):
            rel = PurePosixPath(*parts[cut:]).as_posix()
            if rel not in known_paths:
                continue
            root = str(PurePosixPath(*parts[:cut]))
            cand = by_root.setdefault(root, RootCandidate(root=root))
            if len(cand.examples) < 3 and rel not in cand.examples:
                cand.examples.append(rel)

    # Pass 2 — score each candidate over *all* the paths beneath it, not just the hits
    # that proposed it. A root where only a handful of names line up is a coincidence, and
    # `share_known` is what makes that visible to the human reading the proposal.
    for root, cand in by_root.items():
        prefix = root.rstrip("/") + "/"
        seen: set[str] = set()
        for real in outside:
            if not real.startswith(prefix):
                continue
            rel = real[len(prefix) :]
            if rel in seen:
                continue
            seen.add(rel)
            cand.n_paths += 1
            cand.n_known += rel in known_paths

    return sorted(by_root.values(), key=lambda c: (-c.n_known, c.root))
