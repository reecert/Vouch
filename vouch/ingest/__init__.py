"""ingest — git -> RepoSnapshot. Deterministic, cached, no LLM.

Clone/open a repo, pin HEAD, and normalize commits into a ``RepoSnapshot``. Also exposes
a blame helper the extractors call on demand (blame is too large to precompute for every
line, but is still pure git). Cached by ``repo + head_sha``.

All git access is via subprocess with ``check=True`` — a git failure raises, it is never
silently swallowed (except blame, which returns None for the legitimate "no prior line"
case).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path

from vouch.schemas import CommitRecord, RepoSnapshot

# Separators that cannot appear in git identity or subject text.
_FS = "\x1f"
_RS = "\x1e"

_REVERT_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")

DEFAULT_CACHE_DIR = Path(".vouch_cache")

SNAPSHOT_VERSION = 3


def _git(repo_path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def resolve_repo(repo_url: str, cache_dir: Path | None = None) -> Path:
    """Return a local git dir for ``repo_url``.

    If ``repo_url`` is an existing local git repo, it is used in place (no copy — handy
    for fixtures and already-cloned repos). Otherwise it is blobless-cloned into
    ``cache_dir`` (default ``.vouch_cache``), keyed by a hash of the URL so repeat runs
    reuse the clone.
    """
    local = Path(repo_url)
    if (local / ".git").is_dir() or (local.is_dir() and (local / "HEAD").is_file()):
        return local

    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(repo_url.encode()).hexdigest()[:16]
    dest = cache_dir / f"repo_{key}"
    if not (dest / ".git").is_dir():
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--quiet", repo_url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
    return dest


def _revert_map(repo_path: Path) -> dict[str, str]:
    """sha -> reverted-sha, parsed from commit bodies. Empty if no reverts."""
    raw = _git(repo_path, "log", "--no-merges", f"--pretty=format:{_RS}%H{_FS}%b")
    out: dict[str, str] = {}
    for rec in raw.split(_RS):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, _, body = rec.partition(_FS)
        m = _REVERT_RE.search(body)
        if m:
            out[sha] = m.group(1)
    return out


def _parse_commits(repo_path: Path) -> list[CommitRecord]:
    reverts = _revert_map(repo_path)
    # %aN/%aE are mailmap-resolved; %cE/%cI let L1 spot a rebase-rewritten history.
    fmt = f"--pretty=format:{_RS}%H{_FS}%aN{_FS}%aE{_FS}%aI{_FS}%cE{_FS}%cI{_FS}%s"
    raw = _git(repo_path, "log", "--no-merges", "--use-mailmap", "--name-status", fmt)

    commits: list[CommitRecord] = []
    for rec in raw.split(_RS):
        if not rec.strip():
            continue
        header, _, rest = rec.partition("\n")
        # The subject is last and may itself contain anything except our separators.
        sha, an, ae, aiso, ce, ciso, subj = header.split(_FS, 6)
        files: list[str] = []
        for line in rest.splitlines():
            if not line.strip():
                continue
            files.append(line.split("\t")[-1])  # last col handles A/M/D and renames
        commits.append(
            CommitRecord(
                sha=sha,
                author_name=an,
                author_email=ae,
                authored_at=datetime.fromisoformat(aiso),
                subject=subj,
                files=files,
                reverts_sha=reverts.get(sha),
                committer_email=ce,
                committed_at=datetime.fromisoformat(ciso),
            )
        )
    return commits


def _count_merges(repo_path: Path) -> int:
    """Number of merge commits. Zero across a long history means squash/rebase merging."""
    out = _git(repo_path, "rev-list", "--merges", "--count", "HEAD").strip()
    return int(out or 0)


def _is_shallow(repo_path: Path) -> bool:
    """True if this is a shallow clone — history is truncated and every count is a floor."""
    try:
        return _git(repo_path, "rev-parse", "--is-shallow-repository").strip() == "true"
    except subprocess.CalledProcessError:
        return False


def ingest(repo_url: str, cache_dir: Path | None = None) -> RepoSnapshot:
    """Resolve ``repo_url`` to a local repo, pin HEAD, normalize to a ``RepoSnapshot``.

    The snapshot is cached on disk by ``repo + head_sha``; a second call re-parses
    nothing. Only the initial clone touches the network.
    """
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    repo_path = resolve_repo(repo_url, cache_dir)
    head_sha = _git(repo_path, "rev-parse", "HEAD").strip()

    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(repo_url.encode()).hexdigest()[:16]
    # SNAPSHOT_VERSION keys the file, so a shape change is a miss rather than a defaulted hydrate.
    snap_path = cache_dir / f"snap_v{SNAPSHOT_VERSION}_{key}_{head_sha}.json"
    if snap_path.is_file():
        return RepoSnapshot.model_validate_json(snap_path.read_text())

    snapshot = RepoSnapshot(
        repo=repo_url,
        head_sha=head_sha,
        commits=_parse_commits(repo_path),
        ingested_at=datetime.now(),
        n_merge_commits=_count_merges(repo_path),
        is_shallow=_is_shallow(repo_path),
    )
    snap_path.write_text(snapshot.model_dump_json())
    return snapshot


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? ")


def changed_old_lines(repo_path: Path, sha: str, file: str) -> list[int]:
    """Old-side (pre-image) line numbers that ``sha`` modified in ``file``.

    These are the lines to blame against ``sha^`` to see who wrote the code being fixed.
    Pure additions contribute no old-side lines and are skipped.
    """
    try:
        patch = _git(
            repo_path, "show", "--unified=0", "--format=", sha, "--", file
        )
    except subprocess.CalledProcessError:
        return []
    lines: list[int] = []
    for row in patch.splitlines():
        m = _HUNK_RE.match(row)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        if count == 0:  # pure insertion at this hunk — nothing to blame
            continue
        lines.extend(range(start, start + count))
    return lines


def to_ranges(lines: list[int]) -> list[tuple[int, int]]:
    """Collapse line numbers into contiguous ``(start, end)`` ranges. Sorted, deduped."""
    out: list[tuple[int, int]] = []
    for ln in sorted(set(lines)):
        if out and ln == out[-1][1] + 1:
            out[-1] = (out[-1][0], ln)
        else:
            out.append((ln, ln))
    return out


_PORCELAIN_HEADER_RE = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)")


def blame_ranges(
    repo_path: Path, sha: str, file: str, lines: list[int]
) -> dict[int, tuple[str, str]]:
    """Blame many lines of one file in **one** git call. ``line -> (email, blamed_sha)``.

    The v0 prototype ran one ``git blame`` subprocess per changed line, so a 50-line fix
    across 3 files cost up to 150 process spawns — fine on a fixture, unusable on a real
    repo. ``git blame`` accepts repeated ``-L`` options, and porcelain output only repeats a
    commit's headers the first time it appears, so one call plus a sha->email cache does
    the whole job.

    Blames against ``sha^`` (the pre-image): we want who wrote the code being changed, not
    who changed it. Returns ``{}`` when the file has no parent state (root commit, pure
    addition) — an honest empty, never a guess.
    """
    ranges = to_ranges(lines)
    if not ranges:
        return {}

    args = ["blame", "--porcelain"]
    for start, end in ranges:
        args += ["-L", f"{start},{end}"]
    args += [f"{sha}^", "--", file]
    try:
        out = _git(repo_path, *args)
    except subprocess.CalledProcessError:
        return {}

    result: dict[int, tuple[str, str]] = {}
    email_by_sha: dict[str, str] = {}
    cur_sha: str | None = None
    cur_line: int | None = None

    for row in out.splitlines():
        if row.startswith("\t"):  # the content line closes an entry
            continue
        m = _PORCELAIN_HEADER_RE.match(row)
        if m:
            cur_sha, cur_line = m.group(1), int(m.group(2))
            # Headers are only emitted the first time a commit appears in the output.
            known = email_by_sha.get(cur_sha)
            if known is not None:
                result[cur_line] = (known, cur_sha)
            continue
        if row.startswith("author-mail ") and cur_sha is not None and cur_line is not None:
            email = row[len("author-mail ") :].strip().strip("<>").lower()
            email_by_sha[cur_sha] = email
            result[cur_line] = (email, cur_sha)

    return result


def blame_line_author(
    repo_path: Path, sha: str, file: str, line: int
) -> tuple[str, str] | None:
    """Return ``(author_email, blamed_sha)`` for ``file:line`` as of ``sha^``.

    The single-line form of :func:`blame_ranges`, which is what L1 uses. Returns ``None``
    if the line has no prior state (pure addition, no parent) or cannot be blamed.
    """
    try:
        out = _git(
            repo_path,
            "blame",
            "-L",
            f"{line},{line}",
            "--porcelain",
            f"{sha}^",
            "--",
            file,
        )
    except subprocess.CalledProcessError:
        return None
    lines = out.splitlines()
    if not lines:
        return None
    blamed_sha = lines[0].split()[0]
    email = None
    for ln in lines:
        if ln.startswith("author-mail "):
            email = ln[len("author-mail ") :].strip().strip("<>")
            break
    if email is None:
        return None
    return email, blamed_sha
