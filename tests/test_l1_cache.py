"""L1 persistence, and the keying that makes a stale hit impossible.

A labelling round used to cost forty-seven minutes, nearly all of it `git blame` on real
histories. That is not a comfort problem: a round that expensive gets done once, in one
sitting, under time pressure — and the corpus is the only thing standing between the judge
and an unmeasured accuracy claim.

`RepoFacts` is already a pure function of (repo, pinned HEAD, subject, config) with no
wall-clock in it, which the golden files rest on. These tests pin the other half: that
every input which could change the output is in the cache key, so a hit is never a lie.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures import repos
from vouch.ingest import ingest
from vouch.l1.cache import (
    EXTRACTOR_VERSION,
    cache_key,
    cached_extract,
    load_cached_facts,
    store_facts,
)
from vouch.l1.config import L1Config, MinN
from vouch.l1.extract import extract_facts

SUBJECT = "alice@example.com"


@pytest.fixture
def built(tmp_path: Path):
    repo = tmp_path / "healthy"
    repos.healthy(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "gitcache")
    facts = extract_facts(snapshot, SUBJECT, repo)
    return repo, snapshot, facts, tmp_path / "cache"


# --- what the key covers -------------------------------------------------------------------


def test_the_same_inputs_produce_the_same_key() -> None:
    a = cache_key("r", "a" * 40, SUBJECT)
    b = cache_key("r", "a" * 40, SUBJECT)
    assert a == b


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param({"repo": "other"}, id="repo"),
        pytest.param({"head_sha": "b" * 40}, id="head"),
        pytest.param({"author": "bob@example.com"}, id="author"),
        pytest.param({"aliases": ["alice@personal.dev"]}, id="aliases"),
    ],
)
def test_every_input_that_changes_the_facts_changes_the_key(changed) -> None:
    base = dict(repo="r", head_sha="a" * 40, author=SUBJECT, aliases=[])
    assert cache_key(**base) != cache_key(**{**base, **changed})


def test_a_moving_head_is_a_different_measurement(built) -> None:
    """A branch name would let the cache answer for a history that has since grown."""
    assert cache_key("r", "a" * 40, SUBJECT) != cache_key("r", "b" * 40, SUBJECT)


def test_changing_a_threshold_changes_the_key(built) -> None:
    """`L1Config.fingerprint()` already covers the thresholds; the key must include it."""
    strict = L1Config(min_n=MinN(fix_commits=99))
    assert cache_key("r", "a" * 40, SUBJECT) != cache_key(
        "r", "a" * 40, SUBJECT, config=strict
    )


def test_alias_order_does_not_change_the_key() -> None:
    """Two callers listing the same aliases differently must not miss each other's work."""
    assert cache_key("r", "h", SUBJECT, ["b@x.com", "a@x.com"]) == cache_key(
        "r", "h", SUBJECT, ["a@x.com", "b@x.com"]
    )


def test_the_extractor_version_is_in_the_key() -> None:
    """A changed predicate leaves the schema identical and every cached value wrong."""
    key = cache_key("r", "a" * 40, SUBJECT)
    import vouch.l1.cache as cache_mod

    assert cache_mod.EXTRACTOR_VERSION == EXTRACTOR_VERSION

    original = cache_mod.EXTRACTOR_VERSION
    try:
        cache_mod.EXTRACTOR_VERSION = "l1-extract/999"
        assert cache_key("r", "a" * 40, SUBJECT) != key
    finally:
        cache_mod.EXTRACTOR_VERSION = original


# --- round-tripping --------------------------------------------------------------------------


def test_facts_survive_a_round_trip_byte_for_byte(built) -> None:
    _repo, _snapshot, facts, cache_dir = built
    store_facts("k", facts, cache_dir)

    assert load_cached_facts("k", cache_dir).model_dump_json() == facts.model_dump_json()


def test_a_miss_returns_none_rather_than_raising(built) -> None:
    *_rest, cache_dir = built
    assert load_cached_facts("never-written", cache_dir) is None


def test_a_corrupt_entry_is_a_miss_and_is_removed(built) -> None:
    """A cache that costs a failed parse on every run is worse than no cache."""
    _repo, _snapshot, facts, cache_dir = built
    path = store_facts("k", facts, cache_dir)
    path.write_text("{ this is not json")

    assert load_cached_facts("k", cache_dir) is None
    assert not path.exists()


# --- the behaviour that saves the time ---------------------------------------------------------


def test_the_second_run_does_not_recompute(built) -> None:
    repo, snapshot, _facts, cache_dir = built
    calls = 0

    def compute():
        nonlocal calls
        calls += 1
        return extract_facts(snapshot, SUBJECT, repo)

    first, cached_a = cached_extract(
        str(repo), snapshot.head_sha, SUBJECT, compute, cache_dir=cache_dir
    )
    second, cached_b = cached_extract(
        str(repo), snapshot.head_sha, SUBJECT, compute, cache_dir=cache_dir
    )

    assert calls == 1
    assert (cached_a, cached_b) == (False, True)
    assert first.model_dump_json() == second.model_dump_json()


def test_refresh_recomputes_even_on_a_hit(built) -> None:
    repo, snapshot, _facts, cache_dir = built
    calls = 0

    def compute():
        nonlocal calls
        calls += 1
        return extract_facts(snapshot, SUBJECT, repo)

    cached_extract(str(repo), snapshot.head_sha, SUBJECT, compute, cache_dir=cache_dir)
    cached_extract(
        str(repo), snapshot.head_sha, SUBJECT, compute, cache_dir=cache_dir, refresh=True
    )

    assert calls == 2


def test_a_version_bump_invalidates_without_deleting_anything(built) -> None:
    """The acceptance behaviour: change the extractor, get a miss, not a stale answer."""
    repo, snapshot, _facts, cache_dir = built
    import vouch.l1.cache as cache_mod

    calls = 0

    def compute():
        nonlocal calls
        calls += 1
        return extract_facts(snapshot, SUBJECT, repo)

    cached_extract(str(repo), snapshot.head_sha, SUBJECT, compute, cache_dir=cache_dir)
    original = cache_mod.EXTRACTOR_VERSION
    try:
        cache_mod.EXTRACTOR_VERSION = "l1-extract/999"
        _facts2, was_cached = cached_extract(
            str(repo), snapshot.head_sha, SUBJECT, compute, cache_dir=cache_dir
        )
    finally:
        cache_mod.EXTRACTOR_VERSION = original

    assert was_cached is False
    assert calls == 2
    # The old entry is still there, so reverting the version reverts to the old cache.
    assert (
        cached_extract(
            str(repo), snapshot.head_sha, SUBJECT, compute, cache_dir=cache_dir
        )[1]
        is True
    )
