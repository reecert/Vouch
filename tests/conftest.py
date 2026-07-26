"""Shared L1 test plumbing: build a fixture repo and run the extractor over it."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures import repos
from vouch.ingest import ingest
from vouch.l1.config import L1Config
from vouch.l1.extract import extract_facts
from vouch.l1.facts import RepoFacts

SUBJECT = "alice@example.com"


@pytest.fixture
def l1(tmp_path: Path):
    """``l1("healthy")`` -> RepoFacts. Builds the named fixture repo and extracts.

    Fully offline: the fixture repo is built locally and ``ingest`` resolves a local path
    without cloning.

    Each call gets its own directory, so a test may build the same variant twice (e.g. to
    compare with and without an alias) without the second build landing on top of the
    first and failing with "nothing to commit".
    """
    builds = 0

    def _run(
        variant: str,
        subject: str = SUBJECT,
        aliases: list[str] | None = None,
        config: L1Config | None = None,
    ) -> RepoFacts:
        nonlocal builds
        builds += 1
        repo = tmp_path / f"{variant}_{builds}"
        getattr(repos, variant)(repo)
        snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
        return extract_facts(
            snapshot, subject, repo, aliases=aliases, config=config
        )

    return _run
