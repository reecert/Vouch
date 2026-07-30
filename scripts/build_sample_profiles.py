"""Rebuild the viewer's git-only sample profile from a synthetic fixture repo.

    python scripts/build_sample_profiles.py

Why this is a committed script and not a paragraph in a README: a snapshot's filename is
its ``profile_id``, and that id is a hash of the file's own bytes, so a snapshot can only
be *corrected* by being regenerated. The pair this replaces proved the point — one had been
hand-edited after generation and hashed to neither its stored nor its computed id, and
because nobody could reproduce it, nobody could tell what else in it had been touched.

``tests/test_web_share.py::test_stored_id_reproduces`` already checks that a stored document
is honest about itself. That is a different property from this one: it says the bytes and
the id agree, not that the bytes came from anywhere in particular. Both are needed, because
a hand-edited file can satisfy the first.

The fixture repo is built at a directory named ``git-only-solo`` because
:func:`vouch.ingest.repo_label` keeps the leaf of a local path, and that leaf is the label
the document will carry. ``generated_at`` is pinned: it sits outside the hash, so a moving
stamp would produce a byte-different file with an identical id, and the byte pin in
``PINNED_SNAPSHOTS`` would fail on every run.

The telemetry sample (``with-telemetry``) predates this script and is **not**
reproducible from source: its session metrics and corroboration report were assembled by
hand rather than parsed from logs. Regenerating it needs synthetic session logs first.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "web" / "data" / "profiles"

#: Outside the hash, so it is pinned rather than left to the clock — see the module docstring.
GENERATED_AT = datetime.fromisoformat("2026-07-26T12:00:00")

SUBJECT = "alice@example.com"
LABEL = "git-only-solo"


def build_git_only_solo(profile_dir: Path) -> Path:
    """Solo repo, no telemetry: one invalidating confound, planning discipline not collected."""
    sys.path.insert(0, str(ROOT))  # the fixture builders live in tests/, which is not packaged

    from tests.fixtures import repos
    from vouch.ingest import ingest
    from vouch.l1.extract import extract_facts
    from vouch.l4.diffs import extract_diff
    from vouch.l4.grounding import build_allowlist
    from vouch.l4.judge import judge_profile
    from vouch.l4.mock import MockJudgeProvider, MockMode
    from vouch.l4.sampling import select_commits
    from vouch.l5.profile import build_profile

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / LABEL
        repos.solo(repo)

        snapshot = ingest(str(repo), cache_dir=Path(tmp) / "cache")
        facts = extract_facts(snapshot, SUBJECT, repo)

        provider = MockJudgeProvider(MockMode.HONEST)
        sample = select_commits(snapshot.commits, facts)
        provider.bind(build_allowlist(facts, [extract_diff(repo, c) for c in sample.commits]))

        judgment = judge_profile(provider, facts, repo, snapshot.commits)
        profile = build_profile(facts, judgment, generated_at=GENERATED_AT)

    for stale in profile_dir.glob("*.json"):
        if json.loads(stale.read_text())["evidence_inspected"]["repo"] == LABEL:
            stale.unlink()

    target = profile_dir / f"{profile.profile_id}.json"
    target.write_text(profile.model_dump_json(indent=2))
    return target


if __name__ == "__main__":
    written = build_git_only_solo(PROFILE_DIR)
    print(f"wrote {written.relative_to(ROOT)}")
    print("now re-pin PINNED_SNAPSHOTS in tests/test_web_share.py")
