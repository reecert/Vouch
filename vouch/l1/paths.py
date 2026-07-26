"""Path classification — which touched files actually carry engineering signal.

The v0 prototype counted every path in a commit, so `package-lock.json` churn read as
sustained involvement and a vendored dependency bump read as an unfocused commit. Every
L1 fact is computed over *significant* paths only, and the counts of what was excluded are
reported (never silently dropped).

Classification is by path segment, not substring: ``testing/server.py`` is source, not a
test file. Pure functions, no I/O — this module is arithmetic.
"""
from __future__ import annotations

import re
from enum import StrEnum

__all__ = ["PathKind", "classify", "is_significant", "is_test", "is_noise"]


class PathKind(StrEnum):
    """What a touched path is. ``SOURCE`` and ``TEST`` are significant; the rest is noise."""

    SOURCE = "source"
    TEST = "test"
    LOCKFILE = "lockfile"
    VENDORED = "vendored"
    GENERATED = "generated"
    DOCS = "docs"


# Exact filenames that are dependency lockfiles — machine-authored, high churn, zero signal.
_LOCKFILES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "poetry.lock",
        "uv.lock",
        "pipfile.lock",
        "cargo.lock",
        "gemfile.lock",
        "composer.lock",
        "go.sum",
        "mix.lock",
        "pubspec.lock",
        "packages.lock.json",
        "gradle.lockfile",
        "flake.lock",
    }
)

# Directory names that mean "not our code" wherever they appear in the path.
_VENDOR_DIRS = frozenset(
    {
        "vendor",
        "vendored",
        "node_modules",
        "third_party",
        "thirdparty",
        "external",
        "externals",
        "bower_components",
        "pods",
        ".yarn",
        "site-packages",
    }
)

# Directory names that mean "build output / machine-written".
_GENERATED_DIRS = frozenset(
    {
        "dist",
        "build",
        "out",
        "target",
        "coverage",
        "__snapshots__",
        "__pycache__",
        ".next",
        ".nuxt",
        ".output",
        "generated",
        "gen",
    }
)

# Directory names that mean "test".
_TEST_DIRS = frozenset({"test", "tests", "spec", "specs", "__tests__", "testdata", "e2e"})

_DOC_DIRS = frozenset({"doc", "docs"})

# Filename patterns for generated artifacts.
_GENERATED_FILE_RE = re.compile(
    r"""
    \.min\.(js|css)$
  | \.map$
  | ^.*_pb2(_grpc)?\.pyi?$
  | \.pb\.(go|cc|h)$
  | _generated\.[^.]+$
  | \.generated\.[^.]+$
  | \.g\.dart$
  | \.designer\.cs$
  | \.snap$
  | ^.*\.lock$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Filename patterns for tests.
_TEST_FILE_RE = re.compile(
    r"""
    ^test_[^/]*\.py$
  | ^conftest\.py$
  | _test\.(py|go|rb|ts|tsx|js|jsx|cc|cpp)$
  | \.test\.(ts|tsx|js|jsx|mjs|cjs)$
  | \.spec\.(ts|tsx|js|jsx|mjs|cjs|rb)$
  | ^.*Test\.(java|kt|scala|cs)$
  | ^.*Tests\.(java|kt|scala|cs)$
  | ^.*_spec\.rb$
    """,
    re.VERBOSE,
)

_DOC_FILE_RE = re.compile(r"\.(md|rst|adoc|txt)$", re.IGNORECASE)


def _segments(path: str) -> list[str]:
    return [s for s in path.replace("\\", "/").split("/") if s and s != "."]


def classify(path: str) -> PathKind:
    """Classify one repo-relative path.

    Order matters: vendored and generated *directories* win over everything, because a
    test file inside ``node_modules/`` is not this engineer's test. Lockfiles are checked
    before the generic ``*.lock`` pattern so they get the specific kind.
    """
    segs = _segments(path)
    if not segs:
        return PathKind.SOURCE
    name = segs[-1]
    lower = name.lower()
    dirs = {s.lower() for s in segs[:-1]}

    # "Not our code" and "not hand-written" dominate — check directories first.
    if dirs & _VENDOR_DIRS:
        return PathKind.VENDORED
    if dirs & _GENERATED_DIRS:
        return PathKind.GENERATED

    if lower in _LOCKFILES:
        return PathKind.LOCKFILE

    if dirs & _TEST_DIRS or _TEST_FILE_RE.search(name):
        return PathKind.TEST

    if _GENERATED_FILE_RE.search(name):
        return PathKind.GENERATED

    if dirs & _DOC_DIRS or _DOC_FILE_RE.search(name):
        return PathKind.DOCS

    return PathKind.SOURCE


def is_test(path: str) -> bool:
    """True if ``path`` is a test file that this engineer plausibly wrote."""
    return classify(path) is PathKind.TEST


def is_significant(path: str) -> bool:
    """True if ``path`` carries engineering signal (source or test).

    Docs are excluded from fact denominators but are not counted as *noise* — a
    docs-only commit is real work, it just isn't evidence for any fact L1 measures.
    """
    return classify(path) in (PathKind.SOURCE, PathKind.TEST)


def is_noise(path: str) -> bool:
    """True if ``path`` is machine-authored or third-party (lockfile/vendored/generated)."""
    return classify(path) in (PathKind.LOCKFILE, PathKind.VENDORED, PathKind.GENERATED)
