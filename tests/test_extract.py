"""Deterministic extract tests. Each ownership signal gets a positive and a discriminating
negative case. No network, no LLM."""
from pathlib import Path

from tests.fixtures.builder import ALICE, BOB, Step, build_repo
from vouch.extract import extract
from vouch.ingest import ingest


def _snap(tmp_path: Path, name: str, steps: list[Step]):
    repo = tmp_path / name
    build_repo(repo, steps)
    snap = ingest(str(repo), cache_dir=tmp_path / f"cache_{name}")
    return snap, repo


def _sig(bundle, key):
    return next(s for s in bundle.signals if s.key == key)


def test_returned_to_own_code_positive_and_gap(tmp_path: Path):
    # Alice touches a.py, comes back 40 days later -> sustained. b.py is drive-by (once).
    snap, repo = _snap(
        tmp_path,
        "ret",
        [
            Step(ALICE, "2024-01-01T10:00:00", "start a", {"a.py": "1\n", "b.py": "1\n"}),
            Step(ALICE, "2024-02-10T10:00:00", "return to a", {"a.py": "2\n"}),
        ],
    )
    b = extract(snap, "alice@example.com", repo_path=repo)
    s = _sig(b, "returned_to_own_code")
    assert s.value == 1  # only a.py qualifies
    assert set(s.evidence) == set(x for x in [c.sha for c in snap.commits])


def test_returned_to_own_code_below_gap_is_zero(tmp_path: Path):
    snap, repo = _snap(
        tmp_path,
        "ret2",
        [
            Step(ALICE, "2024-01-01T10:00:00", "start", {"a.py": "1\n"}),
            Step(ALICE, "2024-01-03T10:00:00", "quick follow", {"a.py": "2\n"}),  # 2 days
        ],
    )
    b = extract(snap, "alice@example.com", repo_path=repo)
    assert _sig(b, "returned_to_own_code").value == 0


def test_fixed_own_bug_counts_only_self_fixes(tmp_path: Path):
    # Alice writes calc.py, then fixes her own line -> counts.
    # Bob writes util.py; Alice "fixes" it -> blame != Alice -> does NOT count.
    snap, repo = _snap(
        tmp_path,
        "fix",
        [
            Step(ALICE, "2024-01-01T10:00:00", "add calc", {"calc.py": "def f():\n    return 1\n"}),
            Step(BOB, "2024-01-02T10:00:00", "add util", {"util.py": "def g():\n    return 9\n"}),
            Step(ALICE, "2024-02-01T10:00:00", "fix calc bug", {"calc.py": "def f():\n    return 2\n"}),
            Step(ALICE, "2024-02-02T10:00:00", "fix util bug", {"util.py": "def g():\n    return 8\n"}),
        ],
    )
    b = extract(snap, "alice@example.com", repo_path=repo)
    s = _sig(b, "fixed_own_bug")
    assert s.value == 1
    # the one evidence sha is the calc fix, whose subject mentions calc
    assert b.commit_index[s.evidence[0]].subject == "fix calc bug"


def test_fixed_own_bug_zero_without_repo_path(tmp_path: Path):
    snap, repo = _snap(
        tmp_path,
        "fix2",
        [Step(ALICE, "2024-01-01T10:00:00", "add", {"calc.py": "x=1\n"})],
    )
    b = extract(snap, "alice@example.com", repo_path=None)  # no blame available
    assert _sig(b, "fixed_own_bug").value == 0


def test_tests_accompany_fixes_fraction(tmp_path: Path):
    snap, repo = _snap(
        tmp_path,
        "tf",
        [
            Step(ALICE, "2024-01-01T10:00:00", "fix a with test",
                 {"a.py": "1\n", "tests/test_a.py": "def t(): pass\n"}),
            Step(ALICE, "2024-01-02T10:00:00", "fix b no test", {"b.py": "1\n"}),
        ],
    )
    b = extract(snap, "alice@example.com", repo_path=repo)
    s = _sig(b, "tests_accompany_fixes")
    assert s.value == 0.5  # 1 of 2 fix-commits carried a test
    assert len(s.evidence) == 1
    assert b.commit_index[s.evidence[0]].touched_tests is True


def test_revert_recovery_positive(tmp_path: Path):
    repo = tmp_path / "rr"
    first = build_repo(
        repo, [Step(ALICE, "2024-01-01T10:00:00", "feature", {"a.py": "v=1\n"})]
    )[0]
    build_repo(
        repo,
        [
            Step(ALICE, "2024-01-05T10:00:00", 'Revert "feature"', {"a.py": "v=0\n"},
                 body=f"This reverts commit {first}."),
            Step(ALICE, "2024-01-10T10:00:00", "re-land feature correctly", {"a.py": "v=2\n"}),
        ],
    )
    snap = ingest(str(repo), cache_dir=tmp_path / "c")
    b = extract(snap, "alice@example.com", repo_path=repo)
    s = _sig(b, "revert_recovery")
    assert s.value == 1
    assert len(s.evidence) == 2  # [revert, recovery]


def test_revert_recovery_zero_when_no_reland(tmp_path: Path):
    repo = tmp_path / "rr2"
    first = build_repo(
        repo, [Step(ALICE, "2024-01-01T10:00:00", "feature", {"a.py": "v=1\n"})]
    )[0]
    build_repo(
        repo,
        [Step(ALICE, "2024-01-05T10:00:00", 'Revert "feature"', {"a.py": "v=0\n"},
              body=f"This reverts commit {first}.")],
    )
    snap = ingest(str(repo), cache_dir=tmp_path / "c2")
    b = extract(snap, "alice@example.com", repo_path=repo)
    assert _sig(b, "revert_recovery").value == 0


def test_commit_atomicity_fraction(tmp_path: Path):
    snap, repo = _snap(
        tmp_path,
        "atom",
        [
            Step(ALICE, "2024-01-01T10:00:00", "focused", {"a.py": "1\n"}),  # 1 file
            Step(ALICE, "2024-01-02T10:00:00", "sprawl",
                 {"b.py": "1\n", "c.py": "1\n", "d.py": "1\n", "e.py": "1\n"}),  # 4 files > 3
        ],
    )
    b = extract(snap, "alice@example.com", repo_path=repo)
    assert _sig(b, "commit_atomicity").value == 0.5


def test_bundle_only_indexes_cited_shas(tmp_path: Path):
    snap, repo = _snap(
        tmp_path,
        "idx",
        [
            Step(ALICE, "2024-01-01T10:00:00", "start", {"a.py": "1\n"}),
            Step(ALICE, "2024-02-10T10:00:00", "return", {"a.py": "2\n"}),
        ],
    )
    b = extract(snap, "alice@example.com", repo_path=repo)
    # every SHA any signal cites must be in commit_index, and index has no strangers
    cited = {sha for s in b.signals for sha in s.evidence}
    assert set(b.commit_index) == cited
    assert cited.issubset(b.known_shas())
    assert b.n_commits_by_subject == 2
