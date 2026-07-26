"""Identity resolution — aliases are merged only when vouched for, never on a guess."""
from __future__ import annotations

from vouch.l1.confounds import mask_email
from vouch.l1.identity import github_login, is_bot, normalize_email, resolve_identity

AUTHORS = [
    ("Alice Dev", "alice@example.com"),
    ("Alice Dev", "alice@personal.dev"),  # same name, different address
    ("alice", "12345+alice@users.noreply.github.com"),  # same GitHub login
    ("Bob Other", "bob@example.com"),
    ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
]


def test_normalize_and_login() -> None:
    assert normalize_email("  <Alice@Example.COM> ") == "alice@example.com"
    assert github_login("12345+alice@users.noreply.github.com") == "alice"
    assert github_login("alice@users.noreply.github.com") == "alice"
    assert github_login("alice@example.com") is None


def test_bot_detection() -> None:
    assert is_bot("dependabot[bot]", "x@y.com")
    assert is_bot("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
    assert is_bot("renovate", "renovate@whitesourcesoftware.com")
    assert not is_bot("Alice Dev", "alice@example.com")


def test_near_matches_are_reported_not_merged() -> None:
    """The whole point: a name match must not silently change the numbers."""
    identity, unclaimed = resolve_identity(AUTHORS, "alice@example.com")

    assert identity.emails == ["alice@example.com"]
    assert identity.matches("alice@example.com")
    assert not identity.matches("alice@personal.dev")

    # Both near-matches surfaced for a human to decide on; the bot is not among them.
    assert unclaimed == ["12345+alice@users.noreply.github.com", "alice@personal.dev"]


def test_explicit_aliases_are_merged() -> None:
    identity, unclaimed = resolve_identity(
        AUTHORS, "alice@example.com", aliases=["alice@personal.dev"]
    )

    assert identity.matches("alice@personal.dev")
    assert unclaimed == ["12345+alice@users.noreply.github.com"]


def test_unrelated_author_is_not_a_near_match() -> None:
    _identity, unclaimed = resolve_identity(AUTHORS, "bob@example.com")
    assert unclaimed == []


def test_resolution_is_deterministic() -> None:
    """Byte-reproducibility: same input, same order, every time."""
    a = resolve_identity(AUTHORS, "alice@example.com")
    b = resolve_identity(list(reversed(AUTHORS)), "alice@example.com")
    assert a[0].model_dump() == b[0].model_dump()
    assert a[1] == b[1]


def test_masking_protects_third_party_addresses() -> None:
    """A near-match is often someone else. A shareable profile should not publish it."""
    assert mask_email("jane.doe@corp.com") == "j*******@corp.com"
    assert mask_email("a@b.com") == "a*@b.com"
    assert mask_email("garbage") == "***"
