"""Is there a person's address in this text?

One transcription of the rule, because it had become four. :func:`vouch.eval.labels.load_labels`
refuses a label file containing an address, `tests/test_eval_corpus.py` asserts the same of
the corpus, and `tests/test_eval.py` scans every blob in the history for one — each with its
own copy of the same regex. Copies drift, and the drift that matters is the one where a
scanner quietly stops catching what its docstring still claims it catches.

**A remote URL is not an address.** `git@github.com:acme/api` and
`https://x-token:secret@github.com/acme/api` are `userinfo@host` — URL syntax that happens to
contain an `@`. Reading those as mailboxes forces exactly the wrong repair: the shortest way
to quiet the scanner is to put `github.com` on the allowlist, and from that moment every real
mailbox that host serves walks straight through. So the authority is removed structurally,
before the mailbox pattern is applied, and the allowlist stays what it says it is — reserved
and fixture *domains* — rather than a list of hosts we happen to clone from.

The discrimination is positional, never by domain. Userinfo is what sits between `://` and
the first `/` of the path; scp syntax is `user@host:path`. An address in a URL *path*
(`https://site.example/u/alice@corp.example`) is not in either position, is still an address,
and is still found.

Broad on purpose otherwise: this catches a slip, it does not parse RFC 5322. A false positive
costs one rephrased sentence. A false negative is a third party's address in a public
repository's history, where deleting it from the tree does not remove it.
"""
from __future__ import annotations

import re

__all__ = ["ADDRESS_RE", "contains_address", "find_addresses"]

ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: `scheme://userinfo@` — userinfo may not contain `/`, which is what spares an address in a path.
_URL_USERINFO_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/@]*@")

#: scp-style `user@host:path`; a mailbox in prose is not followed by a colon and no space.
_SCP_REMOTE_RE = re.compile(r"(?<![\w.%+-])[\w.%+-]+@[\w.-]+(?=:[^\s])")


def _without_remotes(text: str) -> str:
    return _SCP_REMOTE_RE.sub("", _URL_USERINFO_RE.sub("", text))


def find_addresses(text: str) -> list[str]:
    """Every mailbox-shaped string in ``text``, in order, with remote URLs discounted."""
    return ADDRESS_RE.findall(_without_remotes(text))


def contains_address(text: str) -> bool:
    """True if ``text`` holds anything shaped like a person's address."""
    return bool(ADDRESS_RE.search(_without_remotes(text)))
