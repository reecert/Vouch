"""Share metadata, and the documents it must not disturb.

A share link is `/p/<profile_id>` and `profile_id` is a content hash, so anything that
changes what gets hashed silently invalidates every link already sent. Metadata is
supposed to be inert with respect to that: it lives entirely in the viewer, describes the
document, and touches none of its bytes.

"Supposed to" is what these tests replace. Four of them pin the things that would have to
move for a link to break — the snapshot bytes, the id they resolve at, the id each document
still hashes to, and the *shape* of the hashed payload — so a future change that rehashes
stored profiles fails here rather than in someone's inbox. The shape test is the one that
was missing: `Provenance` gained `session_snapshot` after the checked-in snapshots were
written, which rewrote the payload for every profile ever generated, and nothing caught it
because `test_l5_profile.py::test_profile_id_is_stable_across_regeneration` only compares
two runs inside one process.

`test_stored_id_reproduces` is the other half of that lesson, and the one that would have
caught what actually happened: both previous snapshots had drifted from their own ids —
one because the schema moved underneath it, one because it was edited by hand afterwards —
so a share link pointed at a document that was no longer the document its id described. A
content hash that nothing recomputes is decoration.

`test_no_machine_local_data_ships` is the leak control. It scans the finished bytes rather
than any one producer, because the producers are not enumerable: the address is normalized
at ingest, but a judge that reads source can quote an absolute path back into a summary.

The rest cover what surrounds the document rather than the document itself: the card must be
the size unfurlers expect, the module that builds the metadata must stay unable to see who
the profile is about, the site must not ship a list of who has a profile, and the profile
page must stay outside the product's navigation and out of reach of the delete path.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
import struct
from pathlib import Path

import pytest

from tests.conftest import CANARY_LEAKS, assert_no_machine_locals
from vouch.l1.facts import BiasDirection, Confound, ConfoundKey, Severity
from vouch.l4.schema import (
    Claim,
    Confidence,
    DimensionFinding,
    DimensionKey,
    Locator,
    Verdict,
)
from vouch.l5.profile import EvidenceSummary, Profile, Provenance

WEB = Path(__file__).resolve().parents[1] / "web"
SNAPSHOTS = WEB / "data" / "profiles"

#: The bytes behind every share link in this repo. A diff here is a broken link, not a nit.
PINNED_SNAPSHOTS = {
    "29ea47da5e6c6137.json":
        "62aeac83b836c5e5f73fb18a06eaef8a7ec6fab69dbcdc462c3531d0ee63d4dd",
    "e5289e0775c2c373.json":
        "8f6390c0df413bea8338950beb85d074314a8373ff1be22a851922a175943fc4",
}

#: Discovered, not listed: a snapshot dropped in later is checked without being enrolled.
SNAPSHOT_NAMES = sorted(path.name for path in SNAPSHOTS.glob("*.json"))

#: Every field `compute_id()` hashes. Adding one rehashes profiles that already exist.
PINNED_HASHED_FIELDS = [
    "confounds[].affects[]",
    "confounds[].detail",
    "confounds[].direction",
    "confounds[].key",
    "confounds[].severity",
    "corroboration.n_ambiguous",
    "corroboration.n_commits",
    "corroboration.n_corroborated",
    "corroboration.n_uncorroborated",
    "corroboration.ran",
    "evidence_inspected.excluded_paths",
    "evidence_inspected.head_sha",
    "evidence_inspected.measured_facts",
    "evidence_inspected.n_commits_by_subject",
    "evidence_inspected.n_commits_in_repo",
    "evidence_inspected.n_diffs_available",
    "evidence_inspected.n_diffs_read",
    "evidence_inspected.n_sessions",
    "evidence_inspected.repo",
    "evidence_inspected.session_telemetry",
    "evidence_inspected.window_first",
    "evidence_inspected.window_last",
    "evidence_inspected.withheld_facts",
    "findings[].claims[].locators[].path",
    "findings[].claims[].locators[].sha",
    "findings[].claims[].text",
    "findings[].confidence",
    "findings[].dimension",
    "findings[].limitations[]",
    "findings[].risks_to_probe[]",
    "findings[].summary",
    "findings[].verdict",
    "limitations[]",
    "provenance.downgrades[]",
    "provenance.judge_model",
    "provenance.l1_schema",
    "provenance.prompt_version",
    "provenance.session_snapshot",
    "risks_to_probe[]",
    "schema_version",
    "subject",
]


def _representative_profile() -> Profile:
    """One of everything, so the shape walk reaches every nested model."""
    return Profile(
        subject="alice@example.com",
        evidence_inspected=EvidenceSummary(repo="example/repo", head_sha="abc123"),
        findings=[
            DimensionFinding(
                dimension=DimensionKey.OWNERSHIP,
                verdict=Verdict.STRONG,
                confidence=Confidence.HIGH,
                summary="Returns to their own defects.",
                claims=[Claim(text="Fixed it.", locators=[Locator(sha="abc", path="a.py")])],
                limitations=["Based on one repository."],
                risks_to_probe=["Ask about someone else's code."],
            )
        ],
        risks_to_probe=["Ask about someone else's code."],
        confounds=[
            Confound(
                key=ConfoundKey.SOLO_REPO,
                severity=Severity.INVALIDATING,
                direction=BiasDirection.UNKNOWN,
                detail="12/12 commits.",
                affects=["ownership_loop"],
            )
        ],
        limitations=["It is not a hiring decision."],
        provenance=Provenance(downgrades=["ownership: strong -> limited"]),
    )


def _field_paths(node: object, prefix: str = "") -> set[str]:
    """Dotted paths of every leaf in the hashed payload; `[]` marks a list of models."""
    if isinstance(node, dict):
        if not node:  # `excluded_paths` is free-form, so it is a leaf, not a shape
            return {prefix}
        out: set[str] = set()
        for key, value in node.items():
            out |= _field_paths(value, f"{prefix}.{key}" if prefix else key)
        return out
    if isinstance(node, list):
        if not node:
            return {prefix}
        return _field_paths(node[0], f"{prefix}[]")
    return {prefix}


class TestSharedDocumentsAreUndisturbed:
    def test_snapshot_bytes_are_pinned(self) -> None:
        """Metadata is viewer-side; if these bytes moved, something reached past it."""
        on_disk = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(SNAPSHOTS.glob("*.json"))
        }
        assert on_disk == PINNED_SNAPSHOTS

    @pytest.mark.parametrize("name", SNAPSHOT_NAMES)
    def test_share_link_resolves_to_the_id_inside_the_file(self, name: str) -> None:
        """`/p/<id>` is served from `<id>.json`, so the two must not drift apart."""
        data = json.loads((SNAPSHOTS / name).read_text())
        stem = name.removesuffix(".json")
        assert data["profile_id"] == stem
        # The viewer refuses any id outside this shape (web/lib/data.ts:27).
        assert re.fullmatch(r"[a-f0-9]{8,64}", stem)

    @pytest.mark.parametrize("name", SNAPSHOT_NAMES)
    def test_stored_id_reproduces(self, name: str) -> None:
        """The id must still be the hash of the document it names.

        A stored profile that no longer hashes to its own id is either hand-edited or left
        behind by a schema change; both mean the link resolves to something other than what
        was shared. Regenerate the snapshot rather than editing the id to match.
        """
        profile = Profile.model_validate_json((SNAPSHOTS / name).read_text())
        assert profile.profile_id == profile.compute_id()

    @pytest.mark.parametrize("name", SNAPSHOT_NAMES)
    def test_no_machine_local_data_ships(self, name: str) -> None:
        """Nothing in a published document may describe the machine that built it."""
        raw = (SNAPSHOTS / name).read_text()
        assert_no_machine_locals(raw, subject=json.loads(raw)["subject"])

    def test_the_canary_floor_is_not_empty(self) -> None:
        """A parametrized list that empties out reports zero failures, not zero tests.

        `test_the_scan_catches_what_it_is_for` collects one case per canary, so deleting
        the canaries deletes the coverage silently. This is the one assertion that notices.
        """
        assert len(CANARY_LEAKS) >= 6
        assert any(leak.startswith("/Users/") for leak in CANARY_LEAKS), "no macOS home"
        assert any(leak.startswith("/home/") for leak in CANARY_LEAKS), "no CI home"
        assert any("@" in leak for leak in CANARY_LEAKS), "no remote address"

    @pytest.mark.parametrize("leaked", CANARY_LEAKS)
    def test_the_scan_catches_what_it_is_for(self, leaked: str) -> None:
        """The discriminating half: a scanner that cannot fail is not a control.

        These are fixed strings, so this test says the same thing on CI as it does here.
        The tmp path is verbatim what the previous snapshots shipped.
        """
        document = json.dumps(
            {
                "subject": "alice@example.com",
                "limitations": [f"Based on a single repository ({leaked})."],
            }
        )
        with pytest.raises(AssertionError):
            assert_no_machine_locals(document, subject="alice@example.com")

    def test_the_scan_also_catches_this_machine(self) -> None:
        """The machine-derived needles sit on top of the canary floor, not instead of it."""
        for local in (socket.gethostname(), str(Path.home())):
            document = json.dumps({"limitations": [f"Built at {local}."]})
            with pytest.raises(AssertionError):
                assert_no_machine_locals(document)

    def test_the_scan_allows_what_a_profile_legitimately_says(self) -> None:
        """The subject's address, a masked alias, and repo-relative paths are all data."""
        document = json.dumps(
            {
                "subject": "alice@example.com",
                "evidence_inspected": {"repo": "acme/private-api"},
                "confounds": [{"detail": "1 other address (a****@example.com) resembles it."}],
                "findings": [{"claims": [{"locators": [{"path": "src/ratelimit.py"}]}]}],
                "limitations": ["12/12 human commits; see tests/test_auth.py."],
            }
        )
        assert_no_machine_locals(document, subject="alice@example.com")

    def test_hashed_payload_shape_is_pinned(self) -> None:
        """A new field here changes `profile_id` for every profile already shared."""
        payload = json.loads(_representative_profile().frozen_payload())
        assert sorted(_field_paths(payload)) == PINNED_HASHED_FIELDS

    def test_the_stamp_and_the_id_stay_out_of_the_hash(self) -> None:
        payload = json.loads(_representative_profile().frozen_payload())
        assert "profile_id" not in payload
        assert "generated_at" not in payload["provenance"]


class TestShareCard:
    def test_card_is_a_1200x630_png(self) -> None:
        """The size every unfurler crops to; wrong dimensions letterbox or get rejected."""
        png = (WEB / "public" / "og.png").read_bytes()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", png[16:24])  # IHDR payload starts at byte 16
        assert (width, height) == (1200, 630)

    def test_metadata_cannot_see_who_the_profile_is_about(self) -> None:
        """An unfurled card outlives the document, so identity must not be in scope here.

        `profileShareMetadata` takes counts, not a `Profile`. This keeps it that way: the
        regression to fear is a later edit reaching for the subject to make the card
        "more useful", which is exactly the leak the content-free card exists to prevent.
        """
        body = "\n".join(
            line
            for line in (WEB / "lib" / "share.ts").read_text().splitlines()
            if not line.lstrip().startswith(("*", "//", "/*"))
        )
        assert "lib/profile" not in body and './profile"' not in body, (
            "share.ts imports the document type; the point is that it cannot see one"
        )
        for field in (".subject", ".findings", ".verdict", ".confidence",
                      ".evidence_inspected", ".limitations", ".confounds"):
            assert field not in body, f"share.ts reads {field} off a profile"


def _source(*parts: str) -> str:
    """A file's code, with comments and imports dropped so a mention in prose does not count."""
    return "\n".join(
        line
        for line in WEB.joinpath(*parts).read_text().splitlines()
        if not line.lstrip().startswith(("*", "//", "/*", "import "))
    )


class TestLandingPage:
    def test_the_index_ships_no_list_of_who_is_profiled(self) -> None:
        """The index is onboarding in production and a dev convenience only in `next dev`.

        A browsable list of everyone profiled is a candidate directory — a phase-1 non-goal,
        and a disclosure an unlisted link exists to prevent. The guard is a build-time
        constant, so the enumeration has to sit behind it rather than beside it.
        """
        body = _source("app", "(site)", "page.tsx")
        guard = body.find('process.env.NODE_ENV === "production"')

        assert guard != -1, "page.tsx enumerates profiles with nothing gating production"
        assert guard < body.find("listProfileIds("), (
            "profiles are enumerated before the production guard, so the site lists them"
        )


class TestTheDocumentStandsApartFromTheProduct:
    """A profile is read by someone who was sent a link, not by a visitor browsing a site."""

    def test_the_profile_page_is_outside_the_navigated_group(self) -> None:
        """Product chrome around someone's document is an invitation to sign up, over their name."""
        assert "Nav" in _source("app", "(site)", "layout.tsx")
        assert (WEB / "app" / "p" / "[id]" / "page.tsx").is_file()
        assert not (WEB / "app" / "(site)" / "p").exists(), (
            "the profile route moved under the group that renders the product nav"
        )

    def test_revoking_cannot_reach_a_checked_in_sample(self) -> None:
        """`deleteProfile` runs on a request; the tracked samples must be out of its reach."""
        body = _source("lib", "data.ts")
        deleter = body[body.index("export function deleteProfile") :]

        assert "RUNTIME_DIR" in deleter
        assert "SAMPLE_DIR" not in deleter and "DIRS" not in deleter
