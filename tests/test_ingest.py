"""Deterministic ingest tests against synthetic fixture repos. No network, no LLM."""
from pathlib import Path

import pytest

from tests.fixtures.builder import ALICE, BOB, Step, build_repo
from vouch.ingest import (
    blame_line_author,
    changed_old_lines,
    ingest,
    repo_label,
)


def test_ingest_normalizes_commits(tmp_path: Path):
    repo = tmp_path / "r"
    shas = build_repo(
        repo,
        [
            Step(ALICE, "2024-01-01T10:00:00", "add core", {"src/a.py": "x = 1\n"}),
            Step(
                BOB,
                "2024-01-02T10:00:00",
                "add tests",
                {"tests/test_a.py": "def test(): pass\n"},
            ),
        ],
    )
    snap = ingest(str(repo), cache_dir=tmp_path / "cache")
    assert snap.head_sha == shas[-1]
    assert len(snap.commits) == 2
    # commits come newest-first from git log
    by_sha = {c.sha: c for c in snap.commits}
    assert by_sha[shas[0]].author_email == "alice@example.com"
    assert by_sha[shas[0]].files == ["src/a.py"]
    assert by_sha[shas[1]].files == ["tests/test_a.py"]


def test_ingest_is_cached(tmp_path: Path):
    repo = tmp_path / "r"
    build_repo(repo, [Step(ALICE, "2024-01-01T10:00:00", "init", {"a.py": "1\n"})])
    cache = tmp_path / "cache"
    snap1 = ingest(str(repo), cache_dir=cache)
    # cache file exists keyed by repo + head sha
    hits = list(cache.glob("snap_*.json"))
    assert len(hits) == 1
    snap2 = ingest(str(repo), cache_dir=cache)
    assert snap1 == snap2


@pytest.mark.parametrize(
    ("address", "label"),
    [
        ("git@github.com:acme/private-api.git", "acme/private-api"),
        ("ssh://git@gitlab.acme-corp.internal:22/infra/deploy.git", "infra/deploy"),
        ("https://x-token:ghp_secret@github.com/acme/private-api.git", "acme/private-api"),
        ("https://github.com/acme/private-api/", "acme/private-api"),
        # One path segment: the org slot is empty, and the host does not get to fill it.
        ("https://git.bigco.internal/api", "api"),
    ],
)
def test_repo_label_keeps_org_and_repo_for_a_remote(address: str, label: str):
    """The org is public — it is in the link anyone would be sent — and it makes `api` legible."""
    assert repo_label(address) == label


@pytest.mark.parametrize(
    ("path", "label"),
    [
        ("/Users/alice/clients/bigco/api", "api"),
        ("/Users/alice/Projects/acme-api", "acme-api"),
        ("/home/runner/work/vouch/vouch", "vouch"),
        ("../checkouts/acme-api", "acme-api"),
        ("acme-api", "acme-api"),
    ],
)
def test_repo_label_keeps_only_the_leaf_for_a_local_path(path: str, label: str):
    """A parent directory is where someone filed a clone, not who owns it: `clients/bigco`."""
    assert repo_label(path) == label


@pytest.mark.parametrize(
    "path",
    [
        "/Users/alice/clients/bigco/api",
        "/home/runner/work/vouch/vouch",
        "/var/folders/qn/myx3dwjs/T/tmpad9a3c6d/repo",
        "~/clients/bigco/api",
        "../checkouts/acme-api",
    ],
)
def test_repo_label_never_emits_a_parent_directory(path: str):
    """The whole point of the branch: no local path may contribute more than one segment.

    `bigco/api` passes `assert_no_machine_locals` — it is not a home directory, not a
    hostname, not address-shaped — so nothing downstream would catch it.
    """
    assert "/" not in repo_label(path)


@pytest.mark.parametrize(
    "address",
    [
        "/Users/alice/Projects/acme-api",
        "git@gitlab.acme-corp.internal:acme/private-api.git",
        "https://x-token:ghp_secret@github.com/acme/private-api.git",
    ],
)
def test_repo_label_drops_home_host_and_credentials(address: str):
    """The negative case: what a plain two-segment split of the raw string would keep."""
    label = repo_label(address)
    for leaked in ("Users", "alice", "gitlab.acme-corp.internal", "ghp_secret", "@"):
        assert leaked not in label


def test_snapshot_stores_the_label_not_the_address(tmp_path: Path):
    repo = tmp_path / "workspace" / "acme-api"
    build_repo(repo, [Step(ALICE, "2024-01-01T10:00:00", "init", {"a.py": "1\n"})])
    snap = ingest(str(repo), cache_dir=tmp_path / "cache")
    assert snap.repo == "acme-api"
    assert str(tmp_path) not in snap.model_dump_json()


def test_revert_body_is_parsed(tmp_path: Path):
    repo = tmp_path / "r"
    # Build the feature commit first so its real SHA can go in the revert body.
    first = build_repo(
        repo, [Step(ALICE, "2024-01-01T10:00:00", "feature", {"a.py": "v = 1\n"})]
    )[0]
    build_repo(
        repo,
        [
            Step(
                ALICE,
                "2024-01-02T10:00:00",
                'Revert "feature"',
                {"a.py": "v = 0\n"},
                body=f"This reverts commit {first}.",
            )
        ],
    )
    snap = ingest(str(repo), cache_dir=tmp_path / "cache")
    revert_commit = next(c for c in snap.commits if c.subject.startswith("Revert"))
    assert revert_commit.reverts_sha == first


def test_blame_and_changed_lines(tmp_path: Path):
    repo = tmp_path / "r"
    shas = build_repo(
        repo,
        [
            Step(ALICE, "2024-01-01T10:00:00", "add", {"calc.py": "def f():\n    return 1\n"}),
            Step(
                ALICE,
                "2024-02-01T10:00:00",
                "fix off-by-one",
                {"calc.py": "def f():\n    return 2\n"},
            ),
        ],
    )
    fix = shas[1]
    old_lines = changed_old_lines(repo, fix, "calc.py")
    assert old_lines  # the modified 'return 1' line
    blamed = blame_line_author(repo, fix, "calc.py", old_lines[0])
    assert blamed is not None
    email, blamed_sha = blamed
    assert email == "alice@example.com"
    assert blamed_sha == shas[0]
