"""The corpus loader and its runtime author resolver.

Two things are under test. The mechanical one: a selector resolves to the right person,
and disagreement between the rank and the digest is fatal rather than quietly resolved.
The other is an invariant about this repository rather than about any function —
``eval/repos.yaml`` must not contain an address — and it is asserted here because a test
is the only thing that will still be checking it in six months.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.fixtures.builder import ALICE, BOB, Step, build_repo
from vouch.eval.corpus import (
    AuthorSelector,
    CorpusError,
    RepoSpec,
    email_digest,
    load_corpus,
    ranked_authors,
    resolve_aliases,
    resolve_author,
)
from vouch.l4.dimensions import DIMENSIONS

DEPENDABOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = REPO_ROOT / "eval" / "repos.yaml"

# Broad on purpose: this catches a slip, it does not parse RFC 5322.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Alice 3 commits, Bob 2, a bot 4 — so bot filtering changes the ranking if it fails."""
    path = tmp_path / "corpus_repo"
    build_repo(
        path,
        [
            Step(ALICE, "2024-01-01T12:00:00+00:00", "feat: one", {"a.py": "1\n"}),
            Step(BOB, "2024-01-02T12:00:00+00:00", "feat: two", {"b.py": "1\n"}),
            Step(DEPENDABOT, "2024-01-03T12:00:00+00:00", "chore: bump", {"c.txt": "1\n"}),
            Step(DEPENDABOT, "2024-01-04T12:00:00+00:00", "chore: bump", {"c.txt": "2\n"}),
            Step(ALICE, "2024-01-05T12:00:00+00:00", "feat: three", {"a.py": "2\n"}),
            Step(DEPENDABOT, "2024-01-06T12:00:00+00:00", "chore: bump", {"c.txt": "3\n"}),
            Step(BOB, "2024-01-07T12:00:00+00:00", "feat: four", {"b.py": "2\n"}),
            Step(DEPENDABOT, "2024-01-08T12:00:00+00:00", "chore: bump", {"c.txt": "4\n"}),
            Step(ALICE, "2024-01-09T12:00:00+00:00", "feat: five", {"a.py": "3\n"}),
        ],
    )
    return path


def _spec(rank: int, email: str, **kw) -> RepoSpec:
    return RepoSpec(
        id=kw.pop("id", "fixture"),
        axis="test",
        repo="local",
        head="HEAD",
        author=AuthorSelector(rank=rank, email_sha256=email_digest(email)),
        **kw,
    )


def test_ranked_authors_drops_bots_and_orders_by_volume(repo: Path) -> None:
    ranked = ranked_authors(repo, "HEAD")
    assert ranked == [(ALICE[1], 3), (BOB[1], 2)]  # the bot's 4 commits are not a rank


def test_resolve_author_returns_the_address_from_the_clone(repo: Path) -> None:
    resolved = resolve_author(_spec(1, ALICE[1]), repo)
    assert (resolved.email, resolved.rank, resolved.commits) == (ALICE[1], 1, 3)


def test_resolve_author_handles_a_non_top_rank(repo: Path) -> None:
    assert resolve_author(_spec(2, BOB[1]), repo).email == BOB[1]


def test_rank_and_digest_disagreeing_is_fatal(repo: Path) -> None:
    """The pinned rank points at Alice; the digest says Bob. Refuse, and say where he is.

    Silently trusting the digest would be the dangerous fix: it would let a row keep
    resolving while its `measured:` block — computed under the old ranking — went stale.
    """
    with pytest.raises(CorpusError) as exc:
        resolve_author(_spec(1, BOB[1]), repo)
    assert "rank 2" in str(exc.value) and "pinned rank 1" in str(exc.value)


def test_a_subject_absent_from_the_history_is_fatal(repo: Path) -> None:
    with pytest.raises(CorpusError, match="matches digest"):
        resolve_author(_spec(1, "nobody@example.com"), repo)


def test_error_text_never_prints_an_address(repo: Path) -> None:
    """Failure messages are the easy place for a scrubbed address to reappear."""
    for spec in (_spec(1, BOB[1]), _spec(1, "nobody@example.com")):
        with pytest.raises(CorpusError) as exc:
            resolve_author(spec, repo)
        assert not _EMAIL_RE.search(str(exc.value))


def test_a_rank_past_the_end_is_fatal(repo: Path) -> None:
    with pytest.raises(CorpusError):
        resolve_author(_spec(9, ALICE[1]), repo)


def test_a_missing_head_is_fatal_not_empty(repo: Path) -> None:
    with pytest.raises(CorpusError, match="pinned head"):
        ranked_authors(repo, "0" * 40)


def test_aliases_resolve_by_digest_too(repo: Path) -> None:
    spec = _spec(1, ALICE[1], aliases=[AuthorSelector(rank=2, email_sha256=email_digest(BOB[1]))])
    assert resolve_aliases(spec, repo) == [BOB[1]]


def test_a_plaintext_author_is_rejected_by_the_schema(tmp_path: Path) -> None:
    """The whole point of the module: `author: someone@example.com` must not load."""
    path = tmp_path / "repos.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "eval/repos/1",
                "name": "fixture corpus",
                "repos": [
                    {
                        "id": "x",
                        "axis": "test",
                        "repo": "local",
                        "head": "HEAD",
                        "author": "someone@example.com",
                    }
                ],
            }
        )
    )
    with pytest.raises(CorpusError):
        load_corpus(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "repos.yaml"
    row = {
        "id": "x",
        "axis": "test",
        "repo": "local",
        "head": "HEAD",
        "author": {"by": "commit_rank", "rank": 1, "email_sha256": email_digest(ALICE[1])},
    }
    path.write_text(
        yaml.safe_dump(
            {"schema_version": "eval/repos/1", "name": "fixture corpus", "repos": [row, row]}
        )
    )
    # The full phrase: `tmp_path` holds this test's name, so a bare "duplicate" always matches.
    with pytest.raises(CorpusError, match="duplicate corpus id"):
        load_corpus(path)


def test_a_corpus_that_does_not_name_itself_is_refused(tmp_path: Path) -> None:
    """A number's provenance is the name it is quoted under.

    "The eval corpus" is not a description of anything: this one is public repositories,
    which have no session telemetry and never will, so an agreement number measured here
    is about the commit-trail half of the judge and nothing else. The name is the only
    field that travels with a citation, so a corpus without one does not load.
    """
    path = tmp_path / "repos.yaml"
    path.write_text(yaml.safe_dump({"schema_version": "eval/repos/1", "repos": []}))

    with pytest.raises(CorpusError, match="name"):
        load_corpus(path)


def test_the_committed_corpus_contains_no_address() -> None:
    """No third-party address in this repository's history. The reason this module exists."""
    found = _EMAIL_RE.findall(CORPUS_PATH.read_text())
    assert found == [], f"address-shaped tokens in {CORPUS_PATH.name}: {found}"


def test_every_committed_row_is_loadable() -> None:
    corpus = load_corpus(CORPUS_PATH)
    assert len(corpus.repos) == 12
    assert all(spec.author.by == "commit_rank" for spec in corpus.repos)


def test_every_test_named_in_the_privacy_note_exists() -> None:
    """`notes.privacy` cites tests instead of asserting a state. The citations must resolve.

    A note that asserts "no address is anywhere in this history" is true the day it is
    written and unfalsifiable afterwards. Citing the check that enforces it is better only
    if the citation is kept honest — a reference to a test somebody deleted is worse than
    the assertion it replaced, because it reads as verified.
    """
    note = yaml.safe_load(CORPUS_PATH.read_text())["notes"]["privacy"]

    # `path::test_x`, `path::Class::test_x`, and `...::test_x` carrying the last file forward.
    cited, current = [], None
    for path, name in re.findall(
        r"(tests/\S+?\.py|\.\.\.)::(?:\w+::)?(test_\w+)", note
    ):
        current = path if path != "..." else current
        assert current is not None, f"'...' shorthand before any file was named: {name}"
        cited.append((current, name))

    assert len(cited) >= 10, f"the privacy note cites only {len(cited)} tests"
    missing = [
        f"{path}::{name}"
        for path, name in cited
        if f"def {name}(" not in (REPO_ROOT / path).read_text()
    ]
    assert not missing, f"notes.privacy cites tests that do not exist: {missing}"


def test_the_corpus_declares_its_coverage_and_is_right() -> None:
    """Every row is a public repo, so no row can carry L2 — and the file says which
    dimensions that leaves it able to calibrate.

    Checked against `DIMENSIONS` rather than trusted, because the declaration is prose's
    job everywhere else in this file and prose cannot notice when a dimension gains a
    layer. If `ownership` ever reads a session metric, this corpus stops calibrating it
    fully and this test is what says so — before an agreement number is quoted as if
    nothing had changed.
    """
    corpus = load_corpus(CORPUS_PATH)

    for spec in DIMENSIONS:
        if not spec.l2_metrics:
            expected = "full"  # nothing it reads from is missing here
        elif not spec.l1_facts:
            expected = "none"  # L2 alone: every row is forced not_collected
        else:
            expected = "l1_half"
        assert corpus.calibrates.get(spec.key.value) == expected, (
            f"{spec.key.value} is declared {corpus.calibrates.get(spec.key.value)!r} in "
            f"{CORPUS_PATH.name}, but its evidence layers make it {expected!r}"
        )

    assert set(corpus.calibrates) == {spec.key.value for spec in DIMENSIONS}


def test_the_corpus_name_carries_the_limit_not_just_a_label() -> None:
    """The name is what a citation quotes, so the constraint has to be inside it."""
    corpus = load_corpus(CORPUS_PATH)

    assert "L1" in corpus.name
    assert "session telemetry" in corpus.name


def test_the_target_shape_axis_is_present_and_paired() -> None:
    """The axis the product's actual user falls in — see the header block in the YAML.

    Asserted because it is the one axis whose absence would be invisible: every other row
    is an elite maintainer, and a corpus of only those looks complete right up until
    someone asks what the pipeline returns to a junior engineer.
    """
    corpus = load_corpus(CORPUS_PATH)
    rows = [spec for spec in corpus.repos if spec.axis == "target_shape"]
    assert len(rows) == 2
    # Thin by construction: both sit far below the ~200-commit floor of every other row.
    assert all(spec.measured["subject_commits"] <= 50 for spec in rows)
