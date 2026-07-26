"""Bounded diff extraction — the one place the model sees source.

`ARCHITECTURE.md` forbade this outright ("No raw diffs sent to the model. Ever."), and the
new brief requires it: whether a fix was real or cosmetic, and whether a test exercises the
failure it claims to, are not answerable from metadata. The reversal is deliberate and
documented in docs/plan.md §1.4. Phase 1 is public repos only, so the diff content is
already public; private-repo support would need this revisited before it ships.

What survives the reversal is the grounding guarantee, and it gets *stricter*: the model may
now read diff text, but it may still only cite SHAs and paths that L1 handed it, and the
validator now checks the path as well as the SHA (see :mod:`vouch.l4.grounding`).

Diffs are bounded on three axes — files per commit, lines per file, and total characters —
because an unbounded diff is both a cost problem and a quality problem: a 5,000-line
vendored bump crowds out the twelve lines that matter. Truncation is always **stated in the
text the model reads**, so it can answer `insufficient_evidence` rather than confidently
judging a fragment it did not know was a fragment.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from vouch.l1.paths import is_noise
from vouch.schemas import CommitRecord

__all__ = ["DiffBudget", "DEFAULT_BUDGET", "CommitDiff", "extract_diff"]


@dataclass(frozen=True)
class DiffBudget:
    """Limits on what one commit's diff may occupy."""

    max_files: int = 12
    max_lines_per_file: int = 200
    max_chars: int = 24_000

    def fingerprint(self) -> str:
        return f"f{self.max_files}-l{self.max_lines_per_file}-c{self.max_chars}"


DEFAULT_BUDGET = DiffBudget()


@dataclass(frozen=True)
class CommitDiff:
    """One commit's diff, bounded, with an honest account of what was left out."""

    sha: str
    subject: str
    text: str
    files_shown: tuple[str, ...]
    files_omitted: tuple[str, ...]
    truncated: bool

    def render(self) -> str:
        """The block the model reads. Omissions are stated inside it, not alongside it."""
        header = [f"commit {self.sha}", f"subject: {self.subject}"]
        if self.files_omitted:
            header.append(
                "NOTE: not all files are shown. Omitted: "
                + ", ".join(self.files_omitted)
            )
        if self.truncated:
            header.append(
                "NOTE: this diff was truncated. Judge only what is visible; answer "
                "insufficient_evidence if the visible portion does not support a call."
            )
        return "\n".join(header) + "\n" + self.text


def _git_show(repo_path: Path, sha: str, path: str) -> str:
    try:
        return subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "show",
                "--format=",
                "--no-color",
                "--unified=3",
                sha,
                "--",
                path,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return ""


def _clip(text: str, max_lines: int) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    kept = lines[:max_lines]
    kept.append(f"... [{len(lines) - max_lines} more lines in this file, not shown]")
    return "\n".join(kept), True


def extract_diff(
    repo_path: Path,
    commit: CommitRecord,
    budget: DiffBudget | None = None,
) -> CommitDiff:
    """Read one commit's diff, bounded by ``budget``.

    Machine-authored files are dropped before the budget is applied, so a lockfile cannot
    consume the space a real change needed. They are still listed as omitted — the model
    should know a commit touched a lockfile, just not read 4,000 lines of it.
    """
    budget = budget or DEFAULT_BUDGET

    significant = [p for p in commit.files if not is_noise(p)]
    noise = [p for p in commit.files if is_noise(p)]

    shown: list[str] = []
    omitted: list[str] = list(noise)
    truncated = False
    chunks: list[str] = []
    used = 0

    for path in significant:
        if len(shown) >= budget.max_files:
            omitted.append(path)
            truncated = True
            continue

        body = _git_show(repo_path, commit.sha, path)
        if not body.strip():
            omitted.append(path)
            continue

        body, clipped = _clip(body, budget.max_lines_per_file)
        truncated = truncated or clipped

        if used + len(body) > budget.max_chars:
            omitted.append(path)
            truncated = True
            continue

        chunks.append(body)
        shown.append(path)
        used += len(body)

    return CommitDiff(
        sha=commit.sha,
        subject=commit.subject,
        text="\n".join(chunks) if chunks else "(no textual diff available)",
        files_shown=tuple(shown),
        files_omitted=tuple(sorted(set(omitted))),
        truncated=truncated,
    )
