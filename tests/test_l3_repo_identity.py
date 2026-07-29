"""Which paths are this repo — the layer under the join.

Every test here is a way the previous resolver was wrong, and each maps to a defect with a
direction. The false *negatives* (a repo that moved, a spelling the filesystem considers
equal) are the dangerous ones: they do not look like errors, they look like a person who
committed without supervision.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures import joins
from vouch.ingest import ingest
from vouch.l2.parser import parse_log_dir
from vouch.l3.join import join, session_edits
from vouch.l3.repo_identity import (
    HistoricalRoot,
    PathOutcome,
    RepoIdentity,
    detect_case_insensitive,
    discover_candidate_roots,
    history_paths,
    load_identity_file,
    resolve_identity,
)


def _session_file(path: Path, session_id: str, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({**r, "sessionId": session_id}) + "\n" for r in records)
    )


def _edit(file_path: str, hours: float, cwd: str | None = None) -> dict:
    record = {
        "type": "assistant",
        "timestamp": joins.iso(hours),
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": file_path}}
            ],
        },
    }
    if cwd is not None:
        record["cwd"] = cwd
    return record


def _prompt(hours: float, cwd: str | None = None) -> dict:
    record = {
        "type": "user",
        "timestamp": joins.iso(hours),
        "message": {"role": "user", "content": "go"},
    }
    if cwd is not None:
        record["cwd"] = cwd
    return record


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    joins.build_repo_for_join(r)
    return r


def test_a_repo_that_moved_corroborates_nothing_until_the_move_is_declared(
    tmp_path: Path, repo: Path
) -> None:
    """The silent false negative, in miniature.

    The session recorded absolute paths under the repo's *old* home. Nothing about those
    paths is wrong and nothing about the commit is unsupervised — but a resolver that knows
    only one root sees no overlap and reports `uncorroborated`, which a reader takes as
    "no evidence this was supervised".
    """
    old_root = tmp_path / "OldName"
    logs = tmp_path / "logs"
    _session_file(
        logs / "S.jsonl",
        "S",
        [_prompt(-1.5), _edit(str(old_root / "src/a.py"), -1)],
    )
    sessions = parse_log_dir(logs).sessions

    before = join(ingest(str(repo), cache_dir=tmp_path / "c").commits, sessions, repo)
    assert before.n_corroborated == 0

    identity = resolve_identity(repo, declared=[HistoricalRoot(path=str(old_root))])
    after = join(
        ingest(str(repo), cache_dir=tmp_path / "c").commits, sessions, identity
    )
    assert after.n_corroborated == 1


def test_a_declared_root_only_admits_paths_this_history_has_seen(
    tmp_path: Path, repo: Path
) -> None:
    """A declaration is a claim, not a licence — a fork at a similar path proves nothing."""
    old_root = tmp_path / "OldName"
    identity = resolve_identity(repo, declared=[HistoricalRoot(path=str(old_root))])

    assert identity.relativize(str(old_root / "src/a.py"), None) == (
        PathOutcome.IN_REPO,
        "src/a.py",
    )
    # Same prefix, a file this repo has never contained. Rejected, and counted as such.
    assert identity.relativize(str(old_root / "src/never_here.py"), None) == (
        PathOutcome.UNKNOWN_TO_HISTORY,
        None,
    )


def test_the_rename_is_data_not_a_rewrite_rule(tmp_path: Path, repo: Path) -> None:
    """The old root is read from a file. No spelling of it is compiled into the source."""
    (repo / ".vouch").mkdir(exist_ok=True)
    (repo / ".vouch" / "identity.yaml").write_text(
        "schema_version: repo-identity/1\n"
        "historical_roots:\n"
        f"  - path: {tmp_path / 'OldName'}\n"
        "    why: renamed in the test\n"
    )

    declared = load_identity_file(repo).historical_roots
    assert [d.path for d in declared] == [str(tmp_path / "OldName")]

    identity = resolve_identity(repo)
    assert identity.relativize(str(tmp_path / "OldName" / "src/a.py"), None)[0] is (
        PathOutcome.IN_REPO
    )


def test_a_declared_root_may_be_written_relative_to_the_repo(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`../OldName` — the form a rename in place actually takes, and portable.

    An absolute declaration records the machine that wrote it: `/Users/somebody/...` is
    one person's home directory stored as though it were a property of the repository, and
    it stops being true the moment the checkout moves.
    """
    old_root = repo.parent / "OldName"
    # The CLI is running somewhere else entirely, as it usually is. The base is the repo.
    monkeypatch.chdir(tmp_path)

    identity = resolve_identity(repo, declared=[HistoricalRoot(path="../OldName")])

    assert identity.relativize(str(old_root / "src/a.py"), None) == (
        PathOutcome.IN_REPO,
        "src/a.py",
    )


def test_a_relative_declaration_is_not_resolved_against_the_process_cwd(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the same declaration means a different directory per invocation.

    The same defect as a session path resolved against the CLI's working directory, one
    layer up: it would silently admit whatever happened to sit beside wherever the command
    was run from.
    """
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "OldName").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)

    identity = resolve_identity(repo, declared=[HistoricalRoot(path="OldName")])

    assert identity.relativize(str(elsewhere / "OldName" / "src/a.py"), None) == (
        PathOutcome.OUTSIDE,
        None,
    )


def test_a_root_declared_under_a_different_spelling_is_not_a_second_root(
    tmp_path: Path, repo: Path
) -> None:
    """`./repo/../repo` is the same directory. Declaring it must not create a duplicate."""
    identity = resolve_identity(
        repo, declared=[HistoricalRoot(path=str(repo / ".." / repo.name))]
    )
    assert identity.historical_keys == ()


@pytest.mark.skipif(
    not detect_case_insensitive(Path(__file__)),
    reason="filesystem is case-sensitive, so the two spellings really are two paths",
)
def test_case_insensitive_filesystems_match_either_spelling(repo: Path) -> None:
    identity = resolve_identity(repo)
    swapped = str(repo).swapcase() + "/src/a.py"

    assert identity.case_insensitive is True
    assert identity.relativize(swapped, None)[0] is PathOutcome.IN_REPO


def test_a_path_under_a_similarly_named_sibling_is_outside(repo: Path) -> None:
    """`repo-old/` is not under `repo/`, whatever a prefix comparison thinks."""
    identity = resolve_identity(repo)
    assert identity.relativize(f"{repo}-old/src/a.py", None)[0] is PathOutcome.OUTSIDE


def test_a_relative_path_resolves_against_the_session_cwd(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not against the CLI's cwd — which is a coincidence, not evidence."""
    logs = tmp_path / "logs"
    _session_file(
        logs / "S.jsonl",
        "S",
        [_prompt(-1.5, cwd=str(repo)), _edit("src/a.py", -1)],
    )
    # The CLI is running somewhere else entirely, as it usually is.
    monkeypatch.chdir(tmp_path)

    edits, coverage = session_edits(parse_log_dir(logs).sessions, repo)
    assert [e.paths for e in edits] == [frozenset({"src/a.py"})]
    assert coverage.n_unresolvable == 0


def test_a_relative_path_is_not_resolved_against_the_process_cwd(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The false positive. The session was in another project; the CLI happened to be here.

    Resolving `src/a.py` against the process's working directory would hand this repo an
    edit that belongs to `other/`, and it would look exactly like real evidence.
    """
    other = tmp_path / "other"
    logs = tmp_path / "logs"
    _session_file(
        logs / "S.jsonl",
        "S",
        [_prompt(-1.5, cwd=str(other)), _edit("src/a.py", -1)],
    )
    monkeypatch.chdir(repo)

    edits, coverage = session_edits(parse_log_dir(logs).sessions, repo)
    assert edits == []
    assert coverage.n_in_repo == 0
    assert coverage.n_outside == 1


def test_a_relative_path_with_no_recorded_cwd_is_dropped_and_counted(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unresolvable is an outcome, not a prompt to guess."""
    logs = tmp_path / "logs"
    _session_file(logs / "S.jsonl", "S", [_prompt(-1.5), _edit("src/a.py", -1)])
    monkeypatch.chdir(repo)

    edits, coverage = session_edits(parse_log_dir(logs).sessions, repo)
    assert edits == []
    assert coverage.n_unresolvable == 1
    assert coverage.n_dropped == 1


def test_the_cwd_in_effect_is_the_last_one_recorded(tmp_path: Path, repo: Path) -> None:
    """Sessions move. A path is resolved against where the session was *then*."""
    other = tmp_path / "other"
    logs = tmp_path / "logs"
    _session_file(
        logs / "S.jsonl",
        "S",
        [
            _prompt(-2, cwd=str(other)),
            _edit("src/a.py", -1.5),  # in `other` — not ours
            {"type": "relocated", "relocatedCwd": str(repo)},
            _edit("src/a.py", -1),  # after the move — ours
        ],
    )

    edits, coverage = session_edits(parse_log_dir(logs).sessions, repo)
    assert [e.paths for e in edits] == [frozenset({"src/a.py"})]
    assert coverage.n_in_repo == 1
    assert coverage.n_outside == 1


def test_the_report_carries_the_unresolved_count(tmp_path: Path, repo: Path) -> None:
    """Coverage that drops silently is a defect. This is the loud part."""
    logs = tmp_path / "logs"
    _session_file(logs / "S.jsonl", "S", [_prompt(-1.5), _edit("src/a.py", -1)])

    report = join(
        ingest(str(repo), cache_dir=tmp_path / "c").commits,
        parse_log_dir(logs).sessions,
        repo,
    )
    assert report.path_coverage.n_unresolvable == 1
    assert report.n_corroborated == 0


def test_discovery_proposes_a_root_but_the_join_does_not_use_it(
    tmp_path: Path, repo: Path
) -> None:
    """A candidate is something for a human to accept, never something the join acts on."""
    old_root = tmp_path / "OldName"
    identity = resolve_identity(repo)
    known = history_paths(repo)

    observed = [
        (str(old_root / "src/a.py"), None),
        (str(old_root / "src/c.py"), None),
        (str(tmp_path / "unrelated" / "nothing.py"), None),
    ]
    candidates = discover_candidate_roots(observed, identity, known)

    assert candidates[0].root == str(old_root)
    assert candidates[0].n_known == 2
    assert candidates[0].share_known == 1.0
    # ...and until it is declared, the resolver still refuses those paths.
    assert identity.relativize(str(old_root / "src/a.py"), None)[0] is PathOutcome.OUTSIDE


def test_identity_without_declared_roots_does_no_git_work(repo: Path) -> None:
    """The common case declares nothing and should not pay for a full-history path walk."""
    identity = resolve_identity(repo)
    assert identity.known_paths == frozenset()
    assert isinstance(identity, RepoIdentity)
