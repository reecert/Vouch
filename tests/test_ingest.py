"""Deterministic ingest tests against synthetic fixture repos. No network, no LLM."""
from pathlib import Path

from tests.fixtures.builder import ALICE, BOB, Step, build_repo
from vouch.ingest import (
    blame_line_author,
    changed_old_lines,
    ingest,
    is_test_path,
)


def test_is_test_path():
    assert is_test_path("tests/test_x.py")
    assert is_test_path("pkg/test_thing.py")
    assert is_test_path("pkg/thing_test.go")
    assert is_test_path("conftest.py")
    assert not is_test_path("src/thing.py")
    assert not is_test_path("latest/build.py")  # 'test' not as a boundary token


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
    assert by_sha[shas[0]].test_files == []
    assert by_sha[shas[1]].test_files == ["tests/test_a.py"]


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
