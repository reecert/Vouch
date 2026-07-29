"""Build tiny synthetic git repos for deterministic extractor tests.

No network. Full control over author identity, dates, touched files, and revert bodies —
exactly the axes the ownership signals key off. Returns the ordered list of commit SHAs
so tests can assert on specific evidence.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ALICE = ("Alice Dev", "alice@example.com")
BOB = ("Bob Other", "bob@example.com")


@dataclass
class Step:
    author: tuple[str, str]
    date: str  # ISO, e.g. "2024-01-01T12:00:00"
    subject: str
    write: dict[str, str] = field(default_factory=dict)  # path -> full content
    delete: list[str] = field(default_factory=list)
    body: str = ""
    committer_date: str | None = None  # set it apart from `date` to simulate a rebase


def _run(path: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


def build_repo(path: Path, steps: list[Step]) -> list[str]:
    """Create a git repo at ``path`` from ``steps``; return commit SHAs in order."""
    import os

    path.mkdir(parents=True, exist_ok=True)
    _run(path, "init", "-q")
    _run(path, "config", "user.name", "Builder")
    _run(path, "config", "user.email", "builder@example.com")

    shas: list[str] = []
    for st in steps:
        name, email = st.author
        for rel, content in st.write.items():
            fp = path / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
            _run(path, "add", rel)
        for rel in st.delete:
            _run(path, "rm", "-q", rel)

        env = dict(os.environ)
        env.update(
            GIT_AUTHOR_NAME=name,
            GIT_AUTHOR_EMAIL=email,
            GIT_COMMITTER_NAME=name,
            GIT_COMMITTER_EMAIL=email,
            GIT_AUTHOR_DATE=st.date,
            GIT_COMMITTER_DATE=st.committer_date or st.date,
        )
        message = st.subject if not st.body else f"{st.subject}\n\n{st.body}"
        _run(path, "commit", "-q", "-m", message, env=env)
        shas.append(_run(path, "rev-parse", "HEAD").strip())
    return shas
