"""Shared test plumbing: build a fixture repo, and scan a document for machine-local data.

The scanner lives here rather than beside one test because two different suites need the
same answer — the shipped snapshots in `test_web_share.py`, and the document the CLI
produces end to end in `test_cli.py`. The input-side normalizer (`vouch.ingest.repo_label`)
cannot be the whole control: `findings[].summary`, `claims[].text` and the model's own
limitations are free text from a judge that reads source, and source contains absolute
paths that a model can quote back. This scans the finished bytes, which is the only place
every channel converges.
"""
from __future__ import annotations

import re
import socket
import tempfile
from pathlib import Path

import pytest

from tests.fixtures import repos
from vouch.ingest import ingest
from vouch.l1.config import L1Config
from vouch.l1.extract import extract_facts
from vouch.l1.facts import RepoFacts

SUBJECT = "alice@example.com"

#: A leading `/` with at least two segments; a repo-relative `src/auth.py` has neither.
_LEAK_PATTERNS = (
    ("an absolute path", re.compile(r"(?<![\w~.-])/(?:[\w.-]+/)+[\w.-]+")),
    ("a home directory", re.compile(r"~/|/Users/|/home/|/root/|/var/folders/")),
    ("a remote address", re.compile(r"\w+://|[\w.-]+@[\w.-]+[:/]")),
)

#: The floor the scan must reject everywhere, on any machine.
#:
#: The machine-derived needles below are strictly additive, and on their own they make the
#: scan mean something different on every box: on CI the home directory is
#: `/home/runner`, the hostname is a container id, and a macOS-shaped `/Users/...` leak
#: would be matched by no needle at all — so the suite would go green on the exact string
#: that started this. These are synthetic, fixed, and one per rule, so the guarantee is the
#: same in CI as it is on the laptop that wrote the leak.
CANARY_LEAKS = (
    "/Users/alice/clients/bigco/api",
    "/home/runner/work/vouch/vouch",
    "/var/folders/qn/myx3dwjs/T/tmpad9a3c6d/repo",
    "~/clients/bigco/api",
    "git@github.com:acme/private-api.git",
    "https://x-token:ghp_secret@github.com/acme/private-api",
    "fixture://example/with-telemetry",
)


def _hostnames() -> set[str]:
    """This machine's names, matched on word boundaries — a host may be called `Mac`."""
    host = socket.gethostname()
    return {name for name in (host, host.partition(".")[0]) if name}


def assert_no_machine_locals(document: str, subject: str = "") -> None:
    """Fail if a serialized profile carries anything local to the machine that built it.

    ``subject`` is the sole exemption: the profile is *about* an address, so its own
    canonical email is data rather than leakage. It is masked before the scan, so a second
    address still fails wherever it appears in an address *shape* — `git@host:org/repo`, a
    credentialed URL. A bare `j******@corp.com` passes, and is meant to:
    :func:`vouch.l1.confounds.mask_email` puts it there deliberately.
    """
    haystack = document.replace(subject, "<subject>") if subject else document

    for root in (str(Path.home()), tempfile.gettempdir()):
        assert root not in haystack, f"document carries a machine-local root: {root!r}"

    for host in _hostnames():
        hit = re.search(rf"\b{re.escape(host)}\b", haystack, re.IGNORECASE)
        assert hit is None, f"document names the machine that built it: {host!r}"

    for label, pattern in _LEAK_PATTERNS:
        hit = pattern.search(haystack)
        assert hit is None, f"document carries {label}: {hit.group(0)!r}"


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
