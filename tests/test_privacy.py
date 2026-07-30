"""The address scanner, and the two things it must keep apart.

Every guard that protects "no third-party address in a tracked file" now routes through
:mod:`vouch.privacy`, so the discriminating cases live here once rather than in each caller.
The pairs below are the whole point: a remote URL and an address are both `something@host`,
and a scanner that cannot tell them apart gets repaired by allowlisting the host — which is
the repair that lets a real address through.
"""
from __future__ import annotations

import pytest

from vouch.privacy import contains_address, find_addresses

REMOTES = [
    "git@github.com:acme/private-api.git",
    "https://x-token:ghp_secret@github.com/acme/private-api",
    "ssh://git@gitlab.acme-corp.internal:22/infra/deploy.git",
    "git@gitlab.acme-corp.internal:acme/private-api.git",
    "git@github.com:acme/api",
]

ADDRESSES = [
    "alice@example.com",
    "12345+alice@users.noreply.github.com",
    "first.last%tag@sub.corp.example.org",
]


@pytest.mark.parametrize("text", REMOTES)
def test_a_remote_url_is_not_an_address(text: str) -> None:
    assert find_addresses(text) == []


@pytest.mark.parametrize("text", ADDRESSES)
def test_an_address_is_found(text: str) -> None:
    assert find_addresses(text) == [text]


def test_an_address_in_a_url_path_is_still_an_address() -> None:
    """The discrimination is positional. Userinfo sits before the path; this does not."""
    assert find_addresses("https://site.example/u/alice@corp.example/profile") == [
        "alice@corp.example"
    ]


def test_an_address_beside_a_remote_survives_the_remote() -> None:
    """Stripping the authority must not eat the rest of the line."""
    text = "clone git@github.com:acme/api, then mail alice@corp.example about it"
    assert find_addresses(text) == ["alice@corp.example"]


def test_an_address_at_the_end_of_a_sentence_is_found() -> None:
    """A mailbox followed by punctuation is not scp syntax: the colon needs a path."""
    assert contains_address("reach me at alice@corp.example. thanks") is True
    assert contains_address("subject: alice@corp.example") is True


def test_a_mailto_link_is_found() -> None:
    assert find_addresses("<mailto:alice@corp.example>") == ["alice@corp.example"]


def test_order_is_preserved_and_duplicates_kept() -> None:
    """Callers de-duplicate when they want to; the finder does not decide that for them."""
    assert find_addresses("a@x.example b@y.example a@x.example") == [
        "a@x.example",
        "b@y.example",
        "a@x.example",
    ]


def test_empty_and_plain_text_are_clean() -> None:
    assert contains_address("") is False
    assert contains_address("no address here, just @mentions and user@localhost") is False
