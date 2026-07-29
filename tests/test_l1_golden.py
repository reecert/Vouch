"""Golden-file tests — L1's output is frozen, byte for byte.

The v0 prototype stamped `datetime.now()` into every signal, so no two runs agreed and a
golden file was impossible. With wall-clock removed, `RepoFacts` is a pure function of
(repo, HEAD, config) and can be diffed exactly.

Commit SHAs are stable across machines: a commit hash is determined by tree, message,
author, committer and dates, and every fixture date carries an explicit UTC offset. So the
golden files pin the real SHAs, not placeholders — which means a change to *which commits*
a fact rests on shows up as a diff, not just a change in the totals.

Refresh after an intentional change:  UPDATE_GOLDEN=1 pytest tests/test_l1_golden.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.fixtures import repos
from vouch.ingest import ingest
from vouch.l1.extract import extract_facts

GOLDEN_DIR = Path(__file__).parent / "golden"

VARIANTS = [
    "healthy",
    "solo",
    "squash_merged",
    "bot_heavy",
    "noisy",
    "rebased",
    "aliased",
    "short_window",
]


def _facts_json(variant: str, tmp_path: Path) -> str:
    repo = tmp_path / variant
    getattr(repos, variant)(repo)
    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    facts = extract_facts(snapshot, "alice@example.com", repo)
    # The repo label is the tmp dir's two last segments; everything else is machine-independent.
    payload = json.loads(facts.model_dump_json())
    payload["repo"] = f"fixture://{variant}"
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


@pytest.mark.parametrize("variant", VARIANTS)
def test_golden(variant: str, tmp_path: Path) -> None:
    actual = _facts_json(variant, tmp_path)
    path = GOLDEN_DIR / f"{variant}.json"

    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(actual)
        pytest.skip(f"golden refreshed: {path.name}")

    assert path.is_file(), f"missing golden file {path}; run with UPDATE_GOLDEN=1"
    assert actual == path.read_text()


@pytest.mark.parametrize("variant", ["healthy", "noisy"])
def test_output_is_byte_reproducible(variant: str, tmp_path: Path) -> None:
    """Two independent builds of the same fixture agree exactly — SHAs included."""
    first = _facts_json(variant, tmp_path / "a")
    second = _facts_json(variant, tmp_path / "b")
    assert first == second


def test_golden_files_pin_real_shas() -> None:
    """Guard against a future refactor quietly replacing SHAs with placeholders."""
    payload = json.loads((GOLDEN_DIR / "healthy.json").read_text())
    loop = next(f for f in payload["facts"] if f["key"] == "ownership_loop")
    shas = {loc["sha"] for loc in loop["evidence"]}

    assert len(shas) >= 3
    assert all(len(sha) == 40 and set(sha) <= set("0123456789abcdef") for sha in shas)
